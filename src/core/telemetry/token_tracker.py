"""Token Savings Tracker — 借鉴 RTK 的 SQLite tracking 系统

从 RTK 汲取的设计优点:
- SQLite 持久化追踪工具执行前后的 token 量
- 90 天自动清理过期记录
- 支持按日/周/月统计聚合
- ASCII 图表展示节省趋势
- 项目范围查询支持

数据库路径: 项目目录/.clawd/token_tracker.db

用法:
    tracker = TokenTracker()
    tracker.init()
    tracker.record("git status", raw_tokens=3500, filtered_tokens=800)
    summary = tracker.get_summary()
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class TokenUsage:
    """单次调用的 token 使用量"""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, int]:
        return {
            'input_tokens': self.input_tokens,
            'output_tokens': self.output_tokens,
            'cache_creation_tokens': self.cache_creation_tokens,
            'cache_read_tokens': self.cache_read_tokens,
            'total_tokens': self.total_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenUsage:
        return cls(
            input_tokens=data.get('input_tokens', data.get('prompt_tokens', 0)),
            output_tokens=data.get('output_tokens', data.get('completion_tokens', 0)),
            cache_creation_tokens=data.get('cache_creation_tokens', 0),
            cache_read_tokens=data.get('cache_read_tokens', 0),
        )

    @classmethod
    def from_api_response(cls, response: dict[str, Any]) -> TokenUsage:
        """从 LLM API 响应中提取 token 使用量"""
        usage_data = response.get('usage', {})
        if isinstance(usage_data, dict):
            return cls.from_dict(usage_data)
        return cls()


@dataclass
class TrackingRecord:
    """单次工具执行的 token 追踪记录"""
    tool_name: str                      # 工具名称 (如 BashTool, FileReadTool)
    raw_tokens: int                      # 压缩前 token 量 (原始输出)
    compressed_tokens: int = 0           # 压缩后 token 量
    command: str = ''                    # 命令/操作标识
    elapsed_ms: float = 0.0              # 执行耗时 (ms)
    success: bool = True                 # 是否成功
    timestamp: str = ''                  # ISO 时间戳
    project_path: str = ''               # 项目路径 (用于多项目区分)
    id: int = 0                          # 自增 ID

    @property
    def saved_tokens(self) -> int:
        return self.raw_tokens - self.compressed_tokens

    @property
    def savings_pct(self) -> float:
        if self.raw_tokens == 0:
            return 0.0
        return round(100.0 * self.saved_tokens / self.raw_tokens, 1)


# ---------------------------------------------------------------------------
# 数据库初始化
# ---------------------------------------------------------------------------

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS tracking_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name       TEXT    NOT NULL DEFAULT '',
    raw_tokens      INTEGER NOT NULL DEFAULT 0,
    compressed_tokens  INTEGER NOT NULL DEFAULT 0,
    command         TEXT    NOT NULL DEFAULT '',
    elapsed_ms      REAL    NOT NULL DEFAULT 0.0,
    success         INTEGER NOT NULL DEFAULT 1,
    timestamp       TEXT    NOT NULL DEFAULT '',
    project_path    TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_tracking_timestamp ON tracking_records(timestamp);
CREATE INDEX IF NOT EXISTS idx_tracking_tool ON tracking_records(tool_name);
CREATE INDEX IF NOT EXISTS idx_tracking_command ON tracking_records(command);
CREATE INDEX IF NOT EXISTS idx_tracking_project ON tracking_records(project_path);
"""

# 90 天自动清理
_CLEANUP_OLD_SQL = """
DELETE FROM tracking_records
WHERE timestamp < datetime('now', '-90 days');
"""

DEFAULT_DB_PATH = Path('.clawd') / 'token_tracker.db'


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

class TokenTracker:
    """Token 节省追踪器 — 模仿 RTK 的 tracking.rs

    功能:
    - 记录每次工具执行的 token 用量 (原始 vs 压缩)
    - 查询汇总统计 (总节省、按工具分组)
    - 按日/周/月聚合
    - 90 天自动清理
    - 项目范围查询
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._cleanup_done = False

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """获取 SQLite 连接 (WAL 模式)"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute('PRAGMA journal_mode=WAL')
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
        """初始化数据库表 (幂等) + 90 天清理"""
        with self._connect() as conn:
            conn.executescript(_INIT_SQL)
            conn.execute(_CLEANUP_OLD_SQL)
        self._cleanup_done = True

    # -- 记录 --

    def record(
        self,
        tool_name: str,
        raw_tokens: int,
        compressed_tokens: int = 0,
        command: str = '',
        elapsed_ms: float = 0.0,
        success: bool = True,
        project_path: str = '',
    ) -> TrackingRecord:
        """记录一次工具执行的 token 用量

        Args:
            tool_name: 工具名称
            raw_tokens: 原始输出 token 量
            compressed_tokens: 压缩后 token 量
            command: 命令标识 (如 "git status", "pytest")
            elapsed_ms: 执行耗时 (ms)
            success: 是否成功
            project_path: 项目路径
        """
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).isoformat()

        rec = TrackingRecord(
            tool_name=tool_name,
            raw_tokens=raw_tokens,
            compressed_tokens=compressed_tokens,
            command=command,
            elapsed_ms=elapsed_ms,
            success=success,
            timestamp=timestamp,
            project_path=project_path,
        )

        with self._connect() as conn:
            conn.execute(
                'INSERT INTO tracking_records '
                '(tool_name, raw_tokens, compressed_tokens, command, '
                ' elapsed_ms, success, timestamp, project_path) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    rec.tool_name, rec.raw_tokens, rec.compressed_tokens,
                    rec.command, rec.elapsed_ms, int(rec.success),
                    rec.timestamp, rec.project_path,
                ),
            )

        return rec

    # -- 汇总查询 --

    def get_summary(self, days: int = 30, project_path: str | None = None) -> dict[str, Any]:
        """获取 token 节省汇总统计

        Args:
            days: 统计天数 (默认 30 天)
            project_path: 项目路径过滤 (None = 全部)

        Returns:
            包含总记录数、token 节省量、节省率等的字典
        """
        where = 'WHERE timestamp >= datetime("now", ?)'
        params: list[Any] = [f'-{days} days']

        if project_path:
            where += ' AND project_path = ?'
            params.append(project_path)

        with self._connect() as conn:
            row = conn.execute(
                f'SELECT '
                f' COUNT(*) as total_records, '
                f' SUM(raw_tokens) as total_raw, '
                f' SUM(compressed_tokens) as total_compressed, '
                f' AVG(CASE WHEN raw_tokens > 0 THEN '
                f'   100.0 * (raw_tokens - compressed_tokens) / raw_tokens ELSE 0 END) as avg_savings_pct '
                f'FROM tracking_records {where}',
                params,
            ).fetchone()

        if row is None or row['total_records'] == 0:
            return {
                'total_records': 0,
                'total_raw_tokens': 0,
                'total_compressed_tokens': 0,
                'total_saved_tokens': 0,
                'avg_savings_pct': 0.0,
            }

        total_raw = row['total_raw'] or 0
        total_compressed = row['total_compressed'] or 0
        total_saved = total_raw - total_compressed

        return {
            'total_records': row['total_records'],
            'total_raw_tokens': total_raw,
            'total_compressed_tokens': total_compressed,
            'total_saved_tokens': total_saved,
            'avg_savings_pct': round(row['avg_savings_pct'] or 0.0, 1),
        }

    def get_history(self, limit: int = 50, project_path: str | None = None) -> list[TrackingRecord]:
        """获取最近执行历史

        Args:
            limit: 返回记录数上限
            project_path: 项目路径过滤
        """
        where = ''
        params: list[Any] = []
        if project_path:
            where = 'WHERE project_path = ?'
            params.append(project_path)

        with self._connect() as conn:
            rows = conn.execute(
                f'SELECT * FROM tracking_records {where} '
                f'ORDER BY timestamp DESC LIMIT ?',
                [*params, limit],
            ).fetchall()

        return [
            TrackingRecord(
                id=r['id'],
                tool_name=r['tool_name'],
                raw_tokens=r['raw_tokens'],
                compressed_tokens=r['compressed_tokens'],
                command=r['command'],
                elapsed_ms=r['elapsed_ms'],
                success=bool(r['success']),
                timestamp=r['timestamp'],
                project_path=r['project_path'],
            )
            for r in rows
        ]

    def get_daily_breakdown(self, days: int = 7, project_path: str | None = None) -> list[dict[str, Any]]:
        """按日聚合 token 节省量

        类似 RTK 的 gain --daily 功能。

        Args:
            days: 统计天数
            project_path: 项目路径过滤
        """
        where = 'WHERE timestamp >= datetime("now", ?)'
        params: list[Any] = [f'-{days} days']
        if project_path:
            where += ' AND project_path = ?'
            params.append(project_path)

        with self._connect() as conn:
            rows = conn.execute(
                f'SELECT '
                f'  strftime("%Y-%m-%d", timestamp) as day, '
                f'  COUNT(*) as records, '
                f'  SUM(raw_tokens) as raw, '
                f'  SUM(compressed_tokens) as compressed '
                f'FROM tracking_records {where} '
                f'GROUP BY day ORDER BY day ASC',
                params,
            ).fetchall()

        result = []
        for r in rows:
            raw = r['raw'] or 0
            compressed = r['compressed'] or 0
            result.append({
                'day': r['day'],
                'records': r['records'],
                'raw_tokens': raw,
                'compressed_tokens': compressed,
                'saved_tokens': raw - compressed,
                'savings_pct': round(100.0 * (raw - compressed) / raw, 1) if raw > 0 else 0.0,
            })

        return result

    def get_tool_breakdown(self, days: int = 30, project_path: str | None = None) -> list[dict[str, Any]]:
        """按工具分组统计

        Args:
            days: 统计天数
            project_path: 项目路径过滤
        """
        where = 'WHERE timestamp >= datetime("now", ?)'
        params: list[Any] = [f'-{days} days']
        if project_path:
            where += ' AND project_path = ?'
            params.append(project_path)

        with self._connect() as conn:
            rows = conn.execute(
                f'SELECT '
                f'  tool_name, '
                f'  COUNT(*) as records, '
                f'  SUM(raw_tokens) as raw, '
                f'  SUM(compressed_tokens) as compressed, '
                f'  AVG(elapsed_ms) as avg_ms, '
                f'  SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate '
                f'FROM tracking_records {where} '
                f'GROUP BY tool_name ORDER BY raw DESC',
                params,
            ).fetchall()

        result = []
        for r in rows:
            raw = r['raw'] or 0
            compressed = r['compressed'] or 0
            result.append({
                'tool_name': r['tool_name'],
                'records': r['records'],
                'raw_tokens': raw,
                'compressed_tokens': compressed,
                'saved_tokens': raw - compressed,
                'savings_pct': round(100.0 * (raw - compressed) / raw, 1) if raw > 0 else 0.0,
                'avg_elapsed_ms': round(r['avg_ms'] or 0.0, 1),
                'success_rate': round(r['success_rate'] or 0.0, 1),
            })

        return result

    # -- ASCII 图表 (类似 RTK gain) --

    def get_ascii_chart(self, days: int = 7, width: int = 50, project_path: str | None = None) -> str:
        """生成 token 节省趋势 ASCII 图表

        借鉴 RTK 的 gain 命令中的 ASCII graph 功能。

        Returns:
            格式化的 ASCII 图表字符串
        """
        daily = self.get_daily_breakdown(days=days, project_path=project_path)
        if not daily:
            return '暂无数据。运行一些命令后重试。'

        max_saved = max(d['saved_tokens'] for d in daily) or 1
        lines = []
        lines.append(f'\n{"token 节省趋势 (最近 {days} 天)":^60}')
        lines.append('─' * 60)

        for d in daily:
            bar_len = max(1, int((d['saved_tokens'] / max_saved) * width))
            bar = '█' * bar_len
            saved_str = f"{d['saved_tokens']:,}"
            lines.append(
                f'{d["day"]} │{bar:<{width}}│ {saved_str:>8} tokens ({d["savings_pct"]:.0f}%)'
            )

        lines.append('─' * 60)
        total_saved = sum(d['saved_tokens'] for d in daily)
        avg_pct = sum(d['savings_pct'] for d in daily) / len(daily) if daily else 0
        lines.append(f'总计: {total_saved:,} tokens saved | 平均节省: {avg_pct:.0f}%')
        lines.append('')

        return '\n'.join(lines)

    # -- 格式化报告 --

    def get_report(self, days: int = 30, project_path: str | None = None) -> str:
        """生成完整的 token 节省报告

        Returns:
            格式化的报告字符串
        """
        summary = self.get_summary(days=days, project_path=project_path)

        if summary['total_records'] == 0:
            return '📊 Token 节省报告\n' + '=' * 50 + '\n暂无数据。运行一些命令后重试。'

        lines = [
            '📊 Token 节省报告',
            '=' * 50,
            f'总执行次数:     {summary["total_records"]}',
            f'原始 token 总量: {summary["total_raw_tokens"]:,}',
            f'压缩后 token:   {summary["total_compressed_tokens"]:,}',
            f'节省 token:     {summary["total_saved_tokens"]:,}',
            f'平均节省率:     {summary["avg_savings_pct"]:.1f}%',
            '',
            '─' * 50,
            '按工具分类:',
            '─' * 50,
        ]

        for tool in self.get_tool_breakdown(days=days, project_path=project_path):
            lines.append(
                f'  {tool["tool_name"]:25s} '
                f'节省 {tool["saved_tokens"]:>8,} tokens ({tool["savings_pct"]:5.1f}%)  '
                f'[{tool["records"]} 次执行]'
            )

        lines.append('')
        lines.append(self.get_ascii_chart(days=min(7, days), project_path=project_path))

        return '\n'.join(lines)

    # -- 清理 --

    def cleanup(self, days: int = 90) -> int:
        """清理过期记录

        Returns:
            删除的记录数
        """
        with self._connect() as conn:
            cursor = conn.execute(
                'DELETE FROM tracking_records WHERE timestamp < datetime("now", ?)',
                (f'-{days} days',),
            )
        return cursor.rowcount
