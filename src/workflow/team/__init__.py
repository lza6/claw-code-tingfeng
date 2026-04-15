"""
Team Workflow - 团队工作流模块

从 oh-my-codex-main 汲取的团队工作流相关组件。
"""

from .phase_controller import (
    TeamPhase,
    TerminalPhase,
    TaskCounts,
    TeamPhaseState,
    is_valid_transition,
    is_terminal_phase,
    infer_phase_target_from_task_counts,
    build_transition_path,
    reconcile_phase_state_for_monitor,
    calculate_team_phase,
    default_persisted_phase_state,
)

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
