"""
Team Persistence - 团队持久化

从 oh-my-codex-main/src/team/persistence.ts 汲取。
团队状态持久化和恢复。

功能:
- 团队状态读写
- 成员状态跟踪
- 消息历史持久化
- 协作事件记录
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..utils.file_ops import file_lock, locked_atomic_write_json

# 常量
TEAM_STATE_FILE = "team-state.json"
TEAM_MEMBERS_FILE = "team-members.json"
TEAM_MESSAGES_FILE = "team-messages.json"
#: 兜底目录（数据目录不可用时才用）；正常走 `_team_state_root()`
TEAM_STATE_DIR = Path(".clawd") / "state"


@dataclass
class TeamMemberState:
    """团队成员状态"""
    id: str
    name: str
    role: str
    status: str = "idle"  # idle, busy, waiting, offline
    current_task: str | None = None
    joined_at: str = ""
    last_active_at: str = ""


@dataclass
class TeamMessage:
    """团队消息"""
    id: str
    member_id: str
    content: str
    timestamp: str
    type: str = "message"  # message, action, system


@dataclass
class TeamStateData:
    """团队状态数据"""
    team_id: str
    task: str
    phase: str = "planning"
    iteration: int = 0
    max_iterations: int = 50
    started_at: str = ""
    completed_at: str | None = None
    members: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "task": self.task,
            "phase": self.phase,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "members": self.members,
            "messages": self.messages,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TeamStateData:
        return cls(
            team_id=data.get("team_id", ""),
            task=data.get("task", ""),
            phase=data.get("phase", "planning"),
            iteration=data.get("iteration", 0),
            max_iterations=data.get("max_iterations", 50),
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at"),
            members=data.get("members", []),
            messages=data.get("messages", []),
        )


def _team_state_root() -> Path:
    """团队状态的根目录 —— 跟随数据目录（桌面端写进 userData/data，而不是安装目录）

    原来直接写 `Path(".clawd") / "state"`，是**相对 cwd** 的：桌面端 cwd 是
    `resources/host`，团队状态会落在安装目录里（升级即丢、可能只读）。
    与 v0.88.3 的日志目录问题同源。
    """
    try:
        from ..core.data_dir import data_path

        return data_path("state")
    except (ImportError, OSError) as exc:  # pragma: no cover - 极端环境
        logging.getLogger(__name__).warning(f"数据目录不可用，团队状态回落 {TEAM_STATE_DIR}: {exc}")
        return TEAM_STATE_DIR


def _get_team_state_path(session_id: str | None = None) -> Path:
    """获取团队状态文件路径

    没有 `cwd` 参数：落盘位置**只**由数据目录（`_team_state_root()`）+ `session_id` 决定。
    以前这里有个 `cwd: str = "."` 的形参，函数体从头到尾没用过它 —— 参数被接受但被忽略，
    读代码的人会以为"传 cwd 能改变落盘位置"，实际传什么都不影响。
    """
    base = _team_state_root()
    root = base / session_id if session_id else base
    root.mkdir(parents=True, exist_ok=True)
    return root / TEAM_STATE_FILE


def _ensure_team_state(path: Path) -> TeamStateData:
    """确保团队状态文件存在"""
    if path.exists():
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            return TeamStateData.from_dict(data)
        except Exception:
            pass

    now = datetime.now().isoformat()
    state = TeamStateData(
        team_id="",
        task="",
        started_at=now,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    locked_atomic_write_json(path, state.to_dict())
    return state


def read_team_state(cwd: str = ".", session_id: str | None = None) -> TeamStateData:
    """读取团队状态

    `cwd` **仅为兼容保留**：状态目录走 `data_path('state')`，传什么都不影响落盘位置。
    """
    return _ensure_team_state(_get_team_state_path(session_id))


def write_team_state(
    state: TeamStateData,
    cwd: str = ".",
    session_id: str | None = None,
) -> bool:
    """写入团队状态

    `cwd` **仅为兼容保留**：状态目录走 `data_path('state')`，传什么都不影响落盘位置。
    """
    path = _get_team_state_path(session_id)
    try:
        locked_atomic_write_json(path, state.to_dict())
        return True
    except Exception:
        return False


def _mutate_team_state(
    session_id: str | None,
    mutator: Callable[[TeamStateData], bool],
) -> bool:
    """在文件锁内执行 read -> mutate -> write，避免并发丢更新。"""
    path = _get_team_state_path(session_id)
    with file_lock(path):
        state = _ensure_team_state(path)
        if not mutator(state):
            return False
        return write_team_state(state, session_id=session_id)


def add_team_member(
    member: TeamMemberState,
    cwd: str = ".",
    session_id: str | None = None,
) -> bool:
    """添加团队成员（读改写加锁）

    `cwd` **仅为兼容保留**：状态目录走 `data_path('state')`，传什么都不影响落盘位置。
    """
    member_dict = {
        "id": member.id,
        "name": member.name,
        "role": member.role,
        "status": member.status,
        "current_task": member.current_task,
        "joined_at": member.joined_at,
        "last_active_at": member.last_active_at,
    }

    def _mutate(state: TeamStateData) -> bool:
        # 检查是否已存在
        existing = [m for m in state.members if m.get("id") == member.id]
        if existing:
            return False
        state.members.append(member_dict)
        return True

    return _mutate_team_state(session_id, _mutate)


def remove_team_member(
    member_id: str,
    cwd: str = ".",
    session_id: str | None = None,
) -> bool:
    """移除团队成员（读改写加锁）

    `cwd` **仅为兼容保留**：状态目录走 `data_path('state')`，传什么都不影响落盘位置。
    """
    def _mutate(state: TeamStateData) -> bool:
        state.members = [m for m in state.members if m.get("id") != member_id]
        return True

    return _mutate_team_state(session_id, _mutate)


def update_member_status(
    member_id: str,
    status: str,
    current_task: str | None = None,
    cwd: str = ".",
    session_id: str | None = None,
) -> bool:
    """更新成员状态（读改写加锁）

    `cwd` **仅为兼容保留**：状态目录走 `data_path('state')`，传什么都不影响落盘位置。
    """
    def _mutate(state: TeamStateData) -> bool:
        for member in state.members:
            if member.get("id") == member_id:
                member["status"] = status
                member["last_active_at"] = datetime.now().isoformat()
                if current_task:
                    member["current_task"] = current_task
                return True
        return False

    return _mutate_team_state(session_id, _mutate)


def add_team_message(
    member_id: str,
    content: str,
    msg_type: str = "message",
    cwd: str = ".",
    session_id: str | None = None,
) -> bool:
    """添加团队消息（读改写加锁）

    `cwd` **仅为兼容保留**：状态目录走 `data_path('state')`，传什么都不影响落盘位置。
    """
    def _mutate(state: TeamStateData) -> bool:
        message = {
            "id": f"msg-{len(state.messages) + 1}",
            "member_id": member_id,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "type": msg_type,
        }
        state.messages.append(message)
        # 保持最近 1000 条消息
        state.messages = state.messages[-1000:]
        return True

    return _mutate_team_state(session_id, _mutate)


def get_team_messages(
    member_id: str | None = None,
    limit: int = 100,
    cwd: str = ".",
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """获取团队消息

    `cwd` **仅为兼容保留**：状态目录走 `data_path('state')`，传什么都不影响落盘位置。
    """
    state = read_team_state(cwd, session_id)
    messages = state.messages
    if member_id:
        messages = [m for m in messages if m.get("member_id") == member_id]
    return messages[-limit:]


# ===== 导出 =====
__all__ = [
    "TeamMemberState",
    "TeamMessage",
    "TeamStateData",
    "add_team_member",
    "add_team_message",
    "get_team_messages",
    "read_team_state",
    "remove_team_member",
    "update_member_status",
    "write_team_state",
]
