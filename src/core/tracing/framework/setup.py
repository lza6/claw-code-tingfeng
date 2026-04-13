from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .provider import TraceProvider

GLOBAL_TRACE_PROVIDER: TraceProvider | None = None


def set_trace_provider(provider: TraceProvider) -> None:
    """Set the global trace provider used by tracing utilities."""
    global GLOBAL_TRACE_PROVIDER
    GLOBAL_TRACE_PROVIDER = provider


def get_trace_provider() -> TraceProvider:
    """Get the global trace provider used by tracing utilities."""
    global GLOBAL_TRACE_PROVIDER
    if GLOBAL_TRACE_PROVIDER is None:
        # 返回默认 provider
        from .provider import DefaultTraceProvider
        GLOBAL_TRACE_PROVIDER = DefaultTraceProvider()
    return GLOBAL_TRACE_PROVIDER
