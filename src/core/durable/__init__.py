"""
Durable State Management System

Inspired by GoalX's canonical surfaces pattern, this module provides
machine-readable, persistent state files that survive session restarts.

Core Concepts:
- Canonical Surfaces: Authoritative state files (JSON/YAML)
- Immutable Contracts: User objectives that never change
- Mutable Obligations: Requirements that evolve during execution
- Evidence-Based: All state changes backed by verification evidence
"""

from .surface_manager import SurfaceManager
from .surfaces.assurance_plan import AssurancePlan
from .surfaces.cognition_state import CognitionState
from .surfaces.control_state import ControlState
from .surfaces.coordination_state import CoordinationState
from .surfaces.evidence_log import EvidenceLog
from .surfaces.freshness_state import FreshnessState
from .surfaces.objective_contract import ObjectiveContract
from .surfaces.obligation_model import ObligationModel
from .surfaces.resource_state import ResourceState
from .surfaces.status_summary import StatusSummary
from .surfaces.success_model import SuccessModel

__all__ = [
    "AssurancePlan",
    "CognitionState",
    "ControlState",
    "CoordinationState",
    "EvidenceLog",
    "FreshnessState",
    "ObjectiveContract",
    "ObligationModel",
    "ResourceState",
    "StatusSummary",
    "SuccessModel",
    "SurfaceManager",
]
