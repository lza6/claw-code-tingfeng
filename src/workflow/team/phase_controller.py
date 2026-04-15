"""
Phase Controller - 阶段控制器

从 oh-my-codex-main 汲取的阶段推断与路径构建逻辑。
根据任务数量自动推断目标阶段并构建状态转换路径。

团队阶段:
- team-plan: 规划阶段
- team-prd: PRD 生成阶段
- team-exec: 执行阶段
- team-verify: 验证阶段
- team-fix: 修复阶段

终态:
- complete: 全部完成
- failed: 失败
- cancelled: 取消
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional

logger = logging.getLogger(__name__)


# ===== 类型定义 =====
TeamPhase = Literal["team-plan", "team-prd", "team-exec", "team-verify", "team-fix"]
TerminalPhase = Literal["complete", "failed", "cancelled"]


# ===== 任务计数 =====
@dataclass
class TaskCounts:
    """任务状态计数"""
    pending: int = 0
    blocked: int = 0
    in_progress: int = 0
    failed: int = 0
    completed: int = 0


# ===== 阶段状态 =====
@dataclass
class TeamPhaseState:
    """团队阶段状态"""
    current_phase: TeamPhase | TerminalPhase = "team-exec"
    max_fix_attempts: int = 3
    current_fix_attempt: int = 0
    transitions: list[dict[str, str]] = field(default_factory=list)
    updated_at: str = ""


# ===== 阶段转换规则 =====
TRANSITIONS: dict[TeamPhase, list[TeamPhase | TerminalPhase]] = {
    "team-plan": ["team-prd"],
    "team-prd": ["team-exec"],
    "team-exec": ["team-verify"],
    "team-verify": ["team-fix", "complete", "failed"],
    "team-fix": ["team-exec", "team-verify", "complete", "failed"],
}


def is_valid_transition(from_phase: TeamPhase, to_phase: TeamPhase | TerminalPhase) -> bool:
    """验证阶段转换是否有效"""
    allowed = TRANSITIONS.get(from_phase)
    return allowed is not None and to_phase in allowed


def is_terminal_phase(phase: TeamPhase | TerminalPhase) -> bool:
    """检查是否为终态"""
    return phase in ("complete", "failed", "cancelled")


# ===== 阶段推断 =====
def infer_phase_target_from_task_counts(
    task_counts: TaskCounts,
    options: dict[str, Any] = None,
) -> TeamPhase | TerminalPhase:
    """根据任务计数推断目标阶段

    Args:
        task_counts: 任务状态计数
        options: 可选选项
            - verification_pending: 是否有待验证任务

    Returns:
        目标阶段
    """
    options = options or {}
    verification_pending = options.get("verification_pending", False)

    all_terminal = (
        task_counts.pending == 0
        and task_counts.blocked == 0
        and task_counts.in_progress == 0
    )

    if all_terminal and task_counts.failed == 0:
        if verification_pending:
            return "team-verify"
        return "complete"

    if all_terminal and task_counts.failed > 0:
        return "team-fix"

    return "team-exec"


# ===== 路径构建 =====
def build_transition_path(
    from_phase: TeamPhase | TerminalPhase,
    to_phase: TeamPhase | TerminalPhase,
) -> list[TeamPhase | TerminalPhase]:
    """构建从源阶段到目标阶段的转换路径"""
    if from_phase == to_phase:
        return []

    # 目标: team-verify
    if to_phase == "team-verify":
        if from_phase == "team-plan":
            return ["team-prd", "team-exec", "team-verify"]
        if from_phase == "team-prd":
            return ["team-exec", "team-verify"]
        if from_phase == "team-exec":
            return ["team-verify"]
        if from_phase == "team-fix":
            return ["team-exec", "team-verify"]
        return []

    # 目标: team-exec
    if to_phase == "team-exec":
        if from_phase == "team-plan":
            return ["team-prd", "team-exec"]
        if from_phase == "team-prd":
            return ["team-exec"]
        if from_phase == "team-fix":
            return ["team-exec"]
        return []

    # 目标: team-fix
    if to_phase == "team-fix":
        if from_phase == "team-plan":
            return ["team-prd", "team-exec", "team-verify", "team-fix"]
        if from_phase == "team-prd":
            return ["team-exec", "team-verify", "team-fix"]
        if from_phase == "team-exec":
            return ["team-verify", "team-fix"]
        if from_phase == "team-verify":
            return ["team-fix"]
        return []

    # 目标: complete
    if to_phase == "complete":
        if from_phase == "team-plan":
            return ["team-prd", "team-exec", "team-verify", "complete"]
        if from_phase == "team-prd":
            return ["team-exec", "team-verify", "complete"]
        if from_phase == "team-exec":
            return ["team-verify", "complete"]
        if from_phase == "team-verify":
            return ["complete"]
        if from_phase == "team-fix":
            return ["complete"]
        return []

    # 目标: failed
    if to_phase == "failed":
        if from_phase == "team-plan":
            return ["team-prd", "team-exec", "team-verify", "failed"]
        if from_phase == "team-prd":
            return ["team-exec", "team-verify", "failed"]
        if from_phase == "team-exec":
            return ["team-verify", "failed"]
        if from_phase == "team-verify":
            return ["failed"]
        if from_phase == "team-fix":
            return ["failed"]
        return []

    return []


# ===== 阶段协调 =====
def default_persisted_phase_state() -> TeamPhaseState:
    """获取默认的持久化阶段状态"""
    return TeamPhaseState(
        current_phase="team-exec",
        max_fix_attempts=3,
        current_fix_attempt=0,
        transitions=[],
        updated_at=datetime.now().isoformat(),
    )


def reconcile_phase_state_for_monitor(
    persisted: TeamPhaseState | None,
    target: TeamPhase | TerminalPhase,
) -> TeamPhaseState:
    """协调阶段状态以匹配目标

    根据持久化的状态和目标阶段，计算新的状态。
    自动构建转换路径并记录转换历史。

    Args:
        persisted: 持久化的状态（可能为 None）
        target: 目标阶段

    Returns:
        协调后的新状态
    """
    now = datetime.now().isoformat()
    base = persisted or default_persisted_phase_state()

    # 如果当前阶段就是目标，直接返回
    if base.current_phase == target:
        state_dict = base.__dict__.copy()
        state_dict["updated_at"] = now
        return TeamPhaseState(**state_dict)

    # 如果当前已经是终态
    if is_terminal_phase(base.current_phase):
        if is_terminal_phase(target):
            return base
        # 重新开启任务
        return TeamPhaseState(
            current_phase=target,
            max_fix_attempts=base.max_fix_attempts,
            current_fix_attempt=0,
            transitions=base.transitions + [{
                "from": base.current_phase,
                "to": target,
                "at": now,
                "reason": "tasks_reopened",
            }],
            updated_at=now,
        )

    # 构建转换路径并执行
    transition_path = build_transition_path(base.current_phase, target)
    current = base.current_phase

    for next_phase in transition_path:
        if current == next_phase:
            continue
        if is_terminal_phase(current):
            break

        # 记录转换
        base.transitions.append({
            "from": current,
            "to": next_phase,
            "at": now,
        })
        current = next_phase

    return TeamPhaseState(
        current_phase=current,
        max_fix_attempts=base.max_fix_attempts,
        current_fix_attempt=base.current_fix_attempt,
        transitions=base.transitions,
        updated_at=now,
    )


# ===== 便捷函数 =====
def calculate_team_phase(
    task_counts: TaskCounts,
    verification_pending: bool = False,
    persisted_state: TeamPhaseState | None = None,
) -> TeamPhaseState:
    """计算团队当前阶段

    综合任务计数和持久化状态，计算当前应该处于的阶段。

    Args:
        task_counts: 任务状态计数
        verification_pending: 是否有待验证任务
        persisted_state: 持久化的状态

    Returns:
        当前的团队阶段状态
    """
    target = infer_phase_target_from_task_counts(
        task_counts,
        {"verification_pending": verification_pending},
    )
    return reconcile_phase_state_for_monitor(persisted_state, target)


# ===== 导出 =====
__all__ = [
    "TeamPhase",
    "TerminalPhase",
    "TaskCounts",
    "TeamPhaseState",
    "is_valid_transition",
    "is_terminal_phase",
    "infer_phase_target_from_task_counts",
    "build_transition_path",
    "reconcile_phase_state_for_monitor",
    "calculate_team_phase",
    "default_persisted_phase_state",
]
