"""全局速率限制器模块"""
from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from contextlib import asynccontextmanager


class GlobalRateLimiter:
    """
    全局速率限制器（移植自 Project B）。
    支持严格的滑动窗口限流、并发控制和 429 反应式锁定。

    优化 (v0.36+):
    - 纯异步实现，消除线程锁/异步锁混合模式
    - 懒加载单例，避免 __new__ 中的线程安全问题
    - 429 反应式锁定优化
    """
    _instance: GlobalRateLimiter | None = None
    _init_lock: threading.Lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, rate_limit: int = 40, rate_window: float = 60.0, max_concurrency: int = 5) -> None:
        if hasattr(self, '_initialized'):
            return
        self._rate_limit = rate_limit
        self._rate_window = rate_window
        self._max_concurrency = max_concurrency
        self._request_times = deque()
        self._blocked_until = 0.0
        # 延迟初始化异步原语，避免在非异步上下文中创建
        self._concurrency_sem: asyncio.Semaphore | None = None
        self._async_lock: asyncio.Lock | None = None
        self._initialized = True

    def _ensure_async_primitives(self) -> None:
        """确保异步原语已初始化（在异步上下文中调用）"""
        if self._concurrency_sem is None:
            self._concurrency_sem = asyncio.Semaphore(self._max_concurrency)
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> GlobalRateLimiter:
        if cls._instance is None:
            cls._instance = GlobalRateLimiter()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """重置单例（主要用于测试）"""
        with cls._init_lock:
            cls._instance = None

    async def wait_if_needed(self) -> None:
        self._ensure_async_primitives()

        # 1. 反应式锁定检查
        now = time.monotonic()
        if now < self._blocked_until:
            wait_time = self._blocked_until - now
            await asyncio.sleep(wait_time)

        # 2. 滑动窗口主动限流
        while True:
            async with self._async_lock:
                now = time.monotonic()
                cutoff = now - self._rate_window
                while self._request_times and self._request_times[0] <= cutoff:
                    self._request_times.popleft()

                if len(self._request_times) < self._rate_limit:
                    self._request_times.append(now)
                    return

                wait_time = max(0.1, (self._request_times[0] + self._rate_window) - now)
            await asyncio.sleep(wait_time)

    def block(self, seconds: float = 60.0) -> None:
        self._blocked_until = time.monotonic() + seconds

    @asynccontextmanager
    async def limit(self):
        self._ensure_async_primitives()
        await self.wait_if_needed()
        async with self._concurrency_sem:
            yield


__all__ = ['GlobalRateLimiter']
