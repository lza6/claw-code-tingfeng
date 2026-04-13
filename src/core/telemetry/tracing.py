"""
追踪模块 - 整合自 Onyx 的 Tracing 框架

支持多种追踪后端:
- Langfuse
- Braintrust
- OpenTelemetry (预留)
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class TracingProvider(str, Enum):
    """追踪提供者"""
    NONE = "none"
    LANGFUSE = "langfuse"
    BRAINTRUST = "braintrust"
    OPENTELEMETRY = "opentelemetry"


@dataclass
class TraceContext:
    """追踪上下文"""
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMCall:
    """LLM 调用记录"""
    model: str
    messages: list[dict[str, str]]
    response: str | None = None
    latency_ms: float = 0
    tokens_used: int = 0
    cost: float = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class TracingProcessor:
    """追踪处理器基类"""

    def __init__(self, provider: TracingProvider):
        self.provider = provider
        self.enabled = False

    def start_trace(self, name: str, metadata: dict | None = None) -> TraceContext:
        """开始追踪"""
        raise NotImplementedError

    def end_trace(self, context: TraceContext) -> None:
        """结束追踪"""
        raise NotImplementedError

    def record_llm_call(self, call: LLMCall) -> None:
        """记录 LLM 调用"""
        raise NotImplementedError


class LangfuseProcessor(TracingProcessor):
    """Langfuse 追踪处理器"""

    def __init__(self):
        super().__init__(TracingProvider.LANGFUSE)
        self._client = None

    def _ensure_client(self):
        """确保 Langfuse 客户端已初始化"""
        if self._client is None:
            try:
                from langfuse import Langfuse
                self._client = Langfuse(
                    public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
                    secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
                    host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
                )
                self.enabled = True
                logger.info("Langfuse 追踪已启用")
            except ImportError:
                logger.warning("langfuse 未安装，跳过追踪")
            except Exception as e:
                logger.warning(f"Langfuse 初始化失败: {e}")

    def start_trace(self, name: str, metadata: dict | None = None) -> TraceContext:
        """开始追踪"""
        self._ensure_client()
        if not self.enabled:
            return TraceContext(trace_id="", span_id="")

        import uuid
        trace_id = str(uuid.uuid4())
        span_id = str(uuid.uuid4())

        try:
            self._client.trace(
                name=name,
                trace_id=trace_id,
                metadata=metadata or {},
            )
        except Exception as e:
            logger.warning(f"创建 trace 失败: {e}")

        return TraceContext(trace_id=trace_id, span_id=span_id, metadata=metadata or {})

    def record_llm_call(self, call: LLMCall) -> None:
        """记录 LLM 调用"""
        if not self.enabled:
            return

        try:
            self._client.generation(
                model=call.model,
                input=call.messages,
                output=call.response,
                metadata={
                    "latency_ms": call.latency_ms,
                    "tokens_used": call.tokens_used,
                    "cost": call.cost,
                    **call.metadata,
                },
            )
        except Exception as e:
            logger.warning(f"记录 LLM 调用失败: {e}")


class BraintrustProcessor(TracingProcessor):
    """Braintrust 追踪处理器"""

    def __init__(self):
        super().__init__(TracingProvider.BRAINTRUST)
        self._client = None

    def _ensure_client(self):
        """确保 Braintrust 客户端已初始化"""
        if self._client is None:
            try:
                import braintrust
                self._client = braintrust
                self.enabled = True
                logger.info("Braintrust 追踪已启用")
            except ImportError:
                logger.warning("braintrust 未安装，跳过追踪")
            except Exception as e:
                logger.warning(f"Braintrust 初始化失败: {e}")

    def start_trace(self, name: str, metadata: dict | None = None) -> TraceContext:
        """开始追踪"""
        self._ensure_client()
        if not self.enabled:
            return TraceContext(trace_id="", span_id="")

        import uuid
        return TraceContext(
            trace_id=str(uuid.uuid4()),
            span_id=str(uuid.uuid4()),
            metadata=metadata or {},
        )

    def record_llm_call(self, call: LLMCall) -> None:
        """记录 LLM 调用"""
        if not self.enabled:
            return

        # Braintrust 使用装饰器方式记录
        logger.debug(f"Braintrust: LLM call to {call.model}, latency={call.latency_ms}ms")


class TracingManager:
    """追踪管理器"""

    _instance: TracingProcessor | None = None

    @classmethod
    def initialize(cls, provider: TracingProvider | None = None) -> TracingProcessor:
        """初始化追踪器"""
        if provider is None:
            provider_str = os.environ.get("TRACING_PROVIDER", "none").lower()
            try:
                provider = TracingProvider(provider_str)
            except ValueError:
                provider = TracingProvider.NONE

        if provider == TracingProvider.LANGFUSE:
            cls._instance = LangfuseProcessor()
        elif provider == TracingProvider.BRAINTRUST:
            cls._instance = BraintrustProcessor()
        else:
            cls._instance = TracingProcessor(provider)

        logger.info(f"追踪器已初始化: {provider.value}")
        return cls._instance

    @classmethod
    def get_processor(cls) -> TracingProcessor:
        """获取追踪处理器"""
        if cls._instance is None:
            cls._instance = cls.initialize()
        return cls._instance

    @classmethod
    @contextmanager
    def trace(cls, name: str, metadata: dict | None = None):
        """追踪上下文管理器"""
        processor = cls.get_processor()
        context = processor.start_trace(name, metadata)
        try:
            yield context
        finally:
            processor.end_trace(context)


# 便捷函数
def init_tracing(provider: TracingProvider | None = None) -> TracingProcessor:
    """初始化追踪"""
    return TracingManager.initialize(provider)


def get_tracing_processor() -> TracingProcessor:
    """获取追踪处理器"""
    return TracingManager.get_processor()


@contextmanager
def trace(name: str, metadata: dict | None = None):
    """追踪上下文"""
    with TracingManager.trace(name, metadata) as ctx:
        yield ctx


def record_llm_call(call: LLMCall) -> None:
    """记录 LLM 调用"""
    TracingManager.get_processor().record_llm_call(call)


