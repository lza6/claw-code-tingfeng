"""Session Models - 会话数据模型

从 claude-code-rust-master 汲取的架构优点:
- 清晰的会话数据模型
- 支持消息持久化
- 时间戳和统计信息
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionMessage:
    """会话中的单条消息"""
    role: str  # "user" | "assistant" | "system" | "tool"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Session:
    """会话数据模型

    属性:
    - id: 唯一会话 ID
    - name: 会话名称
    - created_at: 创建时间
    - updated_at: 更新时间
    - messages: 消息列表
    - metadata: 元数据
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: list[SessionMessage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # 统计信息
    total_tokens: int = 0
    total_cost: float = 0.0
    model: str = ""
    provider: str = ""

    def add_message(self, role: str, content: str, **kwargs) -> SessionMessage:
        """添加消息到会话"""
        msg = SessionMessage(role=role, content=content, **kwargs)
        self.messages.append(msg)
        self.updated_at = time.time()
        return msg

    @property
    def message_count(self) -> int:
        """消息数量"""
        return len(self.messages)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典(用于 JSON 序列化)"""
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp,
                    "metadata": m.metadata,
                }
                for m in self.messages
            ],
            "total_tokens": self.total_tokens,
            "total_cost": self.total_cost,
            "model": self.model,
            "provider": self.provider,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        """从字典创建会话"""
        session = cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            total_tokens=data.get("total_tokens", 0),
            total_cost=data.get("total_cost", 0.0),
            model=data.get("model", ""),
            provider=data.get("provider", ""),
            metadata=data.get("metadata", {}),
        )
        session.messages = [
            SessionMessage(
                role=m["role"],
                content=m["content"],
                timestamp=m.get("timestamp", time.time()),
                metadata=m.get("metadata", {}),
            )
            for m in data.get("messages", [])
        ]
        return session


@dataclass
class SessionInfo:
    """会话摘要信息(用于列表显示)"""
    id: str
    name: str
    created_at: float
    updated_at: float
    message_count: int
    model: str = ""
    total_cost: float = 0.0
