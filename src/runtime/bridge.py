"""
Runtime Bridge - 运行时桥接

从 oh-my-codex-main/src/runtime/bridge.ts 转换而来。
提供与 Rust 运行时的桥接功能。
"""

import os
import json
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass


@dataclass
class RuntimeSnapshot:
    """运行时快照"""
    schema_version: int
    authority: dict
    backlog: dict
    replay: dict
    readiness: dict


@dataclass
class AuthoritySnapshot:
    """权限快照"""
    owner: Optional[str]
    lease_id: Optional[str]
    leased_until: Optional[str]
    stale: bool
    stale_reason: Optional[str]


@dataclass
class BacklogSnapshot:
    """积压快照"""
    pending: int
    notified: int
    delivered: int
    failed: int


@dataclass
class ReplaySnapshot:
    """回放快照"""
    cursor: Optional[str]
    pending_events: int
    last_replayed_event_id: Optional[str]
    deferred_leader_notification: bool


@dataclass
class ReadinessSnapshot:
    """就绪快照"""
    ready: bool
    reason: Optional[str]


def omx_state_dir(cwd: str) -> str:
    """获取 OMX 状态目录"""
    return str(Path(cwd) / ".omx" / "state")


def read_runtime_snapshot(cwd: str) -> Optional[RuntimeSnapshot]:
    """读取运行时快照"""
    state_dir = omx_state_dir(cwd)
    snapshot_file = Path(state_dir) / "snapshot.json"

    if not snapshot_file.exists():
        return None

    try:
        with open(snapshot_file, "r") as f:
            data = json.load(f)
        return RuntimeSnapshot(
            schema_version=data.get("schema_version", 1),
            authority=data.get("authority", {}),
            backlog=data.get("backlog", {}),
            replay=data.get("replay", {}),
            readiness=data.get("readiness", {}),
        )
    except Exception:
        return None


def read_authority_snapshot(cwd: str) -> Optional[AuthoritySnapshot]:
    """读取权限快照"""
    snapshot = read_runtime_snapshot(cwd)
    if not snapshot:
        return None

    auth = snapshot.authority
    return AuthoritySnapshot(
        owner=auth.get("owner"),
        lease_id=auth.get("lease_id"),
        leased_until=auth.get("leased_until"),
        stale=auth.get("stale", False),
        stale_reason=auth.get("stale_reason"),
    )


def is_runtime_ready(cwd: str) -> bool:
    """检查运行时是否就绪"""
    snapshot = read_runtime_snapshot(cwd)
    if not snapshot:
        return False
    return snapshot.readiness.get("ready", False)


def get_bridge_enabled(env: Optional[dict] = None) -> bool:
    """检查桥接是否启用"""
    env = env or os.environ
    return env.get("OMX_RUNTIME_BRIDGE", "1") != "0"


# ===== 导出 =====
__all__ = [
    "RuntimeSnapshot",
    "AuthoritySnapshot",
    "BacklogSnapshot",
    "ReplaySnapshot",
    "ReadinessSnapshot",
    "omx_state_dir",
    "read_runtime_snapshot",
    "read_authority_snapshot",
    "is_runtime_ready",
    "get_bridge_enabled",
]
