"""
Team - Team 模块

从 oh-my-codex-main/src/team/ 汲取的团队协作模块。
"""

from .allocation_policy import (
    AllocationPolicy,
    AllocationPolicyManager,
    AllocationStrategy,
    ResourceType,
    WorkerCapacity,
    get_allocation_manager,
)
from .idle_nudge import (
    NudgeConfig,
    NudgeTracker,
    PaneNudgeState,
    capture_pane,
    is_pane_idle,
    pane_has_active_task,
    pane_looks_ready,
    send_to_worker,
)
from .phase_controller import (
    PhaseContext,
    PhaseController,
    PhaseState,
    PhaseTransition,
    PhaseType,
    get_phase_controller,
)

__all__ = [
    "AllocationPolicy",
    "AllocationPolicyManager",
    # Allocation
    "AllocationStrategy",
    # Idle Nudge
    "NudgeConfig",
    "NudgeTracker",
    "PaneNudgeState",
    "PhaseContext",
    "PhaseController",
    "PhaseState",
    "PhaseTransition",
    # Phase
    "PhaseType",
    "ResourceType",
    "WorkerCapacity",
    "capture_pane",
    "get_allocation_manager",
    "get_phase_controller",
    "is_pane_idle",
    "pane_has_active_task",
    "pane_looks_ready",
    "send_to_worker",
]
