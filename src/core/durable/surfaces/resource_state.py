"""
Resource State - Linux resource tracking (Inspired by GoalX)

Tracks system resources including PSI (Pressure Stall Information),
cgroup limits, and process RSS for GoalX processes. Provides health
assessment based on configurable thresholds.

Reference: GoalX resource-state schema
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ResourceHealthState(Enum):
    """Health state classification based on resource pressure."""
    HEALTHY = "healthy"      # Normal operation, plenty of headroom
    TIGHT = "tight"          # Under pressure, may need to slow down
    CRITICAL = "critical"    # Near limits, immediate action required
    UNKNOWN = "unknown"      # Unable to determine state


@dataclass
class HostInfo:
    """Host-level memory information."""
    mem_total_bytes: int = 0
    mem_available_bytes: int = 0
    swap_total_bytes: int = 0
    swap_free_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "mem_total_bytes": self.mem_total_bytes,
            "mem_available_bytes": self.mem_available_bytes,
            "swap_total_bytes": self.swap_total_bytes,
            "swap_free_bytes": self.swap_free_bytes
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HostInfo":
        return cls(
            mem_total_bytes=data.get("mem_total_bytes", 0),
            mem_available_bytes=data.get("mem_available_bytes", 0),
            swap_total_bytes=data.get("swap_total_bytes", 0),
            swap_free_bytes=data.get("swap_free_bytes", 0)
        )


@dataclass
class PSIValues:
    """Pressure Stall Information values for a specific metric."""
    avg10: float = 0.0
    avg60: float = 0.0
    avg300: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "avg10": self.avg10,
            "avg60": self.avg60,
            "avg300": self.avg300
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PSIValues":
        return cls(
            avg10=float(data.get("avg10", 0.0)),
            avg60=float(data.get("avg60", 0.0)),
            avg300=float(data.get("avg300", 0.0))
        )

    def is_high(self, threshold: float = 50.0) -> bool:
        """Check if any avg exceeds the threshold."""
        return self.avg10 > threshold or self.avg60 > threshold or self.avg300 > threshold


@dataclass
class PSIData:
    """Complete PSI data for memory pressure."""
    memory_some: PSIValues = field(default_factory=PSIValues)
    memory_full: PSIValues = field(default_factory=PSIValues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_some_avg10": self.memory_some.avg10,
            "memory_some_avg60": self.memory_some.avg60,
            "memory_some_avg300": self.memory_some.avg300,
            "memory_full_avg10": self.memory_full.avg10,
            "memory_full_avg60": self.memory_full.avg60,
            "memory_full_avg300": self.memory_full.avg300
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PSIData":
        return cls(
            memory_some=PSIValues(
                avg10=float(data.get("memory_some_avg10", 0.0)),
                avg60=float(data.get("memory_some_avg60", 0.0)),
                avg300=float(data.get("memory_some_avg300", 0.0))
            ),
            memory_full=PSIValues(
                avg10=float(data.get("memory_full_avg10", 0.0)),
                avg60=float(data.get("memory_full_avg60", 0.0)),
                avg300=float(data.get("memory_full_avg300", 0.0))
            )
        )


@dataclass
class CgroupEvents:
    """Cgroup memory event counters."""
    low: int = 0
    high: int = 0
    max: int = 0
    oom: int = 0
    oom_kill: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "low": self.low,
            "high": self.high,
            "max": self.max,
            "oom": self.oom,
            "oom_kill": self.oom_kill
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CgroupEvents":
        return cls(
            low=data.get("low", 0),
            high=data.get("high", 0),
            max=data.get("max", 0),
            oom=data.get("oom", 0),
            oom_kill=data.get("oom_kill", 0)
        )

    def has_oom(self) -> bool:
        """Check if OOM events have occurred."""
        return self.oom > 0 or self.oom_kill > 0


@dataclass
class CgroupLimits:
    """Cgroup memory limits and current usage."""
    memory_current_bytes: int = 0
    memory_high_bytes: int = 0
    memory_max_bytes: int = 0
    memory_swap_current_bytes: int = 0
    memory_swap_max_bytes: int = 0
    events: CgroupEvents = field(default_factory=CgroupEvents)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_current_bytes": self.memory_current_bytes,
            "memory_high_bytes": self.memory_high_bytes,
            "memory_max_bytes": self.memory_max_bytes,
            "memory_swap_current_bytes": self.memory_swap_current_bytes,
            "memory_swap_max_bytes": self.memory_swap_max_bytes,
            "events": self.events.to_dict()
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CgroupLimits":
        return cls(
            memory_current_bytes=data.get("memory_current_bytes", 0),
            memory_high_bytes=data.get("memory_high_bytes", 0),
            memory_max_bytes=data.get("memory_max_bytes", 0),
            memory_swap_current_bytes=data.get("memory_swap_current_bytes", 0),
            memory_swap_max_bytes=data.get("memory_swap_max_bytes", 0),
            events=CgroupEvents.from_dict(data.get("events", {}))
        )

    def usage_ratio(self) -> float:
        """Calculate memory usage ratio (0.0 to 1.0+)."""
        if self.memory_max_bytes <= 0:
            return 0.0
        return self.memory_current_bytes / self.memory_max_bytes


@dataclass
class GoalXProcesses:
    """RSS tracking for GoalX processes."""
    master_rss_bytes: int = 0
    runtime_host_rss_bytes: int = 0
    worker_rss_bytes: dict[str, int] = field(default_factory=dict)
    total_goalx_rss_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "master_rss_bytes": self.master_rss_bytes,
            "runtime_host_rss_bytes": self.runtime_host_rss_bytes,
            "worker_rss_bytes": dict(self.worker_rss_bytes),
            "total_goalx_rss_bytes": self.total_goalx_rss_bytes
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GoalXProcesses":
        return cls(
            master_rss_bytes=data.get("master_rss_bytes", 0),
            runtime_host_rss_bytes=data.get("runtime_host_rss_bytes", 0),
            worker_rss_bytes=data.get("worker_rss_bytes", {}),
            total_goalx_rss_bytes=data.get("total_goalx_rss_bytes", 0)
        )


@dataclass
class HealthThresholds:
    """Configurable thresholds for health assessment."""
    # PSI thresholds (percentage, 0-100)
    psi_some_avg10_tight: float = 30.0
    psi_some_avg10_critical: float = 60.0
    psi_full_avg10_tight: float = 10.0
    psi_full_avg10_critical: float = 30.0

    # Memory usage ratio thresholds (0.0-1.0)
    usage_ratio_tight: float = 0.75
    usage_ratio_critical: float = 0.90

    # Headroom thresholds (bytes)
    headroom_tight_bytes: int = 512 * 1024 * 1024  # 512MB
    headroom_critical_bytes: int = 128 * 1024 * 1024  # 128MB


@dataclass
class ResourceState:
    """
    Comprehensive resource state tracking for GoalX.

    Tracks Linux-specific resources:
    - Host memory (total, available, swap)
    - PSI (Pressure Stall Information) for memory pressure
    - Cgroup memory limits and events
    - GoalX process RSS tracking

    Provides health assessment based on configurable thresholds.
    """
    host: HostInfo = field(default_factory=HostInfo)
    psi: PSIData = field(default_factory=PSIData)
    cgroup: CgroupLimits = field(default_factory=CgroupLimits)
    goalx_processes: GoalXProcesses = field(default_factory=GoalXProcesses)
    headroom_bytes: int = 0
    state: ResourceHealthState = ResourceHealthState.UNKNOWN
    reasons: list[str] = field(default_factory=list)
    thresholds: HealthThresholds = field(default_factory=HealthThresholds)
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @classmethod
    def create_default(cls) -> "ResourceState":
        """Create a default resource state."""
        return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResourceState":
        """Load from dictionary."""
        return cls(
            host=HostInfo.from_dict(data.get("host", {})),
            psi=PSIData.from_dict(data.get("psi", {})),
            cgroup=CgroupLimits.from_dict(data.get("cgroup", {})),
            goalx_processes=GoalXProcesses.from_dict(data.get("goalx_processes", {})),
            headroom_bytes=data.get("headroom_bytes", 0),
            state=ResourceHealthState(data.get("state", "unknown")),
            reasons=data.get("reasons", []),
            thresholds=HealthThresholds(),
            updated_at=data.get("updated_at", datetime.utcnow().isoformat())
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "host": self.host.to_dict(),
            "psi": self.psi.to_dict(),
            "cgroup": self.cgroup.to_dict(),
            "goalx_processes": self.goalx_processes.to_dict(),
            "headroom_bytes": self.headroom_bytes,
            "state": self.state.value,
            "reasons": list(self.reasons),
            "updated_at": self.updated_at
        }

    def check_health(self) -> ResourceHealthState:
        """
        Assess health state based on current metrics.

        Updates self.state and self.reasons based on thresholds.
        Returns the determined health state.
        """
        reasons: list[str] = []

        # Check for OOM events (immediate critical)
        if self.cgroup.events.has_oom():
            self.state = ResourceHealthState.CRITICAL
            self.reasons = ["OOM events detected: immediate action required"]
            return self.state

        # Check PSI memory_full (most severe)
        if self.psi.memory_full.avg10 > self.thresholds.psi_full_avg10_critical:
            reasons.append(f"PSI memory_full avg10 critical: {self.psi.memory_full.avg10:.1f}% > {self.thresholds.psi_full_avg10_critical}%")
        elif self.psi.memory_full.avg10 > self.thresholds.psi_full_avg10_tight:
            reasons.append(f"PSI memory_full avg10 tight: {self.psi.memory_full.avg10:.1f}% > {self.thresholds.psi_full_avg10_tight}%")

        # Check PSI memory_some
        if self.psi.memory_some.avg10 > self.thresholds.psi_some_avg10_critical:
            reasons.append(f"PSI memory_some avg10 critical: {self.psi.memory_some.avg10:.1f}% > {self.thresholds.psi_some_avg10_critical}%")
        elif self.psi.memory_some.avg10 > self.thresholds.psi_some_avg10_tight:
            reasons.append(f"PSI memory_some avg10 tight: {self.psi.memory_some.avg10:.1f}% > {self.thresholds.psi_some_avg10_tight}%")

        # Check cgroup usage ratio
        usage_ratio = self.cgroup.usage_ratio()
        if usage_ratio > self.thresholds.usage_ratio_critical:
            reasons.append(f"Cgroup usage critical: {usage_ratio:.1%} > {self.thresholds.usage_ratio_critical:.0%}")
        elif usage_ratio > self.thresholds.usage_ratio_tight:
            reasons.append(f"Cgroup usage tight: {usage_ratio:.1%} > {self.thresholds.usage_ratio_tight:.0%}")

        # Check headroom
        if self.headroom_bytes < self.thresholds.headroom_critical_bytes:
            reasons.append(f"Headroom critical: {self.headroom_bytes / (1024*1024):.1f}MB < {self.thresholds.headroom_critical_bytes / (1024*1024):.1f}MB")
        elif self.headroom_bytes < self.thresholds.headroom_tight_bytes:
            reasons.append(f"Headroom tight: {self.headroom_bytes / (1024*1024):.1f}MB < {self.thresholds.headroom_tight_bytes / (1024*1024):.1f}MB")

        # Check for high event counters
        if self.cgroup.events.high > 0:
            reasons.append(f"Cgroup high events: {self.cgroup.events.high}")
        if self.cgroup.events.max > 0:
            reasons.append(f"Cgroup max events: {self.cgroup.events.max}")

        # Determine state based on reasons
        self.reasons = reasons

        # Classify severity based on reason patterns
        critical_keywords = ["critical", "OOM", "oom"]
        tight_keywords = ["tight"]

        has_critical = any(
            any(kw in reason for kw in critical_keywords)
            for reason in reasons
        )
        has_tight = any(
            any(kw in reason for kw in tight_keywords)
            for reason in reasons
        )

        if has_critical:
            self.state = ResourceHealthState.CRITICAL
        elif has_tight:
            self.state = ResourceHealthState.TIGHT
        elif reasons:
            # Has reasons but none are critical/tight
            self.state = ResourceHealthState.TIGHT
        else:
            self.state = ResourceHealthState.HEALTHY

        return self.state

    def calculate_headroom(self) -> int:
        """
        Calculate available headroom in bytes.

        Considers both host available memory and cgroup limits.
        Returns the minimum of host available and cgroup headroom.
        """
        host_headroom = self.host.mem_available_bytes

        # Cgroup headroom (max - current)
        if self.cgroup.memory_max_bytes > 0:
            cgroup_headroom = self.cgroup.memory_max_bytes - self.cgroup.memory_current_bytes
            host_headroom = min(host_headroom, cgroup_headroom)

        # Also consider memory_high as a soft limit
        if self.cgroup.memory_high_bytes > 0:
            high_headroom = self.cgroup.memory_high_bytes - self.cgroup.memory_current_bytes
            host_headroom = min(host_headroom, high_headroom)

        self.headroom_bytes = max(0, host_headroom)
        return self.headroom_bytes

    def get_summary(self) -> str:
        """Get a human-readable summary of current resource state."""
        lines = [
            f"Resource State: {self.state.value}",
            f"Headroom: {self.headroom_bytes / (1024*1024):.1f} MB",
            f"Host Memory: {self.host.mem_available_bytes / (1024*1024):.1f} / {self.host.mem_total_bytes / (1024*1024):.1f} MB available",
            f"PSI memory_some: {self.psi.memory_some.avg10:.1f}% (10s), {self.psi.memory_some.avg60:.1f}% (60s)",
            f"PSI memory_full: {self.psi.memory_full.avg10:.1f}% (10s), {self.psi.memory_full.avg60:.1f}% (60s)",
            f"Cgroup usage: {self.cgroup.memory_current_bytes / (1024*1024):.1f} / {self.cgroup.memory_max_bytes / (1024*1024):.1f} MB ({self.cgroup.usage_ratio():.1%})"
        ]

        if self.reasons:
            lines.append(f"Reasons: {'; '.join(self.reasons)}")

        if self.cgroup.events.has_oom():
            lines.append(f"WARNING: OOM events detected (oom: {self.cgroup.events.oom}, oom_kill: {self.cgroup.events.oom_kill})")

        return "\n".join(lines)
