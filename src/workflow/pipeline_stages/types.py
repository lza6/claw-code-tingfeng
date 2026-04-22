"""
Common types for pipeline stages.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class StageContext:
    """Context passed to pipeline stages."""
    task: str
    cwd: str
    session_id: str | None = None
    artifacts: dict[str, Any] | None = None

    def __post_init__(self):
        if self.artifacts is None:
            self.artifacts = {}


@dataclass
class StageResult:
    """Result from a pipeline stage."""
    status: str  # 'completed', 'failed', 'skipped'
    artifacts: dict[str, Any]
    duration_ms: int
    error: str | None = None
