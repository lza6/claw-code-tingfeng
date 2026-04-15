"""
Obligation Model - Mutable requirements that must be satisfied

Unlike ObjectiveContract (immutable), this surface evolves as the run progresses.
It tracks what MUST be true for the objective to be considered complete.

Inspired by GoalX's obligation-model pattern.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from ..surface import Surface


class ObligationStatus(Enum):
    """Status of an individual obligation."""
    OPEN = "open"  # Reference: GoalX goalItemStateOpen
    CLAIMED = "claimed"  # Reference: GoalX goalItemStateClaimed
    SATISFIED = "satisfied"  # Reference: GoalX goalItemStateCompleted
    WAIVED = "waived"  # Reference: GoalX goalItemStateWaived
    FAILED = "failed"


@dataclass
class Obligation:
    """A single requirement that must be satisfied."""

    id: str  # Unique identifier
    text: str  # What must be true (GoalX: Text)
    kind: str = "outcome"  # Type of obligation (GoalX: Kind, e.g., outcome, proof, guardrail)
    source: str = "master"  # Who defined it (GoalX: Source, e.g., user, master)
    status: ObligationStatus = ObligationStatus.OPEN
    covers_clauses: list[str] = field(default_factory=list)  # (GoalX: CoversClauses)

    # Evidence
    evidence_paths: list[str] = field(default_factory=list)  # (GoalX: EvidencePaths)
    verification_method: str | None = None

    # Dependencies
    depends_on: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)

    # Tracking
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    assigned_to: str | None = None  # Session ID

    # Metadata
    priority: int = 0
    tags: list[str] = field(default_factory=list)
    note: str = ""  # (GoalX: Note)
    approval_ref: str | None = None  # (GoalX: ApprovalRef)
    assurance_required: bool = False  # (GoalX: AssuranceRequired)


@dataclass
class ObligationModel(Surface):
    """
    Mutable model of all obligations for this run.
    """
    objective_contract_hash: str = ""
    required: list[Obligation] = field(default_factory=list)
    optional: list[Obligation] = field(default_factory=list)
    guardrails: list[Obligation] = field(default_factory=list)

    @classmethod
    def create_default(cls) -> "ObligationModel":
        """Create a default empty obligation model."""
        return cls(
            version=1,
            objective_contract_hash="",
            required=[],
            optional=[],
            guardrails=[],
            updated_at=datetime.utcnow().isoformat()
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ObligationModel":
        """Load from dictionary."""

        def parse_items(items_data):
            items = []
            for item in items_data:
                items.append(Obligation(
                    id=item["id"],
                    text=item["text"],
                    kind=item.get("kind", "outcome"),
                    source=item.get("source", "master"),
                    status=ObligationStatus(item.get("status", "open")),
                    covers_clauses=item.get("covers_clauses", []),
                    evidence_paths=item.get("evidence_paths", []),
                    verification_method=item.get("verification_method"),
                    depends_on=item.get("depends_on", []),
                    blocks=item.get("blocks", []),
                    created_at=item.get("created_at", datetime.utcnow().isoformat()),
                    updated_at=item.get("updated_at", datetime.utcnow().isoformat()),
                    assigned_to=item.get("assigned_to"),
                    priority=item.get("priority", 0),
                    tags=item.get("tags", []),
                    note=item.get("note", ""),
                    approval_ref=item.get("approval_ref"),
                    assurance_required=item.get("assurance_required", False)
                ))
            return items

        return cls(
            version=data.get("version", 1),
            objective_contract_hash=data.get("objective_contract_hash", ""),
            required=parse_items(data.get("required", [])),
            optional=parse_items(data.get("optional", [])),
            guardrails=parse_items(data.get("guardrails", [])),
            updated_at=data.get("updated_at", datetime.utcnow().isoformat())
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = super().to_dict()

        def dump_items(items):
            return [{
                "id": i.id,
                "text": i.text,
                "kind": i.kind,
                "source": i.source,
                "status": i.status.value,
                "covers_clauses": i.covers_clauses,
                "evidence_paths": i.evidence_paths,
                "verification_method": i.verification_method,
                "depends_on": i.depends_on,
                "blocks": i.blocks,
                "created_at": i.created_at,
                "updated_at": i.updated_at,
                "assigned_to": i.assigned_to,
                "priority": i.priority,
                "tags": i.tags,
                "note": i.note,
                "approval_ref": i.approval_ref,
                "assurance_required": i.assurance_required
            } for i in items]

        data.update({
            "objective_contract_hash": self.objective_contract_hash,
            "required": dump_items(self.required),
            "optional": dump_items(self.optional),
            "guardrails": dump_items(self.guardrails)
        })
        return data

    def all_obligations(self) -> list[Obligation]:
        """Return all obligations as a flat list."""
        return self.required + self.optional + self.guardrails

    def get_obligation(self, obl_id: str) -> Obligation | None:
        """Get an obligation by ID."""
        for obl in self.all_obligations():
            if obl.id == obl_id:
                return obl
        return None

    def add_obligation(self, obligation: Obligation, category: str = "required") -> None:
        """Add a new obligation to a specific category."""
        if category == "required":
            self.required.append(obligation)
        elif category == "optional":
            self.optional.append(obligation)
        elif category == "guardrails":
            self.guardrails.append(obligation)
        else:
            raise ValueError(f"Invalid category: {category}")
        self.updated_at = datetime.utcnow().isoformat()

    def update_obligation(self, obl_id: str, **kwargs) -> None:
        """Update an existing obligation."""
        obl = self.get_obligation(obl_id)
        if not obl:
            raise ValueError(f"Obligation not found: {obl_id}")

        for key, value in kwargs.items():
            if hasattr(obl, key):
                setattr(obl, key, value)

        obl.updated_at = datetime.utcnow().isoformat()
        self.updated_at = datetime.utcnow().isoformat()

    def satisfy_obligation(self, obl_id: str, evidence_paths: list[str]) -> None:
        """Mark an obligation as satisfied with evidence."""
        self.update_obligation(
            obl_id,
            status=ObligationStatus.SATISFIED,
            evidence_paths=evidence_paths
        )

    def get_ready_obligations(self) -> list[Obligation]:
        """Get obligations that are ready to work on (no unsatisfied dependencies)."""
        ready = []
        all_obls = {o.id: o for o in self.all_obligations()}

        for obl in self.all_obligations():
            if obl.status != ObligationStatus.OPEN:
                continue

            # Check if all dependencies are satisfied
            deps_satisfied = all(
                all_obls[dep_id].status == ObligationStatus.SATISFIED
                for dep_id in obl.depends_on
                if dep_id in all_obls
            )

            if deps_satisfied:
                ready.append(obl)

        # Sort by priority (descending)
        ready.sort(key=lambda o: o.priority, reverse=True)
        return ready

    def get_completion_percentage(self) -> float:
        """Calculate percentage of required obligations satisfied."""
        if not self.required:
            return 100.0

        satisfied = sum(
            1 for obl in self.required
            if obl.status == ObligationStatus.SATISFIED
        )

        return (satisfied / len(self.required)) * 100

    def __str__(self) -> str:
        """Human-readable representation."""
        all_items = self.all_obligations()
        total = len(all_items)
        satisfied = sum(1 for o in all_items if o.status == ObligationStatus.SATISFIED)
        claimed = sum(1 for o in all_items if o.status == ObligationStatus.CLAIMED)
        waived = sum(1 for o in all_items if o.status == ObligationStatus.WAIVED)

        lines = [
            f"Obligations: {satisfied}/{total} satisfied ({self.get_completion_percentage():.1f}%)",
            f"  Claimed: {claimed}",
            f"  Waived: {waived}",
            f"  Ready: {len(self.get_ready_obligations())}",
        ]

        return "\n".join(lines)
