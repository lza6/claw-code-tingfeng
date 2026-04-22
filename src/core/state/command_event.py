"""Command-Event-Snapshot 三元状态架构 - 移植自 oh-my-codex-main

核心设计理念：
1. Command（命令） - 所有状态变更通过不可变命令对象表达
2. Event（事件） - 命令执行的结果，追加写入事件日志
3. Snapshot（快照） - 定期状态检查点，用于快速恢复

此架构提供：
- 完整事件溯源（Event Sourcing）
- 类型安全的状态转换
- 可重放的操作历史
- 审计追踪能力

来源：oh-my-codex-main/crates/omx-runtime-core/src/lib.rs
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any

# ========== 枚举定义 ==========

class CommandType(Enum):
    """
    运行时命令类型 - 10种核心操作

    所有状态变更必须通过这些命令进行，确保可追踪性
    """
    ACQUIRE_AUTHORITY = auto()       # 获取authority租约
    RENEW_AUTHORITY = auto()         # 续期租约
    RELEASE_AUTHORITY = auto()       # 释放租约
    QUEUE_DISPATCH = auto()          # 队列调度任务
    MARK_NOTIFIED = auto()           # 标记已通知worker
    MARK_DELIVERED = auto()          # 标记已完成
    MARK_FAILED = auto()             # 标记失败
    REQUEST_REPLAY = auto()          # 请求重放
    CAPTURE_SNAPSHOT = auto()        # 捕获快照
    CREATE_MAILBOX_MESSAGE = auto()  # 创建邮箱消息


class EventType(Enum):
    """
    运行时事件类型 - 对应Command的执行结果

    事件是只读的，用于：
    - 审计日志
    - 状态重放
    - 调试分析
    """
    AUTHORITY_ACQUIRED = auto()
    AUTHORITY_RENEWED = auto()
    AUTHORITY_RELEASED = auto()
    DISPATCH_QUEUED = auto()
    DISPATCH_NOTIFIED = auto()
    DISPATCH_DELIVERED = auto()
    DISPATCH_FAILED = auto()


# ========== 命令对象 ==========

WORKFLOW_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class RuntimeCommand:
    """
    不可变命令对象 - 所有指令通过此类型序列化

    设计约束：
    - command_id 全局唯一（UUID v4）
    - timestamp 精确到微秒
    - payload 必须可JSON序列化
    - source 标识命令发起者（worker_id / orchestrator）
    - correlation_id 用于追踪调用链（可选）

    序列化格式：
    {
        "command_id": "uuid",
        "command_type": "ACQUIRE_AUTHORITY",
        "timestamp": "2026-01-15T10:30:00.123456Z",
        "payload": {...},
        "source": "orchestrator-1",
        "correlation_id": "optional-chain-id"
    }
    """
    command_id: str
    command_type: CommandType
    timestamp: datetime
    payload: dict[str, Any]
    source: str
    correlation_id: str | None = None

    def serialize(self) -> str:
        """序列化为JSON字符串（用于持久化）"""
        obj = {
            'command_id': self.command_id,
            'command_type': self.command_type.name,
            'timestamp': self.timestamp.isoformat(),
            'payload': self.payload,
            'source': self.source,
            'correlation_id': self.correlation_id,
        }
        return json.dumps(obj, ensure_ascii=False, sort_keys=True)

    @classmethod
    def deserialize(cls, data: str) -> RuntimeCommand:
        """从JSON字符串反序列化"""
        obj = json.loads(data)
        return cls(
            command_id=obj['command_id'],
            command_type=CommandType[obj['command_type']],
            timestamp=datetime.fromisoformat(obj['timestamp']),
            payload=obj['payload'],
            source=obj['source'],
            correlation_id=obj.get('correlation_id')
        )

    @classmethod
    def create(
        cls,
        command_type: CommandType,
        payload: dict[str, Any],
        source: str,
        correlation_id: str | None = None
    ) -> RuntimeCommand:
        """
        工厂方法 - 创建新命令

        Args:
            command_type: 命令类型
            payload: 命令参数
            source: 命令发起者标识
            correlation_id: 关联ID（可选）

        Returns:
            RuntimeCommand 实例
        """
        return cls(
            command_id=str(uuid.uuid4()),
            command_type=command_type,
            timestamp=datetime.now(timezone.utc),
            payload=payload,
            source=source,
            correlation_id=correlation_id
        )


# ========== 事件对象 ==========

@dataclass(slots=True)
class RuntimeEvent:
    """
    事件溯源记录 - 命令执行的结果

    事件特性：
    - 只读（一旦写入不可修改）
    - 追加写入（Append-only）
    - 包含完整的操作上下文

    用途：
    1. 审计追踪：谁在何时执行了什么
    2. 状态重放：从事件日志恢复状态
    3. 调试分析：追踪系统行为历史
    """
    event_id: str
    event_type: EventType
    timestamp: datetime
    source_command: str  # 触发此事件的command_id
    payload: dict[str, Any]

    def to_audit_log(self) -> dict[str, Any]:
        """转换为审计日志格式"""
        return {
            'event_id': self.event_id,
            'event_type': self.event_type.name,
            'timestamp': self.timestamp.isoformat(),
            'source_command': self.source_command,
            'payload': self.payload,
        }

    @classmethod
    def from_command(
        cls,
        command: RuntimeCommand,
        event_type: EventType,
        payload: dict[str, Any]
    ) -> RuntimeEvent:
        """从命令创建事件"""
        return cls(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            source_command=command.command_id,
            payload=payload
        )


# ========== 快照结构 ==========

@dataclass(slots=True)
class AuthoritySnapshot:
    """Authority快照子结构"""
    owner: str | None = None
    lease_id: str | None = None
    leased_until: str | None = None  # ISO 8601
    is_stale: bool = False
    stale_reason: str | None = None


@dataclass(slots=True)
class BacklogSnapshot:
    """任务队列快照"""
    pending: int = 0
    notified: int = 0
    delivered: int = 0
    failed: int = 0


@dataclass(slots=True)
class ReadinessSnapshot:
    """系统就绪度快照"""
    is_ready: bool = False
    blocked_reasons: list[str] = field(default_factory=list)


@dataclass
class RuntimeSnapshot:
    """
    完整运行时快照 - 对标 Project B 的 RuntimeSnapshot

    快照包含五部分：
    1. schema_version - 模式版本（用于迁移）
    2. authority - 权威租赁状态
    3. backlog - 任务队列统计
    4. replay_cursor - 重放游标（已处理事件索引）
    5. readiness - 系统就绪度

    用途：
    - 快速状态恢复（无需重放全部事件）
    - 跨进程/跨机器状态同步
    - 调试时状态检查点
    """
    schema_version: int = WORKFLOW_SCHEMA_VERSION
    authority: AuthoritySnapshot = field(default_factory=AuthoritySnapshot)
    backlog: BacklogSnapshot = field(default_factory=BacklogSnapshot)
    replay_cursor: int = 0
    readiness: ReadinessSnapshot = field(default_factory=ReadinessSnapshot)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（用于JSON持久化）"""
        return {
            'schema_version': self.schema_version,
            'authority': asdict(self.authority),
            'backlog': asdict(self.backlog),
            'replay_cursor': self.replay_cursor,
            'readiness': asdict(self.readiness),
            'created_at': self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeSnapshot:
        """从字典反序列化"""
        return cls(
            schema_version=data['schema_version'],
            authority=AuthoritySnapshot(**data['authority']),
            backlog=BacklogSnapshot(**data['backlog']),
            replay_cursor=data['replay_cursor'],
            readiness=ReadinessSnapshot(**data['readiness']),
            created_at=datetime.fromisoformat(data['created_at'])
        )

    def save(self, path: Path) -> None:
        """保存快照到文件"""
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding='utf-8'
        )

    @classmethod
    def load(cls, path: Path) -> RuntimeSnapshot:
        """从文件加载快照"""
        return cls.from_dict(json.loads(path.read_text(encoding='utf-8')))


# ========== 事件日志 ==========

class RuntimeEventLog:
    """
    事件日志 - 追加写入，支持重放

    文件格式：JSONL（每行一个事件）
    位置：{state_dir}/events.jsonl

    特性：
    - 线程安全
    - 追加只写（WAL模式）
    - 支持从任意游标重放
    """

    def __init__(self, state_dir: Path):
        """
        初始化事件日志

        Args:
            state_dir: 状态目录（事件日志将保存在 {state_dir}/events.jsonl）
        """
        self.state_dir = state_dir
        self.events_file = state_dir / "events.jsonl"
        self._events: list[RuntimeEvent] = []
        self._lock = threading.RLock()
        self._cursor = 0

    def append(self, event: RuntimeEvent) -> None:
        """
        追加事件（线程安全）

        同时更新内存缓存和磁盘文件
        """
        with self._lock:
            self._events.append(event)
            self._cursor += 1
            # 追加到文件
            self.events_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.events_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(event.to_audit_log(), ensure_ascii=False) + '\n')

    def load_all(self) -> list[RuntimeEvent]:
        """
        加载所有历史事件

        首次调用时从磁盘加载，后续直接返回内存缓存
        """
        with self._lock:
            if not self._events:
                if self.events_file.exists():
                    with open(self.events_file, encoding='utf-8') as f:
                        for line in f:
                            data = json.loads(line)
                            self._events.append(RuntimeEvent(
                                event_id=data['event_id'],
                                event_type=EventType[data['event_type']],
                                timestamp=datetime.fromisoformat(data['timestamp']),
                                source_command=data['source_command'],
                                payload=data['payload']
                            ))
            return self._events.copy()

    def get_cursor(self) -> int:
        """获取当前游标（已加载的事件数量）"""
        return self._cursor

    def replay_from(self, cursor: int = 0) -> list[RuntimeEvent]:
        """
        从指定游标重放事件

        Args:
            cursor: 起始游标（从0开始）

        Returns:
            从 cursor 开始的事件列表
        """
        events = self.load_all()
        return events[cursor:]

    def clear(self) -> None:
        """清空事件日志（仅用于测试）"""
        with self._lock:
            self._events.clear()
            self._cursor = 0
            if self.events_file.exists():
                self.events_file.unlink()


# ========== 状态引擎 ==========

class RuntimeStateEngine:
    """
    运行时状态引擎 - 对标 Project B 的 RuntimeEngine

    职责：
    1. 接收并处理 RuntimeCommand
    2. 生成 RuntimeEvent 并写入日志
    3. 维护当前状态（authority, backlog, readiness）
    4. 定期捕获快照

    使用模式：
    ```python
    engine = RuntimeStateEngine(state_dir=Path('.clawd/state'))

    # 执行命令
    cmd = RuntimeCommand.create(
        CommandType.ACQUIRE_AUTHORITY,
        {'owner': 'worker-1', 'ttl': 300},
        source='orchestrator'
    )
    event = engine.execute(cmd)

    # 定期保存快照
    engine.persist_snapshot()

    # 恢复状态
    engine = RuntimeStateEngine.load(state_dir)
    ```
    """

    def __init__(self, state_dir: Path):
        """
        初始化状态引擎

        Args:
            state_dir: 状态持久化目录
        """
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # 事件日志
        self.event_log = RuntimeEventLog(state_dir)

        # Authority Lease 管理器
        from src.core.state.authority import AuthorityLease
        self.authority_lease = AuthorityLease()

        # 加载快照或初始化
        self._snapshot: RuntimeSnapshot = self._load_or_create_snapshot()

        # 线程锁
        self._lock = threading.RLock()

        # 重放历史事件以恢复状态
        self._replay_events()

    def _load_or_create_snapshot(self) -> RuntimeSnapshot:
        """
        加载现有快照或创建新的

        注意：快照仅用于快速启动模板。实际状态通过重放事件日志恢复。
        即使快照存在，也会在 _replay_events 中追加后续事件。
        """
        snapshot_file = self.state_dir / "snapshot.json"
        if snapshot_file.exists():
            try:
                return RuntimeSnapshot.load(snapshot_file)
            except (json.JSONDecodeError, KeyError, TypeError, OSError):
                # 快照损坏，创建新的
                pass
        return RuntimeSnapshot()

    def _replay_events(self) -> None:
        """重放所有历史事件以恢复状态"""
        events = self.event_log.load_all()
        for event in events:
            self._apply_event(event)
        self._snapshot.replay_cursor = len(events)

    def _apply_event(self, event: RuntimeEvent) -> None:
        """
        应用事件到当前状态，同步更新快照和 AuthorityLease
        """
        from datetime import datetime

        from src.core.state.authority import LeaseInfo

        event_type = event.event_type
        payload = event.payload

        if event_type == EventType.AUTHORITY_ACQUIRED:
            # 更新快照
            self._snapshot.authority.owner = payload.get('owner')
            self._snapshot.authority.lease_id = payload.get('lease_id')
            self._snapshot.authority.leased_until = payload.get('leased_until')
            self._snapshot.authority.is_stale = False
            self._snapshot.authority.stale_reason = None
            # 更新 AuthorityLease
            if payload.get('leased_until'):
                expires = datetime.fromisoformat(payload['leased_until'])
                # 重建 LeaseInfo 对象
                self.authority_lease._lease = LeaseInfo(
                    owner=payload['owner'],
                    lease_id=payload['lease_id'],
                    granted_at=event.timestamp,
                    expires_at=expires
                )
            self._snapshot.readiness.is_ready = True
            self._snapshot.readiness.blocked_reasons = []

        elif event_type == EventType.AUTHORITY_RENEWED:
            if payload.get('leased_until'):
                self._snapshot.authority.leased_until = payload['leased_until']
                if self.authority_lease._lease:
                    self.authority_lease._lease = LeaseInfo(
                        owner=self.authority_lease._lease.owner,
                        lease_id=self.authority_lease._lease.lease_id,
                        granted_at=self.authority_lease._lease.granted_at,
                        expires_at=datetime.fromisoformat(payload['leased_until'])
                    )
                self._snapshot.authority.is_stale = False
                self._snapshot.authority.stale_reason = None

        elif event_type == EventType.AUTHORITY_RELEASED:
            self._snapshot.authority = AuthoritySnapshot()
            if self.authority_lease._lease:
                self.authority_lease._lease = None
            if not self._snapshot.readiness.blocked_reasons:
                self._snapshot.readiness.is_ready = False

        elif event_type == EventType.DISPATCH_QUEUED:
            self._snapshot.backlog.pending += 1

        elif event_type == EventType.DISPATCH_NOTIFIED:
            if self._snapshot.backlog.pending > 0:
                self._snapshot.backlog.pending -= 1
            self._snapshot.backlog.notified += 1

        elif event_type == EventType.DISPATCH_DELIVERED:
            if self._snapshot.backlog.notified > 0:
                self._snapshot.backlog.notified -= 1
            self._snapshot.backlog.delivered += 1

        elif event_type == EventType.DISPATCH_FAILED:
            if self._snapshot.backlog.notified > 0:
                self._snapshot.backlog.notified -= 1
            self._snapshot.backlog.failed += 1

    def execute(self, command: RuntimeCommand) -> RuntimeEvent:
        """
        执行命令并生成事件

        流程：
        1. 验证命令
        2. 执行命令逻辑
        3. 生成事件
        4. 写入事件日志
        5. 更新内存状态

        Args:
            command: 要执行的命令

        Returns:
            生成的事件
        """
        with self._lock:
            # 执行命令逻辑（子类可重写）
            event = self._process_command(command)

            # 追加到事件日志
            self.event_log.append(event)

            # 更新状态
            self._apply_event(event)

            return event

    def _process_command(self, command: RuntimeCommand) -> RuntimeEvent:
        """
        处理命令的核心逻辑

        Command → Event 映射：
        - ACQUIRE_AUTHORITY → AUTHORITY_ACQUIRED
        - RENEW_AUTHORITY → AUTHORITY_RENEWED
        - RELEASE_AUTHORITY → AUTHORITY_RELEASED
        - QUEUE_DISPATCH → DISPATCH_QUEUED
        - MARK_NOTIFIED → DISPATCH_NOTIFIED
        - MARK_DELIVERED → DISPATCH_DELIVERED
        - MARK_FAILED → DISPATCH_FAILED
        """

        cmd_type = command.command_type
        payload = command.payload

        if cmd_type == CommandType.ACQUIRE_AUTHORITY:
            owner = payload.get('owner', 'unknown')
            ttl = payload.get('ttl', 300)
            try:
                lease_info = self.authority_lease.acquire(owner, ttl)
                return RuntimeEvent.from_command(
                    command,
                    EventType.AUTHORITY_ACQUIRED,
                    {
                        'owner': lease_info.owner,
                        'lease_id': lease_info.lease_id,
                        'leased_until': lease_info.expires_at.isoformat(),
                    }
                )
            except Exception as e:
                return RuntimeEvent.from_command(
                    command,
                    EventType.DISPATCH_FAILED,
                    {'error': f'acquire failed: {e}'}
                )

        elif cmd_type == CommandType.RENEW_AUTHORITY:
            owner = payload.get('owner')
            ttl = payload.get('ttl', 300)
            if not owner:
                return RuntimeEvent.from_command(
                    command, EventType.DISPATCH_FAILED, {'error': 'owner required'}
                )
            try:
                lease_info = self.authority_lease.renew(owner, ttl)
                return RuntimeEvent.from_command(
                    command,
                    EventType.AUTHORITY_RENEWED,
                    {
                        'owner': lease_info.owner,
                        'lease_id': lease_info.lease_id,
                        'leased_until': lease_info.expires_at.isoformat(),
                    }
                )
            except Exception as e:
                return RuntimeEvent.from_command(
                    command, EventType.DISPATCH_FAILED, {'error': f'renew failed: {e}'}
                )

        elif cmd_type == CommandType.RELEASE_AUTHORITY:
            owner = payload.get('owner')
            if not owner:
                return RuntimeEvent.from_command(
                    command, EventType.DISPATCH_FAILED, {'error': 'owner required'}
                )
            try:
                # 验证所有者
                if self.authority_lease.get_owner() != owner:
                    return RuntimeEvent.from_command(
                        command, EventType.DISPATCH_FAILED,
                        {'error': f'not the holder (current: {self.authority_lease.get_owner()})'}
                    )
                self.authority_lease.release()
                return RuntimeEvent.from_command(
                    command, EventType.AUTHORITY_RELEASED, {'owner': owner}
                )
            except Exception as e:
                return RuntimeEvent.from_command(
                    command, EventType.DISPATCH_FAILED, {'error': f'release failed: {e}'}
                )

        elif cmd_type == CommandType.QUEUE_DISPATCH:
            return RuntimeEvent.from_command(
                command,
                EventType.DISPATCH_QUEUED,
                {
                    'request_id': payload.get('request_id'),
                    'target': payload.get('target'),
                    'metadata': payload.get('metadata'),
                }
            )

        elif cmd_type == CommandType.MARK_NOTIFIED:
            return RuntimeEvent.from_command(
                command,
                EventType.DISPATCH_NOTIFIED,
                {
                    'request_id': payload.get('request_id'),
                    'channel': payload.get('channel'),
                }
            )

        elif cmd_type == CommandType.MARK_DELIVERED:
            return RuntimeEvent.from_command(
                command,
                EventType.DISPATCH_DELIVERED,
                {'request_id': payload.get('request_id')}
            )

        elif cmd_type == CommandType.MARK_FAILED:
            return RuntimeEvent.from_command(
                command,
                EventType.DISPATCH_FAILED,
                {
                    'request_id': payload.get('request_id'),
                    'reason': payload.get('reason'),
                }
            )

        else:
            # 未知命令类型
            return RuntimeEvent.from_command(
                command,
                EventType.DISPATCH_FAILED,  # 使用一个占位事件类型
                {'error': f'unknown command type: {cmd_type}'}
            )

    def persist_snapshot(self) -> None:
        """持久化当前快照到磁盘"""
        self._snapshot.save(self.state_dir / "snapshot.json")

    def get_snapshot(self) -> RuntimeSnapshot:
        """获取当前快照（只读副本）"""
        with self._lock:
            return self._snapshot

    def get_events(self) -> list[RuntimeEvent]:
        """获取所有已加载的事件"""
        return self.event_log.load_all()

    @classmethod
    def load(cls, state_dir: Path) -> RuntimeStateEngine:
        """
        从磁盘加载并重放事件

        此方法用于系统重启后恢复状态：
        1. 加载最新的快照
        2. 读取事件日志
        3. 重放快照之后的事件

        Args:
            state_dir: 状态目录

        Returns:
            恢复的 RuntimeStateEngine 实例
        """
        engine = cls(state_dir)
        # _replay_events 在 __init__ 中已自动调用
        return engine

    def is_ready(self) -> bool:
        """检查系统是否就绪"""
        with self._lock:
            return self._snapshot.readiness.is_ready

    def get_blocked_reasons(self) -> list[str]:
        """获取阻塞原因"""
        with self._lock:
            return self._snapshot.readiness.blocked_reasons.copy()
