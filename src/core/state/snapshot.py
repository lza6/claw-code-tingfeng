"""状态快照定义模块

包含 SystemSnapshot、ReplaySnapshot 等核心快照类。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# SystemSnapshot 需要的 AuthoritySnapshot/BacklogSnapshot/ReadinessSnapshot
# 通过延迟导入避免循环依赖


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
            'cursor': self.cursor,
            'pending_events': self.pending_events,
            'last_replayed_event_id': self.last_replayed_event_id,
            'deferred_leader_notification': self.deferred_leader_notification,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReplaySnapshot:
        return cls(**data)


@dataclass
class SystemSnapshot:
    """系统完整快照 - 对应 omx-runtime-core 的 RuntimeSnapshot

    整合所有子系统状态。
    """
    schema_version: int = 1
    authority: Any = field(default_factory=lambda: _get_authority_snapshot())
    backlog: Any = field(default_factory=lambda: _get_backlog_snapshot())
    replay: ReplaySnapshot = field(default_factory=ReplaySnapshot)
    readiness: Any = field(default_factory=lambda: _get_readiness_snapshot())

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
        # 延迟导入避免循环依赖
        from src.core.state.command_event import AuthoritySnapshot, BacklogSnapshot, ReadinessSnapshot
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


def _get_authority_snapshot():
    """延迟导入 AuthoritySnapshot 避免循环依赖"""
    from src.core.state.command_event import AuthoritySnapshot
    return AuthoritySnapshot()


def _get_backlog_snapshot():
    """延迟导入 BacklogSnapshot 避免循环依赖"""
    from src.core.state.command_event import BacklogSnapshot
    return BacklogSnapshot()


def _get_readiness_snapshot():
    """延迟导入 ReadinessSnapshot 避免循环依赖"""
    from src.core.state.command_event import ReadinessSnapshot
    return ReadinessSnapshot()
