"""
Control State - Execution and phase management (Inspired by GoalX)

Tracks the current run phase, active sessions, leases for exclusive operations,
and provider alerts. This state drives the workflow engine.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional
from enum import Enum


class RunPhase(Enum):
    """Execution phases of a run"""
    INITIALIZE = "initialize"
    INTAKE = "intake"
    EXPLORE = "explore"
    PLAN = "plan"
    EXECUTE = "execute"
    VERIFY = "verify"
    REVIEW = "review"
    CLOSEOUT = "closeout"


class ContinuityState(Enum):
    """Continuity state of the run"""
    RUNNING = "running"
    PAUSED = "paused"
    BLOCKED = "blocked"
    TERMINATED = "terminated"


@dataclass
class ControlLease:
    """Exclusive lease for an operation (e.g., git commit, deployment)"""
    holder: str
    run_id: str
    epoch: int = 1
    renewed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    expires_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    pid: int = 0
    transport: str = "local"


@dataclass
class ControlState:
    """
    Control state manages the workflow phase, active sessions, and 
    system-level alerts.
    """
    version: int = 1
    goal_state: str = "open"  # open, completed, dropped
    continuity_state: ContinuityState = ContinuityState.RUNNING
    phase: RunPhase = RunPhase.INITIALIZE
    active_session_count: int = 0
    
    # Alerts from AI providers or system
    provider_dialog_alerts: Dict[str, str] = field(default_factory=dict)
    master_alerts: Dict[str, str] = field(default_factory=dict)
    
    # Active leases for exclusive resources
    leases: Dict[str, ControlLease] = field(default_factory=dict)
    
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @classmethod
    def create_default(cls) -> "ControlState":
        """Create a default control state."""
        return cls()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ControlState":
        """Load from dictionary."""
        leases = {}
        for holder, lease_data in data.get("leases", {}).items():
            leases[holder] = ControlLease(
                holder=lease_data.get("holder", holder),
                run_id=lease_data.get("run_id", ""),
                epoch=lease_data.get("epoch", 1),
                renewed_at=lease_data.get("renewed_at", datetime.utcnow().isoformat()),
                expires_at=lease_data.get("expires_at", datetime.utcnow().isoformat()),
                pid=lease_data.get("pid", 0),
                transport=lease_data.get("transport", "local")
            )
            
        return cls(
            version=data.get("version", 1),
            goal_state=data.get("goal_state", "open"),
            continuity_state=ContinuityState(data.get("continuity_state", "running")),
            phase=RunPhase(data.get("phase", "initialize")),
            active_session_count=data.get("active_session_count", 0),
            provider_dialog_alerts=data.get("provider_dialog_alerts", {}),
            master_alerts=data.get("master_alerts", {}),
            leases=leases,
            updated_at=data.get("updated_at", datetime.utcnow().isoformat())
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        leases_dict = {}
        for holder, lease in self.leases.items():
            leases_dict[holder] = {
                "holder": lease.holder,
                "run_id": lease.run_id,
                "epoch": lease.epoch,
                "renewed_at": lease.renewed_at,
                "expires_at": lease.expires_at,
                "pid": lease.pid,
                "transport": lease.transport
            }
            
        return {
            "version": self.version,
            "goal_state": self.goal_state,
            "continuity_state": self.continuity_state.value,
            "phase": self.phase.value,
            "active_session_count": self.active_session_count,
            "provider_dialog_alerts": self.provider_dialog_alerts,
            "master_alerts": self.master_alerts,
            "leases": leases_dict,
            "updated_at": self.updated_at
        }
        
    def transition_to(self, phase: RunPhase) -> None:
        """Safely transition to a new phase."""
        self.phase = phase
        self.updated_at = datetime.utcnow().isoformat()
        
    def acquire_lease(self, holder: str, run_id: str, ttl_seconds: int = 30, pid: int = 0) -> bool:
        """Attempt to acquire an exclusive lease."""
        now = datetime.utcnow()
        
        # Check if lease exists and is still valid
        if holder in self.leases:
            lease = self.leases[holder]
            expires = datetime.fromisoformat(lease.expires_at)
            
            # If valid and owned by someone else, fail
            if expires > now and lease.run_id != run_id:
                return False
                
            # Renew existing lease
            lease.epoch += 1
            lease.renewed_at = now.isoformat()
            
            from datetime import timedelta
            lease.expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
            lease.run_id = run_id
            lease.pid = pid
        else:
            # Create new lease
            from datetime import timedelta
            self.leases[holder] = ControlLease(
                holder=holder,
                run_id=run_id,
                epoch=1,
                renewed_at=now.isoformat(),
                expires_at=(now + timedelta(seconds=ttl_seconds)).isoformat(),
                pid=pid
            )
            
        self.updated_at = now.isoformat()
        return True
        
    def release_lease(self, holder: str, run_id: str) -> None:
        """Release a lease if owned by this run."""
        if holder in self.leases and self.leases[holder].run_id == run_id:
            # Mark as expired immediately
            now = datetime.utcnow().isoformat()
            self.leases[holder].expires_at = now
            self.updated_at = now
