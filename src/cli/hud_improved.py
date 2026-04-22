"""HUD (Heads-Up Display) 状态显示器增强版

参考: oh-my-codex-main/src/hud/
功能:
    - 实时状态显示 (Rich Panel)
    - 通知队列展示
    - 资源监控 (Budget, Memory, CPU)
    - 进度指示
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from ...core.notifications.dispatcher import NotificationDispatcher, NotificationLevel
from ...utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class HUDState:
    """HUD 状态"""
    current_iteration: int = 0
    max_iterations: int = 0
    status: str = "idle"  # idle, running, paused, error
    current_task: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0
    notifications: list[dict] = field(default_factory=list)
    resource_pressure: float = 0.0


class HUD:
    """Heads-Up Display

    提供实时状态反馈，不阻塞主线程。
    三种显示模式:
        - Live: 动态刷新 (Rich Live)
        - One-shot: 单次显示
        - HUD 文件: 供外部程序读取
    """

    def __init__(self, state: HUDState | None = None):
        self.state = state or HUDState()
        self.console = Console()
        self.live: Live | None = None
        self.running = False
        self.dispatcher = NotificationDispatcher.get()

    def start_live(self) -> None:
        """启动实时 HUD (Live 模式)"""
        if self.running:
            return
        self.running = True
        self.live = Live(
            self._render(),
            refresh_per_second=2,
            console=self.console,
            transient=False,
        )
        self.live.start()
        logger.info("HUD live display started")

    def stop(self) -> None:
        """停止 HUD"""
        self.running = False
        if self.live:
            self.live.stop()
            self.live = None

    def _render(self) -> Panel:
        """渲染 HUD 内容"""
        status_color = {
            "idle": "dim",
            "running": "green",
            "paused": "yellow",
            "error": "red",
        }.get(self.state.status, "white")

        # 主体内容
        table = Table.grid(padding=(0, 1))
        table.add_column(style="bold cyan")
        table.add_column()

        table.add_row("状态", f"[{status_color}]{self.state.status}[/{status_color}]")
        table.add_row(
            "进度",
            f"{self.state.current_iteration}/{self.state.max_iterations} 迭代",
        )
        table.add_row("当前", self.state.current_task[:50] + "..." if len(self.state.current_task) > 50 else self.state.current_task)
        table.add_row(
            "开销",
            f"${self.state.cost_usd:.4f} · {self.state.tokens_used:,} tokens",
        )
        table.add_row(
            "压力",
            self._format_pressure(self.state.resource_pressure),
        )

        # 最近通知
        recent = self.state.notifications[-3:] if self.state.notifications else []
        if recent:
            table.add_row("---", "---")
            for n in recent:
                level_color = {
                    "debug": "dim",
                    "info": "white",
                    "warning": "yellow",
                    "error": "red",
                    "critical": "bold red",
                }.get(n.get("level", "info"), "white")
                icon = {"info": "ℹ️", "warning": "⚠️", "error": "❌", "critical": "💥"}.get(
                    n.get("level"), "●"
                )
                table.add_row(
                    icon,
                    f"[{level_color}]{n.get('title', '')}[/{level_color}]: {n.get('message', '')[:40]}",
                )

        return Panel(table, title="Clawd Code", border_style="cyan")

    def _format_pressure(self, pressure: float) -> str:
        """格式化资源压力"""
        if pressure < 0.5:
            return f"[green]█{'█' * int(pressure * 10)}[/green] {pressure*100:.0f}%"
        elif pressure < 0.8:
            return f"[yellow]█{'█' * int(pressure * 10)}[/yellow] {pressure*100:.0f}%"
        else:
            return f"[red]█{'█' * int(pressure * 10)}[/red] {pressure*100:.0f}%"

    def update(self, **kwargs) -> None:
        """更新状态"""
        self.state.__dict__.update(kwargs)

    def print_notification(self, level: NotificationLevel, title: str, message: str) -> None:
        """单次打印通知到 HUD"""
        self.state.notifications.append({
            "level": level.value,
            "title": title,
            "message": message,
            "timestamp": time.time(),
        })
        # 保持最近 20 条
        self.state.notifications = self.state.notifications[-20:]
        if self.live:
            self.live.update(self._render())

    def one_shot(self, message: str, title: str = "Clawd Code") -> None:
        """单次显示模式 (不启动 Live)"""
        panel = Panel(message, title=title, border_style="cyan")
        self.console.print(panel)


# ==================== 与通知系统集成 ====================

def setup_hud_notification_integration(hud: HUD) -> None:
    """将通知系统连接到 HUD"""
    dispatcher = NotificationDispatcher.get()

    def on_notification(notification: Notification) -> None:
        # 仅 WARNING 及以上级别显示在 HUD
        if notification.level in (NotificationLevel.WARNING, NotificationLevel.ERROR, NotificationLevel.CRITICAL):
            hud.print_notification(
                notification.level,
                notification.title,
                notification.message,
            )

    dispatcher.subscribe(on_notification)


# 便捷函数
def get_hud() -> HUD:
    """获取全局 HUD 实例"""
    return HUD()


__all__ = [
    "HUD",
    "HUDState",
    "get_hud",
    "setup_hud_notification_integration",
]
