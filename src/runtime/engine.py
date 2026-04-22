"""Runtime 核心类型定义

汲取 oh-my-codex-main/crates/omx-runtime-core/src/lib.rs

提供：
- 权威租赁类型 (Authority) — 谁有权执行操作
- 分派状态机 (Dispatch) — 任务流转跟踪
- 邮箱记录 (Mailbox) — 消息传递
- 重放状态 (Replay) — 事件溯源
- 快照结构 (Snapshot) — 状态序列化

作者: Kilo Code (整合 oh-my-codex 设计, 2026-04-17)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

# =============================================================================
# Authority / Leasing (权威租赁)
# =============================================================================

class AuthorityError(Exception):
    """权威租赁相关错误"""
    pass


class AuthorityLease:
    """权威租赁 — 跟踪谁拥有执行权以及租赁期限

    对应 Rust: AuthorityLease
    借鉴: omx-runtime-core/src/authority.rs
    """

    def __init__(
        self,
        owner: str | None = None,
        lease_id: str | None = None,
        leased_until: str | None = None,
    ) -> None:
        self.owner: str | None = owner
        self.lease_id: str | None = lease_id
        self.leased_until: str | None = leased_until
        self._stale: bool = False
        self._stale_reason: str | None = None

    @classmethod
    def new(cls) -> AuthorityLease:
        """创建新的空租赁"""
        return cls()

    def acquire(
        self,
        owner: str,
        lease_id: str,
        leased_until: str,
    ) -> None:
        """获取权威租赁

        Args:
            owner: 所有者标识
            lease_id: 租赁ID (用于续期/识别)
            leased_until: 租赁过期时间(ISO格式)

        Raises:
            AuthorityError: 租赁已被其他所有者持有
        """
        if self.owner is not None and self.owner != owner:
            raise AuthorityError(
                f"lease already held by {self.owner!r}, cannot acquire for {owner!r}"
            )
        self.owner = owner
        self.lease_id = lease_id
        self.leased_until = leased_until
        self._stale = False
        self._stale_reason = None

    def renew(
        self,
        owner: str,
        lease_id: str,
        leased_until: str,
    ) -> None:
        """续期权威租赁

        Args:
            owner: 所有者标识（必须与当前所有者一致）
            lease_id: 新的租赁ID
            leased_until: 新的过期时间

        Raises:
            AuthorityError: 租赁未被持有或所有者不匹配
        """
        if self.owner is None:
            raise AuthorityError("no lease currently held")
        if self.owner != owner:
            raise AuthorityError(
                f"owner mismatch: lease held by {self.owner!r}, cannot renew for {owner!r}"
            )
        self.lease_id = lease_id
        self.leased_until = leased_until
        self._stale = False
        self._stale_reason = None

    def force_release(self) -> None:
        """强制释放租赁（无论状态如何）"""
        self.owner = None
        self.lease_id = None
        self.leased_until = None
        self._stale = False
        self._stale_reason = None

    def mark_stale(self, reason: str) -> None:
        """标记租赁为过时（例如心跳超时）"""
        self._stale = True
        self._stale_reason = reason

    def clear_stale(self) -> None:
        """清除过时标记"""
        self._stale = False
        self._stale_reason = None

    def is_held(self) -> bool:
        """租赁是否被持有"""
        return self.owner is not None

    def is_stale(self) -> bool:
        """租赁是否过时"""
        return self._stale

    def current_owner(self) -> str | None:
        """获取当前所有者"""
        return self.owner

    def to_snapshot(self) -> AuthoritySnapshot:
        """导出快照"""
        return AuthoritySnapshot(
            owner=self.owner,
            lease_id=self.lease_id,
            leased_until=self.leased_until,
            stale=self._stale,
            stale_reason=self._stale_reason,
        )


# =============================================================================
# Dispatch Log (任务分派日志)
# =============================================================================

class DispatchStatus(Enum):
    """分派状态"""
    PENDING = "pending"
    NOTIFIED = "notified"
    DELIVERED = "delivered"
    FAILED = "failed"


class DispatchError(Exception):
    """分派操作错误"""
    pass


class NotFoundError(DispatchError):
    """记录未找到"""
    def __init__(self, request_id: str):
        super().__init__(f"dispatch record not found: {request_id!r}")
        self.request_id = request_id


class InvalidTransitionError(DispatchError):
    """状态转换无效"""
    def __init__(self, request_id: str, from_status: str, to_status: str):
        super().__init__(
            f"invalid transition for {request_id!r}: {from_status!r} -> {to_status!r}"
        )
        self.request_id = request_id
        self.from_status = from_status
        self.to_status = to_status


@dataclass
class DispatchRecord:
    """分派记录 — 跟踪一个任务的完整流转"""
    request_id: str
    target: str
    status: DispatchStatus
    created_at: str
    notified_at: str | None = None
    delivered_at: str | None = None
    failed_at: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] | None = None

    def can_transition_to(self, new_status: DispatchStatus) -> bool:
        """检查是否允许转换到目标状态"""
        transitions = {
            DispatchStatus.PENDING: [DispatchStatus.NOTIFIED, DispatchStatus.FAILED],
            DispatchStatus.NOTIFIED: [DispatchStatus.DELIVERED, DispatchStatus.FAILED],
            DispatchStatus.DELIVERED: [],
            DispatchStatus.FAILED: [],
        }
        return new_status in transitions.get(self.status, [])


class DispatchLog:
    """分派日志 — 维护任务分派的完整 audit trail

    对应 Rust: DispatchLog
    借鉴: omx-runtime-core/src/dispatch.rs

    状态机:
        PENDING ──(mark_notified)──> NOTIFIED ──(mark_delivered)──> DELIVERED
           │                                │
           └────────(mark_failed)──────────┘
    """

    def __init__(self) -> None:
        self._records: list[DispatchRecord] = []

    @classmethod
    def new(cls) -> DispatchLog:
        """创建新的分派日志"""
        return cls()

    def queue(
        self,
        request_id: str,
        target: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """入队一个新分派请求

        Args:
            request_id: 请求唯一标识
            target: 目标 worker/agent
            metadata: 附加的元数据（优先级、标签等）
        """
        self._records.append(DispatchRecord(
            request_id=request_id,
            target=target,
            status=DispatchStatus.PENDING,
            created_at=_now_iso(),
            metadata=metadata,
        ))

    def mark_notified(self, request_id: str, channel: str) -> None:
        """标记为已通知（worker 已收到消息）"""
        record = self._find_mut(request_id)
        if record.status != DispatchStatus.PENDING:
            raise InvalidTransitionError(
                request_id, record.status.value, DispatchStatus.NOTIFIED.value
            )
        record.status = DispatchStatus.NOTIFIED
        record.notified_at = _now_iso()
        record.reason = channel

    def mark_delivered(self, request_id: str) -> None:
        """标记为已交付（worker 完成处理）"""
        record = self._find_mut(request_id)
        if record.status != DispatchStatus.NOTIFIED:
            raise InvalidTransitionError(
                request_id, record.status.value, DispatchStatus.DELIVERED.value
            )
        record.status = DispatchStatus.DELIVERED
        record.delivered_at = _now_iso()

    def mark_failed(self, request_id: str, reason: str) -> None:
        """标记为失败"""
        record = self._find_mut(request_id)
        if record.status not in (DispatchStatus.PENDING, DispatchStatus.NOTIFIED):
            raise InvalidTransitionError(
                request_id, record.status.value, DispatchStatus.FAILED.value
            )
        record.status = DispatchStatus.FAILED
        record.failed_at = _now_iso()
        record.reason = reason

    def records(self) -> list[DispatchRecord]:
        """获取所有记录副本"""
        return list(self._records)

    def to_backlog_snapshot(self) -> BacklogSnapshot:
        """生成待办快照（用于仪表板显示）"""
        snap = BacklogSnapshot()
        for record in self._records:
            if record.status == DispatchStatus.PENDING:
                snap.pending += 1
            elif record.status == DispatchStatus.NOTIFIED:
                snap.notified += 1
            elif record.status == DispatchStatus.DELIVERED:
                snap.delivered += 1
            elif record.status == DispatchStatus.FAILED:
                snap.failed += 1
        return snap

    def _find_mut(self, request_id: str) -> DispatchRecord:
        """查找并返回可变记录引用"""
        for record in self._records:
            if record.request_id == request_id:
                return record
        raise NotFoundError(request_id)

    def compact(self, keep_pending: bool = True) -> None:
        """压缩日志 — 清理已达 terminal 状态的记录

        Args:
            keep_pending: 是否保持 pending 状态记录（通常为 True）
        """
        terminal_statuses = {DispatchStatus.DELIVERED, DispatchStatus.FAILED}
        self._records = [
            r for r in self._records
            if (keep_pending and r.status == DispatchStatus.PENDING)
            or r.status not in terminal_statuses
        ]


# =============================================================================
# Mailbox (消息邮箱)
# =============================================================================

class MailboxError(Exception):
    """邮箱操作错误"""
    pass


class MailboxNotFoundError(MailboxError):
    """消息未找到"""
    def __init__(self, message_id: str):
        super().__init__(f"mailbox record not found: {message_id!r}")
        self.message_id = message_id


class AlreadyDeliveredError(MailboxError):
    """消息已被投递"""
    def __init__(self, message_id: str):
        super().__init__(f"mailbox message already delivered: {message_id!r}")
        self.message_id = message_id


@dataclass
class MailboxRecord:
    """邮箱记录 — 跨 worker 的消息传递"""
    message_id: str
    from_worker: str
    to_worker: str
    body: str
    created_at: str
    notified_at: str | None = None
    delivered_at: str | None = None


class MailboxLog:
    """邮箱日志 — 可靠的消息传递与确认

    对应 Rust: MailboxLog
    借鉴: omx-runtime-core/src/mailbox.rs

    生命周期: created → notified → delivered
    """

    def __init__(self) -> None:
        self._records: list[MailboxRecord] = []

    @classmethod
    def new(cls) -> MailboxLog:
        return cls()

    def create(
        self,
        message_id: str,
        from_worker: str,
        to_worker: str,
        body: str,
    ) -> None:
        """创建一条新消息

        Args:
            message_id: 消息唯一标识
            from_worker: 发件人
            to_worker: 收件人
            body: 消息内容
        """
        self._records.append(MailboxRecord(
            message_id=message_id,
            from_worker=from_worker,
            to_worker=to_worker,
            body=body,
            created_at=_now_iso(),
        ))

    def mark_notified(self, message_id: str) -> None:
        """标记消息已通知（收件人已收到）"""
        record = self._find_mut(message_id)
        if record.delivered_at is not None:
            raise AlreadyDeliveredError(message_id)
        record.notified_at = _now_iso()

    def mark_delivered(self, message_id: str) -> None:
        """标记消息已投递（收件人已处理）"""
        record = self._find_mut(message_id)
        if record.delivered_at is not None:
            raise AlreadyDeliveredError(message_id)
        record.delivered_at = _now_iso()

    def records(self) -> list[MailboxRecord]:
        """获取所有记录"""
        return list(self._records)

    def _find_mut(self, message_id: str) -> MailboxRecord:
        """查找记录"""
        for record in self._records:
            if record.message_id == message_id:
                return record
        raise MailboxNotFoundError(message_id)


# =============================================================================
# Replay State (重放状态 — 事件溯源)
# =============================================================================

@dataclass
class ReplayState:
    """重放状态 — 跟踪待重放的事件

    对应 Rust: ReplayState
    借鉴: omx-runtime-core/src/replay.rs
    """
    cursor: str | None = None
    pending_events: int = 0
    last_replayed_event_id: str | None = None
    deferred_leader_notification: bool = False

    @classmethod
    def new(cls) -> ReplayState:
        return cls()

    def queue_event(self) -> None:
        """入队一个新事件等待重放"""
        self.pending_events += 1

    def mark_replayed(self, event_id: str) -> None:
        """标记事件已重放"""
        if self.pending_events > 0:
            self.pending_events -= 1
        self.last_replayed_event_id = event_id

    def defer_leader_notification(self) -> None:
        """推迟主线程通知"""
        self.deferred_leader_notification = True

    def clear_deferred_leader_notification(self) -> None:
        """清除推迟标记"""
        self.deferred_leader_notification = False

    def to_snapshot(self) -> ReplaySnapshot:
        """导出快照"""
        return ReplaySnapshot(
            cursor=self.cursor,
            pending_events=self.pending_events,
            last_replayed_event_id=self.last_replayed_event_id,
            deferred_leader_notification=self.deferred_leader_notification,
        )


# =============================================================================
# Snapshots (状态快照)
# =============================================================================

@dataclass
class AuthoritySnapshot:
    """权威快照（可序列化）"""
    owner: str | None = None
    lease_id: str | None = None
    leased_until: str | None = None
    stale: bool = False
    stale_reason: str | None = None

    def is_held(self) -> bool:
        return self.owner is not None


@dataclass
class BacklogSnapshot:
    """待办快照 — 分派状态计数"""
    pending: int = 0
    notified: int = 0
    delivered: int = 0
    failed: int = 0

    def __str__(self) -> str:
        return (
            f"pending={self.pending} notified={self.notified} "
            f"delivered={self.delivered} failed={self.failed}"
        )


@dataclass
class ReplaySnapshot:
    """重放快照"""
    cursor: str | None = None
    pending_events: int = 0
    last_replayed_event_id: str | None = None
    deferred_leader_notification: bool = False

    def __str__(self) -> str:
        return (
            f"cursor={self.cursor or 'none'} "
            f"pending_events={self.pending_events} "
            f"last_replayed={self.last_replayed_event_id or 'none'} "
            f"deferred={self.deferred_leader_notification}"
        )


@dataclass
class ReadinessSnapshot:
    """就绪状态快照"""
    ready: bool = False
    reasons: list[str] = field(default_factory=list)

    @classmethod
    def ready(cls) -> ReadinessSnapshot:
        return cls(ready=True, reasons=[])

    @classmethod
    def blocked(cls, reason: str) -> ReadinessSnapshot:
        return cls(ready=False, reasons=[reason])

    def add_reason(self, reason: str) -> None:
        self.ready = False
        self.reasons.append(reason)

    def __str__(self) -> str:
        if self.ready:
            return "ready"
        return f"blocked({'; '.join(self.reasons)})"


@dataclass
class RuntimeSnapshot:
    """运行时整体快照 — 单一序列化点"""
    schema_version: int
    authority: AuthoritySnapshot
    backlog: BacklogSnapshot
    replay: ReplaySnapshot
    readiness: ReadinessSnapshot

    def ready(self) -> bool:
        return self.readiness.ready

    def __str__(self) -> str:
        return (
            f"schema={self.schema_version} "
            f"authority={self.authority} "
            f"backlog={self.backlog} "
            f"replay={self.replay} "
            f"readiness={self.readiness}"
        )


# =============================================================================
# Runtime Events (运行时事件)
# =============================================================================

class RuntimeEvent:
    """运行时事件的基类（用于事件序列化）"""
    pass


@dataclass
class AuthorityAcquiredEvent(RuntimeEvent):
    """权威获取事件"""
    owner: str
    lease_id: str
    leased_until: str


@dataclass
class AuthorityRenewedEvent(RuntimeEvent):
    """权威续期事件"""
    owner: str
    lease_id: str
    leased_until: str


@dataclass
class DispatchQueuedEvent(RuntimeEvent):
    """任务入队事件"""
    request_id: str
    target: str
    metadata: dict[str, Any] | None = None


@dataclass
class DispatchNotifiedEvent(RuntimeEvent):
    """任务已通知事件"""
    request_id: str
    channel: str


@dataclass
class DispatchDeliveredEvent(RuntimeEvent):
    """任务已交付事件"""
    request_id: str


@dataclass
class DispatchFailedEvent(RuntimeEvent):
    """任务失败事件"""
    request_id: str
    reason: str


@dataclass
class ReplayRequestedEvent(RuntimeEvent):
    """重放请求事件"""
    cursor: str | None = None


class SnapshotCapturedEvent(RuntimeEvent):
    """快照捕获事件"""
    pass


@dataclass
class MailboxMessageCreatedEvent(RuntimeEvent):
    """邮箱消息创建事件"""
    message_id: str
    from_worker: str
    to_worker: str


@dataclass
class MailboxNotifiedEvent(RuntimeEvent):
    """邮箱消息已通知事件"""
    message_id: str


@dataclass
class MailboxDeliveredEvent(RuntimeEvent):
    """邮箱消息已投递事件"""
    message_id: str


# =============================================================================
# Runtime Commands (运行时命令)
# =============================================================================

class RuntimeCommand:
    """运行时命令的基类"""
    pass


@dataclass
class AcquireAuthorityCommand(RuntimeCommand):
    """获取权威命令"""
    owner: str
    lease_id: str
    leased_until: str


@dataclass
class RenewAuthorityCommand(RuntimeCommand):
    """续期权威命令"""
    owner: str
    lease_id: str
    leased_until: str


@dataclass
class QueueDispatchCommand(RuntimeCommand):
    """入队分派命令"""
    request_id: str
    target: str
    metadata: dict[str, Any] | None = None


@dataclass
class MarkNotifiedCommand(RuntimeCommand):
    """标记已通知命令"""
    request_id: str
    channel: str


@dataclass
class MarkDeliveredCommand(RuntimeCommand):
    """标记已交付命令"""
    request_id: str


@dataclass
class MarkFailedCommand(RuntimeCommand):
    """标记失败命令"""
    request_id: str
    reason: str


@dataclass
class RequestReplayCommand(RuntimeCommand):
    """请求重放命令"""
    cursor: str | None = None


class CaptureSnapshotCommand(RuntimeCommand):
    """捕获快照命令"""
    pass


@dataclass
class CreateMailboxMessageCommand(RuntimeCommand):
    """创建邮箱消息命令"""
    message_id: str
    from_worker: str
    to_worker: str
    body: str


@dataclass
class MarkMailboxNotifiedCommand(RuntimeCommand):
    """标记邮箱已通知命令"""
    message_id: str


@dataclass
class MarkMailboxDeliveredCommand(RuntimeCommand):
    """标记邮箱已投递命令"""
    message_id: str


# =============================================================================
# Export / Constants
# =============================================================================

RUNTIME_SCHEMA_VERSION = 1

RUNTIME_COMMAND_NAMES = [
    "acquire-authority",
    "renew-authority",
    "queue-dispatch",
    "mark-notified",
    "mark-delivered",
    "mark-failed",
    "request-replay",
    "capture-snapshot",
    "create-mailbox-message",
    "mark-mailbox-notified",
    "mark-mailbox-delivered",
]

RUNTIME_EVENT_NAMES = [
    "authority-acquired",
    "authority-renewed",
    "dispatch-queued",
    "dispatch-notified",
    "dispatch-delivered",
    "dispatch-failed",
    "replay-requested",
    "snapshot-captured",
    "mailbox-message-created",
    "mailbox-notified",
    "mailbox-delivered",
]


# =============================================================================
# Helper Functions
# =============================================================================

def _now_iso() -> str:
    """当前时间的 ISO 8601 格式字符串（毫秒精度）"""
    return datetime.now().isoformat(timespec="milliseconds") + "Z"


def derive_readiness(
    authority: AuthorityLease,
    dispatch: DispatchLog,
    replay: ReplayState,
) -> ReadinessSnapshot:
    """计算系统就绪状态

    就绪条件：
    1. 权威租赁已被获取
    2. 权威未过时
    3. 重放无待处理事件

    Args:
        authority: 权威租赁
        dispatch: 分派日志（用于未来扩展）
        replay: 重放状态

    Returns:
        就绪快照
    """
    reasons: list[str] = []

    if not authority.is_held():
        reasons.append("authority lease not acquired")
    elif authority.is_stale():
        stale_detail = authority._stale_reason or "unknown"
        reasons.append(f"authority lease is stale: {stale_detail}")

    if replay.pending_events > 0:
        reasons.append(f"replay has {replay.pending_events} pending events")

    if reasons:
        snap = ReadinessSnapshot.blocked(reasons[0])
        for reason in reasons[1:]:
            snap.add_reason(reason)
        return snap
    return ReadinessSnapshot.ready()


# =============================================================================
# Runtime Engine (核心引擎)
# =============================================================================

class EngineError(Exception):
    """RuntimeEngine 顶层错误"""
    pass


class RuntimeEngine:
    """运行时引擎 — 统一协调 authority, dispatch, mailbox, replay 状态

    对应 Rust: RuntimeEngine
    借鉴: omx-runtime-core/src/engine.rs

    职责:
        - 处理运行时命令（acquire-authority, queue-dispatch 等）
        - 生成事件日志（用于审计、回放、调试）
        - 持久化状态快照（支持进程崩溃恢复）
        - 提供系统就绪度检查（readiness）

    使用示例:
        >>> engine = RuntimeEngine.with_state_dir(".clawd/runtime")
        >>> engine.process(AcquireAuthorityCommand(...))
        >>> snap = engine.snapshot()
        >>> engine.persist()
    """

    SCHEMA_VERSION = RUNTIME_SCHEMA_VERSION

    def __init__(
        self,
        authority: AuthorityLease | None = None,
        dispatch: DispatchLog | None = None,
        mailbox: MailboxLog | None = None,
        replay: ReplayState | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self.authority = authority or AuthorityLease()
        self.dispatch = dispatch or DispatchLog()
        self.mailbox = mailbox or MailboxLog()
        self.replay = replay or ReplayState()
        self.event_log: list[RuntimeEvent] = []
        self._state_dir = state_dir

    @classmethod
    def new(cls) -> RuntimeEngine:
        """创建全新的引擎实例（无状态目录）"""
        return cls()

    @classmethod
    def with_state_dir(cls, state_dir: str | Path) -> RuntimeEngine:
        """创建引擎并配置状态持久化目录"""
        path = Path(state_dir)
        return cls(state_dir=path)

    # ==================== 命令处理 (Command Handler) ====================

    def process(self, command: RuntimeCommand) -> RuntimeEvent:
        """处理运行时命令并返回对应事件"""
        event: RuntimeEvent

        if isinstance(command, AcquireAuthorityCommand):
            self.authority.acquire(command.owner, command.lease_id, command.leased_until)
            event = AuthorityAcquiredEvent(command.owner, command.lease_id, command.leased_until)

        elif isinstance(command, RenewAuthorityCommand):
            self.authority.renew(command.owner, command.lease_id, command.leased_until)
            event = AuthorityRenewedEvent(command.owner, command.lease_id, command.leased_until)

        elif isinstance(command, QueueDispatchCommand):
            self.dispatch.queue(request_id=command.request_id, target=command.target, metadata=command.metadata)
            event = DispatchQueuedEvent(request_id=command.request_id, target=command.target, metadata=command.metadata)

        elif isinstance(command, MarkNotifiedCommand):
            self.dispatch.mark_notified(command.request_id, command.channel)
            event = DispatchNotifiedEvent(request_id=command.request_id, channel=command.channel)

        elif isinstance(command, MarkDeliveredCommand):
            self.dispatch.mark_delivered(command.request_id)
            event = DispatchDeliveredEvent(request_id=command.request_id)

        elif isinstance(command, MarkFailedCommand):
            self.dispatch.mark_failed(command.request_id, command.reason)
            event = DispatchFailedEvent(request_id=command.request_id, reason=command.reason)

        elif isinstance(command, RequestReplayCommand):
            self.replay.queue_event()
            self.replay.cursor = command.cursor
            event = ReplayRequestedEvent(cursor=command.cursor)

        elif isinstance(command, CaptureSnapshotCommand):
            event = SnapshotCapturedEvent()

        elif isinstance(command, CreateMailboxMessageCommand):
            self.mailbox.create(message_id=command.message_id, from_worker=command.from_worker, to_worker=command.to_worker, body=command.body)
            event = MailboxMessageCreatedEvent(message_id=command.message_id, from_worker=command.from_worker, to_worker=command.to_worker)

        elif isinstance(command, MarkMailboxNotifiedCommand):
            self.mailbox.mark_notified(command.message_id)
            event = MailboxNotifiedEvent(message_id=command.message_id)

        elif isinstance(command, MarkMailboxDeliveredCommand):
            self.mailbox.mark_delivered(command.message_id)
            event = MailboxDeliveredEvent(message_id=command.message_id)

        else:
            raise EngineError(f"Unknown command type: {type(command).__name__}")

        self.event_log.append(event)
        return event

    # ==================== 状态查询 ====================

    def snapshot(self) -> RuntimeSnapshot:
        """获取当前运行时状态的快照"""
        return RuntimeSnapshot(
            schema_version=self.SCHEMA_VERSION,
            authority=self.authority.to_snapshot(),
            backlog=self.dispatch.to_backlog_snapshot(),
            replay=self.replay.to_snapshot(),
            readiness=derive_readiness(self.authority, self.dispatch, self.replay),
        )

    def is_ready(self) -> bool:
        """系统是否已就绪（可安全执行任务）"""
        return self.snapshot().ready()

    def get_readiness(self) -> ReadinessSnapshot:
        """获取详细的就绪度信息"""
        return derive_readiness(self.authority, self.dispatch, self.replay)

    def get_event_log(self) -> list[RuntimeEvent]:
        """获取事件日志副本"""
        return list(self.event_log)

    # ==================== 持久化 ====================

    def persist(self) -> None:
        """将引擎状态持久化到磁盘"""
        if self._state_dir is None:
            raise EngineError("no state_dir configured: use with_state_dir()")


        self._ensure_state_dir()
        self._acquire_lock()

        try:
            snapshot_path = self._state_dir / "snapshot.json"
            snap_dict = asdict(self.snapshot())
            snapshot_path.write_text(json.dumps(snap_dict, indent=2, default=_json_default), encoding="utf-8")

            events_path = self._state_dir / "events.json"
            events_list = [_event_to_dict(e) for e in self.event_log]
            events_path.write_text(json.dumps(events_list, indent=2, default=_json_default), encoding="utf-8")

            mailbox_path = self._state_dir / "mailbox.json"
            mailbox_data = {"records": [r.__dict__ for r in self.mailbox.records()]}
            mailbox_path.write_text(json.dumps(mailbox_data, indent=2, default=_json_default), encoding="utf-8")

        finally:
            self._release_lock()

    def write_compatibility_view(self) -> None:
        """写入兼容性视图文件（供其他语言读取）"""
        if self._state_dir is None:
            raise EngineError("no state_dir configured")


        self._ensure_state_dir()
        snap = self.snapshot()

        (self._state_dir / "authority.json").write_text(
            json.dumps(asdict(snap.authority), indent=2, default=_json_default), encoding="utf-8"
        )
        (self._state_dir / "backlog.json").write_text(
            json.dumps(asdict(snap.backlog), indent=2, default=_json_default), encoding="utf-8"
        )
        (self._state_dir / "readiness.json").write_text(
            json.dumps(asdict(snap.readiness), indent=2, default=_json_default), encoding="utf-8"
        )
        (self._state_dir / "replay.json").write_text(
            json.dumps(asdict(snap.replay), indent=2, default=_json_default), encoding="utf-8"
        )

        dispatch_data = {"records": [r.__dict__ for r in self.dispatch.records()]}
        (self._state_dir / "dispatch.json").write_text(
            json.dumps(dispatch_data, indent=2, default=_json_default), encoding="utf-8"
        )

        mailbox_data = {"records": [r.__dict__ for r in self.mailbox.records()]}
        (self._state_dir / "mailbox.json").write_text(
            json.dumps(mailbox_data, indent=2, default=_json_default), encoding="utf-8"
        )

    def compact(self) -> None:
        """压缩事件日志 — 清理已达 terminal 状态的分派事件"""
        terminal_statuses = {DispatchStatus.DELIVERED, DispatchStatus.FAILED}
        self.event_log = [
            ev for ev in self.event_log
            if not (
                isinstance(ev, DispatchQueuedEvent)
                and any(
                    r.status in terminal_statuses
                    for r in self.dispatch.records()
                    if r.request_id == ev.request_id
                )
            )
        ]

    @classmethod
    def load(cls, state_dir: str | Path) -> RuntimeEngine:
        """从磁盘加载引擎状态"""

        p = Path(state_dir)
        if not p.exists():
            raise EngineError(f"state directory not found: {state_dir}")

        events_path = p / "events.json"
        if not events_path.exists():
            raise EngineError(f"events.json not found in {state_dir}")

        events_data = json.loads(events_path.read_text(encoding="utf-8"))

        engine = cls.new().with_state_dir(p)

        for event_dict in events_data:
            event = _deserialize_event(event_dict)
            engine._replay_event(event)
            engine.event_log.append(event)

        logger = __import__('logging').getLogger(__name__)
        logger.info(f"RuntimeEngine loaded from {state_dir}: {len(events_data)} events")
        return engine

    def _replay_event(self, event: RuntimeEvent) -> None:
        """将单个事件应用到状态机（用于 load 重建）"""
        if isinstance(event, AuthorityAcquiredEvent):
            self.authority.acquire(event.owner, event.lease_id, event.leased_until)
        elif isinstance(event, AuthorityRenewedEvent):
            self.authority.renew(event.owner, event.lease_id, event.leased_until)
        elif isinstance(event, DispatchQueuedEvent):
            self.dispatch.queue(request_id=event.request_id, target=event.target, metadata=event.metadata)
        elif isinstance(event, DispatchNotifiedEvent):
            self.dispatch.mark_notified(event.request_id, event.channel)
        elif isinstance(event, DispatchDeliveredEvent):
            self.dispatch.mark_delivered(event.request_id)
        elif isinstance(event, DispatchFailedEvent):
            self.dispatch.mark_failed(event.request_id, event.reason)
        elif isinstance(event, ReplayRequestedEvent):
            self.replay.queue_event()
            self.replay.cursor = event.cursor
        elif isinstance(event, MailboxMessageCreatedEvent):
            self.mailbox.create(message_id=event.message_id, from_worker=event.from_worker, to_worker=event.to_worker, body="")
        elif isinstance(event, MailboxNotifiedEvent):
            self.mailbox.mark_notified(event.message_id)
        elif isinstance(event, MailboxDeliveredEvent):
            self.mailbox.mark_delivered(event.message_id)
        # SnapshotCapturedEvent 无状态变更，忽略

    # ==================== 工具方法 ====================

    def _ensure_state_dir(self) -> None:
        assert self._state_dir is not None
        self._state_dir.mkdir(parents=True, exist_ok=True)

    def _acquire_lock(self) -> None:
        lock_file = self._state_dir / "engine.lock"
        try:
            lock_file.touch(exist_ok=False)
        except FileExistsError:
            pass  # 锁冲突在真实环境应重试

    def _release_lock(self) -> None:
        lock_file = self._state_dir / "engine.lock"
        try:
            lock_file.unlink(missing_ok=True)
        except Exception:
            pass


# =============================================================================
# JSON 序列化辅助
# =============================================================================

def _now_iso() -> str:
    """当前时间的 ISO 8601 格式字符串（毫秒精度）"""
    return datetime.now().isoformat(timespec="milliseconds") + "Z"


def _json_default(obj: Any) -> Any:
    """JSON 序列化默认处理器"""
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


def _event_to_dict(event: RuntimeEvent) -> dict[str, Any]:
    """将 RuntimeEvent 转换为字典（用于 JSON 序列化）"""
    if hasattr(event, "__dict__"):
        d = event.__dict__.copy()
        d["__type__"] = type(event).__name__
        return d
    return {"__type__": type(event).__name__}


def _deserialize_event(data: dict[str, Any]) -> RuntimeEvent:
    """从字典反序列化为 RuntimeEvent"""
    event_type = data.get("__type__", "")

    event_map: dict[str, type[RuntimeEvent]] = {
        "AuthorityAcquiredEvent": AuthorityAcquiredEvent,
        "AuthorityRenewedEvent": AuthorityRenewedEvent,
        "DispatchQueuedEvent": DispatchQueuedEvent,
        "DispatchNotifiedEvent": DispatchNotifiedEvent,
        "DispatchDeliveredEvent": DispatchDeliveredEvent,
        "DispatchFailedEvent": DispatchFailedEvent,
        "ReplayRequestedEvent": ReplayRequestedEvent,
        "SnapshotCapturedEvent": SnapshotCapturedEvent,
        "MailboxMessageCreatedEvent": MailboxMessageCreatedEvent,
        "MailboxNotifiedEvent": MailboxNotifiedEvent,
        "MailboxDeliveredEvent": MailboxDeliveredEvent,
    }

    cls = event_map.get(event_type)
    if cls is None:
        # 未知事件类型，返回基类占位
        return RuntimeEvent()  # type: ignore[return-value]

    field_names = {f.name for f in getattr(cls, "__dataclass_fields__", [])}
    init_args = {k: v for k, v in data.items() if k in field_names}
    return cls(**init_args)  # type: ignore[arg-type]


def derive_readiness(
    authority: AuthorityLease,
    dispatch: DispatchLog,
    replay: ReplayState,
) -> ReadinessSnapshot:
    """计算系统就绪状态"""
    reasons: list[str] = []

    if not authority.is_held():
        reasons.append("authority lease not acquired")
    elif authority.is_stale():
        stale_detail = authority._stale_reason or "unknown"
        reasons.append(f"authority lease is stale: {stale_detail}")

    if replay.pending_events > 0:
        reasons.append(f"replay has {replay.pending_events} pending events")

    if reasons:
        snap = ReadinessSnapshot.blocked(reasons[0])
        for reason in reasons[1:]:
            snap.add_reason(reason)
        return snap
    return ReadinessSnapshot.ready()


# =============================================================================
# Export / Constants
# =============================================================================

__all__ = [
    "RUNTIME_COMMAND_NAMES",
    "RUNTIME_EVENT_NAMES",
    "RUNTIME_SCHEMA_VERSION",
    "AcquireAuthorityCommand",
    "AlreadyDeliveredError",
    "AuthorityAcquiredEvent",
    "AuthorityError",
    # Authority
    "AuthorityLease",
    "AuthorityRenewedEvent",
    # Snapshots
    "AuthoritySnapshot",
    "BacklogSnapshot",
    "CaptureSnapshotCommand",
    "CreateMailboxMessageCommand",
    "DispatchDeliveredEvent",
    "DispatchError",
    "DispatchFailedEvent",
    # Dispatch
    "DispatchLog",
    "DispatchNotifiedEvent",
    "DispatchQueuedEvent",
    "DispatchRecord",
    "DispatchStatus",
    "EngineError",
    "InvalidTransitionError",
    "MailboxDeliveredEvent",
    "MailboxError",
    # Mailbox
    "MailboxLog",
    "MailboxMessageCreatedEvent",
    "MailboxNotFoundError",
    "MailboxNotifiedEvent",
    "MailboxRecord",
    "MarkDeliveredCommand",
    "MarkFailedCommand",
    "MarkMailboxDeliveredCommand",
    "MarkMailboxNotifiedCommand",
    "MarkNotifiedCommand",
    "NotFoundError",
    "QueueDispatchCommand",
    "ReadinessSnapshot",
    "RenewAuthorityCommand",
    "ReplayRequestedEvent",
    "ReplaySnapshot",
    # Replay
    "ReplayState",
    "RequestReplayCommand",
    "RuntimeCommand",
    # Engine
    "RuntimeEngine",
    # Events & Commands
    "RuntimeEvent",
    "RuntimeSnapshot",
    "SnapshotCapturedEvent",
    # Utilities
    "derive_readiness",
]
