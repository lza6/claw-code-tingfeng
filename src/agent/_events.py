"""AgentEngine 事件处理 - 事件发布逻辑

从 engine.py 拆分，负责：
- 事件背压配置
- 任务/步骤/工具/LLM 事件发布
- Token 用量和成本更新事件
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..core.events import Event, EventType

if TYPE_CHECKING:
    from ..core.events import EventBus


class EventMixin:
    """事件处理 Mixin

    提供事件发布功能。
    需要与设置了 enable_events 和 _event_bus 属性的类配合使用。
    """

    enable_events: bool
    _event_bus: EventBus

    def _configure_event_backpressure(self) -> None:
        """配置事件总线背压控制

        对高频事件启用节流和采样：
        - TOKEN_USAGE: 每 0.5 秒最多发布一次（节流）
        - COST_UPDATE: 每 1.0 秒最多发布一次（节流）
        """
        # 节流配置
        self._event_bus.set_throttle(EventType.AGENT_TOKEN_USAGE, 0.5)
        self._event_bus.set_throttle(EventType.AGENT_COST_UPDATE, 1.0)

    def publish_task_started(self, goal: str, max_iterations: int) -> None:
        """发布任务开始事件"""
        if self.enable_events:
            self._event_bus.publish(Event(
                type=EventType.AGENT_STEP_STARTED,
                data={'goal': goal, 'max_iterations': max_iterations},
                source='agent_engine',
            ))

    def publish_llm_call_started(self, iteration: int, message_count: int) -> None:
        """发布 LLM 调用开始事件"""
        if self.enable_events:
            self._event_bus.publish(Event(
                type=EventType.LLM_CALL_STARTED,
                data={'iteration': iteration, 'message_count': message_count},
                source='agent_engine',
            ))

    def publish_llm_call_completed(self, iteration: int, model: str, tokens: dict[str, Any]) -> None:
        """发布 LLM 调用完成事件"""
        if self.enable_events:
            self._event_bus.publish(Event(
                type=EventType.LLM_CALL_COMPLETED,
                data={
                    'iteration': iteration,
                    'model': model,
                    'tokens': tokens,
                },
                source='agent_engine',
            ))

    def publish_tool_exec_started(self, tool_name: str, args: dict[str, Any]) -> None:
        """发布工具执行开始事件"""
        if self.enable_events:
            self._event_bus.publish(Event(
                type=EventType.TOOL_EXEC_STARTED,
                data={'tool_name': tool_name, 'args': args},
                source='agent_engine',
            ))

    def publish_tool_exec_completed(self, tool_name: str, args: dict[str, Any], result: Any) -> None:
        """发布工具执行完成/错误事件"""
        if self.enable_events:
            event_type = EventType.TOOL_EXEC_COMPLETED if result.success else EventType.TOOL_EXEC_ERROR
            self._event_bus.publish(Event(
                type=event_type,
                data={
                    'tool_name': tool_name,
                    'args': args,
                    'success': result.success,
                    'output': str(result.output)[:500] if result.output else '',
                    'error': str(result.error) if result.error else '',
                },
                source='agent_engine',
            ))

    def publish_task_completed(self, goal: str, result: str, total_tokens: int, steps_count: int) -> None:
        """发布任务完成事件"""
        if self.enable_events:
            self._event_bus.publish(Event(
                type=EventType.AGENT_TASK_COMPLETED,
                data={
                    'goal': goal,
                    'result': result[:500] if result else '',
                    'total_tokens': total_tokens,
                    'steps_count': steps_count,
                },
                source='agent_engine',
            ))

    def publish_task_error(self, goal: str, error: str, error_code: str | None, total_tokens: int) -> None:
        """发布任务错误事件"""
        if self.enable_events:
            data: dict[str, Any] = {
                'goal': goal,
                'error': error,
                'total_tokens': total_tokens,
            }
            if error_code:
                data['error_code'] = error_code
            self._event_bus.publish(Event(
                type=EventType.AGENT_TASK_ERROR,
                data=data,
                source='agent_engine',
            ))

    def publish_token_and_cost_update(self, total_tokens: int, cost_summary: dict[str, Any] | None) -> None:
        """发布 Token 用量和成本更新事件"""
        if self.enable_events:
            self._event_bus.publish(Event(
                type=EventType.AGENT_TOKEN_USAGE,
                data={'total_tokens': total_tokens},
                source='agent_engine',
            ))
            if cost_summary:
                self._event_bus.publish(Event(
                    type=EventType.AGENT_COST_UPDATE,
                    data=cost_summary,
                    source='agent_engine',
                ))
