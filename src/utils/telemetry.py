"""Telemetry Utility — Privacy-conscious performance tracking.
Ported from Project B (Zig core).
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VERSION = "0.1.0"

@dataclass
class TelemetryEvent:
    event_type: str
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    version: str = VERSION
    platform: str = os.name

    def to_dict(self) -> dict:
        return asdict(self)

class Telemetry:
    """Lightweight telemetry recorder.

    Disabled by default. Honors TINGFENG_NO_TELEMETRY environment variable.
    """

    def __init__(self, data_dir: str | Path, disabled: bool = True):
        self.enabled = not (disabled or os.environ.get("TINGFENG_NO_TELEMETRY"))
        self.data_dir = Path(data_dir)
        self.log_file = self.data_dir / "telemetry.ndjson"

        if self.enabled:
            self.data_dir.mkdir(parents=True, exist_ok=True)

    def record(self, event: TelemetryEvent):
        """Record an event to the local NDJSON file."""
        if not self.enabled:
            return

        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Failed to record telemetry: {e}")

    def record_tool_call(self, tool_name: str, latency_ms: float, is_error: bool, data_size_bytes: int = 0):
        """Record a tool execution event with token/data awareness."""
        event = TelemetryEvent(
            event_type="tool_call",
        )
        data = event.to_dict()
        data.update({
            "tool": tool_name,
            "latency_ms": latency_ms,
            "error": is_error,
            "data_size_bytes": data_size_bytes
        })
        self._write_raw(data)

    def record_codebase_stats(self, stats: dict[str, Any]):
        """Record high-level codebase statistics."""
        event = TelemetryEvent(
            event_type="codebase_stats",
        )
        data = event.to_dict()
        data.update(stats)
        self._write_raw(data)

    def _write_raw(self, data: dict):
        if not self.enabled:
            return
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Failed to record telemetry: {e}")
