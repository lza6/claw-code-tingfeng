"""
Objective Contract - Immutable user goal definition

This surface captures the user's original intent and never changes.
It serves as the authoritative source of truth for what the run should achieve.

Inspired by GoalX's objective-contract pattern.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional


@dataclass
class ObjectiveContract:
    """
    Immutable contract defining the user's objective.

    Once created, this contract NEVER changes. It represents the
    original user intent and serves as the north star for the entire run.
    """

    # Core fields
    objective: str  # The user's goal in natural language
    created_at: str  # ISO timestamp
    run_id: str  # Unique run identifier

    # Context
    initial_context: Dict[str, Any] = field(default_factory=dict)  # Repo state, env vars, etc.
    constraints: list[str] = field(default_factory=list)  # Hard constraints (e.g., "no breaking changes")
    success_criteria: list[str] = field(default_factory=list)  # How to know when done

    # Metadata
    user: Optional[str] = None  # User who created this
    priority: str = "normal"  # low, normal, high, critical
    tags: list[str] = field(default_factory=list)  # Categorization tags

    @classmethod
    def create_default(cls) -> "ObjectiveContract":
        """Create a default empty contract."""
        return cls(
            objective="",
            created_at=datetime.utcnow().isoformat(),
            run_id="",
            initial_context={},
            constraints=[],
            success_criteria=[],
            user=None,
            priority="normal",
            tags=[]
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ObjectiveContract":
        """Load from dictionary."""
        return cls(
            objective=data["objective"],
            created_at=data["created_at"],
            run_id=data["run_id"],
            initial_context=data.get("initial_context", {}),
            constraints=data.get("constraints", []),
            success_criteria=data.get("success_criteria", []),
            user=data.get("user"),
            priority=data.get("priority", "normal"),
            tags=data.get("tags", [])
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "objective": self.objective,
            "created_at": self.created_at,
            "run_id": self.run_id,
            "initial_context": self.initial_context,
            "constraints": self.constraints,
            "success_criteria": self.success_criteria,
            "user": self.user,
            "priority": self.priority,
            "tags": self.tags
        }

    def __str__(self) -> str:
        """Human-readable representation."""
        lines = [
            f"Objective: {self.objective}",
            f"Run ID: {self.run_id}",
            f"Created: {self.created_at}",
        ]

        if self.constraints:
            lines.append(f"Constraints: {len(self.constraints)}")
            for c in self.constraints:
                lines.append(f"  - {c}")

        if self.success_criteria:
            lines.append(f"Success Criteria: {len(self.success_criteria)}")
            for sc in self.success_criteria:
                lines.append(f"  - {sc}")

        return "\n".join(lines)
