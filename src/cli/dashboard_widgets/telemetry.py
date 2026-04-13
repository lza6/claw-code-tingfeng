"""Dashboard Telemetry Widgets — 遥测指标组件

包含:
- TelemetryPanel: 遥测指标面板
- AnimatedProgressBar: 非线性步进进度条
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label

from .animations import ease_in_out

# 导入数据模型
from .models import RAGMetrics, TelemetryData


class TelemetryPanel(Vertical):
    """遥测指标面板 — Delta Rendering 增量渲染版本

    显示: Token 计数、成本、延迟、调用次数、以及 RAG 索引状态
    """

    DEFAULT_CSS = """
    TelemetryPanel {
        width: 1fr;
        padding: 0 1;
    }
    .metric-row {
        height: auto;
        margin: 0;
        padding: 0;
    }
    .metric-label {
        color: $text-muted;
        width: auto;
    }
    .metric-value {
        color: $text;
        width: 1fr;
        transition: color 0.3s;
    }
    .metric-value.highlight {
        color: #FFC107;
        text-style: bold;
    }
    .metric-value.updated {
        color: #4CAF50;
    }
    .metric-value.info {
        color: #2196F3;
    }
    .section-header {
        color: $accent;
        text-style: bold;
        margin-top: 1;
        border-bottom: thin $accent;
    }
    """

    # 指标配置
    LLM_METRICS: ClassVar[list[tuple[str, str, bool]]] = [
        ("total_tokens", "Tokens", True),
        ("total_cost", "Cost", True),
        ("llm_calls", "LLM Calls", False),
        ("cache_read_tokens", "Cache Read", False),
        ("cache_write_tokens", "Cache Write", False),
        ("reasoning_tokens", "Reasoning", False),
        ("avg_latency_ms", "Avg Latency", False),
    ]

    RAG_METRICS: ClassVar[list[tuple[str, str, bool]]] = [
        ("indexed_files", "Indexed Files", False),
        ("total_terms", "Total Terms", False),
        ("coverage_percent", "Coverage", True),
    ]

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._telemetry = TelemetryData()
        self._rag_metrics = RAGMetrics()
        self._value_labels: dict[str, Label] = {}  # key -> value_label

    def compose(self) -> ComposeResult:
        """初始化指标 widget (首次渲染)"""
        yield Label("LLM TELEMETRY", classes="section-header")
        for key, label_text, highlight in self.LLM_METRICS:
            initial_value = "0"
            if key == "total_cost":
                initial_value = "$0.0000"
            elif key == "avg_latency_ms":
                initial_value = "0ms"

            row = Horizontal(
                Label(label_text, classes="metric-label"),
                Label(initial_value, classes=f"metric-value{' highlight' if highlight else ''}", id=f"metric-value-{key}"),
                classes="metric-row",
            )
            self._value_labels[key] = row.query_one(f"#metric-value-{key}", Label)
            yield row

        yield Label("RAG INDEX STATUS", classes="section-header")
        for key, label_text, highlight in self.RAG_METRICS:
            initial_value = "0"
            if key == "coverage_percent":
                initial_value = "0.0%"

            row = Horizontal(
                Label(label_text, classes="metric-label"),
                Label(initial_value, classes=f"metric-value{' info' if not highlight else ' highlight'}", id=f"metric-value-{key}"),
                classes="metric-row",
            )
            self._value_labels[key] = row.query_one(f"#metric-value-{key}", Label)
            yield row

    def update_telemetry(self, **kwargs) -> None:
        """更新遥测数据 (Delta: 只更新变化的值)"""
        from .models import TelemetryData
        if not hasattr(self, '_telemetry'):
            self._telemetry = TelemetryData()

        for key, value in kwargs.items():
            old_value = getattr(self._telemetry, key, None)
            setattr(self._telemetry, key, value)

            if old_value != value and key in self._value_labels:
                self._update_metric_value(key, value)

    def update_rag_metrics(self, **kwargs) -> None:
        """更新 RAG 指标"""
        from .models import RAGMetrics
        if not hasattr(self, '_rag_metrics'):
            self._rag_metrics = RAGMetrics()

        for key, value in kwargs.items():
            old_value = getattr(self._rag_metrics, key, None)
            setattr(self._rag_metrics, key, value)

            if old_value != value and key in self._value_labels:
                self._update_metric_value(key, value)

    def _update_metric_value(self, key: str, value: Any) -> None:
        """更新单个指标值 (Delta + 动画反馈)"""
        if key not in self._value_labels:
            return

        value_label = self._value_labels[key]

        # 格式化值
        if key == "total_cost":
            formatted = f"${value:.4f}"
        elif key in ("total_tokens", "indexed_files", "total_terms", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens"):
            formatted = f"{value:,}"
        elif key == "avg_latency_ms":
            formatted = f"{value:.0f}ms"
        elif key == "coverage_percent":
            formatted = f"{value:.1f}%"
        else:
            formatted = str(value)

        # 更新值 + 高亮动画
        try:
            value_label.update(formatted)
            value_label.add_class("updated")

            # 延迟移除高亮
            def remove_highlight() -> None:
                with contextlib.suppress(Exception):
                    value_label.remove_class("updated")

            if self.app is not None:
                self.app.call_later(remove_highlight)
        except Exception:
            pass


# ============================================================================
# 非线性步进进度条 (Micro-Animations)
# ============================================================================

class AnimatedProgressBar(Vertical):
    """非线性步进进度条 — Ease-in-out 动画效果

    特点:
    - 平滑的非线性进度更新 (Ease-in-out)
    - 模拟人类节奏的步进感
    - 支持确定和不确定模式
    """

    DEFAULT_CSS = """
    AnimatedProgressBar {
        width: 1fr;
        height: auto;
        padding: 0 1;
    }
    #progress-bar-widget {
        width: 1fr;
    }
    #progress-label {
        color: $text-muted;
        width: 1fr;
        text-align: center;
    }
    """

    # 动画配置
    ANIMATION_DURATION = 0.5  # 秒
    ANIMATION_FPS = 30  # 帧率

    # 步进配置 (模拟人类节奏: 快→慢→快)
    STEP_PATTERNS: ClassVar[list[tuple[float, float]]] = [
        (0.0, 0.3),   # 快速启动
        (0.3, 0.5),   # 减速
        (0.5, 0.7),   # 缓慢继续
        (0.7, 0.85),  # 再次加速
        (0.85, 1.0),  # 冲刺
    ]

    def __init__(
        self,
        total: float = 100.0,
        show_percentage: bool = True,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._total = total
        self._current = 0.0
        self._target = 0.0
        self._show_percentage = show_percentage
        self._animating = False
        self._progress_bar: Label | None = None
        self._progress_label: Label | None = None
        self._progress_bar_id = f"progress-{id}" if id else "progress-bar-widget"

    def compose(self) -> ComposeResult:
        """初始化组件"""
        yield Label(id=self._progress_bar_id)
        if self._show_percentage:
            yield Label("0%", id="progress-label")

    def on_mount(self) -> None:
        """挂载时获取 widget 引用"""
        self._progress_bar = self.query_one(f"#{self._progress_bar_id}", Label)
        if self._show_percentage:
            self._progress_label = self.query_one("#progress-label", Label)
        self._update_progress_bar(0.0)

    def set_progress(self, value: float, animate: bool = True) -> None:
        """设置进度 (支持动画)"""
        self._target = min(max(value, 0), self._total)

        if not animate or self._animating:
            self._current = self._target
            self._update_progress_bar(self._current)
            return

        # 启动动画
        self._animating = True
        self._run_animation()

    async def _run_animation(self) -> None:
        """运行进度动画"""
        start_value = self._current
        end_value = self._target
        duration = self.ANIMATION_DURATION
        start_time = time.time()

        while self._animating:
            elapsed = time.time() - start_time
            t = min(elapsed / duration, 1.0)

            # 应用 ease-in-out
            eased_t = ease_in_out(t)

            # 计算当前值
            self._current = start_value + (end_value - start_value) * eased_t
            self._update_progress_bar(self._current)

            if t >= 1.0:
                self._animating = False
                self._current = self._target
                break

            await asyncio.sleep(1 / self.ANIMATION_FPS)

    def _update_progress_bar(self, value: float) -> None:
        """更新进度条显示"""
        if self._progress_bar is None:
            return

        percentage = (value / self._total) * 100
        bar_width = 30
        filled = int((percentage / 100) * bar_width)
        bar_str = "█" * filled + "░" * (bar_width - filled)

        self._progress_bar.update(f"[cyan]{bar_str}[/] {percentage:.0f}%")

        if self._progress_label is not None:
            self._progress_label.update(f"{percentage:.1f}%")

    def pulse(self) -> None:
        """脉冲动画 (不确定模式)"""
        if self._animating:
            return
        self._animating = True
        self._pulse_animation()

    async def _pulse_animation(self) -> None:
        """脉冲动画循环"""
        direction = 1
        current = 50.0

        while self._animating:
            current += direction * 2.0
            if current >= 100 or current <= 0:
                direction *= -1

            self._update_progress_bar(current * self._total / 100)
            await asyncio.sleep(0.1)


__all__ = [
    "AnimatedProgressBar",
    "TelemetryPanel",
]
