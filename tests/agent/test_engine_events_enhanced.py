import pytest
from unittest.mock import MagicMock
from src.agent.engine_events import EventPublisher
from src.core.events import EventBus

def test_event_publisher_all_events():
    mock_bus = MagicMock(spec=EventBus)
    publisher = EventPublisher(mock_bus, enabled=True)

    publisher.publish_task_started("goal", 10)
    publisher.publish_task_completed("goal", "res", 100, 5)
    publisher.publish_task_error("goal", "err", "CODE", 50)
    publisher.publish_llm_call_started(1, 2)
    publisher.publish_llm_call_completed(1, "gpt-4o", {"tokens": 100})
    publisher.publish_tool_exec_started("BashTool", {"cmd": "ls"})
    publisher.publish_tool_exec_completed("BashTool", {}, MagicMock(success=True))
    publisher.publish_token_and_cost_update(500, {"cost": 0.01})

    # 验证是否都调用了 publish
    assert mock_bus.publish.call_count == 8

def test_event_publisher_disabled():
    mock_bus = MagicMock(spec=EventBus)
    publisher = EventPublisher(mock_bus, enabled=False)

    publisher.publish_task_started("goal", 10)
    assert mock_bus.publish.call_count == 0
