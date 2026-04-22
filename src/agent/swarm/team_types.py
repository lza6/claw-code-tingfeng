"""Team Orchestration Types - 团队编排类型定义

借鉴 oh-my-codex 的团队状态管理类型系统。
提供精细化的团队工作流状态跟踪。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TeamPhase(str, Enum):
    """团队工作流阶段"""
    PLAN = "team-plan"
    PRD = "team-prd"
    EXEC = "team-exec"
    VERIFY = "team-verify"
    FIX = "team-fix"


class TerminalPhase(str, Enum):
    """终止阶段"""
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkerState(str, Enum):
    """Worker 状态"""
    IDLE = "idle"
    WORKING = "working"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"
    DRAINING = "draining"
    UNKNOWN = "unknown"


# 有效的阶段转换规则
TRANSITIONS: dict[TeamPhase, list[TeamPhase | TerminalPhase]] = {
    TeamPhase.PLAN: [TeamPhase.PRD],
    TeamPhase.PRD: [TeamPhase.EXEC],
    TeamPhase.EXEC: [TeamPhase.VERIFY],
    TeamPhase.VERIFY: [TeamPhase.FIX, TerminalPhase.COMPLETE, TerminalPhase.FAILED],
    TeamPhase.FIX: [TeamPhase.EXEC, TeamPhase.VERIFY, TerminalPhase.COMPLETE, TerminalPhase.FAILED],
}

TERMINAL_PHASES = [p.value for p in TerminalPhase]


def is_valid_transition(from_phase: TeamPhase, to_phase: TeamPhase | TerminalPhase) -> bool:
    """验证阶段转换是否有效"""
    allowed = TRANSITIONS.get(from_phase, [])
    return to_phase in allowed


def is_terminal_phase(phase: TeamPhase | TerminalPhase) -> bool:
    """检查是否是终止阶段"""
    return phase in TERMINAL_PHASES or phase in [p.value for p in TerminalPhase]


@dataclass
class WorkerInfo:
    """Worker 信息"""
    name: str
    index: int
    role: str
    assigned_tasks: list[str] = field(default_factory=list)
    pid: int | None = None
    pane_id: str | None = None
    working_dir: str | None = None
    worktree_path: str | None = None
    worktree_branch: str | None = None
    worktree_detached: bool = False


@dataclass
class WorkerHeartbeat:
    """Worker 心跳"""
    pid: int
    last_turn_at: str
    turn_count: int
    alive: bool


@dataclass
class WorkerStatus:
    """Worker 状态"""
    state: WorkerState = WorkerState.IDLE
    current_task_id: str | None = None
    reason: str | None = None
    updated_at: str = ""


@dataclass
class TeamTask:
    """团队任务"""
    id: str
    subject: str
    description: str
    status: str = "pending"  # pending, in_progress, completed, failed, blocked
    requires_code_change: bool = True
    role: str = "executor"
    owner: str | None = None
    result: str | None = None
    error: str | None = None
    blocked_by: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    created_at: str = ""
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "description": self.description,
            "status": self.status,
            "requires_code_change": self.requires_code_change,
            "role": self.role,
            "owner": self.owner,
            "result": self.result,
            "error": self.error,
            "blocked_by": self.blocked_by,
            "depends_on": self.depends_on,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


@dataclass
class TeamState:
    """团队状态"""
    active: bool = False
    phase: TeamPhase | TerminalPhase = TeamPhase.PLAN
    task_description: str = ""
    created_at: str = ""
    phase_transitions: list[dict[str, str]] = field(default_factory=list)
    tasks: list[TeamTask] = field(default_factory=list)
    max_fix_attempts: int = 3
    current_fix_attempt: int = 0
    workers: list[WorkerInfo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "phase": self.phase.value if isinstance(self.phase, Enum) else self.phase,
            "task_description": self.task_description,
            "created_at": self.created_at,
            "phase_transitions": self.phase_transitions,
            "tasks": [t.to_dict() for t in self.tasks],
            "max_fix_attempts": self.max_fix_attempts,
            "current_fix_attempt": self.current_fix_attempt,
            "workers": [
                {
                    "name": w.name,
                    "index": w.index,
                    "role": w.role,
                    "assigned_tasks": w.assigned_tasks,
                }
                for w in self.workers
            ],
        }


def create_team_state(task_description: str, max_fix_attempts: int = 3) -> TeamState:
    """创建初始团队状态"""
    return TeamState(
        active=True,
        phase=TeamPhase.PLAN,
        task_description=task_description,
        created_at=datetime.now().isoformat(),
        phase_transitions=[],
        tasks=[],
        max_fix_attempts=max_fix_attempts,
        current_fix_attempt=0,
    )


def transition_phase(
    state: TeamState,
    to_phase: TeamPhase | TerminalPhase,
    reason: str | None = None,
) -> TeamState:
    """转换到下一阶段"""
    from_phase = state.phase

    # 检查是否从终止阶段转换
    if is_terminal_phase(from_phase):
        raise ValueError(f"Cannot transition from terminal phase: {from_phase}")

    # 验证转换有效性
    if isinstance(from_phase, TeamPhase) and not is_valid_transition(from_phase, to_phase):
        raise ValueError(f"Invalid transition: {from_phase} -> {to_phase}")

    # 计算 fix 尝试次数
    next_fix_attempt = state.current_fix_attempt
    if to_phase == TeamPhase.FIX:
        next_fix_attempt += 1
        # 检查是否超过最大尝试次数
        if next_fix_attempt > state.max_fix_attempts:
            return TeamState(
                active=False,
                phase=TerminalPhase.FAILED,
                task_description=state.task_description,
                created_at=state.created_at,
                phase_transitions=[
                    *state.phase_transitions,
                    {
                        "from": from_phase.value if isinstance(from_phase, Enum) else from_phase,
                        "to": "failed",
                        "at": datetime.now().isoformat(),
                        "reason": f"team-fix loop limit reached ({state.max_fix_attempts})",
                    },
                ],
                tasks=state.tasks,
                max_fix_attempts=state.max_fix_attempts,
                current_fix_attempt=next_fix_attempt,
            )

    # 执行转换
    return TeamState(
        active=not is_terminal_phase(to_phase),
        phase=to_phase,
        task_description=state.task_description,
        created_at=state.created_at,
        phase_transitions=[
            *state.phase_transitions,
            {
                "from": from_phase.value if isinstance(from_phase, Enum) else from_phase,
                "to": to_phase.value if isinstance(to_phase, Enum) else to_phase,
                "at": datetime.now().isoformat(),
                "reason": reason,
            },
        ],
        tasks=state.tasks,
        max_fix_attempts=state.max_fix_attempts,
        current_fix_attempt=next_fix_attempt,
    )


def get_phase_agents(phase: TeamPhase) -> list[str]:
    """获取每个阶段推荐的 Agent 角色"""
    mapping = {
        TeamPhase.PLAN: ["analyst", "planner"],
        TeamPhase.PRD: ["product-manager", "analyst"],
        TeamPhase.EXEC: ["executor", "designer", "test-engineer"],
        TeamPhase.VERIFY: ["verifier", "quality-reviewer", "security-reviewer"],
        TeamPhase.FIX: ["executor", "build-fixer", "debugger"],
    }
    return mapping.get(phase, ["executor"])


def get_phase_instructions(phase: TeamPhase) -> str:
    """获取阶段指令"""
    mapping = {
        TeamPhase.PLAN: "PHASE: Planning. Use /analyst for requirements, /planner for task breakdown. Output: task list with dependencies.",
        TeamPhase.PRD: "PHASE: Requirements. Use /product-manager for PRD, /analyst for acceptance criteria. Output: explicit scope and success metrics.",
        TeamPhase.EXEC: "PHASE: Execution. Use /executor for implementation, /test-engineer for tests. Output: working code with tests.",
        TeamPhase.VERIFY: "PHASE: Verification. Use /verifier for evidence collection, /quality-reviewer for review. Output: pass/fail with evidence.",
        TeamPhase.FIX: "PHASE: Fixing. Use /debugger for root cause, /executor for fixes. Output: fixed code, re-verify needed.",
    }
    return mapping.get(phase, "")


# 导出
__all__ = [
    "TERMINAL_PHASES",
    "TRANSITIONS",
    "TeamPhase",
    "TeamState",
    "TeamTask",
    "TerminalPhase",
    "WorkerHeartbeat",
    "WorkerInfo",
    "WorkerState",
    "WorkerStatus",
    "create_team_state",
    "get_phase_agents",
    "get_phase_instructions",
    "is_terminal_phase",
    "is_valid_transition",
    "transition_phase",
]
