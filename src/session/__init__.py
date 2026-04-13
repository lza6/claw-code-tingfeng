"""Session Module - 会话管理系统

从 claude-code-rust-master 汲取的架构优点:
- 完整的会话生命周期管理
- 持久化存储
- 会话历史追踪

使用方式:
    from src.session import SessionManager

    mgr = SessionManager()
    session = mgr.create(name="my-session")
"""
from __future__ import annotations

from .manager import SessionManager
from .models import Session, SessionInfo, SessionMessage
from .storage import SessionStorage

__all__ = [
    "Session",
    "SessionInfo",
    "SessionManager",
    "SessionMessage",
    "SessionStorage",
]
