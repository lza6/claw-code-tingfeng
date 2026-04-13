"""Dashboard Panels — 面板组件

包含:
- BreathingPanel: 呼吸灯边框面板
- StreamingMarkdownView: 流式 Markdown 视图
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Markdown


class BreathingPanel(Vertical):
    """带呼吸灯效果的面板

    边框颜色会随状态平滑过渡:
    - idle: Cyan
    - thinking: Cyan → Purple (呼吸动画)
    - executing: Purple
    - done: Green
    - error: Red
    """

    DEFAULT_CSS = """
    BreathingPanel {
        border: solid #00BCD4;
        padding: 1;
        margin: 1;
    }
    BreathingPanel.breathing {
        border: solid #00BCD4;
        animation: breathe 2s infinite alternate;
    }
    BreathingPanel.executing {
        border: solid #673AB7;
    }
    BreathingPanel.done {
        border: solid #4CAF50;
    }
    BreathingPanel.error {
        border: solid #F44336;
    }
    """

    # 响应式状态
    panel_state: reactive[str] = reactive("idle")
    panel_title: reactive[str] = reactive("")
    is_breathing: reactive[bool] = reactive(False)

    def __init__(
        self,
        *children,
        title: str = "",
        state: str = "idle",
        id: str | None = None,
    ) -> None:
        super().__init__(*children, id=id)
        self.panel_title = title
        self.panel_state = state

    def watch_panel_state(self, old_state: str, new_state: str) -> None:
        """状态变化时更新边框样式"""
        self.remove_class("breathing", "executing", "done", "error")

        if new_state == "thinking":
            self.is_breathing = True
            self.add_class("breathing")
        elif new_state == "executing":
            self.is_breathing = False
            self.add_class("executing")
        elif new_state == "done":
            self.is_breathing = False
            self.add_class("done")
        elif new_state == "error":
            self.is_breathing = False
            self.add_class("error")
        else:
            self.is_breathing = False


class StreamingMarkdownView(VerticalScroll):
    """流式 Markdown 渲染视图

    支持增量更新，自动滚动到底部
    """

    DEFAULT_CSS = """
    StreamingMarkdownView {
        height: 1fr;
        padding: 0 1;
    }
    #md-content {
        width: 1fr;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._content = ""
        self._md_widget: Markdown | None = None

    def compose(self) -> ComposeResult:
        self._md_widget = Markdown(self._content, id="md-content")
        yield self._md_widget

    def append_content(self, chunk: str) -> None:
        """追加流式内容"""
        self._content += chunk
        if self._md_widget:
            self._md_widget.update(self._content)
            # 自动滚动到底部
            self.scroll_end(animate=True)

    def set_content(self, content: str) -> None:
        """设置完整内容"""
        self._content = content
        if self._md_widget:
            self._md_widget.update(self._content)


__all__ = [
    "BreathingPanel",
    "StreamingMarkdownView",
]
