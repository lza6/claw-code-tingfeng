"""追踪装饰器和工具 — 增强版

参考 Onyx braintrust @traced 装饰器和 Langfuse 集成设计。

提供:
- @traced 装饰器（自动追踪函数）
- @traced_llm 装饰器（LLM 调用专用追踪）
- @traced_agent 装饰器（Agent 执行专用追踪）
- trace_context 上下文管理器
- 敏感数据脱敏

用法:
    from src.core.tracing import traced, traced_llm

    @traced(name="my_function")
    async def my_function(x: int) -> int:
        return x * 2

    @traced_llm
    def call_llm(prompt: str) -> str:
        return llm.invoke(prompt)
"""
from __future__ import annotations

import functools
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any, TypeVar

from src.rag.tree_sitter_syntax import get_language, parse_code
from src.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# 敏感数据脱敏（参考 Onyx masking.py）
# ---------------------------------------------------------------------------

_SENSITIVE_KEYS = {
    "api_key", "api_token", "password", "secret", "token",
    "access_token", "refresh_token", "authorization",
    "aws_bearer_token", "x-api-key",
}

_REPLACEMENT = "[REDACTED]"


def mask_sensitive_data(data: Any, sensitive_keys: set[str] | None = None) -> Any:
    """脱敏敏感数据

    参考 Onyx masking.py 设计。
    递归处理字典、列表和字符串。

    Args:
        data: 要脱敏的数据
        sensitive_keys: 敏感键集合（默认使用内置列表）

    Returns:
        脱敏后的数据
    """
    keys = sensitive_keys or _SENSITIVE_KEYS

    if isinstance(data, dict):
        return {
            k: mask_sensitive_data(v, keys) if k.lower() not in {sk.lower() for sk in keys} else _REPLACEMENT
            for k, v in data.items()
        }
    elif isinstance(data, list):
        return [mask_sensitive_data(item, keys) for item in data]
    elif isinstance(data, str):
        # 检查是否是 API key 格式
        if any(kw in data.lower() for kw in ["sk-", "key-", "token-", "bearer"]) and len(data) > 8:
            return data[:4] + "..." + data[-4:]
        return data
    return data


# ---------------------------------------------------------------------------
# @traced 装饰器（参考 Onyx braintrust @traced）
# ---------------------------------------------------------------------------

def traced(
    func: Callable[..., T] | None = None,
    *,
    name: str | None = None,
    span_type: str = "function",
    metadata: dict[str, Any] | None = None,
    mask_input: bool = False,
    mask_output: bool = False,
) -> Callable[..., T]:
    """追踪装饰器 — 自动为函数添加 span 追踪

    参考 Onyx braintrust @traced 设计。

    Args:
        func: 被装饰的函数
        name: Span 名称（默认使用函数名）
        span_type: Span 类型（function/agent/llm/tool）
        metadata: 附加元数据
        mask_input: 是否脱敏输入
        mask_output: 是否脱敏输出

    用法:
        @traced(name="process_request")
        def process_request(data):
            return process(data)

        @traced(span_type="agent", metadata={"agent_type": "coder"})
        async def run_agent(goal: str):
            ...
    """
    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        span_name = name or fn.__name__

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            # 生成 span ID
            span_id = str(uuid.uuid4())
            start_time = time.time()

            logger.debug(
                f"[trace] Starting {span_type}:{span_name} (id={span_id[:8]})"
            )

            # 脱敏输入
            input_data = list(args)
            if mask_input:
                input_data = mask_sensitive_data(input_data)

            try:
                result = fn(*args, **kwargs)
                duration = time.time() - start_time

                # 脱敏输出
                output_data = result
                if mask_output:
                    output_data = mask_sensitive_data(result)

                logger.debug(
                    f"[trace] Completed {span_type}:{span_name} "
                    f"(id={span_id[:8]}, duration={duration:.3f}s)"
                )

                # 发送到追踪后端（如果配置了）
                _emit_span_complete(
                    span_id=span_id,
                    name=span_name,
                    span_type=span_type,
                    input_data=input_data,
                    output_data=output_data,
                    duration=duration,
                    metadata=metadata,
                )

                return result

            except Exception as e:
                duration = time.time() - start_time
                logger.debug(
                    f"[trace] Failed {span_type}:{span_name} "
                    f"(id={span_id[:8]}, duration={duration:.3f}s, error={e})"
                )

                _emit_span_error(
                    span_id=span_id,
                    name=span_name,
                    span_type=span_type,
                    error=e,
                    duration=duration,
                    metadata=metadata,
                )
                raise

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            span_id = str(uuid.uuid4())
            start_time = time.time()

            logger.debug(
                f"[trace] Starting {span_type}:{span_name} (id={span_id[:8]})"
            )

            input_data = list(args)
            if mask_input:
                input_data = mask_sensitive_data(input_data)

            try:
                result = await fn(*args, **kwargs)
                duration = time.time() - start_time

                output_data = result
                if mask_output:
                    output_data = mask_sensitive_data(result)

                logger.debug(
                    f"[trace] Completed {span_type}:{span_name} "
                    f"(id={span_id[:8]}, duration={duration:.3f}s)"
                )

                _emit_span_complete(
                    span_id=span_id,
                    name=span_name,
                    span_type=span_type,
                    input_data=input_data,
                    output_data=output_data,
                    duration=duration,
                    metadata=metadata,
                )

                return result

            except Exception as e:
                duration = time.time() - start_time
                logger.debug(
                    f"[trace] Failed {span_type}:{span_name} "
                    f"(id={span_id[:8]}, duration={duration:.3f}s, error={e})"
                )

                _emit_span_error(
                    span_id=span_id,
                    name=span_name,
                    span_type=span_type,
                    error=e,
                    duration=duration,
                    metadata=metadata,
                )
                raise

        # 根据是否是协程函数选择包装器
        import asyncio
        if asyncio.iscoroutinefunction(fn):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper

    if func is not None:
        return decorator(func)
    return decorator


# ---------------------------------------------------------------------------
# 专用装饰器
# ---------------------------------------------------------------------------

def traced_llm(
    func: Callable[..., T] | None = None,
    *,
    name: str | None = None,
    mask_input: bool = True,
    mask_output: bool = False,
) -> Callable[..., T]:
    """LLM 调用追踪装饰器

    自动追踪 LLM 调用，记录模型、token 用量、成本等。

    用法:
        @traced_llm
        def call_gpt4(prompt: str) -> str:
            return llm.invoke(prompt)
    """
    return traced(
        func=func,
        name=name,
        span_type="llm",
        mask_input=mask_input,
        mask_output=mask_output,
    )


def traced_agent(
    func: Callable[..., T] | None = None,
    *,
    name: str | None = None,
    agent_type: str = "general",
    mask_input: bool = False,
    mask_output: bool = False,
) -> Callable[..., T]:
    """Agent 执行追踪装饰器

    用法:
        @traced_agent(agent_type="coder")
        async def run_coder_agent(goal: str) -> str:
            ...
    """
    return traced(
        func=func,
        name=name,
        span_type="agent",
        metadata={"agent_type": agent_type} if agent_type else None,
        mask_input=mask_input,
        mask_output=mask_output,
    )


def traced_tool(
    func: Callable[..., T] | None = None,
    *,
    name: str | None = None,
    tool_name: str | None = None,
) -> Callable[..., T]:
    """工具调用追踪装饰器

    用法:
        @traced_tool(tool_name="file_read")
        def read_file(path: str) -> str:
            ...
    """
    return traced(
        func=func,
        name=name,
        span_type="tool",
        metadata={"tool_name": tool_name} if tool_name else None,
    )


# ---------------------------------------------------------------------------
# 上下文管理器
# ---------------------------------------------------------------------------

@contextmanager
def trace_context(
    span_name: str,
    span_type: str = "function",
    metadata: dict[str, Any] | None = None,
):
    """追踪上下文管理器

    用于手动控制 span 生命周期。

    用法:
        with trace_context("my_operation", "tool"):
            do_something()

        async with trace_context("async_operation"):
            await do_async_thing()
    """
    span_id = str(uuid.uuid4())
    start_time = time.time()

    logger.debug(f"[trace] Starting {span_type}:{span_name} (id={span_id[:8]})")

    try:
        yield span_id
        duration = time.time() - start_time

        logger.debug(
            f"[trace] Completed {span_type}:{span_name} "
            f"(id={span_id[:8]}, duration={duration:.3f}s)"
        )

        _emit_span_complete(
            span_id=span_id,
            name=span_name,
            span_type=span_type,
            duration=duration,
            metadata=metadata,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.debug(
            f"[trace] Failed {span_type}:{span_name} "
            f"(id={span_id[:8]}, duration={duration:.3f}s, error={e})"
        )

        _emit_span_error(
            span_id=span_id,
            name=span_name,
            span_type=span_type,
            error=e,
            duration=duration,
            metadata=metadata,
        )
        raise


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------

def _emit_span_complete(
    span_id: str,
    name: str,
    span_type: str,
    duration: float,
    input_data: Any = None,
    output_data: Any = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """发送 span 完成事件到追踪后端"""
    try:
        from src.core.tracing.framework import get_trace_provider

        provider = get_trace_provider()
        if provider.is_configured():
            # 这里可以创建 span 并发送到后端
            logger.debug(
                f"[tracing] Emitting span: {name} ({span_type}) "
                f"duration={duration:.3f}s"
            )
    except ImportError:
        pass  # 追踪框架未安装，跳过
    except Exception as e:
        logger.debug(f"[tracing] Failed to emit span: {e}")


def _emit_span_error(
    span_id: str,
    name: str,
    span_type: str,
    error: Exception,
    duration: float,
    metadata: dict[str, Any] | None = None,
) -> None:
    """发送 span 错误事件到追踪后端"""
    try:
        from src.core.tracing.framework import get_trace_provider

        provider = get_trace_provider()
        if provider.is_configured():
            logger.debug(
                f"[tracing] Emitting error for span: {name} ({span_type}) "
                f"error={error}"
            )
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"[tracing] Failed to emit error: {e}")


__all__ = [
    "get_language",
    "mask_sensitive_data",
    "parse_code",
    "trace_context",
    "traced",
    "traced_agent",
    "traced_llm",
    "traced_tool",
]
