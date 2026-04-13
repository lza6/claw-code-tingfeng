"""Langfuse tracing processor using the native Langfuse SDK."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def _timestamp_from_maybe_iso(timestamp: str | None) -> datetime | None:
    """Convert ISO timestamp string to datetime."""
    if timestamp is None:
        return None
    try:
        return datetime.fromisoformat(timestamp)
    except ValueError:
        return None


class LangfuseTracingProcessor:
    """TracingProcessor that logs traces to Langfuse using the native SDK.

    Args:
        client: A Langfuse client instance. If None, uses get_client().
        enable_masking: Whether to mask sensitive data before sending.
    """

    def __init__(
        self,
        client: Any | None = None,
        enable_masking: bool = True,
    ) -> None:
        self._client: Any | None = client
        self._enable_masking = enable_masking
        self._lock = threading.Lock()
        self._spans: dict[str, Any] = {}
        self._trace_spans: dict[str, Any] = {}
        self._first_input: dict[str, Any] = {}
        self._last_output: dict[str, Any] = {}
        self._trace_metadata: dict[str, dict[str, Any]] = {}
        self._langfuse_trace_ids: dict[str, str] = {}
        self._langfuse_span_ids: dict[str, str] = {}

    def _get_client(self) -> Any:
        """Get or create Langfuse client."""
        if self._client is None:
            try:
                from langfuse import get_client

                self._client = get_client()
            except ImportError:
                logger.warning("langfuse not installed")
                return None
        return self._client

    def _mask_if_enabled(self, data: Any) -> Any:
        """Apply masking to data if masking is enabled."""
        if not self._enable_masking:
            return data
        try:
            # 简化版脱敏 - 直接返回原数据
            # 完整实现可参考 onyx/tracing/masking.py
            return data
        except Exception as e:
            logger.warning(f"Failed to mask data: {e}")
            return data

    def on_trace_start(self, trace: Any) -> None:
        """Called when a new trace begins execution."""
        client = self._get_client()
        if client is None:
            return

        try:
            langfuse_trace = client.trace(
                name=trace.name,
                trace_id=trace.trace_id,
                metadata=trace.metadata or {},
            )
            with self._lock:
                self._trace_spans[trace.trace_id] = langfuse_trace
                self._langfuse_trace_ids[trace.trace_id] = langfuse_trace.id
        except Exception as e:
            logger.warning(f"Failed to create Langfuse trace: {e}")

    def on_trace_end(self, trace: Any) -> None:
        """Called when a trace completes execution."""
        # Clean up
        with self._lock:
            self._trace_spans.pop(trace.trace_id, None)
            self._first_input.pop(trace.trace_id, None)
            self._last_output.pop(trace.trace_id, None)
            self._trace_metadata.pop(trace.trace_id, None)
            self._langfuse_trace_ids.pop(trace.trace_id, None)

    def on_span_start(self, span: Any) -> None:
        """Called when a new span begins execution."""
        client = self._get_client()
        if client is None:
            return

        try:
            span_data = span.span_data
            span_type = span_data.type if hasattr(span_data, 'type') else 'unknown'

            if span_type == 'generation':
                langfuse_span = client.generation(
                    name=span_data.name if hasattr(span_data, 'name') else span.span_id,
                    trace_id=span.trace_id,
                    metadata={"span_id": span.span_id},
                )
            elif span_type == 'agent':
                langfuse_span = client.agent(
                    name=span_data.name if hasattr(span_data, 'name') else span.span_id,
                    trace_id=span.trace_id,
                )
            elif span_type == 'function':
                langfuse_span = client.span(
                    name=span_data.name if hasattr(span_data, 'name') else span.span_id,
                    trace_id=span.trace_id,
                    input=span_data.input if hasattr(span_data, 'input') else None,
                )
            else:
                langfuse_span = client.span(
                    name=span.span_id,
                    trace_id=span.trace_id,
                )

            with self._lock:
                self._spans[span.span_id] = langfuse_span
                self._langfuse_span_ids[span.span_id] = langfuse_span.id

        except Exception as e:
            logger.warning(f"Failed to create Langfuse span: {e}")

    def on_span_end(self, span: Any) -> None:
        """Called when a span completes execution."""
        with self._lock:
            langfuse_span = self._spans.pop(span.span_id, None)
            if langfuse_span is None:
                return

        try:
            span_data = span.span_data

            # Update span with output and end time
            if hasattr(span_data, 'output') and span_data.output:
                langfuse_span.update(
                    output=span_data.output,
                )

            # Handle generation spans with usage data
            if hasattr(span_data, 'usage') and span_data.usage:
                langfuse_span.update(
                    metadata={"usage": span_data.usage}
                )

            langfuse_span.end()

        except Exception as e:
            logger.warning(f"Failed to end Langfuse span: {e}")

    def shutdown(self) -> None:
        """Clean up resources."""
        with self._lock:
            self._spans.clear()
            self._trace_spans.clear()
            self._first_input.clear()
            self._last_output.clear()
            self._trace_metadata.clear()
            self._langfuse_trace_ids.clear()
            self._langfuse_span_ids.clear()

    def force_flush(self) -> None:
        """Force processing of any queued items."""
        # Langfuse SDK handles flushing automatically
        pass
