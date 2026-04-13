from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any


class StructuredLogger:
    """Structured JSONL Logger for automated analytics.

    Ported from Project B's telemetry system.
    """
    def __init__(self, component: str, log_file: Path | str) -> None:
        self.component = component
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._timers: dict[str, float] = {}

    def _write(self, level: str, event: str, **kwargs: Any) -> None:
        entry = {
            "timestamp": time.time(),
            "level": level,
            "component": self.component,
            "event": event,
            **kwargs
        }
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logging.error(f"Failed to write structured log: {e}")

    def info(self, event: str, **kwargs: Any) -> None:
        self._write("INFO", event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._write("ERROR", event, **kwargs)

    def start_timer(self, name: str) -> None:
        self._timers[name] = time.perf_counter()

    def stop_timer(self, name: str, event: str | None = None, **kwargs: Any) -> float:
        start = self._timers.pop(name, None)
        if start is None:
            return 0.0
        duration = time.perf_counter() - start
        if event:
            self.info(event, duration_s=duration, timer_name=name, **kwargs)
        return duration
