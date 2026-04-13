"""Omni-Glow MirrorPane 组件

Shadow Preview 影子预览面板:
- 40% 宽度右侧弹出
- 实时显示正在生成的代码
- 高风险行以警示色加粗显示
- 悬浮显示受影响文件列表
"""
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widgets import Label, Static


class MirrorPane(VerticalScroll):
    """Shadow Preview 影子预览面板

    特性:
    - 40% 宽度右侧弹出
    - 实时显示正在生成的代码
    - 高风险行以警示色加粗显示
    - 悬浮显示受影响文件列表
    """

    DEFAULT_CSS = """
    MirrorPane {
        width: 40%;
        dock: right;
        background: $surface;
        border-left: double $primary;
        padding: 1;
    }
    MirrorPane .pane-title {
        text-style: bold;
        color: $primary;
        padding: 0 1;
    }
    MirrorPane .code-content {
        font-family: monospace;
        font-size: 0.85em;
        padding: 0 1;
        width: 1fr;
    }
    MirrorPane .risky-line {
        color: #FF6B6B;
        text-style: bold;
        background: rgba(255, 100, 100, 0.15);
    }
    MirrorPane .file-list {
        color: $text-muted;
        padding: 0 1;
        margin: 1 0;
        border-top: solid $border;
    }
    """

    # 响应式数据
    is_visible: reactive[bool] = reactive(False)
    current_content: reactive[str] = reactive("")
    risky_lines: reactive[list[int]] = reactive([])
    affected_files: reactive[list[str]] = reactive([])

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._code_buffer: list[str] = []
        self._risky_line_map: dict[int, str] = {}  # line -> reason

    def compose(self) -> ComposeResult:
        yield Label("🪞 Shadow Preview", classes="pane-title", id="mirror-title")
        yield Static("", classes="code-content", id="mirror-code")
        yield Static("", classes="file-list", id="mirror-files")

    def append_code(self, line: str, is_risky: bool = False, risk_reason: str = "") -> None:
        """追加代码行"""
        self._code_buffer.append(line)

        if is_risky:
            line_num = len(self._code_buffer) - 1
            self._risky_line_map[line_num] = risk_reason

        self._refresh_display()

    def set_content(self, content: str, risky_lines: list[int] | None = None) -> None:
        """设置完整内容"""
        self._code_buffer = content.split('\n')

        if risky_lines:
            for line_num in risky_lines:
                if 0 <= line_num < len(self._code_buffer):
                    self._risky_line_map[line_num] = "高风险操作"

        self._refresh_display()

    def set_affected_files(self, files: list[str]) -> None:
        """设置受影响文件列表"""
        self.affected_files = files
        self._update_file_list()

    def clear(self) -> None:
        """清空内容"""
        self._code_buffer.clear()
        self._risky_line_map.clear()
        self._refresh_display()

    def _refresh_display(self) -> None:
        """刷新显示"""
        try:
            code_widget = self.query_one("#mirror-code", Static)
            lines = []

            for i, line in enumerate(self._code_buffer[-50:]):  # 只显示最后 50 行
                if i in self._risky_line_map:
                    # 高风险行: 添加标记
                    reason = self._risky_line_map[i]
                    lines.append(f"[bold red]⚠ {line}[/]  ({reason})")
                else:
                    lines.append(line)

            code_widget.update('\n'.join(lines))
            self.scroll_end(animate=True)
        except Exception:
            pass

    def _update_file_list(self) -> None:
        """更新受影响文件列表"""
        try:
            files_widget = self.query_one("#mirror-files", Static)
            if self.affected_files:
                text = "受影响文件:\n" + '\n'.join(f"  • {f}" for f in self.affected_files[-5:])
                files_widget.update(text)
            else:
                files_widget.update("")
        except Exception:
            pass
