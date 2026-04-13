import pytest
import asyncio
from unittest.mock import MagicMock, patch
from src.agent._lifecycle_manager import LifecycleManager
from src.core.events import EventType

@pytest.mark.asyncio
async def test_lifecycle_manager_shutdown():
    # Mock getters and setters
    shutdown_requested = [False]
    shutdown_time = [0.0]
    is_running = [True]

    def get_sr(): return shutdown_requested[0]
    def set_sr(v): shutdown_requested[0] = v
    def set_st(v): shutdown_time[0] = v
    def set_ir(v): is_running[0] = v

    mock_bus = MagicMock()
    mock_tools_clear = MagicMock()
    mock_cost_reset = MagicMock()

    manager = LifecycleManager(
        event_bus=mock_bus,
        events_enabled=True,
        shutdown_getter=get_sr,
        shutdown_setter=set_sr,
        shutdown_reason_setter=MagicMock(),
        shutdown_time_setter=set_st,
        is_running_setter=set_ir,
        tools_clear=mock_tools_clear,
        cost_estimator_reset=mock_cost_reset
    )

    # 第一次关闭
    await manager.shutdown(timeout=0.1)

    assert shutdown_requested[0] is True
    assert is_running[0] is False
    mock_tools_clear.assert_called_once()
    mock_cost_reset.assert_called_once()

    # 验证事件发布
    # 我们预计会有 SHUTDOWN_COMPLETED 事件
    assert mock_bus.publish.call_count >= 1

@pytest.mark.asyncio
async def test_lifecycle_manager_multiple_shutdown():
    # 验证重复关闭不会报错
    manager = LifecycleManager(
        MagicMock(), True, lambda: True, MagicMock(), MagicMock(),
        MagicMock(), MagicMock(), MagicMock(), MagicMock()
    )
    await manager.shutdown() # 应该直接返回
