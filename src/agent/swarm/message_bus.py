"""Agent 间消息总线"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    """消息类型"""
    TASK_ASSIGN = "task_assign"          # 分配任务
    TASK_SUBMIT = "task_submit"          # 提交结果
    AUDIT_REQUEST = "audit_request"      # 请求审计
    AUDIT_PASS = "audit_pass"            # 审计通过
    AUDIT_FAIL = "audit_fail"            # 审计驳回
    REVIEW_REQUEST = "review_request"    # 请求审查
    REVIEW_PASS = "review_pass"          # 审查通过
    REVIEW_FAIL = "review_fail"          # 审查驳回
    INTEGRATE_REQUEST = "integrate_request"  # 请求集成
    INTEGRATE_PASS = "integrate_pass"    # 集成通过
    INTEGRATE_FAIL = "integrate_fail"    # 集成失败
    STATUS_UPDATE = "status_update"      # 状态更新
    SYNC_STATE = "sync_state"            # 状态同步 (NEW: Master-Worker)
    TX_SYNC = "tx_sync"                  # 事务同步 (NEW: Integrator Transaction)
    ERROR = "error"                      # 错误


@dataclass
class AgentMessage:
    """Agent 间消息"""
    sender: str                    # 发送 Agent ID
    recipient: str                 # 接收 Agent ID
    message_type: MessageType      # 消息类型
    content: str                   # 消息内容
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    message_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    correlation_id: str = ""       # 关联同一任务的消息

    def reply(self, message_type: MessageType, content: str, **kwargs: Any) -> AgentMessage:
        """创建回复消息"""
        return AgentMessage(
            sender=self.recipient,
            recipient=self.sender,
            message_type=message_type,
            content=content,
            correlation_id=self.correlation_id or self.message_id,
            **kwargs,
        )


class MessageBus:
    """Agent 间消息总线

    支持:
    - 发布/订阅模式
    - 消息过滤
    - 异步处理
    """

    def __init__(self) -> None:
        self._subscribers: dict[MessageType, list[Callable]] = {}
        self._message_history: list[AgentMessage] = []
        self._max_history = 1000

    def subscribe(self, message_type: MessageType, callback: Callable) -> None:
        """订阅消息

        参数:
            message_type: 消息类型
            callback: 回调函数 (message: AgentMessage) -> None
        """
        if message_type not in self._subscribers:
            self._subscribers[message_type] = []
        self._subscribers[message_type].append(callback)

    def unsubscribe(self, message_type: MessageType, callback: Callable) -> None:
        """取消订阅"""
        if message_type in self._subscribers:
            self._subscribers[message_type] = [
                cb for cb in self._subscribers[message_type] if cb != callback
            ]

    async def publish(self, message: AgentMessage) -> None:
        """发布消息

        参数:
            message: 消息对象
        """
        # 记录历史
        self._message_history.append(message)
        if len(self._message_history) > self._max_history:
            self._message_history = self._message_history[-self._max_history:]

        # 通知订阅者
        callbacks = self._subscribers.get(message.message_type, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(message)
                else:
                    callback(message)
            except Exception as e:
                logger.error(f'消息处理失败: {e}')

    def get_messages(self, correlation_id: str) -> list[AgentMessage]:
        """获取关联消息"""
        return [
            msg for msg in self._message_history
            if msg.correlation_id == correlation_id or msg.message_id == correlation_id
        ]

    def get_messages_by_type(self, message_type: MessageType) -> list[AgentMessage]:
        """获取指定类型的消息"""
        return [msg for msg in self._message_history if msg.message_type == message_type]

    def clear_history(self) -> None:
        """清空历史"""
        self._message_history.clear()
