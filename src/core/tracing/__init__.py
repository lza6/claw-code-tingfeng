"""Tracing Package — 分布式追踪 (整合自 Onyx v0.50+)

支持多种追踪后端:
- Langfuse
- Braintrust
- OpenTelemetry (预留)

模块结构:
- framework/     : 核心框架 (Trace/Span/Processor)
- langfuse_tracing_processor.py : Langfuse集成
- braintrust_tracing_processor.py : Braintrust集成 (预留)
- setup.py        : 统一初始化
- masking.py     : 敏感数据脱敏
"""
from .framework import (
    AgentSpanData,
    DefaultTraceProvider,
    FunctionSpanData,
    GenerationSpanData,
    Span,
    SpanData,
    Trace,
    TracingExporter,
    TracingProcessor,
    get_trace_provider,
    set_trace_provider,
)
from .langfuse_tracing_processor import LangfuseTracingProcessor
from .setup import setup_tracing

# 兼容旧接口 - 懒加载避免 opentelemetry 依赖问题
try:
    from .otel import (
        SpanKind,
        Status,
        StatusCode,
        Tracing,
        TracingConfig,
        get_tracer,
        trace_async,
        trace_sync,
    )
    _otel_available = True
except ImportError:
    _otel_available = False
    # 提供空实现
    class TracingConfig:
        pass
    class Tracing:
        pass
    def trace_async(*args, **kwargs):
        async def wrapper(func):
            return func
        return wrapper
    def trace_sync(*args, **kwargs):
        def wrapper(func):
            return func
        return wrapper
    def get_tracer(name):
        return None
    class SpanKind:
        pass
    class Status:
        pass
    class StatusCode:
        pass

__all__ = [
    "AgentSpanData",
    "DefaultTraceProvider",
    "FunctionSpanData",
    "GenerationSpanData",
    # Provider
    "LangfuseTracingProcessor",
    "Span",
    "SpanData",
    "SpanKind",
    "Status",
    "StatusCode",
    "Trace",
    "Tracing",
    # 兼容旧接口
    "TracingConfig",
    "TracingExporter",
    # 框架核心
    "TracingProcessor",
    "get_trace_provider",
    "get_tracer",
    "set_trace_provider",
    # 初始化
    "setup_tracing",
    "trace_async",
    "trace_sync",
]
