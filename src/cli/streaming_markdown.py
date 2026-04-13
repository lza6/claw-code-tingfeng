"""流式 Markdown 渲染器 — Rich Console + 代码高亮 + Live 窗口

用于 AgentEngine 流式输出的渲染，支持:
- 实时增量渲染 Markdown
- Python 代码语法高亮
- 自适应终端宽度
- Live 窗口滑动渲染（移植自 Aider mdstream.py）

移植自 Aider mdstream.py:
- MarkdownStream: 基于 rich.Live 的流式渲染器
- NoInsetCodeBlock: 无 padding 的代码块
- LeftHeading: 左对齐标题
"""
from __future__ import annotations

import contextlib
import io
import time
from typing import Any

from rich import box
from rich.console import Console, RenderableType
from rich.live import Live
from rich.markdown import CodeBlock, Heading, Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text


class StreamingMarkdownRenderer:
    """流式 Markdown 渲染器

    用法:
        renderer = StreamingMarkdownRenderer()
        for chunk in stream:
            rendered = renderer.render_chunk(chunk)
            console.print(rendered)
    """

    def __init__(self, console: Console | None = None, theme: str = "monokai") -> None:
        self.console = console or Console()
        self.theme = theme
        self._buffer: str = ""
        self._last_rendered_length = 0

    def reset(self) -> None:
        """重置缓冲区"""
        self._buffer = ""
        self._last_rendered_length = 0

    def append(self, text: str) -> None:
        """追加文本到缓冲区"""
        self._buffer += text

    def render_current(self) -> RenderableType:
        """渲染当前缓冲区为 Markdown"""
        return Markdown(self._buffer)

    def render_code_block(self, code: str, language: str = "python") -> Panel:
        """渲染代码块（带语法高亮）"""
        try:
            syntax = Syntax(code, language, theme=self.theme, line_numbers=True)
            return Panel(syntax, title=f"📄 {language}", border_style="cyan")
        except Exception:
            return Panel(code, title=f"📄 {language}", border_style="dim")

    def render_with_context(self) -> Panel:
        """带上下文的渲染（截取最后 N 行避免溢出）"""
        lines = self._buffer.split("\n")
        max_lines = self.console.height - 10 if self.console.height else 20

        if len(lines) > max_lines:
            # 保留头部和尾部
            head = lines[:5]
            tail = lines[-(max_lines - 7):]
            display = [*head, f"  ... ({len(lines) - len(head) - len(tail)} 行省略) ...", "", *tail]
        else:
            display = lines

        content = "\n".join(display)
        return Panel(Markdown(content), title="📝 输出", border_style="green")


class StreamingCodeHighlighter:
    """流式代码高亮器

    专门用于代码块的实时高亮渲染。
    增量解析代码块边界，逐行高亮。
    """

    def __init__(self, language: str = "python", theme: str = "monokai") -> None:
        self.language = language
        self.theme = theme
        self._buffer: str = ""
        self._in_code_block = False
        self._code_buffer: str = ""

    def feed(self, chunk: str) -> RenderableType | None:
        """输入文本块，返回渲染结果

        返回:
            渲染结果或 None（如果在代码块外且不需要渲染）
        """
        self._buffer += chunk

        # 检测代码块开始
        if not self._in_code_block:
            if "```" in self._buffer:
                self._in_code_block = True
                parts = self._buffer.split("```", 1)
                # 渲染代码块前的 Markdown
                if parts[0].strip():
                    return Markdown(parts[0])
                self._buffer = ""
                self._code_buffer = ""
                return None
            else:
                # 普通 Markdown 文本
                return Markdown(self._buffer)
        else:
            # 在代码块内
            if "```" in self._buffer:
                # 代码块结束
                parts = self._buffer.split("```", 1)
                self._code_buffer += parts[0]
                self._in_code_block = False
                self._buffer = parts[1]

                # 渲染代码块
                syntax = Syntax(self._code_buffer, self.language, theme=self.theme, line_numbers=True)
                return Panel(syntax, title=f"📄 {self.language}", border_style="cyan")
            else:
                self._code_buffer += self._buffer
                self._buffer = ""
                # 渲染当前代码
                syntax = Syntax(self._code_buffer, self.language, theme=self.theme, line_numbers=True)
                return Panel(syntax, title=f"📄 {self.language} (流式)", border_style="cyan")

    def reset(self) -> None:
        """重置"""
        self._buffer = ""
        self._code_buffer = ""
        self._in_code_block = False


# ==================== MarkdownStream（从 Aider mdstream.py 移植） ====================


class NoInsetCodeBlock(CodeBlock):
    """无 padding 的代码块渲染（移植自 Aider）"""

    def __rich_console__(self, console: Any, options: Any):
        code = str(self.text).rstrip()
        syntax = Syntax(code, self.lexer_name, theme=self.theme, word_wrap=True, padding=(1, 0))
        yield syntax


class LeftHeading(Heading):
    """左对齐标题渲染（移植自 Aider）"""

    def __rich_console__(self, console: Any, options: Any):
        text = self.text
        text.justify = "left"
        if self.tag == "h1":
            yield Panel(text, box=box.HEAVY, style="markdown.h1.border")
        else:
            if self.tag == "h2":
                yield Text("")
            yield text


class NoInsetMarkdown(Markdown):
    """无内边距 Markdown 渲染器（移植自 Aider）

    代码块无 padding，标题左对齐。
    """

    elements = {
        **Markdown.elements,
        "fence": NoInsetCodeBlock,
        "code_block": NoInsetCodeBlock,
        "heading_open": LeftHeading,
    }


class MarkdownStream:
    """流式 Markdown 渲染器 — 基于 rich.Live 的滑动窗口（移植自 Aider mdstream.py）

    使用 rich.Live 在终端底部维护一个实时更新的窗口区域，
    已稳定的行输出到 Live 上方的控制台（支持回滚），
    未稳定的行保持在 Live 窗口中可重绘。

    用法:
        ms = MarkdownStream()
        for chunk in stream:
            ms.update(chunk)
        ms.update(full_text, final=True)
    """

    live: Live | None = None
    when: float = 0
    min_delay: float = 1.0 / 20  # 20fps
    live_window: int = 6  # 底部保留的不稳定行数

    def __init__(self, mdargs: dict[str, Any] | None = None) -> None:
        self.printed: list[str] = []
        self.mdargs = mdargs or {}
        self.live = None
        self._live_started = False

    def _render_markdown_to_lines(self, text: str) -> list[str]:
        """将 Markdown 文本渲染为行列表"""
        string_io = io.StringIO()
        console = Console(file=string_io, force_terminal=True)
        markdown = NoInsetMarkdown(text, **self.mdargs)
        console.print(markdown)
        output = string_io.getvalue()
        return output.splitlines(keepends=True)

    def update(self, text: str, final: bool = False) -> None:
        """更新显示的 Markdown 内容

        参数:
            text: 迄今为止接收到的 Markdown 文本
            final: 是否为最终更新
        """
        if not getattr(self, '_live_started', False):
            self.live = Live(Text(""), refresh_per_second=1.0 / self.min_delay)
            self.live.start()
            self._live_started = True

        now = time.time()
        if not final and now - self.when < self.min_delay:
            return
        self.when = now

        start = time.time()
        lines = self._render_markdown_to_lines(text)
        render_time = time.time() - start

        # 根据渲染时间动态调整帧率
        self.min_delay = min(max(render_time * 10, 1.0 / 20), 2)

        num_lines = len(lines)

        if not final:
            num_lines -= self.live_window

        if final or num_lines > 0:
            num_printed = len(self.printed)
            show = num_lines - num_printed

            if show <= 0:
                return

            show_lines = lines[num_printed:num_lines]
            show_text = "".join(show_lines)
            show_text = Text.from_ansi(show_text)
            self.live.console.print(show_text)

            self.printed = lines[:num_lines]

        if final:
            self.live.update(Text(""))
            self.live.stop()
            self.live = None
            return

        rest = lines[num_lines:]
        rest_text = "".join(rest)
        rest_text = Text.from_ansi(rest_text)
        self.live.update(rest_text)

    def reset(self) -> None:
        """重置渲染器状态"""
        self.printed = []
        self.when = 0
        self.min_delay = 1.0 / 20
        self._live_started = False
        if self.live:
            with contextlib.suppress(Exception):
                self.live.stop()
            self.live = None
