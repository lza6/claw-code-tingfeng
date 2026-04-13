"""Omni-Glow 主应用

Omni-Glow V5.0 主应用入口:
- HSL 响应式玻璃拟态风格
- Shadow Preview 影子预览
- Thinking Tree 思维树
- Ctl+B 中断拦截
- 支持 green_theme 动态主题切换
"""
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header

from .omni_glow_indicators import RiskIndicator, StatusIndicator
from .omni_glow_mirror import MirrorPane
from .omni_glow_models import RiskAlert
from .omni_glow_stream import CodeStreamView
from .omni_glow_tree import ThinkingTree


class OmniGlowApp(App):
    """Omni-Glow V5.0 主应用

    特性:
    - HSL 响应式玻璃拟态风格
    - Shadow Preview 影子预览
    - Thinking Tree 思维树
    - Ctl+B 中断拦截
    - 支持 green_theme 动态主题切换
    """

    # 动态设置 CSS 路径，green_theme 启用时使用绿色主题
    @property
    def CSS_PATH(self) -> str:  # type: ignore[override]
        try:
            from .utils.features import features
            if features.is_enabled("green_theme"):
                return "themes/clawgod_green.tcss"
        except Exception:
            pass
        return "themes/omni_glow.tcss"

    # 状态
    app_state: reactive[str] = reactive("idle")

    BINDINGS = [  # noqa: RUF012
        ("ctrl+b", "break_execution", "中断"),
        ("q", "quit", "退出"),
    ]

    def __init__(
        self,
        workdir: str | None = None,
        max_iterations: int = 10,
    ) -> None:
        super().__init__()
        self.workdir = workdir
        self.max_iterations = max_iterations

        # 组件引用
        self._mirror_pane: MirrorPane | None = None
        self._thinking_tree: ThinkingTree | None = None
        self._code_stream: CodeStreamView | None = None
        self._risk_indicator: RiskIndicator | None = None
        self._status_indicator: StatusIndicator | None = None

    def compose(self) -> ComposeResult:
        yield Header()

        # 主容器
        with Container(id="main-container"):
            # 左侧: 主内容区
            with Vertical(id="left-pane"):
                self._thinking_tree = ThinkingTree(id="thinking-tree")
                yield self._thinking_tree

                self._code_stream = CodeStreamView(id="code-stream")
                yield self._code_stream

            # 右侧: Shadow Preview
            self._mirror_pane = MirrorPane(id="mirror-pane")
            yield self._mirror_pane

        # 底部
        self._risk_indicator = RiskIndicator(id="risk-indicator")
        yield self._risk_indicator

        self._status_indicator = StatusIndicator(id="status-indicator")
        yield self._status_indicator

        yield Footer()

    def on_mount(self) -> None:
        """应用启动"""
        self.set_state("idle")

        # 初始化思维树示例
        if self._thinking_tree:
            root_id = self._thinking_tree.add_node("分析需求", confidence=0.9, status="success")
            self._thinking_tree.add_node("制定方案", parent_id=root_id, confidence=0.85, status="running")

    def set_state(self, state: str) -> None:
        """设置应用状态"""
        self.app_state = state

        if self._status_indicator:
            self._status_indicator.set_state(state)

    def append_code_stream(self, code: str, is_risky: bool = False) -> None:
        """追加代码到流"""
        if self._code_stream:
            self._code_stream.append_chunk(code)

        if self._mirror_pane:
            risk_reason = "高风险操作" if is_risky else ""
            self._mirror_pane.append_code(code, is_risky=is_risky, risk_reason=risk_reason)

    def show_risk_alert(self, alert: RiskAlert) -> None:
        """显示风险警示"""
        if self._risk_indicator:
            self._risk_indicator.set_alert(alert)

        self.set_state("alert")

    def action_break_execution(self) -> None:
        """Ctl+B 中断当前执行"""
        self.notify("⛔ 已中断当前操作", title="中断", severity="warning")
        self.set_state("idle")

    def action_quit(self) -> None:
        """退出应用"""
        self.exit()


# ============================================================================
# 启动函数
# ============================================================================

def start_omni_glow_tui(
    workdir: str | None = None,
    max_iterations: int = 10,
) -> int:
    """启动 Omni-Glow TUI

    参数:
        workdir: 工作目录
        max_iterations: 最大迭代次数

    返回:
        退出码
    """
    app = OmniGlowApp(workdir=workdir, max_iterations=max_iterations)
    return app.run()
