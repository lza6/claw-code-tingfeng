"""
Team - Team 模块

从 oh-my-codex-main/src/team/ 汲取的团队协作模块。
"""

from .allocation_policy import (
    AllocationStrategy,
    ResourceType,
    WorkerCapacity,
    AllocationPolicy,
    AllocationPolicyManager,
    get_allocation_manager,
)

from .phase_controller import (
    PhaseType,
    PhaseState,
    PhaseTransition,
    PhaseContext,
    PhaseController,
    get_phase_controller,
)

from .idle_nudge import (
    NudgeConfig,
    PaneNudgeState,
    NudgeTracker,
    capture_pane,
    pane_looks_ready,
    pane_has_active_task,
    is_pane_idle,
    send_to_worker,
)

__all__ = [
    # Allocation
    "AllocationStrategy",
    "ResourceType",
    "WorkerCapacity",
    "AllocationPolicy",
    "AllocationPolicyManager",
    "get_allocation_manager",
    # Phase
    "PhaseType",
    "PhaseState",
    "PhaseTransition",
    "PhaseContext",
    "PhaseController",
    "get_phase_controller",
    # Idle Nudge
    "NudgeConfig",
    "PaneNudgeState",
    "NudgeTracker",
    "capture_pane",
    "pane_looks_ready",
    "pane_has_active_task",
    "is_pane_idle",
    "send_to_worker",
]
