"""
Charter - Project run configuration and limits (Inspired by GoalX)

Defines the core goals, constraints, identity and permissions for a run.
This is the root configuration surface that sets the boundaries for all other operations.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..surface import Surface


@dataclass
class RunIdentity:
    """Identity information for the current run"""
    run_id: str
    project_id: str
    project_root: str
    run_name: str
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class CharterBoundary:
    """Boundaries and constraints for the run"""
    allowed_directories: list[str] = field(default_factory=list)
    forbidden_directories: list[str] = field(default_factory=list)
    allowed_commands: list[str] = field(default_factory=list)
    max_duration_seconds: int | None = None
    max_cost_usd: float | None = None
    max_tokens: int | None = None


@dataclass
class Charter(Surface):
    """
    Project Charter defines the core goals, identity and constraints for a run.
    """
    identity: RunIdentity
    objective: str
    boundary: CharterBoundary = field(default_factory=CharterBoundary)
    context_refs: list[str] = field(default_factory=list)

    @classmethod
    def create(cls, run_id: str, project_root: str, objective: str, run_name: str = "") -> "Charter":
        """Create a new charter."""
        identity = RunIdentity(
            run_id=run_id,
            project_id=os.path.basename(os.path.abspath(project_root)),
            project_root=project_root,
            run_name=run_name or f"run-{run_id[:8]}"
        )
        return cls(identity=identity, objective=objective)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Charter":
        """Load from dictionary."""
        id_data = data.get("identity", {})
        identity = RunIdentity(
            run_id=id_data.get("run_id", ""),
            project_id=id_data.get("project_id", ""),
            project_root=id_data.get("project_root", ""),
            run_name=id_data.get("run_name", ""),
            created_at=id_data.get("created_at", datetime.utcnow().isoformat())
        )

        boundary_data = data.get("boundary", {})
        boundary = CharterBoundary(
            allowed_directories=boundary_data.get("allowed_directories", []),
            forbidden_directories=boundary_data.get("forbidden_directories", []),
            allowed_commands=boundary_data.get("allowed_commands", []),
            max_duration_seconds=boundary_data.get("max_duration_seconds"),
            max_cost_usd=boundary_data.get("max_cost_usd"),
            max_tokens=boundary_data.get("max_tokens")
        )

        return cls(
            identity=identity,
            objective=data.get("objective", ""),
            boundary=boundary,
            context_refs=data.get("context_refs", []),
            updated_at=data.get("updated_at", datetime.utcnow().isoformat())
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({
            "identity": {
                "run_id": self.identity.run_id,
                "project_id": self.identity.project_id,
                "project_root": self.identity.project_root,
                "run_name": self.identity.run_name,
                "created_at": self.identity.created_at
            },
            "objective": self.objective,
            "boundary": {
                "allowed_directories": self.boundary.allowed_directories,
                "forbidden_directories": self.boundary.forbidden_directories,
                "allowed_commands": self.boundary.allowed_commands,
                "max_duration_seconds": self.boundary.max_duration_seconds,
                "max_cost_usd": self.boundary.max_cost_usd,
                "max_tokens": self.boundary.max_tokens
            },
            "context_refs": self.context_refs
        })
        return data

    def __str__(self) -> str:
        return f"Charter[{self.identity.run_name}]: {self.objective}"
