"""Session Module - 会话管理系统

从 claude-code-rust-master 汲取的架构优点:
- 完整的会话生命周期管理
- 持久化存储（已增强：原子写入锁）
- 会话历史追踪（已增强：全文检索）

从 oh-my-codex-main 汲取:
- state-server.ts 的原子写入锁
- session-history/search.ts 的流式会话历史检索

使用方式:
    from src.session import SessionManager, search_session_history

    mgr = SessionManager()
    session = mgr.create(name="my-session")

    # 搜索会话历史
    results = await search_session_history("authentication error")
"""
from __future__ import annotations

from .manager import SessionManager
from .models import Session, SessionInfo, SessionMessage
from .search import (
    SessionSearchOptions,
    SessionSearchReport,
    SessionSearchResult,
    search_session_history,
)
from .storage import SessionStorage

__all__ = [
    "Session",
    "SessionInfo",
    "SessionManager",
    "SessionMessage",
    "SessionSearchOptions",
    "SessionSearchReport",
    "SessionSearchResult",
    "SessionStorage",
    "search_session_history",
]
