"""Agent 生命周期管理器 — 负责信号处理与优雅关闭"""
from __future__ import annotations

import asyncio
import signal
import time
from collections.abc import Callable
from types import FrameType

from ..core.events import Event, EventBus, EventType
from ..utils import info, warn


class LifecycleManager:
    """生命周期管理器 — 负责信号捕获与资源清理"""

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
        self._signal_handlers_registered = False

    def register_signal_handlers(self) -> None:
        if self._signal_handlers_registered:
            return
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, self._handle_signal, sig)
            self._signal_handlers_registered = True
        except (NotImplementedError, RuntimeError):
            warn("当前平台不支持异步信号处理")

    def _handle_signal(self, sig: int, frame: FrameType | None = None) -> None:
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
        if self._get_shutdown_requested():
            return
        info("开始优雅关闭...")
        self._set_shutdown_requested(True)
        self._set_shutdown_time(time.time())
        self._set_is_running(False)
        await asyncio.sleep(min(timeout, 2.0))
        self._cleanup()
        if self._events_enabled:
            self._event_bus.publish(Event(
                type=EventType.AGENT_SHUTDOWN_COMPLETED,
                data={'shutdown_time': time.time()},
                source='lifecycle_manager',
            ))
        info("优雅关闭完成")

    def _cleanup(self) -> None:
        self._tools_clear()
        self._cost_estimator_reset()

    def is_shutting_down(self) -> bool:
        return self._get_shutdown_requested()
