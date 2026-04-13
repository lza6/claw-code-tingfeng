"""EventPublisher 测试 - 事件发布器"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, call

from src.agent._event_publisher import EventPublisher
from src.core.events import EventBus


class TestEventPublisherCreation:
    """EventPublisher 创建测试"""

    def test_create_default(self):
        """测试默认创建"""
        event_bus = EventBus()
        publisher = EventPublisher(event_bus=event_bus)
        assert publisher._enabled is True

    def test_create_disabled(self):
        """测试创建禁用状态"""
        event_bus = EventBus()
        publisher = EventPublisher(event_bus=event_bus, enabled=False)
        assert publisher._enabled is False


class TestEventPublisherTaskEvents:
    """任务事件发布测试"""

    def test_publish_task_started(self):
        """测试发布任务开始事件"""
        event_bus = EventBus()
        event_bus.publish = MagicMock()
        publisher = EventPublisher(event_bus=event_bus)

        publisher.publish_task_started(goal="测试任务", max_iterations=10)

        event_bus.publish.assert_called_once()
        event = event_bus.publish.call_args[0][0]
        assert event.data['goal'] == "测试任务"
        assert event.data['max_iterations'] == 10

    def test_publish_task_completed(self):
        """测试发布任务完成事件"""
        event_bus = EventBus()
        event_bus.publish = MagicMock()
        publisher = EventPublisher(event_bus=event_bus)

        publisher.publish_task_completed(
            goal="测试任务",
            result="完成",
            tokens=500,
            steps=5,
        )

        event_bus.publish.assert_called_once()
        event = event_bus.publish.call_args[0][0]
        assert event.data['goal'] == "测试任务"
        assert event.data['result'] == "完成"
        assert event.data['tokens'] == 500
        assert event.data['steps'] == 5

    def test_publish_task_error(self):
        """测试发布任务错误事件"""
        event_bus = EventBus()
        event_bus.publish = MagicMock()
        publisher = EventPublisher(event_bus=event_bus)

        publisher.publish_task_error(
            goal="测试任务",
            error="错误信息",
            error_code="ERR001",
            tokens=100,
        )

        event_bus.publish.assert_called_once()
        event = event_bus.publish.call_args[0][0]
        assert event.data['goal'] == "测试任务"
        assert event.data['error'] == "错误信息"
        assert event.data['error_code'] == "ERR001"
        assert event.data['tokens'] == 100

    def test_disabled_publisher_does_not_publish(self):
        """测试禁用的发布器不发布事件"""
        event_bus = EventBus()
        event_bus.publish = MagicMock()
        publisher = EventPublisher(event_bus=event_bus, enabled=False)

        publisher.publish_task_started(goal="测试", max_iterations=5)

        event_bus.publish.assert_not_called()


class TestEventPublisherLLMEvents:
    """LLM 事件发布测试"""

    def test_publish_llm_call_started(self):
        """测试发布 LLM 调用开始事件"""
        event_bus = EventBus()
        event_bus.publish = MagicMock()
        publisher = EventPublisher(event_bus=event_bus)

        publisher.publish_llm_call_started(iteration=1, messages_count=3)

        event_bus.publish.assert_called_once()
        event = event_bus.publish.call_args[0][0]
        assert event.data['iteration'] == 1
        assert event.data['messages_count'] == 3

    def test_publish_llm_call_completed(self):
        """测试发布 LLM 调用完成事件"""
        event_bus = EventBus()
        event_bus.publish = MagicMock()
        publisher = EventPublisher(event_bus=event_bus)

        usage = {'prompt_tokens': 100, 'completion_tokens': 50}
        publisher.publish_llm_call_completed(
            iteration=1,
            model="gpt-4",
            usage=usage,
        )

        event_bus.publish.assert_called_once()
        event = event_bus.publish.call_args[0][0]
        assert event.data['iteration'] == 1
        assert event.data['model'] == "gpt-4"
        assert event.data['usage'] == usage


class TestEventPublisherToolEvents:
    """工具事件发布测试"""

    def test_publish_tool_exec_started(self):
        """测试发布工具执行开始事件"""
        event_bus = EventBus()
        event_bus.publish = MagicMock()
        publisher = EventPublisher(event_bus=event_bus)

        publisher.publish_tool_exec_started(
            tool_name="BashTool",
            tool_args={"command": "ls"},
        )

        event_bus.publish.assert_called_once()
        event = event_bus.publish.call_args[0][0]
        assert event.data['tool_name'] == "BashTool"
        assert event.data['tool_args'] == {"command": "ls"}

    def test_publish_tool_exec_completed(self):
        """测试发布工具执行完成事件"""
        event_bus = EventBus()
        event_bus.publish = MagicMock()
        publisher = EventPublisher(event_bus=event_bus)

        result = MagicMock()
        result.success = True

        publisher.publish_tool_exec_completed(
            tool_name="BashTool",
            tool_args={"command": "ls"},
            result=result,
        )

        event_bus.publish.assert_called_once()
        event = event_bus.publish.call_args[0][0]
        assert event.data['tool_name'] == "BashTool"
        assert event.data['tool_args'] == {"command": "ls"}
        assert event.data['success'] is True


class TestEventPublisherTokenEvents:
    """Token 事件发布测试"""

    def test_publish_token_and_cost_update(self):
        """测试发布 Token 和成本更新事件"""
        event_bus = EventBus()
        event_bus.publish = MagicMock()
        publisher = EventPublisher(event_bus=event_bus)

        cost_summary = {'total_cost': 0.05}
        publisher.publish_token_and_cost_update(
            tokens=500,
            cost_summary=cost_summary,
        )

        event_bus.publish.assert_called_once()
        event = event_bus.publish.call_args[0][0]
        assert event.data['tokens'] == 500
        assert event.data['cost_summary'] == cost_summary
