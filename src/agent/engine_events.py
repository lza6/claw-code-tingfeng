"""Agent 事件发布器 — 负责 Agent 核心事件的发送"""
from __future__ import annotations

from typing import Any

from ..core.events import Event, EventBus, EventType


class EventPublisher:
    """事件发布器 — 统一管理 Agent 相关的事件发布"""

    def __init__(self, event_bus: EventBus, enabled: bool = True) -> None:
        self._event_bus = event_bus
        self._enabled = enabled
        self._configure_throttle()

    def _configure_throttle(self) -> None:
        """配置事件节流"""
        self._event_bus.set_throttle(EventType.AGENT_TOKEN_USAGE, 0.5)
        self._event_bus.set_throttle(EventType.AGENT_COST_UPDATE, 1.0)

    def publish_task_started(self, goal: str, max_iterations: int) -> None:
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.AGENT_TASK_STARTED,
            data={'goal': goal, 'max_iterations': max_iterations},
            source='agent_engine',
        ))

    def publish_task_completed(self, goal: str, result: str, tokens: int, steps: int) -> None:
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.AGENT_TASK_COMPLETED,
            data={'goal': goal, 'result': result, 'tokens': tokens, 'steps': steps},
            source='agent_engine',
        ))

    def publish_task_error(self, goal: str, error: str, error_code: str | None, tokens: int) -> None:
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.AGENT_TASK_ERROR,
            data={'goal': goal, 'error': error, 'error_code': error_code, 'tokens': tokens},
            source='agent_engine',
        ))

    def publish_llm_call_started(self, iteration: int, messages_count: int) -> None:
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.AGENT_LLM_CALL_STARTED,
            data={'iteration': iteration, 'messages_count': messages_count},
            source='agent_engine',
        ))

    def publish_llm_call_completed(self, iteration: int, model: str, usage: dict) -> None:
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.AGENT_LLM_CALL_COMPLETED,
            data={'iteration': iteration, 'model': model, 'usage': usage},
            source='agent_engine',
        ))

    def publish_tool_exec_started(self, tool_name: str, tool_args: dict) -> None:
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.AGENT_TOOL_EXEC_STARTED,
            data={'tool_name': tool_name, 'tool_args': tool_args},
            source='agent_engine',
        ))

    def publish_tool_exec_completed(self, tool_name: str, tool_args: dict, result: Any) -> None:
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.AGENT_TOOL_EXEC_COMPLETED,
            data={
                'tool_name': tool_name,
                'tool_args': tool_args,
                'success': getattr(result, 'success', False),
            },
            source='agent_engine',
        ))

    def publish_token_and_cost_update(self, tokens: int, cost_summary: dict | None) -> None:
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.AGENT_TOKEN_USAGE,
            data={'tokens': tokens, 'cost_summary': cost_summary},
            source='agent_engine',
        ))

    def publish_healing_event(self, healing_data: dict[str, Any]) -> None:
        """发布自愈事件数据"""
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.HEALING_EVENT,
            data=healing_data,
            source='self_healing',
        ))

    def publish_healing_stats(self, stats_data: dict[str, Any]) -> None:
        """发布自愈统计数据"""
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.HEALING_STATS_UPDATE,
            data=stats_data,
            source='self_healing',
        ))

    def publish_rag_metrics(self, rag_metrics: dict[str, Any]) -> None:
        """发布 RAG 指标"""
        if not self._enabled:
            return
        self._event_bus.publish(Event(
            type=EventType.RAG_INDEX_UPDATED,
            data=rag_metrics,
            source='rag',
        ))
