"""
Session Manager - Multi-agent coordination system inspired by Project B

This system manages session isolation, task distribution, and agent coordination with load balancing and health monitoring capabilities.
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """Represents a session assignment for an agent."""
    session_id: str
    agent_id: str
    obligation_id: str
    context: dict = field(default_factory=dict)
    status: str = "idle"  # "idle", "executing", "completed", "failed"
    start_time: datetime = field(default_factory=datetime.utcnow)
    retries: int = 0
    backoff_delay: float = 0.5


class BackoffStrategy:
    """Implements exponential backoff for retry logic."""

    def __init__(self, max_retries: int = 3, base_delay: float = 0.5):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.current_delay = self.base_delay

    def calculate_new_delay(self) -> float:
        self.current_delay *= 2
        if self.current_delay > self.max_retries * self.base_delay:
            self.current_delay = self.max_retries * self.base_delay
        return self.current_delay

    def reset(self) -> None:
        self.current_delay = self.base_delay


class SessionManager:
    """Central coordinator for multi-agent sessions with load balancing."""

    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root or Path.cwd()
        self.sessions: dict[str, Session] = {}
        self.load_balancer = LoadBalancer()

    def assign_session(self, session_id: str | None = None, agent_id: str | None = None,
                      obligation_id: str = "", context: dict | None = None) -> str:
        """Assign session with adaptive agent selection."""
        session_id = session_id or str(uuid.uuid4())[:8]
        context = context or {}

        # Check for existing session (OCC)
        if session_id in self.sessions:
            raise RuntimeError(f"Session {session_id} already assigned")

        # Create new session
        self.sessions[session_id] = Session(
            session_id=session_id,
            agent_id=agent_id or "default",
            obligation_id=obligation_id,
            context=context,
            status="executing"
        )

        logger.info(f"Session {session_id} assigned to agent {agent_id}")
        return session_id

    def get_assigned_obligations(self, agent_id: str) -> list[str]:
        """Get obligations assigned to specific agent."""
        return [s.obligation_id for s in self.sessions.values() if s.agent_id == agent_id]

    def unassign_session(self, session_id: str) -> None:
        """Release session with proper cleanup."""
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info(f"Session {session_id} unassigned")

    def get_session_status(self, session_id: str) -> str | None:
        """Get current status of a session."""
        session = self.sessions.get(session_id)
        return session.status if session else None

    def health_check(self) -> dict[str, Any]:
        """Get current load statistics."""
        active = sum(1 for s in self.sessions.values() if s.status == "executing")
        unique_agents = len(set(s.agent_id for s in self.sessions.values()))

        return {
            "active_sessions": active,
            "assigned_agents": unique_agents,
            "total_sessions": len(self.sessions)
        }


class LoadBalancer:
    """Implements load-aware agent selection."""

    def get_least_loaded_agent(self, agent_loads: dict[str, float]) -> str:
        """Choose agent with lowest current load percentage."""
        if not agent_loads:
            return "default"
        sorted_agents = sorted(agent_loads.items(), key=lambda x: x[1])
        return sorted_agents[0][0] if sorted_agents else "default"


def generate_session_id() -> str:
    """Generate a unique session identifier."""
    return str(uuid.uuid4())[:8]


def generate_reservation_id() -> str:
    """Generate a unique reservation identifier."""
    return f"res_{uuid.uuid4().hex[:8]}"
