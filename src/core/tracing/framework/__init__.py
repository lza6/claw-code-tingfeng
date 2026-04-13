"""
Tracing Framework - 整合自 Onyx (v0.50+)

提供完整的分布式追踪能力:
- TracingProcessor 接口
- Trace/Span 生命周期管理
- Langfuse/Braintrust 集成
- 敏感数据脱敏

移植自 onyx-main/backend/onyx/tracing/framework/
"""
from .processor_interface import TracingExporter, TracingProcessor
from .provider import DefaultTraceProvider, TraceProvider
from .setup import get_trace_provider, set_trace_provider
from .span_data import AgentSpanData, FunctionSpanData, GenerationSpanData, SpanData
from .spans import Span
from .traces import Trace

__all__ = [
    "AgentSpanData",
    # Provider
    "DefaultTraceProvider",
    "FunctionSpanData",
    "GenerationSpanData",
    # 核心
    "Span",
    # 数据类
    "SpanData",
    "Trace",
    "TraceProvider",
    "TracingExporter",
    # 接口
    "TracingProcessor",
    "get_trace_provider",
    "set_trace_provider",
]
