"""
Status Summary - High-level run status

Provides a human-readable summary of the current run state.
Updated frequently to give a quick overview of progress.

Inspired by GoalX's status pattern.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum


class RunPhase(Enum):
    """Current phase of the run."""
    INITIALIZING = "initializing"
    INTAKE = "intake"  # Reference: GoalX run intake
    PLANNING = "planning"
    EXPLORE = "explore"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    REVIEWING = "reviewing"
    FINALIZING = "finalizing"  # Reference: GoalX completed_finalization
    CLOSEOUT = "closeout"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class ProviderAlert:
    """Alert from AI provider (GoalX style)"""
    model_id: str
    alert_type: str
    message: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class StatusSummary:
    """
    High-level summary of run status.

    This is the first surface to check when resuming a run or
    checking progress. It provides a quick overview without needing
    to read all other surfaces.
    """

    run_id: str
    phase: RunPhase
    updated_at: str

    # Progress
    progress_percentage: float = 0.0  # 0-100
    obligations_satisfied: int = 0
    obligations_total: int = 0
    scenarios_passed: int = 0
    scenarios_total: int = 0

    # Current activity
    current_activity: str = ""  # What's happening right now
    active_sessions: int = 0
    blocked_sessions: int = 0

    # GoalX advanced fields
    continuity_state: str = "running"
    goal_state: str = "open"
    provider_alerts: List[ProviderAlert] = field(default_factory=list)

    # Timing
    started_at: Optional[str] = None
    estimated_completion: Optional[str] = None
    elapsed_time_seconds: float = 0.0

    # Health
    health_status: str = "healthy"  # healthy, degraded, unhealthy
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    # Summary
    summary: str = ""  # Brief human-readable summary

    @classmethod
    def create_default(cls) -> "StatusSummary":
        """Create default status summary."""
        return cls(
            run_id="",
            phase=RunPhase.INITIALIZING,
            updated_at=datetime.utcnow().isoformat(),
            progress_percentage=0.0,
            obligations_satisfied=0,
            obligations_total=0,
            scenarios_passed=0,
            scenarios_total=0,
            current_activity="Initializing run",
            active_sessions=0,
            blocked_sessions=0,
            continuity_state="running",
            goal_state="open",
            started_at=datetime.utcnow().isoformat(),
            estimated_completion=None,
            elapsed_time_seconds=0.0,
            health_status="healthy",
            warnings=[],
            errors=[],
            summary="Run is starting"
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StatusSummary":
        """Load from dictionary."""
        alerts = []
        for alert_data in data.get("provider_alerts", []):
            alerts.append(ProviderAlert(
                model_id=alert_data.get("model_id", ""),
                alert_type=alert_data.get("alert_type", ""),
                message=alert_data.get("message", ""),
                timestamp=alert_data.get("timestamp", datetime.utcnow().isoformat())
            ))

        return cls(
            run_id=data["run_id"],
            phase=RunPhase(data["phase"]),
            updated_at=data["updated_at"],
            progress_percentage=data.get("progress_percentage", 0.0),
            obligations_satisfied=data.get("obligations_satisfied", 0),
            obligations_total=data.get("obligations_total", 0),
            scenarios_passed=data.get("scenarios_passed", 0),
            scenarios_total=data.get("scenarios_total", 0),
            current_activity=data.get("current_activity", ""),
            active_sessions=data.get("active_sessions", 0),
            blocked_sessions=data.get("blocked_sessions", 0),
            continuity_state=data.get("continuity_state", "running"),
            goal_state=data.get("goal_state", "open"),
            provider_alerts=alerts,
            started_at=data.get("started_at"),
            estimated_completion=data.get("estimated_completion"),
            elapsed_time_seconds=data.get("elapsed_time_seconds", 0.0),
            health_status=data.get("health_status", "healthy"),
            warnings=data.get("warnings", []),
            errors=data.get("errors", []),
            summary=data.get("summary", "")
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "run_id": self.run_id,
            "phase": self.phase.value,
            "updated_at": self.updated_at,
            "progress_percentage": self.progress_percentage,
            "obligations_satisfied": self.obligations_satisfied,
            "obligations_total": self.obligations_total,
            "scenarios_passed": self.scenarios_passed,
            "scenarios_total": self.scenarios_total,
            "current_activity": self.current_activity,
            "active_sessions": self.active_sessions,
            "blocked_sessions": self.blocked_sessions,
            "continuity_state": self.continuity_state,
            "goal_state": self.goal_state,
            "provider_alerts": [
                {
                    "model_id": a.model_id,
                    "alert_type": a.alert_type,
                    "message": a.message,
                    "timestamp": a.timestamp
                } for a in self.provider_alerts
            ],
            "started_at": self.started_at,
            "estimated_completion": self.estimated_completion,
            "elapsed_time_seconds": self.elapsed_time_seconds,
            "health_status": self.health_status,
            "warnings": self.warnings,
            "errors": self.errors,
            "summary": self.summary
        }

    def update_progress(
        self,
        obligations_satisfied: int,
        obligations_total: int,
        scenarios_passed: int,
        scenarios_total: int
    ) -> None:
        """Update progress metrics."""
        self.obligations_satisfied = obligations_satisfied
        self.obligations_total = obligations_total
        self.scenarios_passed = scenarios_passed
        self.scenarios_total = scenarios_total

        # Calculate overall progress (weighted: 70% obligations, 30% scenarios)
        obl_progress = (obligations_satisfied / obligations_total * 100) if obligations_total > 0 else 0
        scenario_progress = (scenarios_passed / scenarios_total * 100) if scenarios_total > 0 else 0
        self.progress_percentage = (obl_progress * 0.7) + (scenario_progress * 0.3)

        self.updated_at = datetime.utcnow().isoformat()

    def add_warning(self, warning: str) -> None:
        """Add a warning."""
        if warning not in self.warnings:
            self.warnings.append(warning)
            if self.health_status == "healthy":
                self.health_status = "degraded"
        self.updated_at = datetime.utcnow().isoformat()

    def add_error(self, error: str) -> None:
        """Add an error."""
        if error not in self.errors:
            self.errors.append(error)
            self.health_status = "unhealthy"
        self.updated_at = datetime.utcnow().isoformat()

    def clear_warnings(self) -> None:
        """Clear all warnings."""
        self.warnings.clear()
        if not self.errors:
            self.health_status = "healthy"
        self.updated_at = datetime.utcnow().isoformat()

    def clear_errors(self) -> None:
        """Clear all errors."""
        self.errors.clear()
        if self.warnings:
            self.health_status = "degraded"
        else:
            self.health_status = "healthy"
        self.updated_at = datetime.utcnow().isoformat()

    def __str__(self) -> str:
        """Human-readable representation."""
        lines = [
            f"Run: {self.run_id}",
            f"Phase: {self.phase.value}",
            f"Progress: {self.progress_percentage:.1f}%",
            f"  Obligations: {self.obligations_satisfied}/{self.obligations_total}",
            f"  Scenarios: {self.scenarios_passed}/{self.scenarios_total}",
            f"Health: {self.health_status}",
        ]

        if self.current_activity:
            lines.append(f"Activity: {self.current_activity}")

        if self.active_sessions > 0:
            lines.append(f"Active Sessions: {self.active_sessions}")

        if self.blocked_sessions > 0:
            lines.append(f"Blocked Sessions: {self.blocked_sessions}")

        if self.warnings:
            lines.append(f"Warnings: {len(self.warnings)}")

        if self.errors:
            lines.append(f"Errors: {len(self.errors)}")

        if self.summary:
            lines.append(f"\n{self.summary}")

        return "\n".join(lines)
