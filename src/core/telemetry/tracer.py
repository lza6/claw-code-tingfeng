from __future__ import annotations

import contextlib
import logging
import time
from typing import Any

try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode
    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False

logger = logging.getLogger(__name__)


class Tracer:
    """企业级全链路追踪器"""

    def __init__(self, service_name: str = "clawd-agent"):
        self.service_name = service_name
        self._tracer = None
        if HAS_OTEL:
            self._tracer = trace.get_tracer(service_name)

    @contextlib.contextmanager
    def start_span(self, name: str, attributes: dict[str, Any] | None = None):
        """开始一个追踪跨度 (Span)"""
        if not HAS_OTEL or not self._tracer:
            start_time = time.monotonic()
            yield None
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.debug(f"[Trace] {name} completed in {duration_ms:.2f}ms")
            return

        with self._tracer.start_as_current_span(name, attributes=attributes) as span:
            try:
                yield span
                span.set_status(Status(StatusCode.OK))
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise


# 全局追踪器实例
_global_tracer = Tracer()


def get_tracer() -> Tracer:
    """获取全局追踪器"""
    return _global_tracer
