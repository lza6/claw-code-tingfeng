"""Rich TUI — Live HUD 2.0 流式仪表盘

功能:
- rich.live.Live 全局控制台实时渲染
- 底部三栏 HUD: [系统资源] | [推理阶段] | [Tokens 成本]
- 输入时颜色从 Cyan 切换到 Yellow（思考中提示）
- 工具调用阶段脉冲式微动画
- Markdown 流式渲染
"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from rich.console import Console, Group, RenderableType
from rich.layout import Layout
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.text import Text

from ..utils.rich_colors import (
    BLUE,
    CYAN,
    DARK_GRAY,
    GRAY,
    GREEN,
    PURPLE,
    RED,
    WHITE,
    YELLOW,
    get_console,
    status_text,
)

# ---------------------------------------------------------------------------
# HUD 状态数据类
# ---------------------------------------------------------------------------

@dataclass
class HUDState:
    """HUD 实时状态"""
    state: str = "idle"
    phase: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    cpu_percent: float = 0.0
    mem_percent: float = 0.0
    streaming_content: str = ""
    active_tools: list[tuple[str, str]] = field(default_factory=list)
    thought_chain: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 进度条动画
# ---------------------------------------------------------------------------

def _progress_spinner(color: str = BLUE) -> Progress:
    """齿轮转动进度条"""
    return Progress(
        SpinnerColumn(
            spinner_name="dots",
            style=f"bold {color}",
        ),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(
            complete_style=color,
            finished_style="bold " + GREEN,
            style=DARK_GRAY,
            bar_width=20,
        ),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        transient=False,
    )


# ---------------------------------------------------------------------------
# 工具调用脉冲动画
# ---------------------------------------------------------------------------

def _pulse_indicator() -> str:
    """脉冲式动画字符"""
    chars = ["◐", "◓", "◑", "◒"]
    idx = int(time.monotonic() * 4) % len(chars)
    return chars[idx]

# ---------------------------------------------------------------------------
# Live HUD 2.0 渲染器
# ---------------------------------------------------------------------------

class LiveHUD:
    """Live HUD 2.0 — 动态仪表盘

    用法:
        hud = LiveHUD(console)
        hud.start()
        hud.update(state="thinking", phase="分析代码...")
        hud.append_stream("## 分析完成\n")
        hud.update(state="done", phase="完成")
        hud.stop()
    """

    def __init__(
        self,
        console: Console | None = None,
        refresh_rate: float = 4,
    ) -> None:
        self.console = console or get_console()
        self.state = HUDState()
        self._live: Live | None = None
        self._refresh_rate = refresh_rate

    # -- 公共接口 --

    def start(self) -> None:
        """启动 Live 渲染"""
        self._live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=self._refresh_rate,
            screen=False,
            transient=False,
        )
        self._live.start()

    def stop(self) -> None:
        """停止 Live 渲染"""
        if self._live:
            self._live.stop()
            self._live = None

    def update(self, **kwargs) -> None:
        """更新 HUD 状态"""
        for key, value in kwargs.items():
            if hasattr(self.state, key):
                setattr(self.state, key, value)
        self._refresh()

    def append_stream(self, text: str) -> None:
        """追加流式输出内容"""
        self.state.streaming_content += text
        self._refresh()

    def set_thought(self, thought: str) -> None:
        """添加思维链条目"""
        self.state.thought_chain.append(thought)
        self._refresh()

    def add_tool(self, name: str, status: str = "执行中") -> None:
        """添加工具调用"""
        self.state.active_tools.append((name, status))
        self._refresh()

    def update_tool(self, name: str, status: str) -> None:
        """更新工具状态"""
        self.state.active_tools = [
            (n, status) if n == name else (n, s)
            for n, s in self.state.active_tools
        ]
        self._refresh()

    # -- 内部渲染 --

    def _refresh(self) -> None:
        if self._live and self._live.is_started:
            self._live.update(self._render())

    def _render(self) -> RenderableType:
        """渲染完整 HUD 布局"""
        layout = Layout()

        layout.split_column(
            Layout(name="main"),
            Layout(name="hud", size=5),
        )

        layout["main"].update(self._render_main())
        layout["hud"].update(self._render_hud())
        return layout

    def _state_color(self) -> str:
        mapping = {
            "idle": CYAN,
            "thinking": YELLOW,
            "executing": BLUE,
            "done": GREEN,
            "error": RED,
        }
        return mapping.get(self.state.state, GRAY)

    def _state_icon(self) -> str:
        mapping = {
            "idle": "●",
            "thinking": "◐",
            "executing": "⚡",
            "done": "✓",
            "error": "✗",
        }
        return mapping.get(self.state.state, "·")

    def _render_main(self) -> RenderableType:
        """渲染主内容区域"""
        s = self.state
        parts: list[RenderableType] = []

        # 工具调用脉冲区域
        if s.state == "executing" and s.active_tools:
            tool_lines: list[Text] = []
            for name, tool_status in s.active_tools:
                tool_lines.append(
                    Text.assemble(
                        f"  {_pulse_indicator()} {name}: ",
                        Text(tool_status, style=GRAY),
                    )
                )
            parts.append(Panel(
                Group(*tool_lines),
                title="[bold yellow]◐ 工具调用",
                border_style=YELLOW,
                padding=(0, 1),
            ))

        # 思维链 / 流式 Markdown 输出
        if s.streaming_content:
            parts.append(Panel(
                Markdown(s.streaming_content),
                title=f"[bold {self._state_color()}]{s.phase}",
                border_style=self._state_color(),
                padding=(0, 1),
            ))

        # 思维链（最近 3 条）
        if s.thought_chain:
            chain_text = Text()
            for t in s.thought_chain[-3:]:
                chain_text.append(f"  {self._state_icon()} {t}\n", style=GRAY)
            parts.append(Panel(
                chain_text,
                title="[bold #af87ff]思维链",
                border_style=PURPLE,
                padding=(0, 1),
            ))

        # 空闲提示
        if not parts:
            parts.append(Panel(
                status_text(s.state),
                border_style=self._state_color(),
                padding=(1, 2),
            ))

        return Group(*parts)

    def _render_hud(self) -> Panel:
        """渲染底部三栏 HUD"""
        s = self.state
        color = self._state_color()

        # 左: 系统资源
        left = Text.assemble(
            "[dim]CPU[/dim] ",
            Text(f"{s.cpu_percent:.0f}%", style=WHITE),
            "  [dim]MEM[/dim] ",
            Text(f"{s.mem_percent:.0f}%", style=WHITE),
        )

        # 中: 推理阶段（颜色随状态切换）
        center = Text.assemble(
            Text(self._state_icon(), style=f"bold {color}"),
            Text(f" {s.phase}", style=f"bold {color}"),
        )

        # 右: Tokens 成本
        right = Text.assemble(
            "[dim]Tokens[/dim] ",
            Text(f"{s.total_tokens:,}", style=WHITE),
            "  [dim]Cost[/dim] ",
            Text(f"${s.cost_usd:.4f}", style=YELLOW),
        )

        # thinking/executing 状态时显示进度条
        if s.state in ("thinking", "executing"):
            prog = _progress_spinner(color=color)
            task_desc = s.phase or "处理中"
            prog.add_task(task_desc, total=100, completed=50)
            return Panel(
                Group(
                    Group(left, center, right),
                    prog,
                ),
                border_style=color,
            )

        return Panel(
            Group(left, center, right),
            border_style=color,
        )


# ---------------------------------------------------------------------------
# 上下文管理器
# ---------------------------------------------------------------------------

@asynccontextmanager
async def live_hud(
    *,
    phase: str = "就绪",
    state: str = "idle",
    console: Console | None = None,
) -> AsyncIterator[LiveHUD]:
    """Live HUD 异步上下文管理器

    async with live_hud(initial_phase="分析代码...") as hud:
        hud.update(state="thinking", phase="分析代码...")
        # ... 执行任务 ...
        hud.update(state="done", phase="任务完成")
    """
    hud = LiveHUD(console=console)
    hud.update(state=state, phase=phase)
    hud.start()
    try:
        yield hud
    finally:
        hud.stop()
