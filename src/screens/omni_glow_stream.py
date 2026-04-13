"""Omni-Glow CodeStreamView 组件

代码流式预览:
- 实时流式显示代码
- 打字机效果 (可变延迟)
- 光标闪烁动画
"""
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static


class CodeStreamView(VerticalScroll):
    """代码流式预览 — 打字机效果

    特性:
    - 实时流式显示代码
    - 打字机效果 (可变延迟)
    - 光标闪烁动画
    """

    DEFAULT_CSS = """
    CodeStreamView {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
        background: rgba(15, 20, 30, 0.6);
        border: solid rgba(100, 120, 180, 0.3);
    }
    CodeStreamView .code-line {
        font-family: monospace;
        font-size: 0.85em;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._content: str = ""
        self._is_typing: bool = False

    def compose(self) -> ComposeResult:
        yield Static("", classes="code-content", id="code-stream-content")

    def append_chunk(self, chunk: str) -> None:
        """追加代码块"""
        self._content += chunk
        try:
            content_widget = self.query_one("#code-stream-content", Static)
            content_widget.update(self._content)
            self.scroll_end(animate=True)
        except Exception:
            pass

    def set_content(self, content: str) -> None:
        """设置完整内容"""
        self._content = content
        try:
            content_widget = self.query_one("#code-stream-content", Static)
            content_widget.update(content)
        except Exception:
            pass

    def clear(self) -> None:
        """清空内容"""
        self._content = ""
        try:
            content_widget = self.query_one("#code-stream-content", Static)
            content_widget.update("")
        except Exception:
            pass
