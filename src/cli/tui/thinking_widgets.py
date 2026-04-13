"""ThinkingCanvas Textual 组件

组件:
    RAGHeatmapWidget: RAG 引用热点图
    ExecutionFlowWidget: 执行流全息投影

用法:
    from src.cli.tui.thinking_widgets import RAGHeatmapWidget, ExecutionFlowWidget
"""
from __future__ import annotations

import logging
from typing import Any

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widgets import Static

from .thinking_models import (
    HLINE,
    LJUNCT_EXT,
    STATE_ICONS,
    VBAR_SEP,
    ExecutionStep,
    RAGCitation,
    _conf_color_icon,
    _heat_bar,
    _render_sparkline,
    _state_color,
    _step_type_color,
    _weight_color_hex,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RAGHeatmapWidget: RAG 引用热点图 (Textual)
# ---------------------------------------------------------------------------


class RAGHeatmapWidget(VerticalScroll):
    """RAG 引用热点图 — Textual 版本

    实时展示当前正在阅读的代码块在 GraphRAG 中的权重分布。
    """

    DEFAULT_CSS = """
    RAGHeatmapWidget {
        width: 1fr;
        height: auto;
        max-height: 18;
        padding: 0 1;
        background: rgba(15, 20, 30, 0.5);
        border: solid rgba(100, 120, 180, 0.25);
    }
    RAGHeatmapWidget .heatmap-title {
        text-style: bold;
        color: #00BCD4;
        padding: 0 1;
    }
    RAGHeatmapWidget .heatmap-body {
        font-family: monospace;
        font-size: 0.8em;
        padding: 0 1;
    }
    """

    citations: reactive[list[RAGCitation]] = reactive([])

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._spark_history: list[float] = []

    def compose(self) -> ComposeResult:
        yield Static("RAG Heatmap", classes="heatmap-title")
        yield Static("", classes="heatmap-body", id="heatmap-body")

    def push_citations(self, citations: list[RAGCitation]) -> None:
        """推送一批新的 RAG 引用"""
        self.citations = sorted(citations, key=lambda c: c.weight, reverse=True)
        if citations:
            max_w = max(c.weight for c in citations)
            self._spark_history.append(max_w)
            self._spark_history = self._spark_history[-20:]

    def clear(self) -> None:
        self.citations = []
        self._spark_history.clear()

    def watch_citations(self, _value: list[RAGCitation]) -> None:
        """响应式刷新"""
        self._refresh()

    def _refresh(self) -> None:
        try:
            body = self.query_one("#heatmap-body", Static)
            lines = self._render()
            body.update("\n".join(lines))
        except Exception as e:
            log.debug("RAGHeatmapWidget._refresh failed: %s", e)

    def _render(self) -> list[str]:
        lines: list[str] = []

        if self._spark_history:
            spark = _render_sparkline(self._spark_history, width=24)
            lines.append(f"  权重趋势: {spark}")

        if not self.citations:
            lines.append("")
            lines.append("  [dim]暂无引用数据[/]")
            return lines

        lines.append("")
        lines.append(f"  {'权重':^6} {'置信度':^6} {'符号':<24} {'关系':<10} 位置")
        lines.append("  " + HLINE * 72)

        for c in self.citations:
            icon = _conf_color_icon(c.weight)
            bar = _heat_bar(c.weight)
            location = f"{c.file_path.split('/')[-1]}:{c.line}" if c.line else c.file_path.split("/")[-1]
            rel = c.relation or "\u2014"
            sym = c.symbol_name[:22]
            lines.append(
                f"  {icon} {c.weight:.2f}   {c.confidence:.2f}    {sym:<24} {rel:<10}  {location}"
            )
            lines.append(f"     [{_weight_color_hex(c.weight)}]{bar}[/]")

        return lines


# ---------------------------------------------------------------------------
# ExecutionFlowWidget: 执行流全息投影 (Textual)
# ---------------------------------------------------------------------------


class ExecutionFlowWidget(VerticalScroll):
    """执行流全息投影 — Textual 版本

    可视化 ``goal -> thought -> tool_call -> observation -> recovery`` 全链路。
    """

    DEFAULT_CSS = """
    ExecutionFlowWidget {
        width: 1fr;
        height: auto;
        max-height: 24;
        padding: 0 1;
        background: rgba(10, 15, 25, 0.6);
        border: solid rgba(157, 75, 219, 0.3);
    }
    ExecutionFlowWidget .flow-title {
        text-style: bold;
        color: #9D4BDB;
        padding: 0 1;
    }
    ExecutionFlowWidget .flow-body {
        font-family: monospace;
        font-size: 0.8em;
        padding: 0 1;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._steps: dict[int, ExecutionStep] = {}
        self._next_step_id: int = 0

    def compose(self) -> ComposeResult:
        yield Static("Execution Flow", classes="flow-title")
        yield Static("", classes="flow-body", id="flow-body")

    def add_step(self, **kwargs: Any) -> int:
        """添加执行步骤"""
        sid = self._next_step_id
        self._next_step_id += 1
        step = ExecutionStep(step_id=sid, **kwargs)
        self._steps[sid] = step
        if step.parent_id is not None and step.parent_id in self._steps:
            self._steps[step.parent_id].children.append(sid)
        self._refresh()
        return sid

    def update_step(self, step_id: int, **kwargs: Any) -> bool:
        """更新步骤状态"""
        if step_id not in self._steps:
            return False
        step = self._steps[step_id]
        for key, val in kwargs.items():
            setattr(step, key, val)
        self._refresh()
        return True

    def clear(self) -> None:
        self._steps.clear()
        self._next_step_id = 0
        self._refresh()

    def _refresh(self) -> None:
        try:
            body = self.query_one("#flow-body", Static)
            lines = self._render()
            body.update("\n".join(lines))
            self.scroll_end(animate=True)
        except Exception as e:
            log.debug("ExecutionFlowWidget._refresh failed: %s", e)

    def _render(self) -> list[str]:
        lines: list[str] = []
        roots = [s for s in self._steps.values() if s.parent_id is None]
        if not roots:
            lines.append("  [dim]等待执行流...[/]")
            return lines
        for root in roots:
            self._render_node(root, lines, depth=0)
        return lines

    def _render_node(self, step: ExecutionStep, lines: list[str], depth: int) -> None:
        from .thinking_models import STEP_ICONS

        indent = "  " * depth
        type_icon = STEP_ICONS.get(step.step_type, "\u00b7")
        state_icon = STATE_ICONS.get(step.state, "\u00b7")
        color = _step_type_color(step.step_type)
        sc = _state_color(step.state)
        conf_icon = _conf_color_icon(step.confidence)
        elapsed = f"{step.elapsed_ms:.0f}ms" if step.elapsed_ms > 0 else ""
        detail = f"  [dim]({step.detail})[/]" if step.detail else ""

        lines.append(
            f"{indent}{type_icon} [{sc}]{state_icon}[/] "
            f"[{color}]{step.label}[/]{detail}"
        )

        meta: list[str] = []
        if step.tool_name:
            meta.append(f"tool=[bold {color}]{step.tool_name}[/]")
        if step.confidence > 0:
            meta.append(f"{conf_icon}{step.confidence:.0%}")
        if elapsed:
            meta.append(f"[dim]\u23f1 {elapsed}[/]")

        if meta:
            lines.append(f"{indent}    {VBAR_SEP.join(meta)}")

        for c in step.rag_citations[:3]:
            cbar = _heat_bar(c.weight, width=6)
            lines.append(
                f"{indent}    {LJUNCT_EXT}{c.symbol_name} "
                f"[{_weight_color_hex(c.weight)}]{cbar}[/] {c.weight:.2f}"
            )

        for cid in step.children:
            if cid in self._steps:
                self._render_node(self._steps[cid], lines, depth=depth + 1)
