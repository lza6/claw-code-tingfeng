"""Team Mailbox - 消息队列管理

汲取 oh-my-codex-main/src/team/state/mailbox.ts (概念)

提供团队内部消息传递、广播、私聊等功能。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class TeamMessage:
    """团队消息"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    from_id: str = ""
    to_id: str = ""  # 空表示广播
    message_type: str = "status_update"  # status_update, task_assign, task_result, etc.
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    correlation_id: str | None = None

    # 消息状态
    delivered: bool = False
    notified: bool = False
    read: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "from_id": self.from_id,
            "to_id": self.to_id,
            "message_type": self.message_type,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "delivered": self.delivered,
            "notified": self.notified,
            "read": self.read,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TeamMessage:
        msg = cls(
            id=data.get("id", str(uuid.uuid4())),
            from_id=data.get("from_id", ""),
            to_id=data.get("to_id", ""),
            message_type=data.get("message_type", "status_update"),
            content=data.get("content", ""),
            metadata=data.get("metadata", {}),
            correlation_id=data.get("correlation_id"),
        )
        msg.timestamp = datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now()
        msg.delivered = data.get("delivered", False)
        msg.notified = data.get("notified", False)
        msg.read = data.get("read", False)
        return msg


class MailboxStore:
    """邮箱存储（文件系统版）"""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir / "mailbox"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._inbox_dir = self.state_dir / "inbox"
        self._inbox_dir.mkdir(parents=True, exist_ok=True)
        self._sent_dir = self.state_dir / "sent"
        self._sent_dir.mkdir(parents=True, exist_ok=True)

    def _inbox_path(self, agent_id: str) -> Path:
        return self._inbox_dir / f"{agent_id}.json"

    def _sent_path(self, agent_id: str) -> Path:
        return self._sent_dir / f"{agent_id}.json"

    def send_message(self, message: TeamMessage) -> bool:
        """发送消息"""
        try:
            # 保存到发送者的已发送箱
            sent_path = self._sent_path(message.from_id)
            sent_messages = []
            if sent_path.exists():
                sent_messages = [TeamMessage.from_dict(m) for m in json.loads(sent_path.read_text())]
            sent_messages.append(message)
            sent_path.write_text(json.dumps([m.to_dict() for m in sent_messages], indent=2))

            # 如果不是广播，保存到收件人的收件箱
            if message.to_id:
                inbox_path = self._inbox_path(message.to_id)
                inbox_messages = []
                if inbox_path.exists():
                    inbox_messages = [TeamMessage.from_dict(m) for m in json.loads(inbox_path.read_text())]
                inbox_messages.append(message)
                inbox_path.write_text(json.dumps([m.to_dict() for m in inbox_messages], indent=2))
            else:
                # 广播消息：保存到所有活跃代理的收件箱（这里简化处理）
                pass

            return True
        except Exception:
            return False

    def get_inbox_messages(self, agent_id: str, mark_as_read: bool = False) -> list[TeamMessage]:
        """获取代理的收件箱消息"""
        inbox_path = self._inbox_path(agent_id)
        if not inbox_path.exists():
            return []

        try:
            messages = [TeamMessage.from_dict(m) for m in json.loads(inbox_path.read_text())]
            if mark_as_read:
                for msg in messages:
                    msg.read = True
                self._save_inbox_messages(agent_id, messages)
            return messages
        except Exception:
            return []

    def get_sent_messages(self, agent_id: str) -> list[TeamMessage]:
        """获取代理的已发送消息"""
        sent_path = self._sent_path(agent_id)
        if not sent_path.exists():
            return []

        try:
            return [TeamMessage.from_dict(m) for m in json.loads(sent_path.read_text())]
        except Exception:
            return []

    def _save_inbox_messages(self, agent_id: str, messages: list[TeamMessage]) -> None:
        """保存收件箱消息"""
        inbox_path = self._inbox_path(agent_id)
        inbox_path.write_text(json.dumps([m.to_dict() for m in messages], indent=2))

    def mark_as_delivered(self, agent_id: str, message_id: str) -> bool:
        """标记消息为已送达"""
        messages = self.get_inbox_messages(agent_id)
        for msg in messages:
            if msg.id == message_id:
                msg.delivered = True
                self._save_inbox_messages(agent_id, messages)
                return True
        return False

    def mark_as_notified(self, agent_id: str, message_id: str) -> bool:
        """标记消息为已通知"""
        messages = self.get_inbox_messages(agent_id)
        for msg in messages:
            if msg.id == message_id:
                msg.notified = True
                self._save_inbox_messages(agent_id, messages)
                return True
        return False

    def get_unread_messages(self, agent_id: str) -> list[TeamMessage]:
        """获取未读消息"""
        messages = self.get_inbox_messages(agent_id)
        return [msg for msg in messages if not msg.read]

    def clear_inbox(self, agent_id: str) -> bool:
        """清空收件箱"""
        inbox_path = self._inbox_path(agent_id)
        if inbox_path.exists():
            inbox_path.write_text("[]")
            return True
        return False


def send_direct_message(
    from_agent: str,
    to_agent: str,
    message_type: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> bool:
    """发送直接消息"""
    store = MailboxStore(Path.cwd() / ".clawd")
    message = TeamMessage(
        from_id=from_agent,
        to_id=to_agent,
        message_type=message_type,
        content=content,
        metadata=metadata or {},
        correlation_id=correlation_id,
    )
    return store.send_message(message)


def broadcast_message(
    from_agent: str,
    message_type: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """广播消息"""
    store = MailboxStore(Path.cwd() / ".clawd")
    message = TeamMessage(
        from_id=from_agent,
        to_id="",  # 空表示广播
        message_type=message_type,
        content=content,
        metadata=metadata or {},
    )
    return store.send_message(message)


def send_task_assign(
    from_agent: str,
    to_agent: str,
    task_id: str,
    task_description: str,
) -> bool:
    """发送任务分配消息"""
    return send_direct_message(
        from_agent=from_agent,
        to_agent=to_agent,
        message_type="task_assign",
        content=task_description,
        metadata={"task_id": task_id},
    )


def send_task_result(
    from_agent: str,
    to_agent: str,
    task_id: str,
    result: str,
    success: bool = True,
) -> bool:
    """发送任务结果消息"""
    return send_direct_message(
        from_agent=from_agent,
        to_agent=to_agent,
        message_type="task_result",
        content=result,
        metadata={
            "task_id": task_id,
            "success": success,
        },
    )


def list_mailbox_messages(
    agent_id: str,
    include_sent: bool = False,
) -> dict[str, list[TeamMessage]]:
    """列出代理的邮箱消息"""
    store = MailboxStore(Path.cwd() / ".clawd")
    result = {
        "inbox": store.get_inbox_messages(agent_id),
    }
    if include_sent:
        result["sent"] = store.get_sent_messages(agent_id)
    return result
