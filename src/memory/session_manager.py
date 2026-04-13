"""
会话管理模块 - 整合自 Onyx 的会话加载模式

提供:
- 会话持久化
- 会话历史管理
- 多会话支持
- 会话上下文恢复
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SessionStatus(str, Enum):
    """会话状态"""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


@dataclass
class Message:
    """消息"""
    role: str  # user/assistant/system
    content: str
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Session:
    """会话"""
    session_id: str
    user_id: str | None = None
    title: str = ""
    status: SessionStatus = SessionStatus.ACTIVE
    messages: list[Message] = field(default_factory=list)
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    updated_at: float = field(default_factory=lambda: datetime.now().timestamp())
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_message(self, role: str, content: str, metadata: dict | None = None) -> Message:
        """添加消息"""
        msg = Message(
            role=role,
            content=content,
            metadata=metadata or {}
        )
        self.messages.append(msg)
        self.updated_at = datetime.now().timestamp()
        return msg

    def get_messages(self, limit: int | None = None) -> list[Message]:
        """获取消息"""
        if limit:
            return self.messages[-limit:]
        return self.messages

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "title": self.title,
            "status": self.status.value,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp,
                    "metadata": m.metadata,
                }
                for m in self.messages
            ],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        """从字典创建"""
        session = cls(
            session_id=data["session_id"],
            user_id=data.get("user_id"),
            title=data.get("title", ""),
            status=SessionStatus(data.get("status", "active")),
            created_at=data.get("created_at", datetime.now().timestamp()),
            updated_at=data.get("updated_at", datetime.now().timestamp()),
            metadata=data.get("metadata", {}),
        )
        for msg_data in data.get("messages", []):
            session.messages.append(Message(
                role=msg_data["role"],
                content=msg_data["content"],
                timestamp=msg_data.get("timestamp", datetime.now().timestamp()),
                metadata=msg_data.get("metadata", {}),
            ))
        return session


class SessionStorage:
    """会话存储基类"""

    def __init__(self, base_path: Path | None = None):
        self.base_path = base_path or Path("./.clawd/sessions")

    async def save(self, session: Session) -> None:
        """保存会话"""
        raise NotImplementedError

    async def load(self, session_id: str) -> Session | None:
        """加载会话"""
        raise NotImplementedError

    async def list_sessions(
        self,
        user_id: str | None = None,
        status: SessionStatus | None = None,
        limit: int = 50
    ) -> list[Session]:
        """列出会话"""
        raise NotImplementedError

    async def delete(self, session_id: str) -> bool:
        """删除会话"""
        raise NotImplementedError


class FileSessionStorage(SessionStorage):
    """文件存储会话"""

    async def save(self, session: Session) -> None:
        """保存会话到文件"""
        self.base_path.mkdir(parents=True, exist_ok=True)
        file_path = self.base_path / f"{session.session_id}.json"

        data = session.to_dict()
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.debug(f"会话已保存: {session.session_id}")

    async def load(self, session_id: str) -> Session | None:
        """从文件加载会话"""
        file_path = self.base_path / f"{session_id}.json"
        if not file_path.exists():
            return None

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            return Session.from_dict(data)
        except Exception as e:
            logger.error(f"加载会话失败: {e}")
            return None

    async def list_sessions(
        self,
        user_id: str | None = None,
        status: SessionStatus | None = None,
        limit: int = 50
    ) -> list[Session]:
        """列出会话"""
        if not self.base_path.exists():
            return []

        sessions = []
        for file_path in self.base_path.glob("*.json"):
            try:
                with open(file_path, encoding="utf-8") as f:
                    data = json.load(f)

                # 过滤
                if user_id and data.get("user_id") != user_id:
                    continue
                if status and data.get("status") != status.value:
                    continue

                sessions.append(Session.from_dict(data))
            except Exception:
                continue

        # 按更新时间排序
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions[:limit]

    async def delete(self, session_id: str) -> bool:
        """删除会话"""
        file_path = self.base_path / f"{session_id}.json"
        if file_path.exists():
            file_path.unlink()
            return True
        return False


class SessionManager:
    """会话管理器"""

    _instance: SessionStorage | None = None

    @classmethod
    def initialize(cls, storage: SessionStorage | None = None) -> SessionStorage:
        """初始化"""
        if storage is None:
            base_path = Path(os.environ.get("SESSION_STORAGE_PATH", "./.clawd/sessions"))
            storage = FileSessionStorage(base_path)

        cls._instance = storage
        logger.info("会话管理器已初始化")
        return storage

    @classmethod
    def get_storage(cls) -> SessionStorage:
        """获取存储"""
        if cls._instance is None:
            cls._instance = cls.initialize()
        return cls._instance

    @classmethod
    async def create_session(
        cls,
        session_id: str,
        user_id: str | None = None,
        title: str = ""
    ) -> Session:
        """创建会话"""
        session = Session(
            session_id=session_id,
            user_id=user_id,
            title=title or f"会话 {session_id[:8]}",
        )
        await cls.get_storage().save(session)
        return session

    @classmethod
    async def get_session(cls, session_id: str) -> Session | None:
        """获取会话"""
        return await cls.get_storage().load(session_id)

    @classmethod
    async def save_session(cls, session: Session) -> None:
        """保存会话"""
        await cls.get_storage().save(session)

    @classmethod
    async def list_sessions(
        cls,
        user_id: str | None = None,
        status: SessionStatus | None = None,
        limit: int = 50
    ) -> list[Session]:
        """列出会话"""
        return await cls.get_storage().list_sessions(user_id, status, limit)

    @classmethod
    async def delete_session(cls, session_id: str) -> bool:
        """删除会话"""
        return await cls.get_storage().delete(session_id)


# 便捷函数
async def create_session(
    session_id: str,
    user_id: str | None = None,
    title: str = ""
) -> Session:
    """创建会话"""
    return await SessionManager.create_session(session_id, user_id, title)


async def get_session(session_id: str) -> Session | None:
    """获取会话"""
    return await SessionManager.get_session(session_id)


async def save_session(session: Session) -> None:
    """保存会话"""
    await SessionManager.save_session(session)
