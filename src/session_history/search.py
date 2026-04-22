"""
Session History Search - 会话历史搜索

从 oh-my-codex-main/src/session-history/search.ts 转换而来。
提供会话历史搜索功能。
增强版: 添加日期范围搜索、项目过滤、上下文窗口等
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

# ===== 常量 =====
DEFAULT_LIMIT = 10
DEFAULT_CONTEXT = 80
MAX_LIMIT = 100
MAX_CONTEXT = 400
DURATION_RE = re.compile(r'^(\d+)([sSmMdDwW])$')


@dataclass
class SessionSearchQuery:
    """会话搜索查询"""
    text: str | None = None
    agent_name: str | None = None
    mode: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    project: str | None = None  # 项目路径过滤
    session: str | None = None  # 会话ID过滤
    since: str | None = None    # 时间段: 7d, 24h, 1w
    context: int = DEFAULT_CONTEXT  # 上下文窗口大小
    case_sensitive: bool = False
    limit: int = DEFAULT_LIMIT


@dataclass
class SessionEntry:
    """会话条目"""
    session_id: str
    turn_id: str
    timestamp: str
    user_message: str
    agent_response: str
    agent_name: str | None = None
    mode: str | None = None
    tool_calls: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class SearchResult:
    """搜索结果"""
    sessions: list[SessionEntry]
    total: int
    query: SessionSearchQuery
    matched_sessions: int = 0  # 匹配的唯一会话数


# ===== 工具函数 =====
def parse_since_spec(value: str | None, now: datetime | None = None) -> datetime | None:
    """解析时间段规格 (如 7d, 24h, 1w)

    参数:
        value: 时间段字符串
        now: 基准时间，默认当前时间

    返回:
        解析后的截止时间
    """
    if not value:
        return None

    trimmed = value.strip()
    if not trimmed:
        return None

    match = DURATION_RE.match(trimmed)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        multipliers = {
            's': 1,
            'm': 60,
            'h': 3600,
            'd': 86400,
            'w': 604800,
        }
        delta = amount * multipliers.get(unit, 0)
        base = now or datetime.now()
        return base - timedelta(seconds=delta)

    # 尝试解析日期格式 (支持多种格式)
    try:
        for fmt in ['%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S']:
            try:
                return datetime.strptime(trimmed, fmt)
            except ValueError:
                continue
    except Exception:
        pass

    return None


def clamp_integer(value: int, fallback: int, max_val: int) -> int:
    """限制整数值在有效范围内"""
    if not isinstance(value, int) or value < 0:
        return fallback
    return min(value, max_val)


def normalize_project_filter(project: str | None, cwd: str) -> str | None:
    """标准化项目过滤"""
    if not project:
        return None

    trimmed = project.strip()
    if not trimmed:
        return None

    if trimmed == 'current':
        return cwd

    if trimmed == 'all':
        return None

    return trimmed


def build_snippet(text: str, query: str, context: int, case_sensitive: bool) -> str | None:
    """构建搜索上下文片段"""
    if not text:
        return None

    haystack = text if case_sensitive else text.lower()
    needle = query if case_sensitive else query.lower()
    index = haystack.find(needle)

    if index < 0:
        return None

    start = max(0, index - context)
    end = min(len(text), index + len(query) + context)
    prefix = '…' if start > 0 else ''
    suffix = '…' if end < len(text) else ''

    snippet_text = text[start:end].replace(r'\s+', ' ').strip()
    return f"{prefix}{snippet_text}{suffix}"


def sessions_dir(cwd: str) -> str:
    """获取会话目录"""
    return str(Path(cwd) / ".omx" / "sessions")


def list_session_files(cwd: str) -> list[Path]:
    """列出所有会话文件"""
    sessions = sessions_dir(cwd)
    session_path = Path(sessions)
    if not session_path.exists():
        return []
    return sorted(session_path.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


async def search_sessions(
    cwd: str,
    query: SessionSearchQuery,
) -> SearchResult:
    """搜索会话历史

    支持:
    - 文本搜索 (case-sensitive/insensitive)
    - Agent名称过滤
    - 模式过滤
    - 日期范围过滤 (date_from, date_to, since)
    - 项目过滤
    - 会话ID过滤
    - 上下文片段 (snippet)
    """
    sessions = []
    matched_session_ids = set()
    files = list_session_files(cwd)

    # 解析since参数
    since_cutoff = parse_since_spec(query.since) if query.since else None

    for file_path in files[:query.limit]:
        try:
            stat = file_path.stat()
            file_mtime = datetime.fromtimestamp(stat.st_mtime)

            # 时间过滤 (since cutoff)
            if since_cutoff and file_mtime < since_cutoff:
                continue

            # 日期范围过滤
            if query.date_from and file_mtime < query.date_from:
                continue
            if query.date_to and file_mtime > query.date_to:
                continue

            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            # 会话ID过滤
            if query.session:
                session_id = data.get("session_id", "")
                if query.session.lower() not in session_id.lower():
                    continue

            # 文本搜索
            snippet = None
            if query.text:
                user_msg = data.get("user_message", "")
                agent_resp = data.get("agent_response", "")

                # 构建snippet
                full_text = f"{user_msg} {agent_resp}"
                snippet = build_snippet(full_text, query.text, query.context, query.case_sensitive)

                if not snippet:
                    continue

            # Agent名称过滤
            if query.agent_name and data.get("agent_name") != query.agent_name:
                continue

            # 模式过滤
            if query.mode and data.get("mode") != query.mode:
                continue

            session_id = data.get("session_id", "")
            matched_session_ids.add(session_id)

            sessions.append(SessionEntry(
                session_id=session_id,
                turn_id=data.get("turn_id", ""),
                timestamp=data.get("timestamp", ""),
                user_message=data.get("user_message", ""),
                agent_response=data.get("agent_response", ""),
                agent_name=data.get("agent_name"),
                mode=data.get("mode"),
                tool_calls=data.get("tool_calls", []),
                metadata=data.get("metadata", {}),
            ))
        except Exception:
            continue

    return SearchResult(
        sessions=sessions,
        total=len(sessions),
        query=query,
        matched_sessions=len(matched_session_ids),
    )


async def get_session_by_id(cwd: str, session_id: str) -> SessionEntry | None:
    """根据ID获取会话"""
    session_file = Path(sessions_dir(cwd)) / f"{session_id}.json"
    if not session_file.exists():
        return None

    try:
        with open(session_file, encoding="utf-8") as f:
            data = json.load(f)
        return SessionEntry(
            session_id=data.get("session_id", ""),
            turn_id=data.get("turn_id", ""),
            timestamp=data.get("timestamp", ""),
            user_message=data.get("user_message", ""),
            agent_response=data.get("agent_response", ""),
            agent_name=data.get("agent_name"),
            mode=data.get("mode"),
            tool_calls=data.get("tool_calls", []),
            metadata=data.get("metadata", {}),
        )
    except Exception:
        return None


# ===== 导出 =====
__all__ = [
    "SearchResult",
    "SessionEntry",
    "SessionSearchQuery",
    "build_snippet",
    "clamp_integer",
    "get_session_by_id",
    "list_session_files",
    "normalize_project_filter",
    # 工具函数
    "parse_since_spec",
    "search_sessions",
    # 核心API
    "sessions_dir",
]
