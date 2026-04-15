"""
Subagent Tracker - 子代理跟踪

从 oh-my-codex-main/src/subagents/tracker.ts 转换而来。
提供子代理线程跟踪功能。
"""

import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime


SUBAGENT_TRACKING_SCHEMA_VERSION = 1
DEFAULT_SUBAGENT_ACTIVE_WINDOW_MS = 120_000


@dataclass
class TrackedSubagentThread:
    """跟踪的子代理线程"""
    thread_id: str
    kind: str  # 'leader' | 'subagent'
    first_seen_at: str
    last_seen_at: str
    last_turn_id: Optional[str] = None
    turn_count: int = 0
    mode: Optional[str] = None


@dataclass
class TrackedSubagentSession:
    """跟踪的子代理会话"""
    session_id: str
    leader_thread_id: Optional[str] = None
    updated_at: str = ""
    threads: dict[str, TrackedSubagentThread] = field(default_factory=dict)


@dataclass
class SubagentTrackingState:
    """子代理跟踪状态"""
    schema_version: int = SUBAGENT_TRACKING_SCHEMA_VERSION
    sessions: dict[str, TrackedSubagentSession] = field(default_factory=dict)


@dataclass
class RecordSubagentTurnInput:
    """记录子代理轮次输入"""
    session_id: str
    thread_id: str
    kind: str  # 'leader' | 'subagent'
    turn_id: Optional[str] = None
    mode: Optional[str] = None


def subagent_tracking_file(cwd: str) -> str:
    """获取子代理跟踪文件路径"""
    return str(Path(cwd) / ".omx" / "state" / "subagent_tracking.json")


async def load_tracking_state(cwd: str) -> SubagentTrackingState:
    """加载跟踪状态"""
    file_path = subagent_tracking_file(cwd)
    tracking_file = Path(file_path)

    if not tracking_file.exists():
        return SubagentTrackingState()

    try:
        with open(tracking_file, "r") as f:
            data = json.load(f)
        return SubagentTrackingState(
            schema_version=data.get("schemaVersion", 1),
            sessions={
                sid: TrackedSubagentSession(
                    session_id=sid,
                    leader_thread_id=sess.get("leader_thread_id"),
                    updated_at=sess.get("updated_at", ""),
                    threads={
                        tid: TrackedSubagentThread(
                            thread_id=tid,
                            kind=tdata.get("kind", "subagent"),
                            first_seen_at=tdata.get("first_seen_at", ""),
                            last_seen_at=tdata.get("last_seen_at", ""),
                            last_turn_id=tdata.get("last_turn_id"),
                            turn_count=tdata.get("turn_count", 0),
                            mode=tdata.get("mode"),
                        )
                        for tid, tdata in sess.get("threads", {}).items()
                    },
                )
                for sid, sess in data.get("sessions", {}).items()
            },
        )
    except Exception:
        return SubagentTrackingState()


async def save_tracking_state(cwd: str, state: SubagentTrackingState) -> None:
    """保存跟踪状态"""
    file_path = subagent_tracking_file(cwd)
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)

    data = {
        "schemaVersion": state.schema_version,
        "sessions": {
            sid: {
                "session_id": sess.session_id,
                "leader_thread_id": sess.leader_thread_id,
                "updated_at": sess.updated_at,
                "threads": {
                    tid: {
                        "thread_id": t.thread_id,
                        "kind": t.kind,
                        "first_seen_at": t.first_seen_at,
                        "last_seen_at": t.last_seen_at,
                        "last_turn_id": t.last_turn_id,
                        "turn_count": t.turn_count,
                        "mode": t.mode,
                    }
                    for tid, t in sess.threads.items()
                },
            }
            for sid, sess in state.sessions.items()
        },
    }

    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)


async def record_subagent_turn(cwd: str, input_data: RecordSubagentTurnInput) -> None:
    """记录子代理轮次"""
    state = await load_tracking_state(cwd)
    now = datetime.now().isoformat()

    if input_data.session_id not in state.sessions:
        state.sessions[input_data.session_id] = TrackedSubagentSession(
            session_id=input_data.session_id,
            updated_at=now,
        )

    session = state.sessions[input_data.session_id]

    if input_data.kind == "leader":
        session.leader_thread_id = input_data.thread_id

    if input_data.thread_id in session.threads:
        thread = session.threads[input_data.thread_id]
        thread.last_seen_at = now
        thread.turn_count += 1
        if input_data.turn_id:
            thread.last_turn_id = input_data.turn_id
        if input_data.mode:
            thread.mode = input_data.mode
    else:
        session.threads[input_data.thread_id] = TrackedSubagentThread(
            thread_id=input_data.thread_id,
            kind=input_data.kind,
            first_seen_at=now,
            last_seen_at=now,
            last_turn_id=input_data.turn_id,
            turn_count=1,
            mode=input_data.mode,
        )

    session.updated_at = now
    await save_tracking_state(cwd, state)


async def get_active_subagents(cwd: str, session_id: str) -> list[TrackedSubagentThread]:
    """获取活动的子代理"""
    state = await load_tracking_state(cwd)
    if session_id not in state.sessions:
        return []

    session = state.sessions[session_id]
    now = datetime.now()

    active = []
    for thread in session.threads.values():
        last_seen = datetime.fromisoformat(thread.last_seen_at)
        elapsed = (now - last_seen).total_seconds() * 1000

        if elapsed < DEFAULT_SUBAGENT_ACTIVE_WINDOW_MS:
            active.append(thread)

    return active


# ===== 导出 =====
__all__ = [
    "SUBAGENT_TRACKING_SCHEMA_VERSION",
    "DEFAULT_SUBAGENT_ACTIVE_WINDOW_MS",
    "TrackedSubagentThread",
    "TrackedSubagentSession",
    "SubagentTrackingState",
    "RecordSubagentTurnInput",
    "subagent_tracking_file",
    "load_tracking_state",
    "save_tracking_state",
    "record_subagent_turn",
    "get_active_subagents",
]
