"""Team Monitor - 团队监控状态

汲取 oh-my-codex-main/src/team/state/monitor.ts (概念)

提供团队健康监控、状态快照、摘要等功能。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class TeamSummary:
    """团队摘要"""

    team_name: str
    worker_count: int = 0
    active_workers: int = 0
    idle_workers: int = 0
    pending_tasks: int = 0
    in_progress_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    last_activity: datetime | None = None
    health_status: str = "healthy"  # healthy|warning|critical

    def to_dict(self) -> dict:
        result = asdict(self)
        if self.last_activity:
            result["last_activity"] = self.last_activity.isoformat()
        return result

    @classmethod
    def from_dict(cls, data: dict) -> TeamSummary:
        summary = cls(**data)
        if data.get("last_activity"):
            summary.last_activity = datetime.fromisoformat(data["last_activity"])
        return summary


@dataclass
class MonitorSnapshot:
    """监控快照"""

    team_name: str
    timestamp: datetime = field(default_factory=datetime.now)
    summary: TeamSummary = field(default_factory=lambda: TeamSummary(team_name=""))
    phase: str = "unknown"
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "team_name": self.team_name,
            "timestamp": self.timestamp.isoformat(),
            "summary": self.summary.to_dict(),
            "phase": self.phase,
            "metrics": self.metrics,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MonitorSnapshot:
        summary = TeamSummary.from_dict(data.get("summary", {}))
        return cls(
            team_name=data.get("team_name", ""),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            summary=summary,
            phase=data.get("phase", "unknown"),
            metrics=data.get("metrics", {}),
        )


class MonitorStore:
    """监控数据存储"""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir / "monitor"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._snapshots_dir = self.state_dir / "snapshots"
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)

    def write_snapshot(self, snapshot: MonitorSnapshot) -> None:
        """写入监控快照"""
        path = self._snapshots_dir / f"{snapshot.team_name}_{int(snapshot.timestamp.timestamp())}.json"
        path.write_text(json.dumps(snapshot.to_dict(), indent=2))

    def read_latest_snapshot(self, team_name: str) -> MonitorSnapshot | None:
        """读取最新的监控快照"""
        snapshots = list(self._snapshots_dir.glob(f"{team_name}_*.json"))
        if not snapshots:
            return None

        latest = max(snapshots, key=lambda p: p.stat().st_mtime)
        try:
            data = json.loads(latest.read_text())
            return MonitorSnapshot.from_dict(data)
        except Exception:
            return None

    def list_snapshots(self, team_name: str, limit: int = 10) -> list[MonitorSnapshot]:
        """列出最近的快照"""
        snapshots = list(self._snapshots_dir.glob(f"{team_name}_*.json"))
        snapshots.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        result = []
        for path in snapshots[:limit]:
            try:
                data = json.loads(path.read_text())
                result.append(MonitorSnapshot.from_dict(data))
            except Exception:
                continue
        return result


def get_team_summary(team_name: str, state_dir: Path | None = None) -> TeamSummary:
    """获取团队摘要"""
    if state_dir is None:
        state_dir = Path.cwd() / ".clawd"

    store = MonitorStore(state_dir)
    snapshot = store.read_latest_snapshot(team_name)
    return snapshot.summary if snapshot else TeamSummary(team_name=team_name)


def read_monitor_snapshot(team_name: str, state_dir: Path | None = None) -> MonitorSnapshot | None:
    """读取监控快照"""
    if state_dir is None:
        state_dir = Path.cwd() / ".clawd"

    store = MonitorStore(state_dir)
    return store.read_latest_snapshot(team_name)


def write_monitor_snapshot(
    team_name: str,
    summary: TeamSummary,
    phase: str,
    metrics: dict[str, Any] | None = None,
    state_dir: Path | None = None,
) -> None:
    """写入监控快照"""
    if state_dir is None:
        state_dir = Path.cwd() / ".clawd"

    store = MonitorStore(state_dir)
    snapshot = MonitorSnapshot(
        team_name=team_name,
        summary=summary,
        phase=phase,
        metrics=metrics or {},
    )
    store.write_snapshot(snapshot)
