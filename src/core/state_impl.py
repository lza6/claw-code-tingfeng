"""状态管理系统 - 借鉴 oh-my-codex 的 RuntimeSnapshot 设计

提供状态快照、持久化和恢复机制。
实现类似 omx-runtime-core 的 Authority/Backlog/Mailbox/Replay/Readiness 模式。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = __import__("logging").getLogger(__name__)


class ReadinessStatus(str, Enum):
    """就绪状态枚举"""
    READY = "ready"
    BLOCKED = "blocked"


@dataclass
class AuthoritySnapshot:
    """权限快照 - 对应 omx-runtime-core 的 AuthoritySnapshot

    跟踪谁持有系统权限（类似租约机制）。
    """
    owner: str | None = None
    lease_id: str | None = None
    leased_until: str | None = None  # ISO 时间戳
    stale: bool = False
    stale_reason: str | None = None

    @classmethod
    def acquire(cls, owner: str, lease_id: str, leased_until: str) -> AuthoritySnapshot:
        """获取权限"""
        return cls(
            owner=owner,
            lease_id=lease_id,
            leased_until=leased_until,
            stale=False,
            stale_reason=None,
        )

    def mark_stale(self, reason: str) -> None:
        """标记权限为过期"""
        self.stale = True
        self.stale_reason = reason

    def clear_stale(self) -> None:
        """清除过期标记"""
        self.stale = False
        self.stale_reason = None

    def is_held(self) -> bool:
        """检查是否持有权限"""
        return self.owner is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "lease_id": self.lease_id,
            "leased_until": self.leased_until,
            "stale": self.stale,
            "stale_reason": self.stale_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuthoritySnapshot:
        return cls(**data)


@dataclass
class BacklogSnapshot:
    """后台任务队列快照 - 对应 omx-runtime-core 的 BacklogSnapshot

    跟踪任务队列状态：待处理、已通知、已交付、失败。
    """
    pending: int = 0
    notified: int = 0
    delivered: int = 0
    failed: int = 0

    def queue(self) -> None:
        """入队一个任务"""
        self.pending += 1

    def mark_notified(self) -> bool:
        """标记为已通知"""
        if self.pending == 0:
            return False
        self.pending -= 1
        self.notified += 1
        return True

    def mark_delivered(self) -> bool:
        """标记为已交付"""
        if self.notified == 0:
            return False
        self.notified -= 1
        self.delivered += 1
        return True

    def mark_failed(self) -> bool:
        """标记为失败"""
        if self.notified == 0:
            return False
        self.notified -= 1
        self.failed += 1
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "pending": self.pending,
            "notified": self.notified,
            "delivered": self.delivered,
            "failed": self.failed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BacklogSnapshot:
        return cls(**data)


@dataclass
class ReplaySnapshot:
    """重放快照 - 对应 omx-runtime-core 的 ReplaySnapshot

    跟踪事件重放状态。
    """
    cursor: str | None = None
    pending_events: int = 0
    last_replayed_event_id: str | None = None
    deferred_leader_notification: bool = False

    def queue_event(self) -> None:
        """入队待重放事件"""
        self.pending_events += 1

    def mark_replayed(self, event_id: str) -> None:
        """标记事件已重放"""
        if self.pending_events > 0:
            self.pending_events -= 1
        self.last_replayed_event_id = event_id

    def defer_leader_notification(self) -> None:
        """延迟领导者通知"""
        self.deferred_leader_notification = True

    def clear_deferred_leader_notification(self) -> None:
        """清除延迟通知标志"""
        self.deferred_leader_notification = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "cursor": self.cursor,
            "pending_events": self.pending_events,
            "last_replayed_event_id": self.last_replayed_event_id,
            "deferred_leader_notification": self.deferred_leader_notification,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReplaySnapshot:
        return cls(**data)


@dataclass
class ReadinessSnapshot:
    """就绪状态快照 - 对应 omx-runtime-core 的 ReadinessSnapshot

    系统是否准备好处理新命令。
    """
    ready: bool = False
    reasons: list[str] = field(default_factory=list)

    @classmethod
    def ready_state(cls) -> ReadinessSnapshot:
        return cls(ready=True, reasons=[])

    @classmethod
    def blocked(cls, reason: str) -> ReadinessSnapshot:
        return cls(ready=False, reasons=[reason])

    def add_reason(self, reason: str) -> None:
        self.ready = False
        self.reasons.append(reason)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "reasons": self.reasons,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReadinessSnapshot:
        return cls(**data)


@dataclass
class SystemSnapshot:
    """系统完整快照 - 对应 omx-runtime-core 的 RuntimeSnapshot

    整合所有子系统状态。
    """
    schema_version: int = 1
    authority: AuthoritySnapshot = field(default_factory=AuthoritySnapshot)
    backlog: BacklogSnapshot = field(default_factory=BacklogSnapshot)
    replay: ReplaySnapshot = field(default_factory=ReplaySnapshot)
    readiness: ReadinessSnapshot = field(default_factory=ReadinessSnapshot)

    def ready(self) -> bool:
        """系统是否就绪"""
        return self.readiness.ready

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authority": self.authority.to_dict(),
            "backlog": self.backlog.to_dict(),
            "replay": self.replay.to_dict(),
            "readiness": self.readiness.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SystemSnapshot:
        return cls(
            schema_version=data.get("schema_version", 1),
            authority=AuthoritySnapshot.from_dict(data.get("authority", {})),
            backlog=BacklogSnapshot.from_dict(data.get("backlog", {})),
            replay=ReplaySnapshot.from_dict(data.get("replay", {})),
            readiness=ReadinessSnapshot.from_dict(data.get("readiness", {})),
        )

    def to_json(self, indent: int = 2) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> SystemSnapshot:
        """从 JSON 字符串反序列化"""
        data = json.loads(json_str)
        return cls.from_dict(data)


class StateManager:
    """状态管理器

    负责状态的持久化、加载和快照管理。
    对应 omx-runtime-core 的持久化功能。
    """

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._snapshot_file = self.state_dir / "snapshot.json"
        self._events_file = self.state_dir / "events.json"
        self._lock_file = self.state_dir / "engine.lock"

    def save_snapshot(self, snapshot: SystemSnapshot) -> None:
        """保存状态快照"""
        try:
            # 使用锁防止并发写入
            lock_path = self.state_dir / ".snapshot.lock"
            with lock_path.open("w") as lock_f:
                import fcntl
                fcntl.flock(lock_f, fcntl.LOCK_EX)
                try:
                    self._snapshot_file.write_text(
                        snapshot.to_json(indent=2),
                        encoding="utf-8"
                    )
                finally:
                    fcntl.flock(lock_f, fcntl.LOCK_UN)
            logger.debug(f"状态快照已保存: {self._snapshot_file}")
        except Exception as e:
            logger.error(f"保存状态快照失败: {e}")
            raise

    def load_snapshot(self) -> SystemSnapshot | None:
        """加载状态快照"""
        if not self._snapshot_file.exists():
            return None

        try:
            content = self._snapshot_file.read_text(encoding="utf-8")
            snapshot = SystemSnapshot.from_json(content)
            logger.debug(f"状态快照已加载: {self._snapshot_file}")
            return snapshot
        except Exception as e:
            logger.error(f"加载状态快照失败: {e}")
            return None

    def save_events(self, events: list[dict[str, Any]]) -> None:
        """保存事件日志"""
        try:
            self._events_file.write_text(
                json.dumps(events, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            logger.debug(f"事件日志已保存: {len(events)} 条")
        except Exception as e:
            logger.error(f"保存事件日志失败: {e}")
            raise

    def load_events(self) -> list[dict[str, Any]]:
        """加载事件日志"""
        if not self._events_file.exists():
            return []

        try:
            content = self._events_file.read_text(encoding="utf-8")
            events = json.loads(content)
            logger.debug(f"事件日志已加载: {len(events)} 条")
            return events
        except Exception as e:
            logger.error(f"加载事件日志失败: {e}")
            return []

    def append_event(self, event: dict[str, Any]) -> None:
        """追加单个事件到日志"""
        events = self.load_events()
        events.append(event)
        self.save_events(events)

    def create_compatibility_view(self) -> None:
        """创建兼容性视图文件（用于外部工具读取）

        对应 omx-runtime-core 的 write_compatibility_view 方法。
        生成独立的 JSON 文件供 TypeScript 读取。
        """
        snapshot = self.load_snapshot()
        if not snapshot:
            logger.warning("无法创建兼容性视图：快照不存在")
            return

        try:
            # 权限快照
            authority_file = self.state_dir / "authority.json"
            authority_file.write_text(
                json.dumps(snapshot.authority.to_dict(), indent=2),
                encoding="utf-8"
            )

            # 后台队列快照
            backlog_file = self.state_dir / "backlog.json"
            backlog_file.write_text(
                json.dumps(snapshot.backlog.to_dict(), indent=2),
                encoding="utf-8"
            )

            # 就绪状态快照
            readiness_file = self.state_dir / "readiness.json"
            readiness_file.write_text(
                json.dumps(snapshot.readiness.to_dict(), indent=2),
                encoding="utf-8"
            )

            # 重放快照
            replay_file = self.state_dir / "replay.json"
            replay_file.write_text(
                json.dumps(snapshot.replay.to_dict(), indent=2),
                encoding="utf-8"
            )

            # 调度记录（从事件中提取）
            events = self.load_events()
            dispatch_events = [
                e for e in events
                if e.get("type") in ["DispatchQueued", "DispatchNotified", "DispatchDelivered", "DispatchFailed"]
            ]
            if dispatch_events:
                dispatch_file = self.state_dir / "dispatch.json"
                dispatch_file.write_text(
                    json.dumps(dispatch_events, indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )

            logger.debug("兼容性视图文件已生成")
        except Exception as e:
            logger.error(f"创建兼容性视图失败: {e}")

    def persist(self, snapshot: SystemSnapshot, events: list[dict[str, Any]]) -> None:
        """持久化完整状态（快照+事件）"""
        self.save_snapshot(snapshot)
        self.save_events(events)
        self.create_compatibility_view()
        logger.info("状态持久化完成")

    def load(self) -> tuple[SystemSnapshot | None, list[dict[str, Any]]]:
        """加载完整状态"""
        snapshot = self.load_snapshot()
        events = self.load_events()
        return snapshot, events
