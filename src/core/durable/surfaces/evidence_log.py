"""
Evidence Log - Record of verification evidence

Tracks all evidence collected during the run that proves obligations are satisfied.
Evidence is immutable once recorded - it serves as an audit trail.

Inspired by GoalX's evidence-log pattern.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class EvidenceType(Enum):
    """Type of evidence."""
    TEST_RESULT = "test_result"
    CODE_REVIEW = "code_review"
    MANUAL_VERIFICATION = "manual_verification"
    STATIC_ANALYSIS = "static_analysis"
    RUNTIME_LOG = "runtime_log"
    DOCUMENTATION = "documentation"
    BENCHMARK = "benchmark"
    SCREENSHOT = "screenshot"


@dataclass
class EvidenceEntry:
    """A single piece of evidence."""

    id: str
    type: EvidenceType
    description: str
    recorded_at: str

    # What this proves
    obligation_id: str | None = None  # Which obligation this satisfies
    scenario_id: str | None = None  # Which assurance scenario this relates to

    # The evidence itself
    data: dict[str, Any] = field(default_factory=dict)  # Structured data
    artifacts: list[str] = field(default_factory=list)  # File paths to artifacts

    # Source
    recorded_by: str | None = None  # Session ID that recorded this
    source_command: str | None = None  # Command that generated this

    # Metadata
    tags: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class EvidenceLog:
    """
    Immutable log of all evidence collected during the run.

    Evidence entries are append-only - they never change once recorded.
    This provides an audit trail of how obligations were verified.
    """

    entries: list[EvidenceEntry] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @classmethod
    def create_default(cls) -> "EvidenceLog":
        """Create an empty evidence log."""
        return cls(entries=[])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceLog":
        """Load from dictionary."""
        entries = []
        for entry_data in data.get("entries", []):
            entries.append(EvidenceEntry(
                id=entry_data["id"],
                type=EvidenceType(entry_data["type"]),
                description=entry_data["description"],
                recorded_at=entry_data["recorded_at"],
                obligation_id=entry_data.get("obligation_id"),
                scenario_id=entry_data.get("scenario_id"),
                data=entry_data.get("data", {}),
                artifacts=entry_data.get("artifacts", []),
                recorded_by=entry_data.get("recorded_by"),
                source_command=entry_data.get("source_command"),
                tags=entry_data.get("tags", []),
                notes=entry_data.get("notes", "")
            ))

        return cls(
            entries=entries,
            updated_at=data.get("updated_at", datetime.utcnow().isoformat())
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        entries_list = []
        for entry in self.entries:
            entries_list.append({
                "id": entry.id,
                "type": entry.type.value,
                "description": entry.description,
                "recorded_at": entry.recorded_at,
                "obligation_id": entry.obligation_id,
                "scenario_id": entry.scenario_id,
                "data": entry.data,
                "artifacts": entry.artifacts,
                "recorded_by": entry.recorded_by,
                "source_command": entry.source_command,
                "tags": entry.tags,
                "notes": entry.notes
            })

        return {
            "entries": entries_list,
            "updated_at": self.updated_at
        }

    def record_evidence(self, entry: EvidenceEntry) -> None:
        """
        Record a new piece of evidence.

        Evidence is append-only - once recorded, it cannot be modified.
        """
        self.entries.append(entry)
        self.updated_at = datetime.utcnow().isoformat()

    def get_evidence_for_obligation(self, obligation_id: str) -> list[EvidenceEntry]:
        """Get all evidence for a specific obligation."""
        return [e for e in self.entries if e.obligation_id == obligation_id]

    def get_evidence_for_scenario(self, scenario_id: str) -> list[EvidenceEntry]:
        """Get all evidence for a specific assurance scenario."""
        return [e for e in self.entries if e.scenario_id == scenario_id]

    def get_evidence_by_type(self, evidence_type: EvidenceType) -> list[EvidenceEntry]:
        """Get all evidence of a specific type."""
        return [e for e in self.entries if e.type == evidence_type]

    def get_recent_evidence(self, limit: int = 10) -> list[EvidenceEntry]:
        """Get the most recent evidence entries."""
        return sorted(self.entries, key=lambda e: e.recorded_at, reverse=True)[:limit]

    def __str__(self) -> str:
        """Human-readable representation."""
        total = len(self.entries)
        by_type = {}
        for entry in self.entries:
            by_type[entry.type.value] = by_type.get(entry.type.value, 0) + 1

        lines = [f"Evidence Log: {total} entries"]

        if by_type:
            lines.append("By Type:")
            for etype, count in sorted(by_type.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  {etype}: {count}")

        return "\n".join(lines)
