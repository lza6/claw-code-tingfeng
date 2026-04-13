"""OpenTelemetry Tracing — 分布式追踪（参考 Onyx）"""
from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from dataclasses import dataclass

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace.exporter import OTLPSpanExporter
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)
from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

logger = logging.getLogger(__name__)

# Context变量
span_context: ContextVar[object | None] = ContextVar("span_context", default=None)


@dataclass
class TracingConfig:
    """追踪配置"""
    service_name: str = "clawd"
    service_version: str = "0.1.0"
    jaeger_endpoint: str | None = None
    otlp_endpoint: str | None = None
    log_spans: bool = False


class Tracing:
    """分布式追踪管理器"""

    _initialized = False
    _tracer: Tracer | None = None
    _propagator = TraceContextTextMapPropagator()

    @classmethod
    def initialize(cls, config: TracingConfig | None = None):
        """初始化追踪"""
        if cls._initialized:
            return

        config = config or TracingConfig()

        # 创建资源
        resource = Resource.create({
            SERVICE_NAME: config.service_name,
            "service.version": config.service_version,
        })

        # 创建 provider
        provider = TracerProvider(resource=resource)

        # 添加控制台导出器（开发用）
        if config.log_spans or os.getenv("CLAWD_LOG_SPANS"):
            processor = BatchSpanProcessor(ConsoleSpanExporter())
            provider.add_span_processor(processor)

        # 添加 OTLP 导出器（生产用）
        if config.otlp_endpoint or os.getenv("OTLP_ENDPOINT"):
            exporter = OTLPSpanExporter(
                endpoint=config.otlp_endpoint or os.getenv("OTLP_ENDPOINT"),
            )
            provider.add_span_processor(BatchSpanExporter(exporter))

        # 添加 Jaeger 导出器（可选）
        if config.jaeger_endpoint:
            from opentelemetry.exporter.jaeger.thrift import JaegerExporter
            from opentelemetry.sdk.trace.export import BatchSpanProcessor as BatchSpanProcessor

            jaeger_exporter = JaegerExporter(
                agent_host_name=config.jaeger_endpoint.split(":")[0],
                agent_port=int(config.jaeger_endpoint.split(":")[1]) if ":" in config.jaeger_endpoint else 6831,
            )
            provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))

        trace.set_tracer_provider(provider)
        cls._tracer = trace.get_tracer(config.service_name)

        # 注入日志Instrumentor
        LoggingInstrumentor().instrument(set_logging_format=True)

        cls._initialized = True
        logger.info(f"Tracing initialized: {config.service_name}")

    @classmethod
    def get_tracer(cls) -> Tracer:
        """获取 Tracer"""
        if not cls._initialized:
            cls.initialize()
        return cls._tracer or trace.get_tracer("clawd")

    @classmethod
    def start_span(
        cls,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: dict | None = None,
    ):
        """开始span"""
        tracer = cls.get_tracer()
        span = tracer.start_span(name, kind=kind)

        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, str(value))

        return span

    @classmethod
    def with_trace(cls, name: str, **attributes):
        """上下文管理器：追踪"""
        class TraceContext:
            def __init__(self, name, attrs):
                self.name = name
                self.attrs = attrs
                self.span = None

            def __enter__(self):
                self.span = cls.start_span(self.name, attributes=self.attrs)
                return self.span

            def __exit__(self, exc_type, exc_val, exc_tb):
                if self.span:
                    if exc_type:
                        self.span.set_status(Status(StatusCode.ERROR, str(exc_val)))
                        self.span.record_exception(exc_val)
                    self.span.end()

        return TraceContext(name, attributes)

    @classmethod
    def inject(cls, carrier: dict):
        """注入trace上下文到carrier"""
        cls._propagator.inject(carrier)

    @classmethod
    def extract(cls, carrier: dict):
        """从carrier提取trace上下文"""
        return cls._propagator.extract(carrier)


# 便捷函数
def trace_async(name: str, kind: SpanKind = SpanKind.INTERNAL):
    """装饰器：异步函数追踪"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            with Tracing.with_trace(name, attributes={"function": func.__name__}):
                return await func(*args, **kwargs)
        return wrapper
    return decorator


def trace_sync(name: str, kind: SpanKind = SpanKind.INTERNAL):
    """装饰器：同步函数追踪"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            with Tracing.with_trace(name, attributes={"function": func.__name__}):
                return func(*args, **kwargs)
        return wrapper
    return decorator


def get_tracer() -> Tracer:
    """获取全局 Tracer"""
    return Tracing.get_tracer()


__all__ = [
    "SpanKind",
    "Status",
    "StatusCode",
    "Tracing",
    "TracingConfig",
    "get_tracer",
    "trace_async",
    "trace_sync",
]
