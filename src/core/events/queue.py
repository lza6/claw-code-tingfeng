"""Async Priority Event Queue — 异步优先级事件队列

设计目标:
- 引入 asyncio.PriorityQueue 结合 PriorityMasking 模型
- 核心循环采用 uvloop (Linux) 或 ProactorEventLoop (Windows) 增强 I/O 吞吐
- 解决高负载下事件堆积问题

优先级定义:
- 0 (CRITICAL): 系统错误、崩溃恢复
- 1 (HIGH): LLM 响应、工具执行结果
- 2 (NORMAL): 状态更新、进度通知
- 3 (LOW): 日志记录、统计更新
- 4 (BACKGROUND): 后台任务、缓存更新

PriorityMasking:
- 允许按优先级掩码过滤事件
- 支持动态调整优先级
- 支持批量处理同优先级事件
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

logger = logging.getLogger(__name__)


class EventPriority(IntEnum):
    """事件优先级 (数值越小优先级越高)"""
    CRITICAL = 0     # 系统错误、崩溃恢复
    HIGH = 1         # LLM 响应、工具执行结果
    NORMAL = 2       # 状态更新、进度通知
    LOW = 3          # 日志记录、统计更新
    BACKGROUND = 4   # 后台任务、缓存更新


# 优先级掩码 (用于过滤)
class PriorityMask:
    """优先级掩码工具类

    用法:
        mask = PriorityMask()
        mask.allow(EventPriority.CRITICAL, EventPriority.HIGH)
        mask.is_allowed(EventPriority.NORMAL)  # False
    """

    def __init__(self, allow_all: bool = True) -> None:
        self._allowed: set[int] = set()
        if allow_all:
            self.allow_all()

    def allow_all(self) -> None:
        """允许所有优先级"""
        self._allowed = {p.value for p in EventPriority}

    def allow(self, *priorities: EventPriority) -> None:
        """允许指定优先级"""
        for p in priorities:
            self._allowed.add(p.value)

    def deny(self, *priorities: EventPriority) -> None:
        """拒绝指定优先级"""
        for p in priorities:
            self._allowed.discard(p.value)

    def is_allowed(self, priority: EventPriority) -> bool:
        """检查是否允许该优先级"""
        return priority.value in self._allowed

    def get_allowed_mask(self) -> int:
        """获取优先级掩码 (位运算)"""
        mask = 0
        for p in self._allowed:
            mask |= (1 << p)
        return mask

    @classmethod
    def from_mask(cls, mask: int) -> PriorityMask:
        """从位掩码创建"""
        pm = cls(allow_all=False)
        for p in EventPriority:
            if mask & (1 << p.value):
                pm._allowed.add(p.value)
        return pm


@dataclass(order=True)
class PriorityEvent:
    """带优先级的事件

    注意: dataclass 的 order=True 会按字段顺序比较，
    所以 priority 必须在第一个字段。
    """
    priority: int
    timestamp: float = field(compare=False, default_factory=time.time)
    event_type: str = field(compare=False, default="")
    data: dict[str, Any] = field(compare=False, default_factory=dict)
    source: str = field(compare=False, default="")
    handler: Callable | None = field(compare=False, default=None, repr=False)


class AsyncPriorityEventQueue:
    """异步优先级事件队列

    特性:
    - asyncio.PriorityQueue 保证优先级顺序
    - 背压控制 (maxsize)
    - 优先级掩码过滤
    - 批量处理
    - 优雅关闭

    用法:
        queue = AsyncPriorityEventQueue(maxsize=10000)
        queue.start()

        # 发布事件
        await queue.publish(PriorityEvent(
            priority=EventPriority.HIGH,
            event_type="llm.response",
            data={"content": "..."},
        ))

        # 停止
        await queue.stop()
    """

    def __init__(
        self,
        maxsize: int = 10000,
        batch_size: int = 10,
        batch_timeout: float = 0.1,
    ) -> None:
        self._queue: asyncio.PriorityQueue[PriorityEvent] = asyncio.PriorityQueue(
            maxsize=maxsize
        )
        self._maxsize = maxsize
        self._batch_size = batch_size
        self._batch_timeout = batch_timeout

        self._handlers: dict[str, list[Callable]] = {}
        self._priority_mask = PriorityMask(allow_all=True)

        self._running = False
        self._consumer_task: asyncio.Task | None = None

        # 统计
        self._total_published = 0
        self._total_consumed = 0
        self._total_dropped = 0
        self._total_batched = 0

    def on(self, event_type: str, handler: Callable) -> None:
        """注册事件处理器"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def set_priority_mask(self, mask: PriorityMask) -> None:
        """设置优先级掩码"""
        self._priority_mask = mask

    async def publish(self, event: PriorityEvent) -> bool:
        """发布事件

        返回:
            True 成功, False 队列已满
        """
        # 检查优先级掩码
        priority = EventPriority(event.priority)
        if not self._priority_mask.is_allowed(priority):
            return True  # 静默丢弃

        try:
            # 非阻塞放入队列
            self._queue.put_nowait(event)
            self._total_published += 1
            return True
        except asyncio.QueueFull:
            self._total_dropped += 1
            logger.warning(f"事件队列已满，丢弃事件: {event.event_type}")
            return False

    async def publish_batch(self, events: list[PriorityEvent]) -> int:
        """批量发布事件

        返回:
            成功发布的事件数量
        """
        count = 0
        for event in events:
            if await self.publish(event):
                count += 1
        return count

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """启动消费者循环"""
        if self._running:
            return

        self._running = True
        self._consumer_task = asyncio.create_task(self._consumer_loop())
        logger.info(f"优先级事件队列已启动 (maxsize={self._maxsize})")

    async def stop(self, timeout: float = 5.0) -> None:
        """停止消费者循环

        参数:
            timeout: 等待队列清空的最大时间
        """
        if not self._running:
            return

        self._running = False

        # 等待队列清空
        start = time.time()
        while not self._queue.empty() and (time.time() - start) < timeout:
            await asyncio.sleep(0.05)

        # 取消消费者任务
        if self._consumer_task and not self._consumer_task.done():
            self._consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._consumer_task

        logger.info(
            f"优先级事件队列已停止 "
            f"(发布={self._total_published}, 消费={self._total_consumed}, "
            f"丢弃={self._total_dropped})"
        )

    async def _consumer_loop(self) -> None:
        """消费者主循环 (批量处理)"""
        while self._running:
            try:
                # 批量获取事件
                batch: list[PriorityEvent] = []

                # 获取第一个事件 (阻塞)
                try:
                    event = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=self._batch_timeout,
                    )
                    batch.append(event)
                except asyncio.TimeoutError:
                    continue

                # 获取剩余事件 (非阻塞)
                while len(batch) < self._batch_size:
                    try:
                        event = self._queue.get_nowait()
                        batch.append(event)
                    except asyncio.QueueEmpty:
                        break

                # 批量处理
                if batch:
                    await self._process_batch(batch)
                    self._total_consumed += len(batch)
                    self._total_batched += 1

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"消费者循环异常: {e}")
                await asyncio.sleep(0.1)

    async def _process_batch(self, batch: list[PriorityEvent]) -> None:
        """批量处理事件"""
        for event in batch:
            handlers = self._handlers.get(event.event_type, [])
            for handler in handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)
                except Exception as e:
                    logger.error(f"事件处理器异常: {event.event_type} - {e}")

    @property
    def size(self) -> int:
        """当前队列大小"""
        return self._queue.qsize()

    @property
    def is_empty(self) -> bool:
        """队列是否为空"""
        return self._queue.empty()

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            "total_published": self._total_published,
            "total_consumed": self._total_consumed,
            "total_dropped": self._total_dropped,
            "total_batched": self._total_batched,
            "current_size": self._queue.qsize(),
            "max_size": self._maxsize,
            "handler_count": sum(len(h) for h in self._handlers.values()),
            "event_types": list(self._handlers.keys()),
        }


def setup_optimized_event_loop() -> asyncio.AbstractEventLoop:
    """设置优化的事件循环

    - Linux: uvloop (如果可用)
    - Windows: ProactorEventLoop
    - macOS: uvloop (如果可用), 否则默认

    返回:
        配置好的事件循环
    """
    # 尝试使用 uvloop
    try:
        import uvloop
        loop = uvloop.new_event_loop()
        logger.info("使用 uvloop 事件循环 (高性能)")
        asyncio.set_event_loop(loop)
        return loop
    except ImportError:
        pass

    # Windows: ProactorEventLoop
    if sys.platform == "win32":
        try:
            loop = asyncio.ProactorEventLoop()
            asyncio.set_event_loop(loop)
            logger.info("使用 ProactorEventLoop 事件循环 (Windows 优化)")
            return loop
        except Exception as e:
            logger.warning(f"ProactorEventLoop 初始化失败: {e}")

    # 默认事件循环
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    logger.info("使用默认 asyncio 事件循环")
    return loop
