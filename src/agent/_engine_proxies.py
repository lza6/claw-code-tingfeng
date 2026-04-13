"""Engine Proxy Methods - Event, Stream, and Lifecycle delegation.

v0.38.x: Extracted from engine.py for better modularization.

These methods delegate to composed objects (EventPublisher, StreamExecutor, LifecycleManager)
to keep the main AgentEngine class focused on core logic.

Backward compatible: All methods keep the same signatures.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .engine import AgentEngine

__all__ = [
    'setup_event_proxies',
    'setup_lifecycle_proxies',
    'setup_stream_proxies',
]


def setup_event_proxies(engine: AgentEngine) -> None:
    """Set up event publishing proxy methods on AgentEngine.

    These methods delegate to the composed EventPublisher object.
    """

    # Event proxy methods - delegate to _event_publisher
    def publish_task_started(self: AgentEngine, goal: str, max_iterations: int) -> None:
        """发布任务开始事件 — 代理到 EventPublisher"""
        self._event_publisher.publish_task_started(goal, max_iterations)

    def publish_task_completed(
        self: AgentEngine, goal: str, result: str, tokens: int, steps: int
    ) -> None:
        """发布任务完成事件 — 代理到 EventPublisher"""
        self._event_publisher.publish_task_completed(goal, result, tokens, steps)

    def publish_task_error(
        self: AgentEngine, goal: str, error: str, error_code: str | None, tokens: int
    ) -> None:
        """发布任务错误事件 — 代理到 EventPublisher"""
        self._event_publisher.publish_task_error(goal, error, error_code, tokens)

    def publish_llm_call_started(self: AgentEngine, iteration: int, messages_count: int) -> None:
        """发布 LLM 调用开始事件 — 代理到 EventPublisher"""
        self._event_publisher.publish_llm_call_started(iteration, messages_count)

    def publish_llm_call_completed(self: AgentEngine, iteration: int, model: str, usage: dict) -> None:
        """发布 LLM 调用完成事件 — 代理到 EventPublisher"""
        self._event_publisher.publish_llm_call_completed(iteration, model, usage)

    def publish_tool_exec_started(
        self: AgentEngine, tool_name: str, tool_args: dict
    ) -> None:
        """发布工具执行开始事件 — 代理到 EventPublisher"""
        self._event_publisher.publish_tool_exec_started(tool_name, tool_args)

    def publish_tool_exec_completed(
        self: AgentEngine, tool_name: str, tool_args: dict, result: Any
    ) -> None:
        """发布工具执行完成事件 — 代理到 EventPublisher"""
        self._event_publisher.publish_tool_exec_completed(tool_name, tool_args, result)

    def publish_token_and_cost_update(
        self: AgentEngine, tokens: int, cost_summary: dict | None
    ) -> None:
        """发布 token 和成本更新事件 — 代理到 EventPublisher"""
        self._event_publisher.publish_token_and_cost_update(tokens, cost_summary)

    # Bind methods to engine instance
    engine.publish_task_started = publish_task_started  # type: ignore[method-assign]
    engine.publish_task_completed = publish_task_completed  # type: ignore[method-assign]
    engine.publish_task_error = publish_task_error  # type: ignore[method-assign]
    engine.publish_llm_call_started = publish_llm_call_started  # type: ignore[method-assign]
    engine.publish_llm_call_completed = publish_llm_call_completed  # type: ignore[method-assign]
    engine.publish_tool_exec_started = publish_tool_exec_started  # type: ignore[method-assign]
    engine.publish_tool_exec_completed = publish_tool_exec_completed  # type: ignore[method-assign]
    engine.publish_token_and_cost_update = publish_token_and_cost_update  # type: ignore[method-assign]


def setup_stream_proxies(engine: AgentEngine) -> None:
    """Set up streaming execution proxy methods on AgentEngine.

    These methods delegate to the composed StreamExecutor object.
    """
    # Stream proxy methods - delegate to _stream_executor
    async def run_structured(
        self: AgentEngine, goal: str, output_schema: dict[str, Any]
    ) -> Any:
        """运行 LLM 结构化输出 — 代理到 StreamExecutor"""
        return await self._stream_executor.run_structured(goal, output_schema)

    def has_structured_llm_support(self: AgentEngine) -> bool:
        """检查是否支持结构化输出 — 代理到 StreamExecutor"""
        return self._stream_executor.has_structured_support()

    # Bind methods to engine instance
    engine.run_structured = run_structured  # type: ignore[method-assign]
    engine.has_structured_llm_support = has_structured_llm_support  # type: ignore[method-assign]


def setup_lifecycle_proxies(engine: AgentEngine) -> None:
    """Set up lifecycle management proxy methods on AgentEngine.

    These methods delegate to the composed LifecycleManager object.
    """
    # Lifecycle proxy methods - delegate to _lifecycle
    async def graceful_shutdown(self: AgentEngine, timeout: float = 5.0) -> None:
        """优雅关闭 — 代理到 LifecycleManager"""
        await self._lifecycle.shutdown(timeout)

    def is_shutting_down(self: AgentEngine) -> bool:
        """检查是否正在关闭 — 代理到 LifecycleManager"""
        return self._lifecycle.is_shutting_down()

    # Bind methods to engine instance
    engine.graceful_shutdown = graceful_shutdown  # type: ignore[method-assign]
    engine.is_shutting_down = is_shutting_down  # type: ignore[method-assign]
