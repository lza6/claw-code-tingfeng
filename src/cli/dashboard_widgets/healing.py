"""Dashboard Diff & Healing Widgets — Diff和自愈组件

包含:
- DiffView: Diff 视图
- ConfidenceGradient: 信心渐变指示器
- SelfHealingPanel: 自愈状态面板
"""
from __future__ import annotations

import contextlib
import time

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Label

# 导入数据模型
from .models import ConfidenceHistory, DiffLine, HealingEvent, SelfHealingStats


# ============================================================================
# Self-Healing Stats
# ============================================================================

class SelfHealingStatsPanel(Vertical):
    """自愈统计面板 — 工业级自愈指标可视化"""

    DEFAULT_CSS = """
    SelfHealingStatsPanel {
        height: auto;
        padding: 0 1;
        border-bottom: thin $primary;
    }
    .stats-row {
        height: auto;
        margin: 0;
    }
    .stats-label {
        color: $text-muted;
        width: 15;
    }
    .stats-value {
        color: $text;
        width: 1fr;
    }
    .stats-value.success {
        color: #4CAF50;
        text-style: bold;
    }
    .stats-value.fail {
        color: #F44336;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._stats = SelfHealingStats()
        self._value_labels: dict[str, Label] = {}

    def compose(self) -> ComposeResult:
        yield Label("🛠️ HEALING METRICS", classes="section-title")

        metrics = [
            ("total_fixes_successful", "Successful", True),
            ("total_fixes_attempted", "Total Fixes", False),
            ("success_rate", "Success Rate", True),
            ("avg_attempts_per_fix", "Avg Attempts", False),
        ]

        for key, label_text, is_primary in metrics:
            row = Horizontal(
                Label(label_text, classes="stats-label"),
                Label("0", classes=f"stats-value{' success' if is_primary else ''}", id=f"stats-value-{key}"),
                classes="stats-row"
            )
            self._value_labels[key] = row.query_one(f"#stats-value-{key}", Label)
            yield row

    def update_stats(self, **kwargs) -> None:
        """更新统计数据"""
        from .models import SelfHealingStats
        if not hasattr(self, '_stats'):
            self._stats = SelfHealingStats()

        for key, value in kwargs.items():
            setattr(self._stats, key, value)
            if key in self._value_labels:
                formatted = str(value)
                if key == "success_rate":
                    formatted = f"{value:.1f}%"
                elif key == "avg_attempts_per_fix":
                    formatted = f"{value:.2f}"

                self._value_labels[key].update(formatted)


# ============================================================================
# Diff View
# ============================================================================

class DiffView(VerticalScroll):
    """Diff 视图 — 展示代码修复的差异

    特点:
    - 红色背景显示删除的行
    - 绿色背景显示添加的行
    - 灰色背景显示上下文行
    - 自动滚动到最新变更
    """

    DEFAULT_CSS = """
    DiffView {
        height: 1fr;
        padding: 0 1;
        background: $surface;
    }
    .diff-line {
        padding: 0 1;
        margin: 0;
        font-family: monospace;
        font-size: 0.8em;
        width: 1fr;
    }
    .diff-added {
        background: #1B5E20;
        color: #A5D6A7;
    }
    .diff-removed {
        background: #B71C1C;
        color: #EF9A9A;
    }
    .diff-context {
        background: $surface;
        color: $text-muted;
    }
    .diff-header {
        background: #4A148C;
        color: #CE93D8;
        text-style: bold;
    }
    .diff-line-number {
        width: 6;
        color: $text-muted;
        text-align: right;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._diff_lines: list[DiffLine] = []
        self._line_widgets: list[Horizontal] = []

    def set_diff(self, diff_lines: list[DiffLine]) -> None:
        """设置 Diff 数据 (Delta Rendering: 增量更新)"""
        self._diff_lines = diff_lines
        self._refresh_display()

    def append_diff(self, diff_lines: list[DiffLine]) -> None:
        """追加 Diff 数据 (增量追加)"""
        self._diff_lines.extend(diff_lines)
        self._append_display(diff_lines)

    def clear(self) -> None:
        """清空 Diff"""
        self._diff_lines.clear()
        self._line_widgets.clear()
        with contextlib.suppress(Exception):
            self.remove_children()

    def _refresh_display(self) -> None:
        """刷新显示 (全量)"""
        with contextlib.suppress(Exception):
            self.remove_children()
        self._line_widgets.clear()
        self._append_display(self._diff_lines)

    def _append_display(self, diff_lines: list[DiffLine]) -> None:
        """增量追加显示"""
        for diff_line in diff_lines:
            widget = self._create_diff_line_widget(diff_line)
            self._line_widgets.append(widget)
            with contextlib.suppress(Exception):
                self.mount(widget)

        # 自动滚动到底部
        with contextlib.suppress(Exception):
            self.scroll_end(animate=True)

    def _create_diff_line_widget(self, diff_line: DiffLine) -> Horizontal:
        """创建 Diff 行 widget"""
        type_class = {
            "added": "diff-added",
            "removed": "diff-removed",
            "context": "diff-context",
            "header": "diff-header",
        }.get(diff_line.type, "diff-context")

        prefix = {
            "added": "+",
            "removed": "-",
            "context": " ",
            "header": "#",
        }.get(diff_line.type, " ")

        line_num_label = Label(f"{diff_line.line_number:>4}", classes="diff-line-number")
        content_label = Label(f"{prefix} {diff_line.content}", classes=f"diff-line {type_class}")

        return Horizontal(line_num_label, content_label)


# ============================================================================
# Confidence Gradient
# ============================================================================

class ConfidenceGradient(Vertical):
    """信心渐变指示器 — 展示修复决策信心的演变

    特点:
    - 红色 (低信心) → 黄色 (中等) → 绿色 (高信心)
    - 历史轨迹可视化 (迷你柱状图)
    - 当前信心数值显示
    """

    DEFAULT_CSS = """
    ConfidenceGradient {
        width: 1fr;
        height: auto;
        padding: 0 1;
    }
    #confidence-value {
        width: 1fr;
        text-align: center;
        text-style: bold;
    }
    #confidence-bar-container {
        width: 1fr;
        height: 3;
        border: solid $primary;
    }
    #confidence-bar {
        width: 100%;
        height: 100%;
    }
    #confidence-history {
        width: 1fr;
        height: auto;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._current_confidence: float = 0.0
        self._history = ConfidenceHistory()
        self._confidence_label: Label | None = None
        self._bar_label: Label | None = None

    def compose(self) -> ComposeResult:
        yield Label("Confidence:", classes="section-title")
        yield Label("0%", id="confidence-value")
        yield Label("░" * 20, id="confidence-bar")
        yield Label("History: " + "░" * 20, id="confidence-history")

    def on_mount(self) -> None:
        self._confidence_label = self.query_one("#confidence-value", Label)
        self._bar_label = self.query_one("#confidence-bar", Label)

    def update_confidence(self, confidence: float) -> None:
        """更新信心值 (0.0 - 1.0)"""
        self._current_confidence = max(0.0, min(confidence, 1.0))
        self._history.values.append(self._current_confidence)
        self._history.timestamps.append(time.time())

        # 保持历史记录在合理范围内
        if len(self._history.values) > 20:
            self._history.values.pop(0)
            self._history.timestamps.pop(0)

        self._refresh_display()

    def _refresh_display(self) -> None:
        """刷新显示"""
        if self._confidence_label is None or self._bar_label is None:
            return

        percentage = int(self._current_confidence * 100)
        self._confidence_label.update(f"{percentage}%")

        # 颜色映射
        if self._current_confidence < 0.3:
            color = "#F44336"  # 红
        elif self._current_confidence < 0.6:
            color = "#FFC107"  # 黄
        else:
            color = "#4CAF50"  # 绿

        # 进度条
        bar_width = 20
        filled = int(self._current_confidence * bar_width)
        bar_str = "█" * filled + "░" * (bar_width - filled)

        self._bar_label.update(f"[{color}]{bar_str}[/{color}]")

        # 历史轨迹
        history_label = self.query_one("#confidence-history", Label)
        history_str = " ".join([
            "▓" if v > 0.6 else "░" if v > 0.3 else "░"
            for v in self._history.values[-10:]
        ])
        history_label.update(f"History: {history_str}")


# ============================================================================
# Self-Healing Panel
# ============================================================================

class SelfHealingPanel(Vertical):
    """自愈状态面板 — 整合 Diff View + 信心渐变

    布局:
    ┌──────────────────────────────────┐
    │ 🛡️ Self-Healing Status           │
    ├──────────────────────────────────┤
    │ 信心: ████████████████░░░ 65%   │
    │ 历史: ░░░▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓     │
    ├──────────────────────────────────┤
    │ Diff View:                       │
    │ - old_line = broken_code()       │
    │ + new_line = fixed_code()        │
    └──────────────────────────────────┘
    """

    DEFAULT_CSS = """
    SelfHealingPanel {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
    }
    #healing-status {
        text-style: bold;
        padding: 0 1;
    }
    #healing-error {
        color: #F44336;
        padding: 0 1;
    }
    #healing-strategy {
        color: #4CAF50;
        padding: 0 1;
    }
    #diff-container {
        height: 1fr;
        border: solid $primary;
        title: "Diff";
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._healing_events: list[HealingEvent] = []
        self._current_healing: HealingEvent | None = None

    def compose(self) -> ComposeResult:
        yield Label("🛡️ Self-Healing Status", id="healing-status")
        yield Label("", id="healing-error")
        yield Label("", id="healing-strategy")
        yield ConfidenceGradient(id="confidence-gradient")
        yield Label("Diff View:", classes="section-title")
        yield DiffView(id="diff-view")

    def report_healing(self, event: HealingEvent) -> None:
        """报告自愈事件"""
        self._current_healing = event
        self._healing_events.append(event)
        self._refresh_display()

    def _refresh_display(self) -> None:
        """刷新显示"""
        if self._current_healing is None:
            return

        event = self._current_healing

        try:
            error_label = self.query_one("#healing-error", Label)
            error_label.update(f"❌ {event.error_type}: {event.error_message[:60]}")

            strategy_label = self.query_one("#healing-strategy", Label)
            strategy_label.update(f"✅ 策略: {event.fix_strategy[:50]}")

            # 更新信心
            confidence = self.query_one("#confidence-gradient", ConfidenceGradient)
            confidence.update_confidence(event.confidence)

            # 更新 Diff
            diff_view = self.query_one("#diff-view", DiffView)
            if event.diff_lines:
                diff_view.set_diff(event.diff_lines)
        except Exception:
            pass


__all__ = [
    "ConfidenceGradient",
    "DiffView",
    "SelfHealingPanel",
]
