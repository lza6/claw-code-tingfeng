"""Event Publisher — 组合模式替代 EventMixin

负责 Agent 事件发布（任务/步骤/工具/LLM 事件），
通过组合方式注入 AgentEngine，消除类型系统崩溃。
"""
from __future__ import annotations

from typing import Any

from ..core.events import Event, EventBus, EventType


class EventPublisher:
    """事件发布器 — 组合模式替代 EventMixin

    所有原本通过 Mixin 访问 self._event_bus 和 self.enable_events 的方法，
    现在通过组合对象的自有属性实现，无需 # type: ignore。
    """

    def __init__(self, event_bus: EventBus, enabled: bool = True) -> None:
        self._event_bus = event_bus
        self._enabled = enabled
        self._configure_throttle()

    def _configure_throttle(self) -> None:
        """配置事件节流"""
        self._event_bus.set_throttle(EventType.AGENT_TOKEN_USAGE, 0.5)
        self._event_bus.set_throttle(EventType.AGENT_COST_UPDATE, 1.0)

    def configure_backpressure(self) -> None:
        """配置事件背压 — 代理方法"""
        self._configure_throttle()

    def publish_task_started(self, goal: str, max_iterations: int) -> None:
        """发布任务开始事件"""
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.AGENT_TASK_STARTED,
            data={'goal': goal, 'max_iterations': max_iterations},
            source='agent_engine',
        ))

    def publish_task_completed(self, goal: str, result: str, tokens: int, steps: int) -> None:
        """发布任务完成事件"""
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.AGENT_TASK_COMPLETED,
            data={'goal': goal, 'result': result, 'tokens': tokens, 'steps': steps},
            source='agent_engine',
        ))

    def publish_task_error(self, goal: str, error: str, error_code: str | None, tokens: int) -> None:
        """发布任务错误事件"""
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.AGENT_TASK_ERROR,
            data={'goal': goal, 'error': error, 'error_code': error_code, 'tokens': tokens},
            source='agent_engine',
        ))

    def publish_llm_call_started(self, iteration: int, messages_count: int) -> None:
        """发布 LLM 调用开始事件"""
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.AGENT_LLM_CALL_STARTED,
            data={'iteration': iteration, 'messages_count': messages_count},
            source='agent_engine',
        ))

    def publish_llm_call_completed(self, iteration: int, model: str, usage: dict) -> None:
        """发布 LLM 调用完成事件"""
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.AGENT_LLM_CALL_COMPLETED,
            data={'iteration': iteration, 'model': model, 'usage': usage},
            source='agent_engine',
        ))

    def publish_tool_exec_started(self, tool_name: str, tool_args: dict) -> None:
        """发布工具执行开始事件"""
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.AGENT_TOOL_EXEC_STARTED,
            data={'tool_name': tool_name, 'tool_args': tool_args},
            source='agent_engine',
        ))

    def publish_tool_exec_completed(self, tool_name: str, tool_args: dict, result: Any) -> None:
        """发布工具执行完成事件"""
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.AGENT_TOOL_EXEC_COMPLETED,
            data={
                'tool_name': tool_name,
                'tool_args': tool_args,
                'success': result.success if hasattr(result, 'success') else False,
            },
            source='agent_engine',
        ))

    def publish_token_and_cost_update(self, tokens: int, cost_summary: dict | None) -> None:
        """发布 token 和成本更新事件"""
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.AGENT_TOKEN_USAGE,
            data={'tokens': tokens, 'cost_summary': cost_summary},
            source='agent_engine',
        ))
