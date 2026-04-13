"""BaseAgent 抽象类"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from datetime import datetime

from ...utils.tracing import traced
from .message_bus import AgentMessage, MessageBus, MessageType
from .roles import ROLE_SYSTEM_PROMPTS, AgentRole

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Agent 基类

    子类需要实现:
    - process(): 处理消息并返回结果
    """

    def __init__(
        self,
        agent_id: str,
        role: AgentRole,
        message_bus: MessageBus,
    ) -> None:
        self.agent_id = agent_id
        self.role = role
        self.message_bus = message_bus
        self.logger = logging.getLogger(f'agent.{agent_id}')
        self.system_prompt = ROLE_SYSTEM_PROMPTS.get(role, '')

        # [汲取 GoalX] 启动持久化消息监听
        self._setup_persistence()

    def _setup_persistence(self) -> None:
        """配置持久化消息监听 (汲取 GoalX Inbox 轮询/监听逻辑)"""
        from .persistent_message_bus import PersistentMessageBus
        if isinstance(self.message_bus, PersistentMessageBus):
            self.logger.debug(f"Agent {self.agent_id} 已连接到持久化总线")
            # 订阅我感兴趣的消息类型 (向后兼容)
            # 注意: 实际的 Inbox 处理可能在 PersistentMessageBus.subscribe(catch_up=True) 中

    async def poll_inbox(self) -> None:
        """[汲取 GoalX] 轮询持久化 Inbox 处理未读消息"""
        from .persistent_message_bus import PersistentMessageBus
        if isinstance(self.message_bus, PersistentMessageBus):
            unread = self.message_bus.get_unread_messages(self.agent_id)
            if unread:
                self.logger.info(f"发现 {len(unread)} 条新持久化消息")
                for msg_data in unread:
                    # 将 Message 转换为 AgentMessage
                    agent_msg = AgentMessage(
                        sender=msg_data.from_id,
                        recipient=msg_data.to_id,
                        message_type=MessageType(msg_data.metadata.get("message_type", MessageType.STATUS_UPDATE)),
                        content=msg_data.content,
                        metadata=msg_data.metadata,
                        correlation_id=msg_data.metadata.get("correlation_id", ""),
                    )
                    await self.handle_message(agent_msg)

                # 标记为已读
                self.message_bus.mark_read(self.agent_id, len(unread))

    @abstractmethod
    async def process(self, message: AgentMessage) -> str:
        """处理消息

        参数:
            message: 输入消息

        返回:
            处理结果
        """
        ...

    @traced("agent_handle_message")
    async def handle_message(self, message: AgentMessage) -> None:
        """处理消息并自动回复

        参数:
            message: 输入消息
        """
        try:
            # 记录处理开始
            self.logger.info(f"正在处理消息: {message.message_id} (类型: {message.message_type})")

            result = await self.process(message)

            # [汲取 GoalX] 根据消息类型决定回复类型
            reply_type = MessageType.STATUS_UPDATE
            if message.message_type == MessageType.TASK_ASSIGN:
                reply_type = MessageType.TASK_SUBMIT
            elif message.message_type == MessageType.AUDIT_REQUEST:
                reply_type = MessageType.AUDIT_PASS # 假设成功

            reply = message.reply(
                reply_type,
                result,
                metadata={
                    "agent_role": self.role.value,
                    "processed_at": datetime.utcnow().isoformat()
                }
            )
            await self.message_bus.publish(reply)

            # [汲取 GoalX] 如果是持久化总线，显式同步状态
            from .persistent_message_bus import PersistentMessageBus
            if isinstance(self.message_bus, PersistentMessageBus):
                sync_msg = message.reply(
                    MessageType.SYNC_STATE,
                    f"Agent {self.agent_id} completed {message.message_type}",
                    metadata={
                        "task_id": message.metadata.get("task_id", "unknown"),
                        "status": "completed",
                        "result_summary": result[:100] + "..." if len(result) > 100 else result
                    }
                )
                await self.message_bus.publish(sync_msg)

        except Exception as e:
            self.logger.error(f'处理消息失败: {e}')
            error_reply = message.reply(
                MessageType.ERROR,
                f'处理失败: {e}',
                metadata={'error': str(e)},
            )
            await self.message_bus.publish(error_reply)

    def get_info(self) -> dict[str, Any]:
        """获取 Agent 信息"""
        return {
            'agent_id': self.agent_id,
            'role': self.role.value,
            'system_prompt': self.system_prompt[:100] + '...' if len(self.system_prompt) > 100 else self.system_prompt,
        }
