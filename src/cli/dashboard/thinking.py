"""Dashboard Thinking Canvas Widgets — 思维流视窗组件

包含:
- ReasoningChain: 推理链可视化
- ExecutionTree: 可视化执行树
- ResourceMonitorChart: 实时资源监控图表
- ThinkingCanvas: 思维画布 (整合以上三个)
"""
from __future__ import annotations

import contextlib
from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label

# 导入数据模型 (从 dashboard_widgets 模块)
from ..dashboard_widgets import ReasoningStep, ResourceMetrics

# ============================================================================
# Reasoning Chain
# ============================================================================

class ReasoningChain(Vertical):
    """推理链可视化 — 展示 Agent 的思维流

    特点:
    - 实时展示推理步骤
    - 每个步骤显示: 思维、工具、置信度
    - 置信度演变曲线
    """

    DEFAULT_CSS = """
    ReasoningChain {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
    }
    .reasoning-step {
        padding: 0 1;
        margin: 0;
    }
    .step-pending { color: $text-muted; }
    .step-running { color: #00BCD4; }
    .step-success { color: #4CAF50; }
    .step-error { color: #F44336; }
    .step-confidence {
        color: $text-muted;
        text-align: right;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._steps: list[ReasoningStep] = []
        self._step_widgets: dict[int, Horizontal] = {}

    def add_step(self, step: ReasoningStep) -> None:
        """添加推理步骤"""
        self._steps.append(step)
        self._create_step_widget(step)

    def update_step(self, step_id: int, status: str, confidence: float | None = None) -> None:
        """更新推理步骤"""
        for step in self._steps:
            if step.step_id == step_id:
                step.status = status
                if confidence is not None:
                    step.confidence = confidence
                if step_id in self._step_widgets:
                    self._update_step_widget(self._step_widgets[step_id], step)
                break

    def _create_step_widget(self, step: ReasoningStep) -> None:
        """创建步骤 widget"""
        status_class = f"step-{step.status}"
        icon = {"pending": "○", "running": "◉", "success": "✓", "error": "✗"}.get(step.status, "·")

        thought_text = step.thought[:60] + ("..." if len(step.thought) > 60 else "")
        tool_text = f" [{step.tool_name}]" if step.tool_name else ""

        content_label = Label(f"{icon} Step {step.step_id}: {thought_text}{tool_text}", classes=f"reasoning-step {status_class}")
        conf_label = Label(f"{int(step.confidence * 100)}%", classes="step-confidence")

        row = Horizontal(content_label, conf_label)
        self._step_widgets[step.step_id] = row

        try:
            self.mount(row)
            self.scroll_end(animate=True)
        except Exception:
            pass

    def _update_step_widget(self, widget: Horizontal, step: ReasoningStep) -> None:
        """更新步骤 widget"""
        widget.remove_class("step-pending", "step-running", "step-success", "step-error")
        widget.add_class(f"step-{step.status}")

        try:
            content_label = widget.children[0]
            icon = {"pending": "○", "running": "◉", "success": "✓", "error": "✗"}.get(step.status, "·")
            thought_text = step.thought[:60] + ("..." if len(step.thought) > 60 else "")
            tool_text = f" [{step.tool_name}]" if step.tool_name else ""
            content_label.update(f"{icon} Step {step.step_id}: {thought_text}{tool_text}")

            conf_label = widget.children[1]
            conf_label.update(f"{int(step.confidence * 100)}%")
        except Exception:
            pass


# ============================================================================
# Execution Tree
# ============================================================================

class ExecutionTree(Vertical):
    """可视化执行树 — Unicode 树状图展示多步任务的父子依赖关系

    显示效果:
    └── Task: "修复登录模块"
        ├── ✓ Step 1: 分析问题 (0.95)
        │   └── Tool: grep (0.85)
        ├── ◉ Step 2: 生成修复方案 (0.72)
        │   ├── Tool: read_file (0.90)
        │   └── Tool: write_file (0.65)
        └── ○ Step 3: 验证修复 (0.00)
    """

    DEFAULT_CSS = """
    ExecutionTree {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
        font-family: monospace;
    }
    .tree-node {
        padding: 0;
        margin: 0;
    }
    .tree-root { text-style: bold; color: #00BCD4; }
    .tree-success { color: #4CAF50; }
    .tree-running { color: #FFC107; }
    .tree-error { color: #F44336; }
    .tree-pending { color: $text-muted; }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._root_task: str = ""
        self._steps: list[ReasoningStep] = []

    def set_root_task(self, task: str) -> None:
        """设置根任务"""
        self._root_task = task
        self._refresh_display()

    def add_step(self, step: ReasoningStep) -> None:
        """添加步骤到树"""
        self._steps.append(step)
        self._refresh_display()

    def update_step(self, step_id: int, status: str, confidence: float | None = None) -> None:
        """更新步骤"""
        for step in self._steps:
            if step.step_id == step_id:
                step.status = status
                if confidence is not None:
                    step.confidence = confidence
                break
        self._refresh_display()

    def _refresh_display(self) -> None:
        """刷新显示 (优化版: 仅在必要时增量更新)"""
        # --- RTK: 虚拟化/增量渲染逻辑 (借鉴 RTK ui.rs) ---
        if not self._root_task:
            with contextlib.suppress(Exception):
                self.remove_children()
            return

        # 简单的增量更新策略: 如果子组件数量已经很多，采取延迟加载或截断
        # 这里实现一个简单的虚拟化截断 (保持最近 50 个步骤)
        if len(self._steps) > 50:
            self._steps = self._steps[-50:]

        with contextlib.suppress(Exception):
            self.remove_children()

        # 根任务
        root_label = Label(f"└── Task: {self._root_task}", classes="tree-node tree-root")
        with contextlib.suppress(Exception):
            self.mount(root_label)

        # 排序步骤
        sorted_steps = sorted(self._steps, key=lambda s: s.step_id)

        for i, step in enumerate(sorted_steps):
            is_last = (i == len(sorted_steps) - 1)
            prefix = "    └──" if is_last else "    ├──"

            icon = {"pending": "○", "running": "◉", "success": "✓", "error": "✗"}.get(step.status, "·")
            status_class = f"tree-{step.status}"

            line_text = f"{prefix} {icon} Step {step.step_id}: {step.thought[:40]} ({int(step.confidence * 100)}%)"
            line_label = Label(line_text, classes=f"tree-node {status_class}")
            with contextlib.suppress(Exception):
                self.mount(line_label)

            # 工具信息
            if step.tool_name:
                tool_prefix = "    │   └──" if is_last else "    │   ├──"
                tool_text = f"{tool_prefix} Tool: {step.tool_name}"
                tool_label = Label(tool_text, classes="tree-node tree-pending")
                with contextlib.suppress(Exception):
                    self.mount(tool_label)

        with contextlib.suppress(Exception):
            self.scroll_end(animate=True)


# ============================================================================
# Resource Monitor Chart
# ============================================================================

class ResourceMonitorChart(Vertical):
    """实时资源监控图表 — Token 消耗、延迟、内存占用

    特点:
    - ASCII 折线图展示趋势
    - 高频动态更新 (每 500ms)
    - 多指标对比
    """

    DEFAULT_CSS = """
    ResourceMonitorChart {
        width: 1fr;
        height: auto;
        padding: 0 1;
    }
    .chart-title {
        text-style: bold;
        padding: 0 1;
    }
    .chart-data {
        font-family: monospace;
        font-size: 0.8em;
    }
    .metric-row {
        height: auto;
        padding: 0;
        margin: 0;
    }
    .metric-label {
        color: $text-muted;
        width: 12;
    }
    .metric-value {
        color: $text;
        width: 1fr;
    }
    """

    CHART_WIDTH: ClassVar[int] = 40
    CHART_HEIGHT: ClassVar[int] = 5

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._metrics: list[ResourceMetrics] = []
        self._max_history = 40

    def add_metric(self, metric: ResourceMetrics) -> None:
        """添加指标数据"""
        self._metrics.append(metric)
        if len(self._metrics) > self._max_history:
            self._metrics = self._metrics[-self._max_history:]
        self._refresh_display()

    def _refresh_display(self) -> None:
        """刷新显示"""
        with contextlib.suppress(Exception):
            self.remove_children()

        if not self._metrics:
            return

        # 渲染指标行
        metrics_to_show = [
            ("Tokens In", [m.tokens_input for m in self._metrics]),
            ("Tokens Out", [m.tokens_output for m in self._metrics]),
            ("Latency", [m.latency_ms for m in self._metrics]),
            ("Memory", [m.memory_mb for m in self._metrics]),
        ]

        for label, values in metrics_to_show:
            if not values or all(v == 0 for v in values):
                continue

            # 归一化到 0-1
            max_val = max(values) if max(values) > 0 else 1
            normalized = [v / max_val for v in values]

            # 渲染折线
            chart_line = self._render_sparkline(normalized)

            row = Horizontal(
                Label(f"{label}:", classes="metric-label"),
                Label(f"{values[-1]:.0f}", classes="metric-value"),
                Label(chart_line, classes="chart-data"),
                classes="metric-row",
            )
            with contextlib.suppress(Exception):
                self.mount(row)

    def _render_sparkline(self, values: list[float]) -> str:
        """渲染迷你折线图"""
        if not values:
            return ""

        # 使用 Unicode 块字符
        spark_chars = "▁▂▃▄▅▆▇█"
        result = ""

        for v in values[-self.CHART_WIDTH:]:
            idx = int(v * (len(spark_chars) - 1))
            idx = max(0, min(idx, len(spark_chars) - 1))
            result += spark_chars[idx]

        return result


# ============================================================================
# Thinking Canvas (整合)
# ============================================================================

class ThinkingCanvas(Vertical):
    """思维画布 — 整合推理链 + 执行树 + 资源监控

    布局:
    ┌──────────────────────────────────┐
    │ 🧠 Thinking Canvas               │
    ├──────────────────────────────────┤
    │ Reasoning Chain:                 │
    │ ✓ Step 1: Analyze problem (95%)  │
    │ ◉ Step 2: Generate fix (72%)     │
    │ ○ Step 3: Verify fix (0%)        │
    ├──────────────────────────────────┤
    │ Execution Tree:                  │
    │ └── Task: "Fix login module"    │
    │     ├── ✓ Step 1 (0.95)         │
    │     │   └── Tool: grep (0.85)   │
    │     └── ◉ Step 2 (0.72)         │
    ├──────────────────────────────────┤
    │ Resource Monitor:                │
    │ Tokens In:  1234 ▁▂▃▄▅▆▇█      │
    │ Latency:    45ms ▁▁▂▃▄▅▅▆       │
    └──────────────────────────────────┘
    """

    DEFAULT_CSS = """
    ThinkingCanvas {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
    }
    #canvas-title {
        text-style: bold;
        padding: 0 1;
    }
    #reasoning-container {
        height: 35%;
        border: solid $primary;
        title: "Reasoning Chain";
    }
    #tree-container {
        height: 35%;
        border: solid $primary;
        title: "Execution Tree";
    }
    #resource-container {
        height: 30%;
        border: solid $primary;
        title: "Resource Monitor";
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._next_step_id = 1

    def compose(self) -> ComposeResult:
        yield Label("🧠 Thinking Canvas", id="canvas-title")
        yield ReasoningChain(id="reasoning-chain")
        yield ExecutionTree(id="execution-tree")
        yield ResourceMonitorChart(id="resource-monitor")

    def add_reasoning_step(self, thought: str, tool_name: str = "", tool_args: dict | None = None, confidence: float = 0.0) -> int:
        """添加推理步骤"""
        step = ReasoningStep(
            step_id=self._next_step_id,
            thought=thought,
            tool_name=tool_name,
            tool_args=tool_args or {},
            confidence=confidence,
        )
        self._next_step_id += 1

        reasoning = self.query_one("#reasoning-chain", ReasoningChain)
        reasoning.add_step(step)

        tree = self.query_one("#execution-tree", ExecutionTree)
        tree.add_step(step)

        return step.step_id

    def update_step(self, step_id: int, status: str, confidence: float | None = None) -> None:
        """更新步骤状态"""
        reasoning = self.query_one("#reasoning-chain", ReasoningChain)
        reasoning.update_step(step_id, status, confidence)

        tree = self.query_one("#execution-tree", ExecutionTree)
        tree.update_step(step_id, status, confidence)

    def set_root_task(self, task: str) -> None:
        """设置根任务"""
        tree = self.query_one("#execution-tree", ExecutionTree)
        tree.set_root_task(task)

    def add_resource_metric(self, metric: ResourceMetrics) -> None:
        """添加资源指标"""
        monitor = self.query_one("#resource-monitor", ResourceMonitorChart)
        monitor.add_metric(metric)


__all__ = [
    "ExecutionTree",
    "ReasoningChain",
    "ResourceMonitorChart",
    "ThinkingCanvas",
]
