"""
Coordination State - Session coordination and task coverage

Tracks which sessions are working on which tasks, preventing conflicts
and ensuring complete coverage of all obligations.

Inspired by GoalX's coordination pattern.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from ..surface import Surface


class SessionState(Enum):
    """State of a worker session."""
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


class SurfaceAvailability(Enum):
    """What surfaces a session can access."""
    REPO = "repo"  # Git repository
    RUNTIME = "runtime"  # Can execute code
    ARTIFACTS = "artifacts"  # Can read/write artifacts
    WEB = "web"  # Can access web
    EXTERNAL = "external"  # Can access external APIs


class RequiredExecutionState(Enum):
    """Execution state of a required item (GoalX style)"""
    ACTIVE = "active"
    PROBING = "probing"
    WAITING = "waiting"
    BLOCKED = "blocked"


class RequiredSurfaceState(Enum):
    """Surface availability state (GoalX style)"""
    PENDING = "pending"
    ACTIVE = "active"
    AVAILABLE = "available"
    EXHAUSTED = "exhausted"
    UNREACHABLE = "unreachable"
    NOT_APPLICABLE = "not_applicable"


@dataclass
class RequiredSurface:
    """Surface state for a required coordination item"""
    repo: str = "pending"
    runtime: str = "pending"
    run_artifacts: str = "pending"
    web_research: str = "pending"
    external_system: str = "pending"


@dataclass
class CoordinationRequiredItem:
    """A required coordination item that must be tracked (GoalX style)"""
    execution_state: str = "active"
    blocked_by: str = ""
    surfaces: RequiredSurface = field(default_factory=RequiredSurface)
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class DispatchableSlice:
    """A unit of work that can be dispatched to a session"""
    title: str = ""
    why: str = ""
    mode: str = ""
    suggested_owner: str = ""
    suggested_action: str = ""
    covers_required: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


@dataclass
class CoordinationSession:
    """Information about a worker session (GoalX style)"""
    state: str = ""
    scope: str = ""
    covers_required: list[str] = field(default_factory=list)
    dispatchable_slices: list[DispatchableSlice] = field(default_factory=list)
    last_round: int = 0
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class CoordinationDecision:
    """Decision record for coordination resolution (GoalX style)"""
    root_cause: str = ""
    local_path: str = ""
    compatible_path: str = ""
    architecture_path: str = ""
    chosen_path: str = ""
    chosen_path_reason: str = ""


@dataclass
class SessionInfo:
    """Information about a worker session."""

    session_id: str
    state: SessionState
    created_at: str

    # Assignment
    assigned_obligations: list[str] = field(default_factory=list)  # Obligation IDs
    coverage_items: list[str] = field(default_factory=list)  # What this session covers

    # Capabilities
    available_surfaces: set[SurfaceAvailability] = field(default_factory=set)
    worktree_path: str | None = None  # If using isolated worktree

    # Progress
    progress_notes: str = ""
    last_activity: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # Decisions
    decisions: list[dict[str, Any]] = field(default_factory=list)  # Decision log

    # Metadata
    tags: list[str] = field(default_factory=list)


@dataclass
class CoordinationState(Surface):
    """
    Coordination state for all sessions in the run.
    """
    sessions: dict[str, SessionInfo] = field(default_factory=dict)

    # Coverage tracking
    coverage_map: dict[str, list[str]] = field(default_factory=dict)  # obligation_id -> [session_ids]

    # GoalX advanced fields
    required: dict[str, CoordinationRequiredItem] = field(default_factory=dict)
    decision: CoordinationDecision | None = None
    open_questions: list[str] = field(default_factory=list)

    # Master state
    master_state: str = "active"  # active, paused, completed
    master_notes: str = ""

    @classmethod
    def create_default(cls) -> "CoordinationState":
        """Create default coordination state."""
        return cls(
            sessions={},
            coverage_map={},
            required={},
            master_state="active",
            master_notes=""
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CoordinationState":
        """Load from dictionary."""
        sessions = {}
        for session_id, session_data in data.get("sessions", {}).items():
            sessions[session_id] = SessionInfo(
                session_id=session_data.get("session_id", session_id),
                state=SessionState(session_data.get("state", "idle")),
                created_at=session_data.get("created_at", datetime.utcnow().isoformat()),
                assigned_obligations=session_data.get("assigned_obligations", []),
                coverage_items=session_data.get("coverage_items", []),
                available_surfaces=set(
                    SurfaceAvailability(s) for s in session_data.get("available_surfaces", [])
                ),
                worktree_path=session_data.get("worktree_path"),
                progress_notes=session_data.get("progress_notes", ""),
                last_activity=session_data.get("last_activity", datetime.utcnow().isoformat()),
                decisions=session_data.get("decisions", []),
                tags=session_data.get("tags", [])
            )

        required = {}
        for req_id, req_data in data.get("required", {}).items():
            surface_data = req_data.get("surfaces", {})
            surfaces = RequiredSurface(
                repo=surface_data.get("repo", "pending"),
                runtime=surface_data.get("runtime", "pending"),
                run_artifacts=surface_data.get("run_artifacts", "pending"),
                web_research=surface_data.get("web_research", "pending"),
                external_system=surface_data.get("external_system", "pending")
            )
            required[req_id] = CoordinationRequiredItem(
                execution_state=req_data.get("execution_state", "active"),
                blocked_by=req_data.get("blocked_by", ""),
                surfaces=surfaces,
                updated_at=req_data.get("updated_at", datetime.utcnow().isoformat())
            )

        decision = None
        if data.get("decision"):
            dec_data = data["decision"]
            decision = CoordinationDecision(
                root_cause=dec_data.get("root_cause", ""),
                local_path=dec_data.get("local_path", ""),
                compatible_path=dec_data.get("compatible_path", ""),
                architecture_path=dec_data.get("architecture_path", ""),
                chosen_path=dec_data.get("chosen_path", ""),
                chosen_path_reason=dec_data.get("chosen_path_reason", "")
            )

        return cls(
            sessions=sessions,
            updated_at=data.get("updated_at", datetime.utcnow().isoformat()),
            coverage_map=data.get("coverage_map", {}),
            required=required,
            decision=decision,
            open_questions=data.get("open_questions", []),
            master_state=data.get("master_state", "active"),
            master_notes=data.get("master_notes", "")
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = super().to_dict()
        sessions_dict = {}
        for session_id, session in self.sessions.items():
            sessions_dict[session_id] = {
                "session_id": session.session_id,
                "state": session.state.value if hasattr(session.state, 'value') else session.state,
                "created_at": session.created_at,
                "assigned_obligations": session.assigned_obligations,
                "coverage_items": session.coverage_items,
                "available_surfaces": [s.value if hasattr(s, 'value') else s for s in session.available_surfaces],
                "worktree_path": session.worktree_path,
                "progress_notes": session.progress_notes,
                "last_activity": session.last_activity,
                "decisions": session.decisions,
                "tags": session.tags
            }

        required_dict = {}
        for req_id, req in self.required.items():
            required_dict[req_id] = {
                "execution_state": req.execution_state,
                "blocked_by": req.blocked_by,
                "surfaces": {
                    "repo": req.surfaces.repo,
                    "runtime": req.surfaces.runtime,
                    "run_artifacts": req.surfaces.run_artifacts,
                    "web_research": req.surfaces.web_research,
                    "external_system": req.surfaces.external_system
                },
                "updated_at": req.updated_at
            }

        decision_dict = None
        if self.decision:
            decision_dict = {
                "root_cause": self.decision.root_cause,
                "local_path": self.decision.local_path,
                "compatible_path": self.decision.compatible_path,
                "architecture_path": self.decision.architecture_path,
                "chosen_path": self.decision.chosen_path,
                "chosen_path_reason": self.decision.chosen_path_reason
            }

        data.update({
            "sessions": sessions_dict,
            "coverage_map": self.coverage_map,
            "required": required_dict,
            "decision": decision_dict,
            "open_questions": self.open_questions,
            "master_state": self.master_state,
            "master_notes": self.master_notes
        })
        return data

    def add_session(self, session: SessionInfo) -> None:
        """Register a new session."""
        self.sessions[session.session_id] = session
        self.updated_at = datetime.utcnow().isoformat()

    def update_session(self, session_id: str, **kwargs) -> None:
        """Update session information."""
        if session_id not in self.sessions:
            # 自动注册新 session
            self.add_session(SessionInfo(
                session_id=session_id,
                state=SessionState.IDLE,
                created_at=datetime.utcnow().isoformat()
            ))

        session = self.sessions[session_id]
        for key, value in kwargs.items():
            if hasattr(session, key):
                setattr(session, key, value)

        session.last_activity = datetime.utcnow().isoformat()
        self.updated_at = datetime.utcnow().isoformat()

    def get_session_worktree(self, session_id: str) -> str | None:
        """获取 session 的工作树路径"""
        session = self.sessions.get(session_id)
        return session.worktree_path if session else None

    def assign_obligation(self, session_id: str, obligation_id: str) -> None:
        """Assign an obligation to a session."""
        if session_id not in self.sessions:
            raise ValueError(f"Session not found: {session_id}")

        session = self.sessions[session_id]
        if obligation_id not in session.assigned_obligations:
            session.assigned_obligations.append(obligation_id)

        # Update coverage map
        if obligation_id not in self.coverage_map:
            self.coverage_map[obligation_id] = []
        if session_id not in self.coverage_map[obligation_id]:
            self.coverage_map[obligation_id].append(session_id)

        self.updated_at = datetime.utcnow().isoformat()

    def record_decision(self, session_id: str, decision: dict[str, Any]) -> None:
        """Record a decision made by a session."""
        if session_id not in self.sessions:
            raise ValueError(f"Session not found: {session_id}")

        decision["timestamp"] = datetime.utcnow().isoformat()
        self.sessions[session_id].decisions.append(decision)
        self.updated_at = datetime.utcnow().isoformat()

    def get_active_sessions(self) -> list[SessionInfo]:
        """Get all active sessions."""
        return [
            s for s in self.sessions.values()
            if s.state in [SessionState.PLANNING, SessionState.EXECUTING, SessionState.REVIEWING]
        ]

    def get_idle_sessions(self) -> list[SessionInfo]:
        """Get all idle sessions."""
        return [s for s in self.sessions.values() if s.state == SessionState.IDLE]

    def get_blocked_sessions(self) -> list[SessionInfo]:
        """Get all blocked sessions."""
        return [s for s in self.sessions.values() if s.state == SessionState.BLOCKED]

    def get_coverage_for_obligation(self, obligation_id: str) -> list[str]:
        """Get session IDs covering a specific obligation."""
        return self.coverage_map.get(obligation_id, [])

    def get_uncovered_obligations(self, all_obligation_ids: list[str]) -> list[str]:
        """Get obligations that have no session assigned."""
        return [
            obl_id for obl_id in all_obligation_ids
            if obl_id not in self.coverage_map or not self.coverage_map[obl_id]
        ]

    def __str__(self) -> str:
        """Human-readable representation."""
        total = len(self.sessions)
        active = len(self.get_active_sessions())
        idle = len(self.get_idle_sessions())
        blocked = len(self.get_blocked_sessions())

        lines = [
            f"Coordination: {total} sessions",
            f"  Active: {active}",
            f"  Idle: {idle}",
            f"  Blocked: {blocked}",
            f"  Master: {self.master_state}",
        ]

        return "\n".join(lines)
