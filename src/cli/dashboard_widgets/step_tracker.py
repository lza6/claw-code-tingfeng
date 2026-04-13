"""Dashboard Step Tracker Widget — 步骤追踪组件

包含:
- StepTracker: 工作流步骤追踪器
"""
from __future__ import annotations

import contextlib
import time

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label

# 导入数据模型
from .models import StepInfo


class StepTracker(Vertical):
    """工作流步骤追踪器 — Delta Rendering 增量渲染版本

    显示: IDENTIFY → PLAN → EXECUTE → REVIEW → DISCOVER

    优化:
    - 增量渲染: 只更新变化的 widget，不重绘整个面板
    - 动画图标: 运行中图标有脉冲动画效果
    """

    DEFAULT_CSS = """
    StepTracker {
        width: 1fr;
        padding: 0 1;
    }
    .step-item {
        padding: 0 1;
        margin: 0;
    }
    .step-pending {
        color: $text-muted;
    }
    .step-running {
        color: #00BCD4;
    }
    .step-success {
        color: #4CAF50;
    }
    .step-error {
        color: #F44336;
    }
    .step-icon {
        width: 2;
        text-align: center;
    }
    .step-icon.pulse {
        animation: pulse 1.5s infinite alternate;
    }
    @keyframes pulse {
        0% { opacity: 0.5; }
        100% { opacity: 1; }
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._steps: list[StepInfo] = []
        self._step_widgets: dict[str, Horizontal] = {}  # 缓存步骤 widget
        self._initialized = False

    def compose(self) -> ComposeResult:
        """初始化组件 (首次渲染)"""
        # 初始为空，步骤通过 add_step 动态添加
        yield from []

    def add_step(self, name: str, status: str = "pending", message: str = "") -> None:
        """添加步骤 (Delta Rendering: 增量挂载)"""
        step = StepInfo(name=name, status=status, message=message, timestamp=time.time())
        self._steps.append(step)
        self._create_step_widget(step)

    def update_step(self, name: str, status: str, message: str = "") -> None:
        """更新步骤状态 (Delta Rendering: 只更新变化的部分)"""
        for step in self._steps:
            if step.name == name:
                step.status = status
                step.message = message

                # 只更新变化的 widget，不重绘整个面板
                if name in self._step_widgets:
                    widget = self._step_widgets[name]
                    self._update_step_widget(widget, step)
                break

    def _create_step_widget(self, step: StepInfo) -> None:
        """创建步骤 widget (增量挂载)"""
        icon_map = {
            "pending": "○",
            "running": "◉",
            "success": "✓",
            "error": "✗",
        }
        icon = icon_map.get(step.status, "·")

        status_class = f"step-{step.status}"
        icon_class = "step-icon"
        if step.status == "running":
            icon_class += " pulse"

        icon_label = Label(icon, classes=icon_class)
        text_label = Label(f"{step.name}", classes=f"step-item {status_class}")

        row = Horizontal(
            icon_label,
            text_label,
            classes="step-row",
            id=f"step-row-{step.name}",
        )

        if step.message:
            msg_label = Label(f" — {step.message[:40]}", classes="step-message")
            row.mount(msg_label)

        self._step_widgets[step.name] = row
        try:
            self.mount(row)
            self.scroll_end(animate=True)
        except Exception:
            pass

    def _update_step_widget(self, widget: Horizontal, step: StepInfo) -> None:
        """更新步骤 widget (Delta: 只更新变化的属性)"""
        # 更新状态类
        widget.remove_class("step-pending", "step-running", "step-success", "step-error")
        widget.add_class(f"step-{step.status}")

        # 更新图标 (如果有变化)
        icon_map = {
            "pending": "○",
            "running": "◉",
            "success": "✓",
            "error": "✗",
        }
        icon = icon_map.get(step.status, "·")

        # 更新图标 label
        try:
            icon_label = widget.query_one(".step-icon", Label)
            icon_label.update(icon)

            # 添加/移除脉冲动画
            icon_label.remove_class("pulse")
            if step.status == "running":
                icon_label.add_class("pulse")
        except Exception:
            pass

        # 更新消息
        if step.message:
            try:
                msg_label = widget.query_one(".stepmessage", Label)
                msg_label.update(f" — {step.message[:40]}")
            except Exception:
                # 消息 label 不存在，创建它
                msg_label = Label(f" — {step.message[:40]}", classes="stepmessage")
                with contextlib.suppress(Exception):
                    widget.mount(msg_label)


__all__ = ["StepTracker"]
