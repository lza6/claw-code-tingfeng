"""Lifecycle Manager — 组合模式替代 LifecycleMixin

负责信号处理、优雅关闭、资源清理。
通过回调函数访问宿主状态，消除类型系统崩溃。
"""
from __future__ import annotations

import asyncio
import signal
import time
from collections.abc import Callable
from types import FrameType

from ..core.events import Event, EventBus, EventType
from ..utils import debug, info, warn


class LifecycleManager:
    """生命周期管理器 — 组合模式替代 LifecycleMixin

    使用回调函数替代直接属性访问，避免 Mixin 对宿主内部状态的隐式依赖。
    """

    def __init__(
        self,
        event_bus: EventBus,
        events_enabled: bool,
        shutdown_getter: Callable[[], bool],
        shutdown_setter: Callable[[bool], None],
        shutdown_reason_setter: Callable[[str], None],
        shutdown_time_setter: Callable[[float], None],
        is_running_setter: Callable[[bool], None],
        tools_clear: Callable[[], None],
        cost_estimator_reset: Callable[[], None],
        shutdown_time_getter: Callable[[], float] | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._events_enabled = events_enabled
        self._get_shutdown_requested = shutdown_getter
        self._set_shutdown_requested = shutdown_setter
        self._set_shutdown_reason = shutdown_reason_setter
        self._set_shutdown_time = shutdown_time_setter
        self._set_is_running = is_running_setter
        self._tools_clear = tools_clear
        self._cost_estimator_reset = cost_estimator_reset
        self._get_shutdown_time = shutdown_time_getter
        self._signal_handlers_registered = False

    def register_signal_handlers(self) -> None:
        """注册信号处理器"""
        if self._signal_handlers_registered:
            return

        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, self._handle_signal, sig)
            self._signal_handlers_registered = True
            debug("信号处理器已注册")
        except (NotImplementedError, RuntimeError):
            # Windows 或不支持的事件循环
            warn("当前平台不支持异步信号处理")

    def _handle_signal(self, sig: int, frame: FrameType | None = None) -> None:
        """处理系统信号"""
        sig_name = "SIGINT" if sig == signal.SIGINT else "SIGTERM"
        warn(f"接收到 {sig_name} 信号，正在优雅关闭...")

        self._set_shutdown_requested(True)
        self._set_shutdown_reason(f"received {sig_name}")
        self._set_shutdown_time(time.time())
        self._set_is_running(False)

        if self._events_enabled:
            self._event_bus.publish(Event(
                type=EventType.AGENT_SHUTDOWN_REQUESTED,
                data={'signal': sig_name, 'reason': 'user_interrupt'},
                source='lifecycle_manager',
            ))

    async def shutdown(self, timeout: float = 5.0) -> None:
        """优雅关闭 Agent

        1. 设置关闭标志
        2. 等待当前任务完成
        3. 清理资源
        """
        if self._get_shutdown_requested():
            return

        info("开始优雅关闭...")
        self._set_shutdown_requested(True)
        self._set_shutdown_time(time.time())
        self._set_is_running(False)

        # 等待短暂时间让当前操作完成
        await asyncio.sleep(min(timeout, 2.0))

        # 清理资源
        self._cleanup()

        if self._events_enabled:
            self._event_bus.publish(Event(
                type=EventType.AGENT_SHUTDOWN_COMPLETED,
                data={'shutdown_time': self._get_elapsed_shutdown_time()},
                source='lifecycle_manager',
            ))
        info("优雅关闭完成")

    def _cleanup(self) -> None:
        """清理资源"""
        debug("清理工具和资源...")
        self._tools_clear()
        self._cost_estimator_reset()
        debug("资源清理完成")

    def _get_elapsed_shutdown_time(self) -> float:
        """获取从请求关闭到现在的时间"""
        start_time = self._get_shutdown_time() if self._get_shutdown_time else 0.0
        if start_time <= 0:
            return 0.0
        return time.time() - start_time

    def is_shutting_down(self) -> bool:
        """检查是否正在关闭"""
        return self._get_shutdown_requested()
