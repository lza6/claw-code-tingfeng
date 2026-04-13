"""LifecycleMixin 测试 - 信号处理和优雅关闭"""
from __future__ import annotations

import asyncio
import signal
import time
import sys
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from src.agent._lifecycle import LifecycleMixin, reset_signal_handlers
from src.core.events import EventBus, Event, EventType


class MockLifecycleEngine(LifecycleMixin):
    """用于测试的 Mock Engine"""
    
    def __init__(self):
        self._shutdown_requested = False
        self._shutdown_reason = ''
        self._shutdown_time = 0.0
        self._is_running = True
        self.enable_events = True
        self._event_bus = EventBus()
        self.tools = {}
        self._cost_estimator = MagicMock()


class TestResetSignalHandlers:
    """reset_signal_handlers 函数测试"""

    def test_reset_signal_handlers(self):
        """测试重置信号处理器标志"""
        import src.agent._lifecycle as lifecycle_module
        lifecycle_module._signal_handlers_registered = True
        reset_signal_handlers()
        assert lifecycle_module._signal_handlers_registered is False

    def test_reset_multiple_times(self):
        """测试多次重置不会出错"""
        import src.agent._lifecycle as lifecycle_module
        lifecycle_module._signal_handlers_registered = False
        reset_signal_handlers()
        reset_signal_handlers()
        assert lifecycle_module._signal_handlers_registered is False


class TestLifecycleMixinCreation:
    """LifecycleMixin 创建测试"""

    def test_create_mixin(self):
        """测试创建 LifecycleMixin"""
        engine = MockLifecycleEngine()
        assert engine._shutdown_requested is False
        assert engine._is_running is True
        assert engine.enable_events is True


class TestRegisterSignalHandlers:
    """信号处理器注册测试"""

    def test_register_once(self):
        """测试只注册一次"""
        import src.agent._lifecycle as lifecycle_module
        lifecycle_module._signal_handlers_registered = False
        
        engine = MockLifecycleEngine()
        engine._register_signal_handlers()
        
        assert lifecycle_module._signal_handlers_registered is True
        
        # 再次注册不应改变状态
        engine._register_signal_handlers()
        assert lifecycle_module._signal_handlers_registered is True

    def test_register_skips_if_already_registered(self):
        """测试已注册时跳过"""
        import src.agent._lifecycle as lifecycle_module
        lifecycle_module._signal_handlers_registered = True
        
        engine = MockLifecycleEngine()
        # 不应抛出异常
        engine._register_signal_handlers()

    @pytest.mark.skipif(sys.platform != 'win32', reason="Windows 特定测试")
    def test_register_on_windows(self):
        """测试 Windows 平台注册"""
        import src.agent._lifecycle as lifecycle_module
        lifecycle_module._signal_handlers_registered = False
        
        engine = MockLifecycleEngine()
        with patch('signal.signal') as mock_signal:
            engine._register_signal_handlers()
            # 应该调用 signal.signal 注册 SIGINT
            assert mock_signal.call_count >= 1


class TestSyncShutdownHandler:
    """同步关闭处理器测试"""

    def test_sync_handler_sets_flags(self):
        """测试同步处理器设置标志"""
        import src.agent._lifecycle as lifecycle_module
        lifecycle_module._signal_handlers_registered = False
        
        engine = MockLifecycleEngine()
        engine._sync_shutdown_handler(signal.SIGINT, None)
        
        assert engine._shutdown_requested is True
        assert engine._shutdown_reason == 'SIG2'  # SIGINT 通常是 2
        assert engine._shutdown_time > 0

    def test_sync_handler_publishes_event(self):
        """测试同步处理器发布事件"""
        import src.agent._lifecycle as lifecycle_module
        lifecycle_module._signal_handlers_registered = False
        
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.SYSTEM_SHUTDOWN, callback)
        
        engine = MockLifecycleEngine()
        engine._event_bus = bus
        engine._sync_shutdown_handler(signal.SIGTERM, None)
        
        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.type == EventType.SYSTEM_SHUTDOWN
        assert 'platform' in event.data
        assert event.data['platform'] == 'windows'

    def test_sync_handler_when_events_disabled(self):
        """测试禁用事件时不发布事件"""
        import src.agent._lifecycle as lifecycle_module
        lifecycle_module._signal_handlers_registered = False
        
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.SYSTEM_SHUTDOWN, callback)
        
        engine = MockLifecycleEngine()
        engine._event_bus = bus
        engine.enable_events = False
        engine._sync_shutdown_handler(signal.SIGINT, None)
        
        assert callback.call_count == 0

    def test_sync_handler_event_publish_error(self):
        """测试事件发布失败时不抛出异常"""
        import src.agent._lifecycle as lifecycle_module
        lifecycle_module._signal_handlers_registered = False
        
        bus = MagicMock()
        bus.publish.side_effect = Exception("发布失败")
        
        engine = MockLifecycleEngine()
        engine._event_bus = bus
        # 不应抛出异常
        engine._sync_shutdown_handler(signal.SIGINT, None)

    def test_sync_handler_sigbreak(self):
        """测试 SIGBREAK 信号处理"""
        import src.agent._lifecycle as lifecycle_module
        lifecycle_module._signal_handlers_registered = False
        
        engine = MockLifecycleEngine()
        # SIGBREAK 通常是 21
        engine._sync_shutdown_handler(21, None)
        
        assert engine._shutdown_requested is True
        assert engine._shutdown_reason == 'SIG21'


class TestHandleShutdownSignal:
    """异步关闭信号处理器测试"""

    @pytest.mark.asyncio
    async def test_handle_shutdown_signal(self):
        """测试处理关闭信号"""
        engine = MockLifecycleEngine()
        engine._handle_shutdown_signal(signal.SIGTERM)
        
        assert engine._shutdown_requested is True
        assert 'SIG' in engine._shutdown_reason
        assert engine._shutdown_time > 0

    @pytest.mark.asyncio
    async def test_handle_shutdown_publishes_event(self):
        """测试发布关闭事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.SYSTEM_SHUTDOWN, callback)
        
        engine = MockLifecycleEngine()
        engine._event_bus = bus
        engine._handle_shutdown_signal(signal.SIGINT)
        
        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.type == EventType.SYSTEM_SHUTDOWN
        assert event.data['platform'] == 'unix'

    @pytest.mark.asyncio
    async def test_handle_shutdown_zero_signal(self):
        """测试零信号值处理"""
        engine = MockLifecycleEngine()
        engine._handle_shutdown_signal(0)

        assert engine._shutdown_requested is True
        assert engine._shutdown_reason == 'unknown'

    @pytest.mark.asyncio
    async def test_handle_shutdown_event_error(self):
        """测试事件发布失败"""
        bus = MagicMock()
        bus.publish.side_effect = RuntimeError("事件总线错误")
        
        engine = MockLifecycleEngine()
        engine._event_bus = bus
        # 不应抛出异常
        engine._handle_shutdown_signal(signal.SIGINT)


class TestIsShuttingDown:
    """关闭状态检查测试"""

    def test_is_shutting_down_initially_false(self):
        """测试初始状态未关闭"""
        engine = MockLifecycleEngine()
        assert engine.is_shutting_down is False

    def test_is_shutting_down_after_signal(self):
        """测试信号后关闭状态为真"""
        engine = MockLifecycleEngine()
        engine._shutdown_requested = True
        assert engine.is_shutting_down is True


class TestShutdown:
    """优雅关闭测试"""

    @pytest.mark.asyncio
    async def test_shutdown_basic(self):
        """测试基本关闭"""
        engine = MockLifecycleEngine()
        await engine.shutdown()
        
        assert engine._shutdown_requested is True
        assert engine._is_running is False

    @pytest.mark.asyncio
    async def test_shutdown_idempotent(self):
        """测试关闭幂等性"""
        engine = MockLifecycleEngine()
        await engine.shutdown()
        # 再次关闭不应抛出异常
        await engine.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_clears_tools(self):
        """测试关闭时清理工具"""
        engine = MockLifecycleEngine()
        engine.tools = {'tool1': MagicMock(), 'tool2': MagicMock()}
        await engine.shutdown()
        
        assert len(engine.tools) == 0

    @pytest.mark.asyncio
    async def test_shutdown_resets_cost_estimator(self):
        """测试关闭时重置成本估算器"""
        engine = MockLifecycleEngine()
        await engine.shutdown()
        
        engine._cost_estimator.reset.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_publishes_event(self):
        """测试关闭时发布事件"""
        bus = EventBus()
        callback = MagicMock()
        bus.subscribe(EventType.SYSTEM_SHUTDOWN, callback)
        
        engine = MockLifecycleEngine()
        engine._event_bus = bus
        await engine.shutdown()
        
        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.type == EventType.SYSTEM_SHUTDOWN
        assert event.data['reason'] == 'manual'
        assert event.data['platform'] == 'any'

    @pytest.mark.asyncio
    async def test_shutdown_event_error(self):
        """测试关闭事件发布失败"""
        bus = MagicMock()
        bus.publish.side_effect = Exception("发布失败")
        
        engine = MockLifecycleEngine()
        engine._event_bus = bus
        # 不应抛出异常
        await engine.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_tools_clear_error(self):
        """测试工具清理失败"""
        engine = MockLifecycleEngine()
        engine.tools = MagicMock()
        engine.tools.clear.side_effect = RuntimeError("清理失败")
        # 不应抛出异常
        await engine.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_cost_estimator_error(self):
        """测试成本估算器重置失败"""
        engine = MockLifecycleEngine()
        engine._cost_estimator.reset.side_effect = Exception("重置失败")
        # 不应抛出异常
        await engine.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_with_timeout(self):
        """测试带超时的关闭"""
        engine = MockLifecycleEngine()
        await engine.shutdown(timeout=2.0)
        
        assert engine._shutdown_requested is True

    @pytest.mark.asyncio
    async def test_shutdown_when_already_requested(self):
        """测试已请求关闭时直接返回"""
        engine = MockLifecycleEngine()
        engine._shutdown_requested = True
        await engine.shutdown()
        # 不应改变状态
        assert engine._is_running is True  # 保持原样


class TestShutdownIntegration:
    """关闭集成测试"""

    @pytest.mark.asyncio
    async def test_full_shutdown_sequence(self):
        """测试完整关闭序列"""
        bus = EventBus()
        events = []
        bus.subscribe(EventType.SYSTEM_SHUTDOWN, lambda e: events.append(e))
        
        engine = MockLifecycleEngine()
        engine._event_bus = bus
        engine.tools = {'bash': MagicMock(), 'file': MagicMock()}
        
        # 触发关闭
        engine._handle_shutdown_signal(signal.SIGINT)
        await engine.shutdown()
        
        # 应该收到至少一个关闭事件
        assert len(events) >= 1

    @pytest.mark.asyncio
    async def test_shutdown_without_events(self):
        """测试禁用事件时关闭"""
        engine = MockLifecycleEngine()
        engine.enable_events = False
        await engine.shutdown()
        
        assert engine._shutdown_requested is True
        assert engine._is_running is False
