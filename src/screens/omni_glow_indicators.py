"""Omni-Glow 指示器组件

包含:
- RiskIndicator: SIP 高风险行警示
- StatusIndicator: 状态指示器 (HSL Pulse)
"""
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Label, Static

from .omni_glow_models import (
    COLOR_ALERT,
    COLOR_IDLE,
    COLOR_SUCCESS,
    COLOR_THINKING,
    RiskAlert,
)

# ============================================================================
# RiskIndicator: SIP 风险警示
# ============================================================================

class RiskIndicator(Vertical):
    """SIP 高风险行警示

    特性:
    - 显示当前风险等级
    - 受影响文件列表
    - 警示色加粗显示
    """

    DEFAULT_CSS = """
    RiskIndicator {
        height: auto;
        padding: 0 1;
        margin: 1;
        border: solid #D94F4F;
        background: rgba(255, 80, 80, 0.1);
    }
    RiskIndicator .risk-title {
        color: #D94F4F;
        text-style: bold;
    }
    RiskIndicator .risk-message {
        color: $text-primary;
        padding: 0 1;
    }
    RiskIndicator .risk-files {
        color: $text-secondary;
        padding: 0 1;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._alert: RiskAlert | None = None

    def compose(self) -> ComposeResult:
        yield Label("⚠️ SIP Risk Alert", classes="risk-title", id="risk-title")
        yield Static("", classes="risk-message", id="risk-message")
        yield Static("", classes="risk-files", id="risk-files")

    def set_alert(self, alert: RiskAlert) -> None:
        """设置风险警示"""
        self._alert = alert
        self._refresh_display()

    def clear_alert(self) -> None:
        """清除警示"""
        self._alert = None
        self._refresh_display()

    def _refresh_display(self) -> None:
        """刷新显示"""
        try:
            msg_widget = self.query_one("#risk-message", Static)
            files_widget = self.query_one("#risk-files", Static)

            if self._alert:
                severity_icons = {
                    "low": "🟡",
                    "medium": "🟠",
                    "high": "🔴",
                    "critical": "💀",
                }
                icon = severity_icons.get(self._alert.severity, "⚠️")
                msg_widget.update(f"{icon} {self._alert.message}")

                if self._alert.affected_files:
                    files_text = "影响文件: " + ', '.join(self._alert.affected_files[:3])
                    files_widget.update(files_text)
                else:
                    files_widget.update("")
            else:
                msg_widget.update("")
                files_widget.update("")
        except Exception:
            pass


# ============================================================================
# StatusIndicator: 状态指示器 (HSL Pulse)
# ============================================================================

class StatusIndicator(Horizontal):
    """状态指示器 — HSL Pulse 动态色彩

    特性:
    - Idle: 慢速呼吸 (6s 周期)
    - Thinking: 快速闪动 (0.5s)
    - Alert: 边缘溢出阴影
    - Success: 瞬时高亮扩展
    """

    DEFAULT_CSS = """
    StatusIndicator {
        height: 3;
        padding: 0 2;
        dock: bottom;
    }
    StatusIndicator .status-icon {
        width: 3;
        text-align: center;
    }
    StatusIndicator .status-text {
        color: $text-secondary;
    }
    """

    current_state: reactive[str] = reactive("idle")

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._breath_phase: float = 0.0

    def compose(self) -> ComposeResult:
        yield Label("●", classes="status-icon", id="status-icon")
        yield Label("就绪", classes="status-text", id="status-text")

    def set_state(self, state: str) -> None:
        """设置状态"""
        self.current_state = state
        self._update_display()

    def _update_display(self) -> None:
        """更新显示"""
        try:
            icon_widget = self.query_one("#status-icon", Label)
            text_widget = self.query_one("#status-text", Label)

            state_config = {
                "idle": ("●", "深智监护中", COLOR_IDLE),
                "thinking": ("◉", "神经网络推理", COLOR_THINKING),
                "alert": ("⚠", "高风险操作", COLOR_ALERT),
                "success": ("✓", "任务完成", COLOR_SUCCESS),
                "error": ("✗", "执行错误", COLOR_ALERT),
            }

            icon, text, color = state_config.get(self.current_state, ("?", "未知", COLOR_IDLE))

            icon_widget.update(icon)
            icon_widget.styles.color = color
            text_widget.update(text)

        except Exception:
            pass
