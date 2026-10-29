"""Rich 实时 HUD —— REPL 流式任务的实时面板（真实渲染，不是占位）

之前这里是 20 行空壳：所有方法都是 `pass`，`render_full_layout()` 返回常量 `""`，
于是 `_run_task_rich` 用 `rich.Live` 包住一个空字符串 —— 用户看到的是**什么都不动**。

现在的做法：`render_full_layout()` 返回一个「每次刷新都重新读当前状态」的 renderable，
rich.Live 每 tick 都会调它的 `__rich_console__`，所以迭代数、工具步骤、流式尾巴会真的更新。

对外接口保持向后兼容：`console` / `renderer.state` / `renderer.render_full_layout()`
以及 `set_max_iterations/stream_content/update_iteration/update_status/add_step/update_tokens`。
"""
from __future__ import annotations

from collections import deque
from typing import Any

from rich.console import Console, Group, RenderableType
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .hud import HudContext, render_hud

#: 面板里最多显示多少条工具步骤（滚动窗口）
MAX_VISIBLE_STEPS = 6
#: 流式文本只保留尾部这么多字符（避免长输出把 HUD 撑爆）
MAX_STREAM_TAIL_CHARS = 1200

_STATUS_STYLE = {
    "thinking": "cyan",
    "running": "cyan",
    "done": "green",
    "error": "red",
    "idle": "dim",
}


class _HudRenderSurface:
    """兼容层：`hud.renderer.state` 与 `hud.renderer.render_full_layout()`"""

    def __init__(self, hud: RichLiveHud) -> None:
        self._hud = hud

    @property
    def state(self) -> HudContext:
        return self._hud.state

    def render_full_layout(self) -> RenderableType:
        return self._hud.render_full_layout()


class RichLiveHud:
    """REPL 实时 HUD（rich 渲染）"""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self.state = HudContext()
        self.renderer = _HudRenderSurface(self)
        self._status: tuple[str, str] = ("idle", "")
        self._steps: deque[tuple[str, str, bool]] = deque(maxlen=MAX_VISIBLE_STEPS)
        self._stream_tail: str = ""
        self._total_steps: int = 0

    # ---------- 状态更新 ----------
    def set_max_iterations(self, n: int) -> None:
        self.state.max_iterations = max(int(n or 0), 0)

    def stream_content(self, content: str) -> None:
        if not content:
            return
        tail = self._stream_tail + content
        if len(tail) > MAX_STREAM_TAIL_CHARS:
            tail = tail[-MAX_STREAM_TAIL_CHARS:]
        self._stream_tail = tail

    def update_iteration(self, n: int) -> None:
        self.state.iteration = int(n or 0)

    def update_status(self, status: str, msg: str = "") -> None:
        self._status = (str(status or "idle"), str(msg or ""))

    def add_step(self, type: str, action: str, success: bool) -> None:  # noqa: A002 - 兼容既有调用
        self._steps.append((str(type or ""), str(action or ""), bool(success)))
        self._total_steps += 1

    def update_tokens(self, tokens: int, cost: float) -> None:
        self.state.total_tokens = int(tokens or 0)
        self.state.total_cost = float(cost or 0.0)

    # ---------- 渲染 ----------
    def render_full_layout(self) -> RenderableType:
        """返回当前状态的 renderable（Live 每次刷新都会重新调用）"""
        return self

    def __rich_console__(self, console: Console, options: Any):
        rows: list[RenderableType] = [self._header(), self._status_line()]
        steps = self._steps_table()
        if steps is not None:
            rows.append(steps)
        stream = self._stream_panel()
        if stream is not None:
            rows.append(stream)
        yield Group(*rows)

    def _header(self) -> RenderableType:
        text = render_hud(self.state, "full")
        return Text.from_ansi(text) if text else Text("clawd", style="bold")

    def _status_line(self) -> RenderableType:
        status, msg = self._status
        style = _STATUS_STYLE.get(status, "white")
        line = Text()
        line.append(f" {status} ", style=f"bold {style}")
        if msg:
            line.append(" ")
            line.append_text(Text(msg[:120]))
        if self._total_steps:
            line.append(f"   步骤 {self._total_steps}", style="dim")
        return line

    def _steps_table(self) -> RenderableType | None:
        if not self._steps:
            return None
        table = Table.grid(padding=(0, 1))
        table.add_column(width=4)
        table.add_column(width=8)
        table.add_column()
        for step_type, action, success in self._steps:
            # 用 ASCII 标记：中文 Windows 默认代码页是 GBK，✓/✗ 会触发 UnicodeEncodeError
            icon = Text("ok", style="green") if success else Text("err", style="red")
            table.add_row(
                icon,
                Text(step_type or "-", style="dim"),
                Text(escape(action[:100]), style="white"),
            )
        return table

    def _stream_panel(self) -> RenderableType | None:
        if not self._stream_tail.strip():
            return None
        return Panel(
            Text(self._stream_tail, overflow="fold"),
            title="输出",
            border_style="grey37",
            padding=(0, 1),
        )
