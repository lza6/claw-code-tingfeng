"""SQLite 会话存储 — 替代纯 JSON 文件

设计目标:
- 使用 SQLite 替代 JSON 文件，支持快速查询/索引
- 保留 JSON 兼容（可导出 Transcript Markdown）
- 存储路径: 项目目录/.clawd/sessions/clawd.db
- 支持全文搜索、Token 统计聚合、会话恢复

表结构:
- sessions: 会话元数据（ID、模型、时间、成本）
- messages: 消息内容（角色、内容、工具调用）
- tool_calls: 工具调用记录（名称、参数、结果、耗时）
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .project_context import ProjectContext

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SessionRecord:
    """会话元数据记录"""
    session_id: str
    model: str = ''
    provider: str = ''
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    turn_count: int = 0
    goal: str = ''
    status: str = 'completed'  # completed | failed | cancelled
    started_at: str = ''
    ended_at: str = ''
    tags: str = ''  # JSON 数组: ["refactor","hotfix"]


@dataclass
class MessageRecord:
    """单条消息记录"""
    msg_id: str
    session_id: str
    role: str           # system | user | assistant | tool
    content: str
    tool_calls: str = ''  # JSON: 工具调用列表
    created_at: str = ''
    sequence: int = 0   # 消息在会话中的顺序


@dataclass
class ToolCallRecord:
    """工具调用详情"""
    call_id: str
    session_id: str
    tool_name: str
    tool_args: str  # JSON
    result_output: str = ''
    result_error: str = ''
    success: bool = False
    elapsed_ms: float = 0.0
    created_at: str = ''


# ---------------------------------------------------------------------------
# SQLite 会话存储
# ---------------------------------------------------------------------------

# 默认数据库路径（向后兼容）
# 新项目应通过 ProjectContext 获取路径
DEFAULT_DB_PATH = Path('.clawd') / 'sessions' / 'clawd.db'

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    model       TEXT NOT NULL DEFAULT '',
    provider    TEXT NOT NULL DEFAULT '',
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    total_cost  REAL    NOT NULL DEFAULT 0.0,
    turn_count   INTEGER NOT NULL DEFAULT 0,
    goal        TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'completed',
    tags        TEXT    NOT NULL DEFAULT '[]',
    started_at  TEXT    NOT NULL DEFAULT '',
    ended_at    TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS messages (
    msg_id     TEXT PRIMARY KEY,
    session_id TEXT    NOT NULL,
    role       TEXT    NOT NULL,
    content    TEXT    NOT NULL,
    tool_calls TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT '',
    sequence   INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tool_calls (
    call_id      TEXT PRIMARY KEY,
    session_id   TEXT    NOT NULL,
    tool_name    TEXT    NOT NULL,
    tool_args    TEXT    NOT NULL DEFAULT '',
    result_output TEXT   NOT NULL DEFAULT '',
    result_error TEXT    NOT NULL DEFAULT '',
    success      INTEGER NOT NULL DEFAULT 0,
    elapsed_ms   REAL    NOT NULL DEFAULT 0.0,
    created_at   TEXT    NOT NULL DEFAULT '',
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, sequence);
CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status   ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_started   ON sessions(started_at);
"""


class SQLiteSessionStore:
    """SQLite 会话存储管理器

    用法:
        store = SQLiteSessionStore(db_path)
        store.init()
        store.save_session(record)
        sessions = store.list_sessions()
        session = store.get_session(sid)
    """

    def __init__(self, db_path: Path | str | None = None, project_ctx: ProjectContext | None = None) -> None:
        """初始化 SQLite 会话存储

        Args:
            db_path: 数据库文件路径（显式指定时优先使用）
            project_ctx: 项目上下文（用于自动推导路径）
        """
        if db_path is not None:
            self.db_path = Path(db_path)
        elif project_ctx is not None:
            self.db_path = project_ctx.db_path
        else:
            self.db_path = DEFAULT_DB_PATH

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """获取 SQLite 连接（WAL 模式）"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA foreign_keys=ON')
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        """初始化数据库表（幂等）"""
        with self._connect() as conn:
            conn.executescript(_INIT_SQL)

    # -- Sessions --

    def save_session(self, record: SessionRecord) -> None:
        """保存/更新会话"""
        with self._connect() as conn:
            conn.execute(
                'INSERT OR REPLACE INTO sessions '
                '(session_id, model, provider, input_tokens, output_tokens, '
                ' total_tokens, total_cost, turn_count, goal, status, tags, '
                ' started_at, ended_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    record.session_id, record.model, record.provider,
                    record.input_tokens, record.output_tokens,
                    record.total_tokens, record.total_cost, record.turn_count,
                    record.goal, record.status, record.tags,
                    record.started_at, record.ended_at,
                ),
            )

    def get_session(self, session_id: str) -> SessionRecord | None:
        """获取单条会话记录"""
        with self._connect() as conn:
            row = conn.execute(
                'SELECT * FROM sessions WHERE session_id = ?', (session_id,),
            ).fetchone()
        if row is None:
            return None
        return SessionRecord(**dict(row))

    def list_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ) -> list[SessionRecord]:
        """列出会话（分页）"""
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    'SELECT * FROM sessions WHERE status = ? '
                    'ORDER BY started_at DESC LIMIT ? OFFSET ?',
                    (status, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT * FROM sessions '
                    'ORDER BY started_at DESC LIMIT ? OFFSET ?',
                    (limit, offset),
                ).fetchall()
        return [SessionRecord(**dict(r)) for r in rows]

    def update_session_tokens(
        self,
        session_id: str,
        input_tokens: int,
        output_tokens: int,
        cost: float = 0.0,
    ) -> None:
        """更新会话 Token 统计"""
        with self._connect() as conn:
            conn.execute(
                'UPDATE sessions SET '
                ' input_tokens = input_tokens + ?, '
                ' output_tokens = output_tokens + ?, '
                ' total_tokens = input_tokens + output_tokens + ?, '
                ' total_cost = total_cost + ?, '
                ' turn_count = turn_count + 1 '
                'WHERE session_id = ?',
                (input_tokens, output_tokens,
                 input_tokens + output_tokens, cost, session_id),
            )

    def delete_session(self, session_id: str) -> bool:
        """删除会话及关联数据"""
        with self._connect() as conn:
            cur = conn.execute(
                'DELETE FROM sessions WHERE session_id = ?', (session_id,),
            )
        return cur.rowcount > 0

    # -- Messages --

    def save_message(self, msg: MessageRecord) -> None:
        """保存消息"""
        with self._connect() as conn:
            conn.execute(
                'INSERT OR REPLACE INTO messages '
                '(msg_id, session_id, role, content, tool_calls, created_at, sequence) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (msg.msg_id, msg.session_id, msg.role, msg.content,
                 msg.tool_calls, msg.created_at, msg.sequence),
            )

    def get_messages(self, session_id: str) -> list[MessageRecord]:
        """获取会话所有消息（按 sequence 排序）"""
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT * FROM messages WHERE session_id = ? '
                'ORDER BY sequence ASC', (session_id,),
            ).fetchall()
        return [MessageRecord(**dict(r)) for r in rows]

    def search_messages(self, query: str, limit: int = 20) -> list[MessageRecord]:
        """全文搜索消息内容"""
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT * FROM messages WHERE content LIKE ? '
                'ORDER BY created_at DESC LIMIT ?',
                (f'%{query}%', limit),
            ).fetchall()
        return [MessageRecord(**dict(r)) for r in rows]

    # -- Tool Calls --

    def save_tool_call(self, tc: ToolCallRecord) -> None:
        """保存工具调用记录"""
        with self._connect() as conn:
            conn.execute(
                'INSERT OR REPLACE INTO tool_calls '
                '(call_id, session_id, tool_name, tool_args, '
                ' result_output, result_error, success, elapsed_ms, created_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    tc.call_id, tc.session_id, tc.tool_name, tc.tool_args,
                    tc.result_output, tc.result_error,
                    int(tc.success), tc.elapsed_ms, tc.created_at,
                ),
            )

    def get_tool_calls(self, session_id: str) -> list[ToolCallRecord]:
        """获取会话所有工具调用"""
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT * FROM tool_calls WHERE session_id = ? '
                'ORDER BY created_at ASC', (session_id,),
            ).fetchall()
        return [ToolCallRecord(**{**dict(r), 'success': bool(r['success'])}) for r in rows]

    # -- Analytics --

    def get_usage_summary(self, days: int = 30) -> dict[str, Any]:
        """获取 Token/成本统计摘要

        返回:
            包含总请求数、Token 使用量、成本、错误率的字典
        """
        with self._connect() as conn:
            row = conn.execute(
                'SELECT '
                ' COUNT(*) as total_sessions, '
                ' SUM(total_tokens) as total_tokens, '
                ' SUM(total_cost) as total_cost, '
                ' SUM(input_tokens) as total_input, '
                ' SUM(output_tokens) as total_output '
                'FROM sessions '
                'WHERE started_at >= datetime("now", ?)',
                (f'-{days} days',),
            ).fetchone()
        if row is None:
            return {}
        return {
            'total_sessions': row['total_sessions'] or 0,
            'total_tokens': row['total_tokens'] or 0,
            'total_cost': round(row['total_cost'] or 0.0, 4),
            'total_input_tokens': row['total_input'] or 0,
            'total_output_tokens': row['total_output'] or 0,
        }

    def get_top_tools(self, limit: int = 10) -> list[dict[str, Any]]:
        """获取最常用的工具排行"""
        with self._connect() as conn:
            rows = conn.execute(
                'SELECT tool_name, COUNT(*) as call_count, '
                ' AVG(elapsed_ms) as avg_ms, '
                ' SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate '
                'FROM tool_calls '
                'GROUP BY tool_name '
                'ORDER BY call_count DESC LIMIT ?',
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- Export --

    def export_transcript(self, session_id: str) -> str:
        """导出会话为 Markdown Transcript"""
        session = self.get_session(session_id)
        messages = self.get_messages(session_id)

        if not session:
            return ''

        lines = [
            f'# Session: {session_id}',
            f'- Model: {session.model}',
            f'- Provider: {session.provider}',
            f'- Tokens: {session.total_tokens} '
            f'(input: {session.input_tokens}, output: {session.output_tokens})',
            f'- Cost: ${session.total_cost:.4f}',
            f'- Turns: {session.turn_count}',
            f'- Status: {session.status}',
            f'- Started: {session.started_at}',
            f'- Ended: {session.ended_at}',
            '',
            '---',
            '',
        ]

        for msg in messages:
            role_emoji = {
                'system': '⚙', 'user': '👤',
                'assistant': '🤖', 'tool': '🔧',
            }.get(msg.role, '?')
            lines.append(f'### {role_emoji} {msg.role}')
            lines.append('')
            if msg.tool_calls:
                lines.append('')
            lines.append(msg.content)
            lines.append('')

        # 工具调用附录
        tool_calls = self.get_tool_calls(session_id)
        if tool_calls:
            lines.append('---')
            lines.append('')
            lines.append('## 工具调用详情')
            lines.append('')
            for tc in tool_calls:
                icon = '✅' if tc.success else '❌'
                lines.append(f'### {icon} {tc.tool_name} ({tc.elapsed_ms:.0f}ms)')
                lines.append('')
                lines.append(f'- 参数: `{tc.tool_args}`')
                if tc.result_error:
                    lines.append(f'- 错误: {tc.result_error}')

        return '\n'.join(lines)
