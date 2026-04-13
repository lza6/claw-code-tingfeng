"""Session Manager - 会话管理器

从 claude-code-rust-master 汲取的架构优点:
- 统一的会话生命周期管理
- 创建、加载、保存、删除会话
- 会话历史追踪
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import Session, SessionInfo, SessionMessage
from .storage import SessionStorage


class SessionManager:
    """会话管理器

    提供完整的会话管理功能:
    - 创建新会话
    - 加载已有会话
    - 保存会话到持久化存储
    - 删除会话
    - 列出会话历史

    使用方式:
        mgr = SessionManager()
        session = mgr.create(name="my-session")
        session.add_message("user", "hello")
        await mgr.save(session)
    """

    def __init__(self, sessions_dir: Path | None = None) -> None:
        """初始化会话管理器

        Args:
            sessions_dir: 会话存储目录
        """
        self.storage = SessionStorage(sessions_dir)
        self._current_session: Session | None = None

    @property
    def current_session(self) -> Session | None:
        """获取当前会话"""
        return self._current_session

    def create(self, name: str | None = None, **kwargs) -> Session:
        """创建新会话

        Args:
            name: 会话名称,默认为 None (使用 ID)
            **kwargs: 额外的会话属性

        Returns:
            新创建的 Session 对象
        """
        session = Session(name=name or "", **kwargs)
        self._current_session = session
        return session

    async def load(self, session_id: str) -> Session | None:
        """加载会话

        Args:
            session_id: 会话 ID

        Returns:
            Session 对象,如果不存在则返回 None
        """
        session = await self.storage.load(session_id)
        if session is not None:
            self._current_session = session
        return session

    async def save(self, session: Session | None = None) -> Path:
        """保存会话

        Args:
            session: 要保存的会话,默认为当前会话

        Returns:
            保存的文件路径
        """
        target = session or self._current_session
        if target is None:
            raise ValueError("没有可保存的会话")
        return await self.storage.save(target)

    async def delete(self, session_id: str) -> bool:
        """删除会话

        Args:
            session_id: 会话 ID

        Returns:
            是否成功删除
        """
        if self._current_session and self._current_session.id == session_id:
            self._current_session = None
        return await self.storage.delete(session_id)

    async def list_sessions(self, limit: int = 50) -> list[SessionInfo]:
        """列出所有会话

        Args:
            limit: 返回数量限制

        Returns:
            SessionInfo 列表
        """
        return await self.storage.list_sessions(limit=limit)

    async def get_session(self, session_id: str) -> Session | None:
        """获取会话(不设置为当前会话)

        Args:
            session_id: 会话 ID

        Returns:
            Session 对象或 None
        """
        return await self.storage.load(session_id)

    async def clear_all(self) -> int:
        """清空所有会话

        Returns:
            删除的会话数量
        """
        self._current_session = None
        return await self.storage.clear_all()

    async def get_stats(self) -> dict[str, Any]:
        """获取会话统计信息

        Returns:
            统计信息字典
        """
        stats = await self.storage.get_stats()
        stats["current_session_id"] = self._current_session.id if self._current_session else None
        return stats

    def add_message(self, role: str, content: str, **kwargs) -> SessionMessage | None:
        """向当前会话添加消息

        Args:
            role: 消息角色
            content: 消息内容
            **kwargs: 额外参数

        Returns:
            添加的消息对象,如果没有当前会话则返回 None
        """
        if self._current_session is None:
            return None
        return self._current_session.add_message(role, content, **kwargs)
