"""事件系统增强 - 借鉴 oh-my-codex 的命令/事件模式

提供类型安全的命令和事件定义，支持序列化和重放。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = __import__("logging").getLogger(__name__)


class EventType(str, Enum):
    """事件类型枚举 - 扩展自现有的 EventType"""
    # 工作流事件
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_PHASE_STARTED = "workflow_phase_started"
    WORKFLOW_PHASE_COMPLETED = "workflow_phase_completed"
    WORKFLOW_TASK_STARTED = "workflow_task_started"
    WORKFLOW_TASK_COMPLETED = "workflow_task_completed"

    # 权限/命令事件 (借鉴 omx-runtime-core)
    AUTHORITY_ACQUIRED = "authority_acquired"
    AUTHORITY_RENEWED = "authority_renewed"
    DISPATCH_QUEUED = "dispatch_queued"
    DISPATCH_NOTIFIED = "dispatch_notified"
    DISPATCH_DELIVERED = "dispatch_delivered"
    DISPATCH_FAILED = "dispatch_failed"
    REPLAY_REQUESTED = "replay_requested"
    SNAPSHOT_CAPTURED = "snapshot_captured"
    MAILBOX_MESSAGE_CREATED = "mailbox_message_created"
    MAILBOX_NOTIFIED = "mailbox_notified"
    MAILBOX_DELIVERED = "mailbox_delivered"

    # 自定义业务事件
    CODE_CHANGE_DETECTED = "code_change_detected"
    TEST_RESULT_RECEIVED = "test_result_received"
    SECURITY_VIOLATION_DETECTED = "security_violation_detected"


@dataclass
class Event:
    """基础事件结构"""
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=lambda: __import__("time").time())
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        return cls(
            type=EventType(data["type"]),
            data=data.get("data", {}),
            timestamp=data.get("timestamp", __import__("time").time()),
            source=data.get("source", "unknown"),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


# 权限相关事件 (对应 omx-runtime-core 的 RuntimeEvent)
@dataclass
class AuthorityAcquiredEvent:
    owner: str
    lease_id: str
    leased_until: str

    def to_event(self) -> Event:
        return Event(
            type=EventType.AUTHORITY_ACQUIRED,
            data={
                "owner": self.owner,
                "lease_id": self.lease_id,
                "leased_until": self.leased_until,
            }
        )


@dataclass
class AuthorityRenewedEvent:
    owner: str
    lease_id: str
    leased_until: str

    def to_event(self) -> Event:
        return Event(
            type=EventType.AUTHORITY_RENEWED,
            data={
                "owner": self.owner,
                "lease_id": self.lease_id,
                "leased_until": self.leased_until,
            }
        )


# 调度相关事件
@dataclass
class DispatchQueuedEvent:
    request_id: str
    target: str
    metadata: dict[str, Any] | None = None

    def to_event(self) -> Event:
        return Event(
            type=EventType.DISPATCH_QUEUED,
            data={
                "request_id": self.request_id,
                "target": self.target,
                "metadata": self.metadata or {},
            }
        )


@dataclass
class DispatchNotifiedEvent:
    request_id: str
    channel: str

    def to_event(self) -> Event:
        return Event(
            type=EventType.DISPATCH_NOTIFIED,
            data={
                "request_id": self.request_id,
                "channel": self.channel,
            }
        )


@dataclass
class DispatchDeliveredEvent:
    request_id: str

    def to_event(self) -> Event:
        return Event(
            type=EventType.DISPATCH_DELIVERED,
            data={"request_id": self.request_id}
        )


@dataclass
class DispatchFailedEvent:
    request_id: str
    reason: str

    def to_event(self) -> Event:
        return Event(
            type=EventType.DISPATCH_FAILED,
            data={
                "request_id": self.request_id,
                "reason": self.reason,
            }
        )


# 重放相关事件
@dataclass
class ReplayRequestedEvent:
    cursor: str | None = None

    def to_event(self) -> Event:
        return Event(
            type=EventType.REPLAY_REQUESTED,
            data={"cursor": self.cursor} if self.cursor else {}
        )


@dataclass
class SnapshotCapturedEvent:
    def to_event(self) -> Event:
        return Event(type=EventType.SNAPSHOT_CAPTURED, data={})


# 邮箱相关事件 (借鉴 omx-runtime-core 的 Mailbox)
@dataclass
class MailboxMessageCreatedEvent:
    message_id: str
    from_worker: str
    to_worker: str
    body: str

    def to_event(self) -> Event:
        return Event(
            type=EventType.MAILBOX_MESSAGE_CREATED,
            data={
                "message_id": self.message_id,
                "from_worker": self.from_worker,
                "to_worker": self.to_worker,
                "body": self.body,
            }
        )


@dataclass
class MailboxNotifiedEvent:
    message_id: str

    def to_event(self) -> Event:
        return Event(
            type=EventType.MAILBOX_NOTIFIED,
            data={"message_id": self.message_id}
        )


@dataclass
class MailboxDeliveredEvent:
    message_id: str

    def to_event(self) -> Event:
        return Event(
            type=EventType.MAILBOX_DELIVERED,
            data={"message_id": self.message_id}
        )


# 事件工厂
class EventFactory:
    """事件工厂 - 简化事件创建"""

    @staticmethod
    def authority_acquired(owner: str, lease_id: str, leased_until: str) -> Event:
        return AuthorityAcquiredEvent(owner, lease_id, leased_until).to_event()

    @staticmethod
    def authority_renewed(owner: str, lease_id: str, leased_until: str) -> Event:
        return AuthorityRenewedEvent(owner, lease_id, leased_until).to_event()

    @staticmethod
    def dispatch_queued(request_id: str, target: str, metadata: dict[str, Any] | None = None) -> Event:
        return DispatchQueuedEvent(request_id, target, metadata).to_event()

    @staticmethod
    def dispatch_notified(request_id: str, channel: str) -> Event:
        return DispatchNotifiedEvent(request_id, channel).to_event()

    @staticmethod
    def dispatch_delivered(request_id: str) -> Event:
        return DispatchDeliveredEvent(request_id).to_event()

    @staticmethod
    def dispatch_failed(request_id: str, reason: str) -> Event:
        return DispatchFailedEvent(request_id, reason).to_event()

    @staticmethod
    def replay_requested(cursor: str | None = None) -> Event:
        return ReplayRequestedEvent(cursor).to_event()

    @staticmethod
    def snapshot_captured() -> Event:
        return SnapshotCapturedEvent().to_event()

    @staticmethod
    def mailbox_message_created(message_id: str, from_worker: str, to_worker: str, body: str) -> Event:
        return MailboxMessageCreatedEvent(message_id, from_worker, to_worker, body).to_event()

    @staticmethod
    def mailbox_notified(message_id: str) -> Event:
        return MailboxNotifiedEvent(message_id).to_event()

    @staticmethod
    def mailbox_delivered(message_id: str) -> Event:
        return MailboxDeliveredEvent(message_id).to_event()


# 事件总线增强
class EventBusEnhanced:
    """增强的事件总线 - 支持事件持久化和重放"""

    def __init__(self, event_bus=None):
        # 复用现有的事件总线（如果存在）
        self._event_bus = event_bus
        self._event_store: list[Event] = []
        self._max_store_size = 10000  # 防止内存无限增长

    def publish(self, event: Event) -> None:
        """发布事件到总线和存储"""
        # 存储事件（用于重放和审计）
        self._event_store.append(event)
        if len(self._event_store) > self._max_store_size:
            # 移除最旧的事件
            self._event_store = self._event_store[-self._max_store_size:]

        # 发布到现有总线（如果有）
        if self._event_bus:
            self._event_bus.publish(event)

        logger.debug(f"事件已发布: {event.type.value}")

    def publish_by_type(self, event_type: EventType, data: dict[str, Any] | None = None, source: str = "unknown") -> None:
        """便捷方法：根据类型发布事件"""
        event = Event(type=event_type, data=data or {}, source=source)
        self.publish(event)

    def get_recent_events(self, count: int = 100) -> list[Event]:
        """获取最近的N个事件"""
        return self._event_store[-count:] if self._event_store else []

    def get_events_by_type(self, event_type: EventType) -> list[Event]:
        """按类型过滤事件"""
        return [e for e in self._event_store if e.type == event_type]

    def clear_store(self) -> None:
        """清空事件存储"""
        self._event_store.clear()

    def export_events(self, filepath: str) -> None:
        """导出事件到JSON文件"""
        events_data = [e.to_dict() for e in self._event_store]
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(events_data, f, indent=2, ensure_ascii=False)
        logger.info(f"事件已导出到: {filepath} ({len(self._event_store)} 条)")

    def import_events(self, filepath: str) -> None:
        """从JSON文件导入事件"""
        try:
            with open(filepath, encoding='utf-8') as f:
                events_data = json.load(f)
            self._event_store = [Event.from_dict(data) for data in events_data]
            logger.info(f"事件已从导入: {filepath} ({len(self._event_store)} 条)")
        except Exception as e:
            logger.error(f"导入事件失败: {e}")
            raise


# 为了向后兼容，提供默认实例
default_event_bus_enhanced = EventBusEnhanced()


def get_enhanced_event_bus():
    """获取增强事件总线实例"""
    return default_event_bus_enhanced
