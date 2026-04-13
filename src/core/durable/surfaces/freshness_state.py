"""
Freshness State - Tracks the recency and validity of various inputs/outputs.

Inspired by GoalX's freshness pattern to prevent using stale context or assumptions.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional


@dataclass
class FreshnessEntry:
    """Represents the freshness of a specific resource or fact."""
    resource_id: str
    last_verified_at: str
    valid_until: Optional[str] = None
    confidence_score: float = 1.0  # 0.0 - 1.0
    is_stale: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FreshnessState:
    """
    Tracks the overall 'freshness' of the run state.

    Helps the agent decide when to re-explore or re-verify information.
    """
    run_id: str
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # Resource ID -> FreshnessEntry
    resources: Dict[str, FreshnessEntry] = field(default_factory=dict)

    # Global freshness metrics
    overall_freshness_score: float = 1.0
    stale_resource_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "updated_at": self.updated_at,
            "resources": {k: {
                "resource_id": v.resource_id,
                "last_verified_at": v.last_verified_at,
                "valid_until": v.valid_until,
                "confidence_score": v.confidence_score,
                "is_stale": v.is_stale,
                "metadata": v.metadata
            } for k, v in self.resources.items()},
            "overall_freshness_score": self.overall_freshness_score,
            "stale_resource_count": self.stale_resource_count
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FreshnessState":
        resources = {}
        for k, v in data.get("resources", {}).items():
            resources[k] = FreshnessEntry(**v)

        return cls(
            run_id=data["run_id"],
            updated_at=data["updated_at"],
            resources=resources,
            overall_freshness_score=data.get("overall_freshness_score", 1.0),
            stale_resource_count=data.get("stale_resource_count", 0)
        )

    def mark_resource(self, resource_id: str, is_stale: bool = False) -> None:
        """Update or create a freshness entry for a resource."""
        now = datetime.utcnow().isoformat()
        if resource_id in self.resources:
            self.resources[resource_id].last_verified_at = now
            self.resources[resource_id].is_stale = is_stale
        else:
            self.resources[resource_id] = FreshnessEntry(
                resource_id=resource_id,
                last_verified_at=now,
                is_stale=is_stale
            )
        self._recalculate()

    def _recalculate(self) -> None:
        """Recalculate global metrics."""
        if not self.resources:
            self.overall_freshness_score = 1.0
            self.stale_resource_count = 0
            return

        stale_count = sum(1 for r in self.resources.values() if r.is_stale)
        self.stale_resource_count = stale_count
        self.overall_freshness_score = 1.0 - (stale_count / len(self.resources))
        self.updated_at = datetime.utcnow().isoformat()
