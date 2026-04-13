"""Rich Live HUD 2.0 — 实时终端 UI 面板

使用 Rich 库实现:
- Live 面板实时更新
- 流式 Markdown 渲染（代码高亮、表格、列表）
- 任务树可视化
- 进度条动画
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text
from rich.tree import Tree


@dataclass
class HudState:
    """HUD 渲染状态"""
    title: str = "Clawd Code"
    model: str = ""
    iteration: int = 0
    max_iterations: int = 10
    total_tokens: int = 0
    total_cost: float = 0.0
    session_turns: int = 0
    current_phase: str = "idle"  # idle, thinking, tool_call, done, error
    status_message: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    streaming_content: str = ""
    task_steps: list[dict[str, Any]] = field(default_factory=list)


class RichHudRenderer:
    """Rich HUD 渲染器"""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self.state = HudState()

    def render_header(self) -> Table:
        """渲染头部信息"""
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold cyan")
        table.add_column(style="dim")

        table.add_row("🤖 Clawd Code", f"Model: {self.state.model or 'unknown'}")
        return table

    def render_status_bar(self) -> Panel:
        """渲染状态栏"""
        status_icons = {
            "idle": "⏸",
            "thinking": "💭",
            "tool_call": "⚙",
            "done": "✅",
            "error": "❌",
        }
        icon = status_icons.get(self.state.current_phase, "⏳")

        status_text = Text()
        status_text.append(f"{icon} ", style="bold")
        status_text.append(f"Iter {self.state.iteration}/{self.state.max_iterations}", style="bold yellow")
        status_text.append(" | ", style="dim")
        status_text.append(f"Tokens: {self.state.total_tokens:,}", style="dim green")
        status_text.append(" | ", style="dim")
        status_text.append(f"Cost: ${self.state.total_cost:.4f}", style="dim magenta")

        if self.state.status_message:
            status_text.append(" | ", style="dim")
            status_text.append(self.state.status_message, style="italic")

        return Panel(status_text, border_style="blue")

    def render_tool_calls(self) -> Panel | None:
        """渲染工具调用列表"""
        if not self.state.tool_calls:
            return None

        table = Table(title="🔧 工具调用", show_header=True, header_style="bold cyan")
        table.add_column("#", style="dim", width=3)
        table.add_column("工具", style="green")
        table.add_column("参数", style="dim")
        table.add_column("状态", width=6)

        for i, tc in enumerate(self.state.tool_calls, 1):
            status = "✅" if tc.get("success") else ("❌" if tc.get("error") else "⏳")
            table.add_row(
                str(i),
                tc.get("name", "?"),
                str(tc.get("args", ""))[:50],
                status,
            )

        return Panel(table, border_style="cyan")

    def render_task_tree(self) -> Panel | None:
        """渲染任务树"""
        if not self.state.task_steps:
            return None

        tree = Tree("📋 任务执行", guide_style="bold cyan")

        for step in self.state.task_steps:
            step_type = step.get("step_type", "?")
            action = step.get("action", "")
            success = step.get("success", False)

            icon = "✅" if success else ("❌" if not success and step_type != "llm" else "💭")
            tree.add(f"{icon} [{step_type}] {action[:60]}")

        return Panel(tree, border_style="yellow")

    def render_streaming_content(self, max_lines: int = 10) -> Panel | None:
        """渲染流式内容"""
        if not self.state.streaming_content:
            return None

        lines = self.state.streaming_content.split("\n")
        display_lines = lines[-max_lines:] if len(lines) > max_lines else lines
        content = "\n".join(display_lines)

        # 尝试 Markdown 渲染
        md = Markdown(content)
        return Panel(md, title="📝 流式输出", border_style="green")

    def render_progress(self) -> Progress:
        """渲染进度条"""
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
        )
        return progress

    def render_full_layout(self) -> Layout:
        """渲染完整布局"""
        layout = Layout()

        # 分割布局
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="status", size=3),
            Layout(name="main"),
        )

        layout["header"].update(self.render_header())
        layout["status"].update(self.render_status_bar())

        # 主区域分割
        main = layout["main"]
        main.split_row(
            Layout(name="content", ratio=2),
            Layout(name="sidebar", ratio=1),
        )

        # 内容区
        content_parts = []
        if self.state.streaming_content:
            content_parts.append(self.render_streaming_content())

        main_content = "\n\n".join(str(p) for p in content_parts if p)
        main["content"].update(main_content or Panel("等待任务开始...", border_style="dim"))

        # 侧边栏
        sidebar_parts = []
        tool_panel = self.render_tool_calls()
        if tool_panel:
            sidebar_parts.append(tool_panel)

        task_panel = self.render_task_tree()
        if task_panel:
            sidebar_parts.append(task_panel)

        sidebar_content = "\n\n".join(str(p) for p in sidebar_parts)
        main["sidebar"].update(sidebar_content or Panel("无活动", border_style="dim"))

        return layout


class RichLiveHud:
    """Rich Live HUD 管理器

    用法:
        hud = RichLiveHud()
        with hud.live():
            hud.update_status("thinking", "正在分析任务...")
            hud.add_tool_call("BashTool", {"command": "ls -la"})
            hud.stream_content("# 分析结果\n\n代码将在这里显示...")
    """

    def __init__(self) -> None:
        self.console = Console()
        self.renderer = RichHudRenderer(self.console)
        self._live: Live | None = None

    def live(self, refresh_per_second: int = 4):
        """上下文管理器: 启动 Live 模式"""
        self._live = Live(
            self.renderer.render_full_layout(),
            console=self.console,
            refresh_per_second=refresh_per_second,
            screen=True,
        )
        return self._live

    def update(self) -> None:
        """刷新显示"""
        if self._live:
            self._live.update(self.renderer.render_full_layout())

    def update_status(self, phase: str, message: str = "") -> None:
        """更新状态"""
        self.renderer.state.current_phase = phase
        if message:
            self.renderer.state.status_message = message
        self.update()

    def update_iteration(self, iteration: int) -> None:
        """更新迭代"""
        self.renderer.state.iteration = iteration
        self.update()

    def update_tokens(self, tokens: int, cost: float = 0.0) -> None:
        """更新 token 和成本"""
        self.renderer.state.total_tokens = tokens
        self.renderer.state.total_cost = cost
        self.update()

    def add_tool_call(self, name: str, args: dict, success: bool | None = None, error: str | None = None) -> None:
        """添加工具调用"""
        self.renderer.state.tool_calls.append({
            "name": name,
            "args": args,
            "success": success,
            "error": error,
        })
        self.update()

    def add_step(self, step_type: str, action: str, success: bool = True) -> None:
        """添加任务步骤"""
        self.renderer.state.task_steps.append({
            "step_type": step_type,
            "action": action,
            "success": success,
        })
        self.update()

    def stream_content(self, content: str) -> None:
        """流式添加内容"""
        self.renderer.state.streaming_content += content
        self.update()

    def set_model(self, model: str) -> None:
        """设置模型名"""
        self.renderer.state.model = model
        self.update()

    def set_max_iterations(self, n: int) -> None:
        """设置最大迭代次数"""
        self.renderer.state.max_iterations = n
        self.update()
