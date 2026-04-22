"""通知分发器 (Notification Dispatcher)

借鉴 oh-my-codex-main/src/notifications/dispatcher.ts
提供可扩展的事件驱动通知系统，支持多种后端:
  - Console (控制台输出)
  - HUD (TUI 状态行显示)
  - Files (日志文件)
  - Webhook (外部系统)
  - Hook (自定义钩子)

设计原则:
    - 事件驱动，非阻塞
    - 优先级过滤
    - 可扩展后端
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


class NotificationLevel(str, Enum):
    """通知级别"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Notification:
    """通知对象"""
    id: str
    level: NotificationLevel
    title: str
    message: str
    source: str = ""  # 来源模块
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    actionable: bool = False
    actions: list[dict[str, str]] = field(default_factory=list)  # 可选操作

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class NotificationBackend:
    """通知后端"""
    name: str
    handler: Callable[[Notification], None | asyncio.Task]
    level_filter: NotificationLevel = NotificationLevel.INFO
    enabled: bool = True


class NotificationDispatcher:
    """通知分发器 - 单例模式"""

    _instance: NotificationDispatcher | None = None

    @classmethod
    def get(cls) -> NotificationDispatcher:
        if cls._instance is None:
            cls._instance = NotificationDispatcher()
        return cls._instance

    def __init__(self):
        self.backends: dict[str, NotificationBackend] = {}
        self.subscribers: list[Callable[[Notification], None]] = []
        self.queue: asyncio.Queue = asyncio.Queue()
        self.running = False
        self.worker_task: asyncio.Task | None = None
        self._setup_default_backends()

    def _setup_default_backends(self) -> None:
        """设置默认后端"""
        # Console 后端
        self.register_backend(
            NotificationBackend(
                name="console",
                handler=self._console_handler,
                level_filter=NotificationLevel.INFO,
            )
        )

        # HUD 后端 (轻量级)
        self.register_backend(
            NotificationBackend(
                name="hud",
                handler=self._hud_handler,
                level_filter=NotificationLevel.WARNING,
            )
        )

        # File 后端 (用于审计)
        log_dir = Path(".clawd/logs/notifications")
        log_dir.mkdir(parents=True, exist_ok=True)
        self.register_backend(
            NotificationBackend(
                name="file",
                handler=self._file_handler,
                level_filter=NotificationLevel.WARNING,
            )
        )

    def register_backend(self, backend: NotificationBackend) -> None:
        """注册通知后端"""
        self.backends[backend.name] = backend
        logger.debug(f"Registered notification backend: {backend.name}")

    async def start(self) -> None:
        """启动分发器 (后台worker)"""
        if self.running:
            return
        self.running = True
        self.worker_task = asyncio.create_task(self._worker())
        logger.info("Notification dispatcher started")

    async def stop(self) -> None:
        """停止分发器"""
        self.running = False
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Notification dispatcher stopped")

    def notify(
        self,
        level: NotificationLevel,
        title: str,
        message: str,
        source: str = "",
        metadata: dict | None = None,
        actions: list | None = None,
    ) -> None:
        """发送通知 (同步)"""
        import uuid

        notification = Notification(
            id=str(uuid.uuid4())[:8],
            level=level,
            title=title,
            message=message,
            source=source,
            metadata=metadata or {},
            actions=actions or [],
        )

        # 推送到队列 (异步处理)
        try:
            asyncio.create_task(self.queue.put(notification))
        except RuntimeError:
            # 没有事件循环 - 直接发送 (同步)
            self._dispatch_sync(notification)

    async def notify_async(
        self,
        level: NotificationLevel,
        title: str,
        message: str,
        source: str = "",
        metadata: dict | None = None,
    ) -> None:
        """发送通知 (异步)"""
        import uuid

        notification = Notification(
            id=str(uuid.uuid4())[:8],
            level=level,
            title=title,
            message=message,
            source=source,
            metadata=metadata or {},
        )
        await self.queue.put(notification)

    def subscribe(self, callback: Callable[[Notification], None]) -> None:
        """订阅所有通知"""
        self.subscribers.append(callback)

    async def _worker(self) -> None:
        """后台worker - 从队列消费通知"""
        while self.running:
            try:
                notification = await asyncio.wait_for(
                    self.queue.get(), timeout=1.0
                )
                self._dispatch_all(notification)
                self.queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Notification worker error: {e}")

    def _dispatch_sync(self, notification: Notification) -> None:
        """同步分发到所有后端"""
        for backend in self.backends.values():
            if not backend.enabled:
                continue
            if notification.level.value < backend.level_filter.value:
                continue
            try:
                backend.handler(notification)
            except Exception as e:
                logger.error(f"Backend {backend.name} error: {e}")

    def _dispatch_all(self, notification: Notification) -> None:
        """分发到所有后端和订阅者"""
        # 后端
        self._dispatch_sync(notification)

        # 订阅者
        for callback in self.subscribers:
            try:
                callback(notification)
            except Exception as e:
                logger.error(f"Subscriber error: {e}")

    # ==================== 内置后端处理器 ====================

    def _console_handler(self, notification: Notification) -> None:
        """控制台输出"""
        from rich.console import Console

        color_map = {
            NotificationLevel.DEBUG: "dim",
            NotificationLevel.INFO: "white",
            NotificationLevel.WARNING: "yellow",
            NotificationLevel.ERROR: "red",
            NotificationLevel.CRITICAL: "bold red",
        }
        color = color_map.get(notification.level, "white")

        console = Console()
        icon = {
            NotificationLevel.INFO: "ℹ️ ",
            NotificationLevel.WARNING: "⚠️ ",
            NotificationLevel.ERROR: "❌",
            NotificationLevel.CRITICAL: "💥",
        }.get(notification.level, "●")

        console.print(
            f"[{color}]{icon} [{notification.level.value.upper()}] "
            f"{notification.title}[/{color}]: {notification.message}"
        )

    def _hud_handler(self, notification: Notification) -> None:
        """HUD 更新 - 通过共享状态文件"""
        from pathlib import Path

        hud_file = Path(".clawd/hud/notifications.jsonl")
        hud_file.parent.mkdir(parents=True, exist_ok=True)

        # 只保留最近 20 条
        entries = []
        if hud_file.exists():
            with hud_file.open() as f:
                entries = [json.loads(l) for l in f if l.strip()]
            entries = entries[-20:]

        entries.append({
            "level": notification.level.value,
            "title": notification.title,
            "message": notification.message,
            "timestamp": notification.timestamp,
        })

        with hud_file.open("w") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _file_handler(self, notification: Notification) -> None:
        """文件日志写入"""
        log_file = Path(".clawd/logs/notifications.jsonl")
        log_file.parent.mkdir(parents=True, exist_ok=True)

        with log_file.open("a") as f:
            f.write(json.dumps({
                "id": notification.id,
                "level": notification.level.value,
                "title": notification.title,
                "message": notification.message,
                "source": notification.source,
                "timestamp": notification.timestamp,
            }, ensure_ascii=False) + "\n")


def get_notification_dispatcher() -> NotificationDispatcher:
    """获取全局通知分发器"""
    return NotificationDispatcher.get()


# 便捷函数
def notify(
    level: NotificationLevel,
    title: str,
    message: str,
    source: str = "",
) -> None:
    """快速发送通知"""
    get_notification_dispatcher().notify(level, title, message, source)


def info(title: str, message: str, source: str = "") -> None:
    notify(NotificationLevel.INFO, title, message, source)


def warning(title: str, message: str, source: str = "") -> None:
    notify(NotificationLevel.WARNING, title, message, source)


def error(title: str, message: str, source: str = "") -> None:
    notify(NotificationLevel.ERROR, title, message, source)


def critical(title: str, message: str, source: str = "") -> None:
    notify(NotificationLevel.CRITICAL, title, message, source)


__all__ = [
    "Notification",
    "NotificationBackend",
    "NotificationDispatcher",
    "NotificationLevel",
    "critical",
    "error",
    "get_notification_dispatcher",
    "info",
    "notify",
    "warning",
]
