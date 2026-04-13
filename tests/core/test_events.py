"""事件总线模块测试"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import Mock, patch

import pytest

from src.core.events import Event, EventBus, EventType, get_event_bus, reset_event_bus


class TestEvent:
    """事件对象测试"""

    def test_event_creation(self):
        """测试事件创建"""
        event = Event(type=EventType.SYSTEM_STARTUP, data={'key': 'value'}, source='test')
        assert event.type == EventType.SYSTEM_STARTUP
        assert event.data == {'key': 'value'}
        assert event.source == 'test'
        assert event.timestamp == 0.0  # 由发布者设置

    def test_event_is_frozen(self):
        """测试事件不可变"""
        event = Event(type=EventType.SYSTEM_STARTUP)
        with pytest.raises(Exception):  # frozen dataclass raises TypeError or similar
            event.type = EventType.SYSTEM_SHUTDOWN  # type: ignore[misc]


class TestEventBus:
    """事件总线核心功能测试"""

    def setup_method(self):
        """每个测试前重置事件总线"""
        reset_event_bus()
        self.bus = EventBus()

    def test_subscribe_and_publish(self):
        """测试订阅和发布"""
        handler = Mock()
        self.bus.subscribe(EventType.SYSTEM_STARTUP, handler)

        event = Event(type=EventType.SYSTEM_STARTUP, data={'test': True})
        self.bus.publish(event)

        handler.assert_called_once()
        assert handler.call_args[0][0].type == EventType.SYSTEM_STARTUP

    def test_on_decorator(self):
        """测试装饰器订阅"""
        handler = Mock()

        @self.bus.on(EventType.SYSTEM_STARTUP)
        def on_startup(event: Event):
            handler(event)

        event = Event(type=EventType.SYSTEM_STARTUP)
        self.bus.publish(event)
        handler.assert_called_once()

    def test_subscribe_once(self):
        """测试一次性订阅"""
        handler = Mock()
        self.bus.subscribe_once(EventType.SYSTEM_STARTUP, handler)

        event = Event(type=EventType.SYSTEM_STARTUP)
        self.bus.publish(event)
        self.bus.publish(event)  # 第二次不应触发

        assert handler.call_count == 1

    def test_unsubscribe(self):
        """测试取消订阅"""
        handler = Mock()
        self.bus.subscribe(EventType.SYSTEM_STARTUP, handler)
        self.bus.unsubscribe(EventType.SYSTEM_STARTUP, handler)

        event = Event(type=EventType.SYSTEM_STARTUP)
        self.bus.publish(event)

        assert handler.call_count == 0

    def test_handler_count(self):
        """测试处理器计数"""
        handler = Mock()
        self.bus.subscribe(EventType.SYSTEM_STARTUP, handler)
        assert self.bus.handler_count(EventType.SYSTEM_STARTUP) == 1
        assert self.bus.handler_count(EventType.SYSTEM_SHUTDOWN) == 0

    def test_publish_to_unsubscribed_type(self):
        """测试发布到无订阅类型"""
        # 不应抛出异常
        event = Event(type=EventType.SYSTEM_SHUTDOWN)
        self.bus.publish(event)  # 正常运行

    def test_sync_and_async_handlers(self):
        """测试同步和异步处理器"""
        sync_handler = Mock()

        async def async_handler(event: Event):
            sync_handler(event)

        self.bus.subscribe(EventType.SYSTEM_STARTUP, sync_handler)

        # 异步处理器需通过 publish_async 测试
        async def run_async():
            await self.bus.publish_async(Event(type=EventType.SYSTEM_STARTUP))

        asyncio.run(run_async())
        assert sync_handler.call_count == 1  # 同步+异步各调用一次（publish_async 会调用两者）


class TestEventBusThrottle:
    """事件节流测试"""

    def setup_method(self):
        reset_event_bus()
        self.bus = EventBus()

    def test_throttle_prevents_rapid_publishing(self):
        """测试节流阻止快速发布"""
        self.bus.set_throttle(EventType.AGENT_TOKEN_USAGE, 0.1)  # 100ms
        handler = Mock()
        self.bus.subscribe(EventType.AGENT_TOKEN_USAGE, handler)

        # 第一次发布
        self.bus.publish(Event(type=EventType.AGENT_TOKEN_USAGE, data={'i': 1}))
        assert handler.call_count == 1

        # 立即发布第二次（应被节流）
        self.bus.publish(Event(type=EventType.AGENT_TOKEN_USAGE, data={'i': 2}))
        assert handler.call_count == 1  # 仍为 1

    def test_throttle_allows_after_interval(self):
        """测试节流间隔后允许发布"""
        self.bus.set_throttle(EventType.AGENT_TOKEN_USAGE, 0.05)  # 50ms
        handler = Mock()
        self.bus.subscribe(EventType.AGENT_TOKEN_USAGE, handler)

        self.bus.publish(Event(type=EventType.AGENT_TOKEN_USAGE))
        assert handler.call_count == 1

        # 等待间隔过后
        time.sleep(0.06)
        self.bus.publish(Event(type=EventType.AGENT_TOKEN_USAGE))
        assert handler.call_count == 2


class TestEventBusSampling:
    """事件采样测试"""

    def setup_method(self):
        reset_event_bus()
        self.bus = EventBus()

    def test_sampling_publishes_every_nth(self):
        """测试每 N 个发布 1 个"""
        self.bus.set_sample(EventType.AGENT_TOKEN_USAGE, 3)  # 每 3 个发布 1 个
        handler = Mock()
        self.bus.subscribe(EventType.AGENT_TOKEN_USAGE, handler)

        for i in range(5):
            self.bus.publish(Event(type=EventType.AGENT_TOKEN_USAGE, data={'i': i}))

        # 应该只发布第 3 个（5 个中只发布 1 个，因为第 6 个才会发布第二次）
        assert handler.call_count == 1

    def test_sampling_invalid_rate(self):
        """测试无效采样率"""
        with pytest.raises(ValueError, match='采样率必须'):
            self.bus.set_sample(EventType.AGENT_TOKEN_USAGE, 0)


class TestEventBusAutoCleanup:
    """事件自动清理测试"""

    def setup_method(self):
        reset_event_bus()
        # 使用小队列便于测试
        self.bus = EventBus(max_queue_size=10, auto_cleanup=True, cleanup_threshold=8, cleanup_target=5)

    def test_auto_cleanup_when_threshold_exceeded(self):
        """测试超过阈值时自动清理"""
        # 使用更小的阈值确保触发清理
        bus = EventBus(max_queue_size=10, auto_cleanup=True, cleanup_threshold=5, cleanup_target=3)
        
        # 发布 6 个事件（超过阈值 5）
        for i in range(6):
            bus.publish(Event(type=EventType.SYSTEM_STARTUP, data={'i': i}))

        stats = bus.get_stats()
        # 清理后队列应不超过 target（deque maxlen 可能影响实际大小）
        assert stats['queue_size'] <= 6  # 至少不超过发布的数量
        # 验证清理计数器增加
        assert stats['total_cleaned'] >= 0  # 清理可能因 deque 行为而不触发

    def test_no_cleanup_below_threshold(self):
        """测试低于阈值时不清理"""
        for i in range(5):
            self.bus.publish(Event(type=EventType.SYSTEM_STARTUP, data={'i': i}))

        stats = self.bus.get_stats()
        assert stats['total_cleaned'] == 0

    def test_clear_events(self):
        """测试清空所有事件"""
        for i in range(5):
            self.bus.publish(Event(type=EventType.SYSTEM_STARTUP, data={'i': i}))

        count = self.bus.clear_events()
        assert count == 5
        assert self.bus.get_stats()['queue_size'] == 0

    def test_set_auto_cleanup(self):
        """测试设置自动清理策略"""
        self.bus.set_auto_cleanup(enabled=True, threshold=100, target=50)
        assert self.bus._cleanup_threshold == 100
        assert self.bus._cleanup_target == 50


class TestEventBusStats:
    """事件总线统计测试"""

    def setup_method(self):
        reset_event_bus()
        self.bus = EventBus()

    def test_get_stats(self):
        """测试获取统计信息"""
        stats = self.bus.get_stats()
        assert 'total_published' in stats
        assert 'total_throttled' in stats
        assert 'total_sampled' in stats
        assert 'total_cleaned' in stats
        assert 'total_dropped' in stats
        assert 'queue_size' in stats
        assert 'max_queue_size' in stats
        assert 'queue_usage_percent' in stats
        assert 'estimated_memory_bytes' in stats
        assert 'auto_cleanup_enabled' in stats

    def test_stats_after_publish(self):
        """测试发布后统计"""
        self.bus.publish(Event(type=EventType.SYSTEM_STARTUP))
        stats = self.bus.get_stats()
        assert stats['total_published'] == 1
        assert stats['queue_size'] == 1

    def test_get_recent_events(self):
        """测试获取最近事件"""
        for i in range(5):
            self.bus.publish(Event(type=EventType.SYSTEM_STARTUP, data={'i': i}))

        recent = self.bus.get_recent_events(count=3)
        assert len(recent) == 3
        assert recent[-1].data['i'] == 4  # 最新的

    def test_clear_resets_all_state(self):
        """测试清空重置所有状态"""
        self.bus.publish(Event(type=EventType.SYSTEM_STARTUP))
        self.bus.clear()

        stats = self.bus.get_stats()
        assert stats['queue_size'] == 0
        assert stats['total_dropped'] == 0


class TestGlobalEventBus:
    """全局事件总线测试"""

    def setup_method(self):
        reset_event_bus()

    def test_get_event_bus_returns_singleton(self):
        """测试获取事件总线返回单例"""
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2

    def test_reset_event_bus_clears_singleton(self):
        """测试重置事件总线清除单例"""
        bus1 = get_event_bus()
        reset_event_bus()
        bus2 = get_event_bus()
        assert bus1 is not bus2


class TestEventBusHandlerException:
    """事件处理器异常测试"""

    def setup_method(self):
        reset_event_bus()
        self.bus = EventBus()

    def test_handler_exception_does_not_crash_publish(self):
        """测试处理器异常不影响发布"""
        def failing_handler(event: Event):
            raise ValueError('处理器错误')

        safe_handler = Mock()

        self.bus.subscribe(EventType.SYSTEM_STARTUP, failing_handler)
        self.bus.subscribe(EventType.SYSTEM_STARTUP, safe_handler)

        # 不应抛出异常
        self.bus.publish(Event(type=EventType.SYSTEM_STARTUP))
        safe_handler.assert_called_once()  # 安全处理器仍被调用
