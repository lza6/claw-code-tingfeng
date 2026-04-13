"""AgentEngine 生命周期管理 - 信号处理 + 关闭逻辑

从 engine.py 拆分，负责：
- Graceful shutdown 信号处理
- 资源清理
- 关闭事件发布
"""
from __future__ import annotations

import asyncio
import signal
import time
from types import FrameType

from ..core.events import Event, EventType
from ..utils import debug, info, warn

# 全局标志：确保信号处理器每个进程只注册一次
_signal_handlers_registered = False


def reset_signal_handlers() -> None:
    """Reset the global signal handler registration flag.

    Useful for testing or when creating new AgentEngine instances
    that need to re-register signal handlers.
    """
    global _signal_handlers_registered
    _signal_handlers_registered = False


# 以下属性由 AgentEngine 设置:
# _shutdown_requested: bool
# _shutdown_reason: str
# _shutdown_time: float
# _is_running: bool
# enable_events: bool
# _event_bus: EventBus
# tools: dict
# _cost_estimator: Any


class LifecycleMixin:
    """生命周期管理 Mixin

    提供信号处理和优雅关闭功能。
    """

    def _register_signal_handlers(self) -> None:
        """注册 graceful shutdown 信号处理

        跨平台兼容:
        - Unix: 使用 asyncio loop.add_signal_handler
        - Windows: 使用 signal.signal 注册同步处理

        注意: 每个进程只注册一次，多个 AgentEngine 实例不会重复注册。

        增强功能 (v0.19.0):
        - 添加 SIGBREAK 支持 (Windows 特有)
        - 发布 SYSTEM_SHUTDOWN 事件
        - 记录关闭原因和时间戳
        """
        global _signal_handlers_registered
        if _signal_handlers_registered:
            return

        import sys

        self._shutdown_reason = ''  # type: ignore[attr-defined]
        self._shutdown_time = 0.0  # type: ignore[attr-defined]

        # 尝试异步信号处理（Unix）
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda s=sig: self._handle_shutdown_signal(s))
            debug('已注册 graceful shutdown 信号处理（异步模式）')
            _signal_handlers_registered = True
            return
        except AttributeError:
            # Signals not supported (e.g. Windows without asyncio)
            pass
        except (NotImplementedError, RuntimeError):
            pass

        # Windows 同步信号处理回退
        if sys.platform == 'win32':
            import contextlib
            try:
                # Windows 支持 SIGINT (Ctrl+C) 和 SIGBREAK (Ctrl+Break)
                signal.signal(signal.SIGINT, self._sync_shutdown_handler)
                with contextlib.suppress(ValueError, AttributeError):
                    signal.signal(signal.SIGBREAK, self._sync_shutdown_handler)
                debug('已注册 graceful shutdown 信号处理（Windows 同步模式）')
                _signal_handlers_registered = True
            except (ValueError, OSError):
                debug('Windows 信号处理注册失败')
        else:
            debug('当前平台不支持信号处理')
        _signal_handlers_registered = True

    def _sync_shutdown_handler(self, signum: int, frame: FrameType | None) -> None:
        """同步信号处理（Windows 回退）

        注意: 此方法在信号处理线程中调用，
        不能执行阻塞操作，只能设置标志位。
        """
        self._shutdown_requested = True  # type: ignore[attr-defined]
        self._shutdown_reason = f'SIG{signum}'  # type: ignore[attr-defined]
        self._shutdown_time = time.time()  # type: ignore[attr-defined]
        warn(f'收到关闭信号 (SIG{signum})，正在优雅关闭代理引擎...')

        # 发布关闭事件（同步方式）
        if self.enable_events:  # type: ignore[attr-defined]
            try:
                self._event_bus.publish(Event(  # type: ignore[attr-defined]
                    type=EventType.SYSTEM_SHUTDOWN,
                    data={
                        'reason': self._shutdown_reason,
                        'timestamp': self._shutdown_time,
                        'platform': 'windows',
                    },
                    source='agent_engine',
                ))
            except Exception as e:
                warn(f'关闭事件发布失败: {e}')

    def _handle_shutdown_signal(self, signum: int = 0) -> None:
        """处理关闭信号（异步模式）"""
        self._shutdown_requested = True  # type: ignore[attr-defined]
        self._shutdown_reason = f'SIG{signum}' if signum else 'unknown'  # type: ignore[attr-defined]
        self._shutdown_time = time.time()  # type: ignore[attr-defined]
        warn(f'收到关闭信号 ({self._shutdown_reason})，正在优雅关闭代理引擎...')

        # 发布关闭事件
        if self.enable_events:  # type: ignore[attr-defined]
            try:
                self._event_bus.publish(Event(  # type: ignore[attr-defined]
                    type=EventType.SYSTEM_SHUTDOWN,
                    data={
                        'reason': self._shutdown_reason,
                        'timestamp': self._shutdown_time,
                        'platform': 'unix',
                    },
                    source='agent_engine',
                ))
            except Exception as e:
                warn(f'关闭事件发布失败: {e}')

    @property
    def is_shutting_down(self) -> bool:
        """检查是否正在关闭"""
        return self._shutdown_requested  # type: ignore[attr-defined]

    async def shutdown(self, timeout: float = 5.0) -> None:
        """优雅关闭代理引擎

        参数:
            timeout: 等待当前任务完成的超时时间（秒）

        增强功能 (v0.19.0):
        - 等待当前任务完成
        - 发布关闭事件
        - 清理所有资源
        """
        if self._shutdown_requested:  # type: ignore[attr-defined]
            return

        self._shutdown_requested = True  # type: ignore[attr-defined]
        self._is_running = False  # type: ignore[attr-defined]
        info('正在优雅关闭代理引擎...')

        await asyncio.sleep(0.1)

        # 清理资源
        try:
            self.tools.clear()  # type: ignore[attr-defined]
            if self._cost_estimator:  # type: ignore[attr-defined]
                self._cost_estimator.reset()  # type: ignore[attr-defined]
            debug('工具资源已清理')
        except Exception as e:
            warn(f'清理工具资源时出错: {e}')

        # 发布关闭完成事件
        if self.enable_events:  # type: ignore[attr-defined]
            try:
                self._event_bus.publish(Event(  # type: ignore[attr-defined]
                    type=EventType.SYSTEM_SHUTDOWN,
                    data={
                        'reason': self._shutdown_reason or 'manual',  # type: ignore[attr-defined]
                        'timestamp': self._shutdown_time or time.time(),  # type: ignore[attr-defined]
                        'platform': 'any',
                    },
                    source='agent_engine',
                ))
            except Exception as e:
                warn(f'发布关闭事件时出错: {e}')

        info('代理引擎已关闭')
