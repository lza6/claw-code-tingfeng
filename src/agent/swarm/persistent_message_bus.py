"""
Persistent Message Bus - 持久化消息总线

[Phase 2] 集成 GoalX 风格的 Control Inbox 到现有 MessageBus。
保留现有内存消息总线的所有功能，同时添加磁盘持久化。

设计策略:
- Memory-first: 所有消息仍在内存中 (保持现有性能)
- Disk-backed: 关键消息同时持久化到 JSONL 文件
- 向后兼容: 完全兼容现有 MessageBus API
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .control.inbox import ControlSystem, Message, MessagePriority
from .message_bus import AgentMessage, MessageBus, MessageType

logger = logging.getLogger(__name__)

# 消息类型到优先级的映射
_PRIORITY_MAP = {
    MessageType.ERROR: MessagePriority.CRITICAL,
    MessageType.STATUS_UPDATE: MessagePriority.URGENT,
    MessageType.REVIEW_FAIL: MessagePriority.URGENT,
    MessageType.INTEGRATE_FAIL: MessagePriority.URGENT,
    MessageType.AUDIT_FAIL: MessagePriority.URGENT,
}


class PersistentMessageBus:
    """
    持久化消息总线 - 包装现有 MessageBus + 添加持久化后端

    用法:
        # 创建 (自动持久化)
        bus = PersistentMessageBus(storage_dir=Path(".clawd/runs/run-123/control"))

        # 发送消息 (自动持久化)
        await bus.publish(message)

        # 读取历史消息 (从磁盘加载)
        history = bus.get_persistent_history("session-1")

        # 获取未读消息
        unread = bus.get_unread_messages("master")
    """

    def __init__(
        self,
        storage_dir: Path | None = None,
        inner_bus: MessageBus | None = None,
    ) -> None:
        """
        初始化持久化消息总线。

        Args:
            storage_dir: 持久化存储目录
            inner_bus: 内部消息总线 (如果为 None 则创建新的)
        """
        self._inner_bus = inner_bus or MessageBus()
        self._control_system = None
        self._background_tasks: set[asyncio.Task] = set()

        if storage_dir is not None:
            try:
                self._control_system = ControlSystem(storage_dir)
                logger.info(f"PersistentMessageBus 已启用，存储目录: {storage_dir}")
            except Exception as e:
                logger.warning(f"无法初始化持久化存储: {e}")
                self._control_system = None
        else:
            logger.debug("PersistentMessageBus 使用内存模式 (无持久化)")

    @property
    def inner_bus(self) -> MessageBus:
        """获取内部消息总线"""
        return self._inner_bus

    @property
    def control_system(self) -> ControlSystem | None:
        """获取控制系统 (如果可用)"""
        return self._control_system

    async def publish(self, message: AgentMessage) -> None:
        """
        发布消息 (同时发送到内存和磁盘)。

        转发到内部 MessageBus，同时持久化到磁盘。
        """
        # 1. 发送到内存总线 (保持现有行为)
        await self._inner_bus.publish(message)

        # 2. 持久化到磁盘 (如果可用)
        if self._control_system:
            try:
                priority = _PRIORITY_MAP.get(
                    message.message_type, MessagePriority.NORMAL
                )

                self._control_system.send(
                    from_id=message.sender,
                    to_id=message.recipient,
                    content=message.content,
                    priority=priority,
                    metadata={
                        "message_type": message.message_type.value,
                        "message_id": message.message_id,
                        "correlation_id": message.correlation_id,
                        "timestamp": message.timestamp,
                        **message.metadata,
                    },
                )
            except Exception as e:
                logger.warning(f"消息持久化失败: {e}")

    def subscribe(self, message_type: MessageType, callback, catch_up: bool = False, recipient_id: str | None = None) -> None:
        """
        订阅消息。

        Args:
            message_type: 消息类型
            callback: 回调函数
            catch_up: 是否回溯读取磁盘上的历史消息
            recipient_id: 如果 catch_up 为 True，指定收件人 ID 以读取历史
        """
        self._inner_bus.subscribe(message_type, callback)

        if catch_up and self._control_system and recipient_id:
            history = self.get_persistent_history(recipient_id)
            for msg_data in history:
                # 检查类型匹配
                stored_type = msg_data.metadata.get("message_type")
                if stored_type == message_type.value:
                    # 构造 AgentMessage 并触发回调
                    agent_msg = AgentMessage(
                        sender=msg_data.from_id,
                        recipient=msg_data.to_id,
                        message_type=message_type,
                        content=msg_data.content,
                        metadata=msg_data.metadata,
                        timestamp=msg_data.timestamp,
                        message_id=msg_data.metadata.get("message_id", ""),
                        correlation_id=msg_data.metadata.get("correlation_id", ""),
                    )
                    import asyncio
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            task = asyncio.create_task(callback(agent_msg))
                            self._background_tasks.add(task)
                            task.add_done_callback(self._background_tasks.discard)
                        else:
                            callback(agent_msg)
                    except Exception as e:
                        logger.error(f"历史消息回溯处理失败: {e}")

    def unsubscribe(self, message_type: MessageType, callback) -> None:
        """取消订阅 (转发到内部总线)"""
        self._inner_bus.unsubscribe(message_type, callback)

    def get_unread_count(self, recipient_id: str) -> int:
        """获取收件箱的未读消息数"""
        if not self._control_system:
            return 0
        inbox = self._control_system.get_inbox(recipient_id)
        return inbox.get_unread_count()

    def get_unread_messages(self, recipient_id: str) -> list[Message]:
        """获取收件箱的未读消息"""
        if not self._control_system:
            return []
        inbox = self._control_system.get_inbox(recipient_id)
        return inbox.read_unread()

    def mark_read(self, recipient_id: str, count: int | None = None) -> None:
        """标记消息为已读"""
        if not self._control_system:
            return
        inbox = self._control_system.get_inbox(recipient_id)
        inbox.mark_read(count)

    def get_persistent_history(self, recipient_id: str) -> list[Message]:
        """获取收件箱的所有持久化消息"""
        if not self._control_system:
            return []
        inbox = self._control_system.get_inbox(recipient_id)
        return inbox.read_all()

    def has_urgent(self, recipient_id: str) -> bool:
        """检查收件箱是否有紧急消息"""
        if not self._control_system:
            return False
        inbox = self._control_system.get_inbox(recipient_id)
        return inbox.has_urgent()

    def get_urgent_messages(self, recipient_id: str) -> list[Message]:
        """获取紧急消息"""
        if not self._control_system:
            return []
        inbox = self._control_system.get_inbox(recipient_id)
        return inbox.get_urgent_messages()

    def broadcast(
        self,
        from_id: str,
        recipient_ids: list[str],
        content: str,
        message_type: MessageType = MessageType.STATUS_UPDATE,
    ) -> list[AgentMessage]:
        """
        广播消息给多个收件人。

        同时发送到内存总线和持久化存储。
        """
        messages = []
        for to_id in recipient_ids:
            msg = AgentMessage(
                sender=from_id,
                recipient=to_id,
                message_type=message_type,
                content=content,
            )
            messages.append(msg)

        # 批量持久化
        if self._control_system:
            priority = _PRIORITY_MAP.get(message_type, MessagePriority.NORMAL)
            self._control_system.broadcast(
                from_id=from_id,
                recipient_ids=recipient_ids,
                content=content,
                priority=priority,
            )

        # 异步发送到内存总线
        import asyncio

        async def _publish_all():
            await asyncio.gather(
                *(self._inner_bus.publish(msg) for msg in messages)
            )

        import contextlib
        with contextlib.suppress(RuntimeError):
            task = asyncio.get_running_loop().create_task(_publish_all())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        return messages
