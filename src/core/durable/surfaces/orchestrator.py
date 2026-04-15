"""
Orchestrator Surface - Central coordination hub for multi-agent systems

Implementation inspired by Project B's Lunchroom concept, focusing on agent coordination and resource management.
"""
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class SessionAssignment:
    """Represents an agent's assigned task or obligation."""
    obligation_id: str
    agent_id: str
    start_time: datetime
    status: str = "idle"  # "idle", "executing", "completed", "failed"
    context: dict = field(default_factory=dict)


class Orchestrator:
    """
    Manages agent coordination, task routing, and resource allocation.
    Implements Project B's Lunchroom pattern with enhanced versioning.
    """

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.sessions: dict[str, SessionAssignment] = {}

    @property
    def surface_path(self) -> Path:
        return self.run_dir / "surfaces" / "orchestrator.json"

    def load(self) -> None:
        """Load existing session assignments from disk with OCC."""
        if self.surface_path.exists():
            with open(self.surface_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Extract sessions data, ignoring version field
                sessions_data = {k: v for k, v in data.items() if k != "version"}
                self.sessions = {k: SessionAssignment(**v) for k, v in sessions_data.items()}

    def save(self) -> None:
        """Save session assignments atomically with OCC."""
        data = {k: v.__dict__ for k, v in self.sessions.items()}

        # Version control for atomic updates
        current_version = self.read_version() if self.surface_path.exists() else 0
        new_version = current_version + 1

        # Prepare data with version
        save_data = {"version": new_version, **data}

        try:
            self._atomic_save(save_data)
        finally:
            self.update_version(new_version)

    def read_version(self) -> int:
        """Read current version from file."""
        version_path = self.surface_path.with_suffix(".version")
        if version_path.exists():
            return int(version_path.read_text())
        return 0

    def _atomic_save(self, data: dict) -> None:
        """Perform an atomic write to the surface file."""
        temp_path = self.surface_path.with_suffix(".json.tmp")

        # Backup existing file
        if self.surface_path.exists():
            shutil.copy2(self.surface_path, temp_path)

        # Write to temp
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Atomic rename
        temp_path.replace(self.surface_path)

    def update_version(self, new_version: int) -> None:
        """Track version for conflict detection."""
        version_path = self.surface_path.with_suffix(".version")
        version_path.write_text(str(new_version))

    def assign_session(self, session_id: str, obligation_id: str, agent_id: str,
                       context: dict | None = None, start_time: datetime | None = None):
        """Assign a session to an agent with optimistic concurrency control."""
        start_time = start_time or datetime.utcnow()
        context = context or {}

        # Check for existing assignments (OCC)
        existing = self.sessions.get(session_id)
        if existing:
            raise RuntimeError(f"OCC Conflict: Session {session_id} already assigned")

        # Create new assignment
        self.sessions[session_id] = SessionAssignment(
            obligation_id=obligation_id,
            agent_id=agent_id,
            start_time=start_time,
            status="executing",
            context=context
        )

        self.save()

    def unassign_session(self, session_id: str) -> None:
        """Release an agent from their session."""
        if session_id in self.sessions:
            del self.sessions[session_id]
            self.save()

    def get_assigned_obligations(self, agent_id: str) -> list[str]:
        """Get all current obligations assigned to an agent."""
        return [a.obligation_id for a in self.sessions.values() if a.agent_id == agent_id]

    def get_agent_load(self, agent_id: str) -> int:
        """Get number of active sessions for an agent."""
        return sum(1 for a in self.sessions.values() if a.agent_id == agent_id and a.status == "executing")

    def health_check(self) -> dict[str, Any]:
        """Get current load statistics."""
        active_sessions = sum(1 for a in self.sessions.values() if a.status == "executing")
        unique_agents = len(set(a.agent_id for a in self.sessions.values() if a.status == "executing"))

        return {
            "active_sessions": active_sessions,
            "assigned_agents": unique_agents,
            "total_sessions": len(self.sessions)
        }
