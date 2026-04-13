"""Backward compatibility wrapper for src.core.output_compressor."""
from .telemetry.compressor_models import DEFAULT_FILTER, FilterRule, FilterStrategy
from .telemetry.output_compressor import OutputCompressor

__all__ = [
    "DEFAULT_FILTER",
    "FilterRule",
    "FilterStrategy",
    "OutputCompressor",
]
