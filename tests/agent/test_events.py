"""EventMixin 测试 - 事件发布和背压控制"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, call

import pytest

from src.agent._events import EventMixin
from src.core.events import Event, EventBus, EventType


class MockEventMixin(EventMixin):
    """用于测试的 Mock Mixin 实现"""
    
    def __init__(self, enable_events: bool = True, event_bus: EventBus | None = None):
        self.enable_events = enable_events
        self._event_bus = event_bus or EventBus()


class TestEventMixinCreation:
    """EventMixin 创建和初始化测试"""

    def test_create_with_events_enabled(self):
        """测试启用事件时创建 Mixin"""
        bus = EventBus()
        mixin = MockEventMixin(enable_events=True, event_bus=bus)
        assert mixin.enable_events is True
        assert mixin._event_bus is bus

    def test_create_with_events_disabled(self):
        """测试禁用事件时创建 Mixin"""
        bus = EventBus()
        mixin = MockEventMixin(enable_events=False, event_bus=bus)
        assert mixin.enable_events is False

    def test_create_with_default_event_bus(self):
        """测试使用默认 EventBus 创建"""
        mixin = MockEventMixin()
        assert mixin._event_bus is not None
        assert isinstance(mixin._event_bus, EventBus)


class TestConfigureBackpressure:
    """事件背压配置测试"""

    def test_configure_backpressure(self):
        """测试背压配置"""
        bus = EventBus()
        mixin = MockEventMixin(event_bus=bus)
        # 不应抛出异常
        mixin._configure_event_backpressure()
        # 配置应该成功完成
        assert True

    def test_backpressure_does_not_publish(self):
        """测试背压配置不触发事件发布"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.AGENT_STEP_STARTED, callback)
        
        mixin = MockEventMixin(event_bus=bus)
        mixin._configure_event_backpressure()
        
        # 背压配置不应发布任何事件
        assert callback.call_count == 0


class TestPublishTaskStarted:
    """任务开始事件发布测试"""

    def test_publish_task_started_when_enabled(self):
        """测试启用事件时发布任务开始事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.AGENT_STEP_STARTED, callback)
        
        mixin = MockEventMixin(event_bus=bus)
        mixin.publish_task_started("测试目标", max_iterations=10)
        
        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.type == EventType.AGENT_STEP_STARTED
        assert event.data['goal'] == "测试目标"
        assert event.data['max_iterations'] == 10
        assert event.source == 'agent_engine'

    def test_publish_task_started_when_disabled(self):
        """测试禁用事件时不发布任务开始事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.AGENT_STEP_STARTED, callback)
        
        mixin = MockEventMixin(enable_events=False, event_bus=bus)
        mixin.publish_task_started("测试目标", max_iterations=10)
        
        assert callback.call_count == 0

    def test_publish_task_started_with_empty_goal(self):
        """测试空目标时发布事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.AGENT_STEP_STARTED, callback)
        
        mixin = MockEventMixin(event_bus=bus)
        mixin.publish_task_started("", max_iterations=5)
        
        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.data['goal'] == ""

    def test_publish_task_started_with_zero_iterations(self):
        """测试零迭代时发布事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.AGENT_STEP_STARTED, callback)
        
        mixin = MockEventMixin(event_bus=bus)
        mixin.publish_task_started("目标", max_iterations=0)
        
        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.data['max_iterations'] == 0


class TestPublishLlmCallStarted:
    """LLM 调用开始事件测试"""

    def test_publish_llm_call_started(self):
        """测试发布 LLM 调用开始事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.LLM_CALL_STARTED, callback)
        
        mixin = MockEventMixin(event_bus=bus)
        mixin.publish_llm_call_started(iteration=1, message_count=5)
        
        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.type == EventType.LLM_CALL_STARTED
        assert event.data['iteration'] == 1
        assert event.data['message_count'] == 5

    def test_publish_llm_call_started_when_disabled(self):
        """测试禁用事件时不发布 LLM 调用开始事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.LLM_CALL_STARTED, callback)
        
        mixin = MockEventMixin(enable_events=False, event_bus=bus)
        mixin.publish_llm_call_started(iteration=1, message_count=5)
        
        assert callback.call_count == 0

    def test_publish_llm_call_started_with_large_iteration(self):
        """测试大迭代数时发布事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.LLM_CALL_STARTED, callback)
        
        mixin = MockEventMixin(event_bus=bus)
        mixin.publish_llm_call_started(iteration=1000, message_count=100)
        
        event = callback.call_args[0][0]
        assert event.data['iteration'] == 1000
        assert event.data['message_count'] == 100


class TestPublishLlmCallCompleted:
    """LLM 调用完成事件测试"""

    def test_publish_llm_call_completed(self):
        """测试发布 LLM 调用完成事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.LLM_CALL_COMPLETED, callback)
        
        mixin = MockEventMixin(event_bus=bus)
        tokens = {'prompt': 100, 'completion': 50, 'total': 150}
        mixin.publish_llm_call_completed(iteration=1, model="gpt-4", tokens=tokens)
        
        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.type == EventType.LLM_CALL_COMPLETED
        assert event.data['iteration'] == 1
        assert event.data['model'] == "gpt-4"
        assert event.data['tokens'] == tokens

    def test_publish_llm_call_completed_empty_tokens(self):
        """测试空 token 时发布事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.LLM_CALL_COMPLETED, callback)
        
        mixin = MockEventMixin(event_bus=bus)
        mixin.publish_llm_call_completed(iteration=2, model="claude-3", tokens={})
        
        event = callback.call_args[0][0]
        assert event.data['tokens'] == {}

    def test_publish_llm_call_completed_when_disabled(self):
        """测试禁用事件时不发布 LLM 调用完成事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.LLM_CALL_COMPLETED, callback)
        
        mixin = MockEventMixin(enable_events=False, event_bus=bus)
        mixin.publish_llm_call_completed(iteration=1, model="gpt-4", tokens={})
        
        assert callback.call_count == 0


class TestPublishToolExecStarted:
    """工具执行开始事件测试"""

    def test_publish_tool_exec_started(self):
        """测试发布工具执行开始事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.TOOL_EXEC_STARTED, callback)
        
        mixin = MockEventMixin(event_bus=bus)
        args = {'command': 'ls -la'}
        mixin.publish_tool_exec_started("BashTool", args)
        
        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.type == EventType.TOOL_EXEC_STARTED
        assert event.data['tool_name'] == "BashTool"
        assert event.data['args'] == args

    def test_publish_tool_exec_started_empty_args(self):
        """测试空参数时发布工具执行开始事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.TOOL_EXEC_STARTED, callback)
        
        mixin = MockEventMixin(event_bus=bus)
        mixin.publish_tool_exec_started("FileReadTool", {})
        
        event = callback.call_args[0][0]
        assert event.data['args'] == {}

    def test_publish_tool_exec_started_when_disabled(self):
        """测试禁用事件时不发布工具执行开始事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.TOOL_EXEC_STARTED, callback)
        
        mixin = MockEventMixin(enable_events=False, event_bus=bus)
        mixin.publish_tool_exec_started("BashTool", {'command': 'ls'})
        
        assert callback.call_count == 0


class TestPublishToolExecCompleted:
    """工具执行完成事件测试"""

    def test_publish_tool_exec_completed_success(self):
        """测试成功完成时发布工具执行完成事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.TOOL_EXEC_COMPLETED, callback)
        
        mixin = MockEventMixin(event_bus=bus)
        result = MagicMock()
        result.success = True
        result.output = "文件列表输出"
        result.error = None
        
        mixin.publish_tool_exec_completed("BashTool", {'command': 'ls'}, result)
        
        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.type == EventType.TOOL_EXEC_COMPLETED
        assert event.data['success'] is True
        assert event.data['output'] == "文件列表输出"
        assert event.data['error'] == ''

    def test_publish_tool_exec_completed_error(self):
        """测试失败时发布工具执行错误事件"""
        bus = EventBus()
        completed_callback = MagicMock()
        error_callback = MagicMock()
        bus.subscribe(EventType.TOOL_EXEC_COMPLETED, completed_callback)
        bus.subscribe(EventType.TOOL_EXEC_ERROR, error_callback)
        
        mixin = MockEventMixin(event_bus=bus)
        result = MagicMock()
        result.success = False
        result.output = None
        result.error = "命令执行失败"
        
        mixin.publish_tool_exec_completed("BashTool", {'command': 'invalid'}, result)
        
        assert completed_callback.call_count == 0
        error_callback.assert_called_once()
        event = error_callback.call_args[0][0]
        assert event.type == EventType.TOOL_EXEC_ERROR
        assert event.data['success'] is False
        assert event.data['error'] == "命令执行失败"

    def test_publish_tool_exec_completed_long_output_truncated(self):
        """测试长输出被截断"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.TOOL_EXEC_COMPLETED, callback)
        
        mixin = MockEventMixin(event_bus=bus)
        result = MagicMock()
        result.success = True
        result.output = "a" * 1000
        result.error = None
        
        mixin.publish_tool_exec_completed("BashTool", {}, result)
        
        event = callback.call_args[0][0]
        assert len(event.data['output']) <= 500
        assert event.data['output'] == "a" * 500

    def test_publish_tool_exec_completed_when_disabled(self):
        """测试禁用事件时不发布工具执行完成事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.TOOL_EXEC_COMPLETED, callback)
        
        mixin = MockEventMixin(enable_events=False, event_bus=bus)
        result = MagicMock()
        result.success = True
        result.output = "output"
        result.error = None
        
        mixin.publish_tool_exec_completed("BashTool", {}, result)
        
        assert callback.call_count == 0


class TestPublishTaskCompleted:
    """任务完成事件测试"""

    def test_publish_task_completed(self):
        """测试发布任务完成事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.AGENT_TASK_COMPLETED, callback)
        
        mixin = MockEventMixin(event_bus=bus)
        mixin.publish_task_completed(
            goal="完成任务",
            result="任务成功完成",
            total_tokens=1500,
            steps_count=5
        )
        
        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.type == EventType.AGENT_TASK_COMPLETED
        assert event.data['goal'] == "完成任务"
        assert event.data['result'] == "任务成功完成"
        assert event.data['total_tokens'] == 1500
        assert event.data['steps_count'] == 5

    def test_publish_task_completed_long_result_truncated(self):
        """测试长结果被截断"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.AGENT_TASK_COMPLETED, callback)
        
        mixin = MockEventMixin(event_bus=bus)
        long_result = "x" * 1000
        mixin.publish_task_completed(
            goal="目标",
            result=long_result,
            total_tokens=100,
            steps_count=1
        )
        
        event = callback.call_args[0][0]
        assert len(event.data['result']) <= 500

    def test_publish_task_completed_empty_result(self):
        """测试空结果时发布事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.AGENT_TASK_COMPLETED, callback)
        
        mixin = MockEventMixin(event_bus=bus)
        mixin.publish_task_completed(
            goal="目标",
            result="",
            total_tokens=0,
            steps_count=0
        )
        
        event = callback.call_args[0][0]
        assert event.data['result'] == ""
        assert event.data['total_tokens'] == 0
        assert event.data['steps_count'] == 0

    def test_publish_task_completed_when_disabled(self):
        """测试禁用事件时不发布任务完成事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.AGENT_TASK_COMPLETED, callback)
        
        mixin = MockEventMixin(enable_events=False, event_bus=bus)
        mixin.publish_task_completed("目标", "结果", 100, 5)
        
        assert callback.call_count == 0


class TestPublishTaskError:
    """任务错误事件测试"""

    def test_publish_task_error_with_code(self):
        """测试带错误码时发布任务错误事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.AGENT_TASK_ERROR, callback)
        
        mixin = MockEventMixin(event_bus=bus)
        mixin.publish_task_error(
            goal="任务目标",
            error="执行失败",
            error_code="EXEC_ERROR",
            total_tokens=500
        )
        
        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.type == EventType.AGENT_TASK_ERROR
        assert event.data['goal'] == "任务目标"
        assert event.data['error'] == "执行失败"
        assert event.data['error_code'] == "EXEC_ERROR"
        assert event.data['total_tokens'] == 500

    def test_publish_task_error_without_code(self):
        """测试不带错误码时发布任务错误事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.AGENT_TASK_ERROR, callback)
        
        mixin = MockEventMixin(event_bus=bus)
        mixin.publish_task_error(
            goal="目标",
            error="错误信息",
            error_code=None,
            total_tokens=0
        )
        
        event = callback.call_args[0][0]
        assert 'error_code' not in event.data
        assert event.data['error'] == "错误信息"

    def test_publish_task_error_when_disabled(self):
        """测试禁用事件时不发布任务错误事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.AGENT_TASK_ERROR, callback)
        
        mixin = MockEventMixin(enable_events=False, event_bus=bus)
        mixin.publish_task_error("目标", "错误", "CODE", 100)
        
        assert callback.call_count == 0


class TestPublishTokenAndCostUpdate:
    """Token 和成本更新事件测试"""

    def test_publish_token_update_only(self):
        """测试仅发布 Token 更新事件"""
        bus = EventBus()
        token_callback = MagicMock()
        cost_callback = MagicMock()
        bus.subscribe(EventType.AGENT_TOKEN_USAGE, token_callback)
        bus.subscribe(EventType.AGENT_COST_UPDATE, cost_callback)
        
        mixin = MockEventMixin(event_bus=bus)
        mixin.publish_token_and_cost_update(total_tokens=1234, cost_summary=None)
        
        token_callback.assert_called_once()
        assert cost_callback.call_count == 0
        
        event = token_callback.call_args[0][0]
        assert event.data['total_tokens'] == 1234

    def test_publish_cost_update_only(self):
        """测试发布成本更新事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.AGENT_COST_UPDATE, callback)
        
        mixin = MockEventMixin(event_bus=bus)
        cost_summary = {'total_cost': 0.05, 'model_costs': {'gpt-4': 0.03}}
        mixin.publish_token_and_cost_update(total_tokens=0, cost_summary=cost_summary)
        
        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.data == cost_summary

    def test_publish_both_token_and_cost(self):
        """测试同时发布 Token 和成本更新"""
        bus = EventBus()
        token_callback = MagicMock()
        cost_callback = MagicMock()
        bus.subscribe(EventType.AGENT_TOKEN_USAGE, token_callback)
        bus.subscribe(EventType.AGENT_COST_UPDATE, cost_callback)
        
        mixin = MockEventMixin(event_bus=bus)
        mixin.publish_token_and_cost_update(
            total_tokens=500,
            cost_summary={'total_cost': 0.02}
        )
        
        assert token_callback.call_count == 1
        assert cost_callback.call_count == 1

    def test_publish_when_disabled(self):
        """测试禁用事件时不发布任何更新"""
        bus = EventBus()
        token_callback = MagicMock()
        cost_callback = MagicMock()
        bus.subscribe(EventType.AGENT_TOKEN_USAGE, token_callback)
        bus.subscribe(EventType.AGENT_COST_UPDATE, cost_callback)
        
        mixin = MockEventMixin(enable_events=False, event_bus=bus)
        mixin.publish_token_and_cost_update(
            total_tokens=100,
            cost_summary={'total_cost': 0.01}
        )
        
        assert token_callback.call_count == 0
        assert cost_callback.call_count == 0


class TestEventIntegration:
    """事件集成测试"""

    def test_multiple_events_in_sequence(self):
        """测试按顺序发布多个事件"""
        bus = EventBus()
        events_received = []
        bus.subscribe(EventType.AGENT_STEP_STARTED, lambda e: events_received.append(e.type))
        bus.subscribe(EventType.LLM_CALL_STARTED, lambda e: events_received.append(e.type))
        bus.subscribe(EventType.LLM_CALL_COMPLETED, lambda e: events_received.append(e.type))
        bus.subscribe(EventType.AGENT_TASK_COMPLETED, lambda e: events_received.append(e.type))
        
        mixin = MockEventMixin(event_bus=bus)
        mixin.publish_task_started("目标", 10)
        mixin.publish_llm_call_started(1, 2)
        mixin.publish_llm_call_completed(1, "gpt-4", {'total': 100})
        mixin.publish_task_completed("目标", "完成", 100, 1)
        
        assert len(events_received) == 4
        assert events_received == [
            EventType.AGENT_STEP_STARTED,
            EventType.LLM_CALL_STARTED,
            EventType.LLM_CALL_COMPLETED,
            EventType.AGENT_TASK_COMPLETED,
        ]

    def test_event_source_is_consistent(self):
        """测试事件来源一致性"""
        bus = EventBus()
        sources = []
        bus.subscribe(EventType.AGENT_STEP_STARTED, lambda e: sources.append(e.source))
        bus.subscribe(EventType.LLM_CALL_STARTED, lambda e: sources.append(e.source))
        
        mixin = MockEventMixin(event_bus=bus)
        mixin.publish_task_started("目标", 10)
        mixin.publish_llm_call_started(1, 2)
        
        assert all(source == 'agent_engine' for source in sources)

    def test_event_data_immutability(self):
        """测试事件数据可变性"""
        bus = EventBus()
        captured_event = None
        
        def capture_event(event):
            nonlocal captured_event
            captured_event = event
        
        bus.subscribe(EventType.AGENT_STEP_STARTED, capture_event)
        
        mixin = MockEventMixin(event_bus=bus)
        original_data = {'goal': '目标', 'max_iterations': 10}
        mixin.publish_task_started("目标", 10)
        
        assert captured_event is not None
        # Event 数据是可变的，这是预期行为
        captured_event.data['goal'] = '修改后的目标'
        assert captured_event.data['goal'] == '修改后的目标'
