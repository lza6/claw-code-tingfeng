"""Backward compatibility wrapper for src.core.metrics_exporter."""
from .telemetry.exporter import (
    MetricPoint,
    MetricsCollector,
    get_metrics_collector,
    reset_metrics_collector,
)

__all__ = [
    "MetricPoint",
    "MetricsCollector",
    "get_metrics_collector",
    "reset_metrics_collector",
]
