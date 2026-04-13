"""ThinkingCanvas 主复合组件

组件:
    ThinkingCanvas: 复合型思考可视化面板 (Textual)
    ThinkingCanvasRich: 纯 Rich 独立模式

用法:
    from src.cli.tui.thinking_canvas import ThinkingCanvas, ThinkingCanvasRich
"""
from __future__ import annotations

import logging
from typing import Any

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical

from .thinking_models import (
    LJUNCT_EXT,
    STATE_ICONS,
    STEP_ICONS,
    VBAR_SEP,
    ExecutionStep,
    RAGCitation,
    StepState,
    _conf_color_icon,
    _heat_bar,
    _render_sparkline,
    _state_color,
    _step_type_color,
    _weight_color_hex,
)
from .thinking_widgets import ExecutionFlowWidget, RAGHeatmapWidget

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ThinkingCanvas: 思考过程可视化 (Textual 复合组件)
# ---------------------------------------------------------------------------


class ThinkingCanvas(Vertical):
    """思考过程可视化面板 — Textual 版本

    整合 RAG 热点 + 执行流 + 多路推理路径。
    """

    DEFAULT_CSS = """
    ThinkingCanvas {
        width: 1fr;
        height: auto;
        padding: 0;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._rag_heatmap: RAGHeatmapWidget | None = None
        self._exec_flow: ExecutionFlowWidget | None = None

    def compose(self) -> ComposeResult:
        self._rag_heatmap = RAGHeatmapWidget(id="rag-heatmap")
        yield self._rag_heatmap
        self._exec_flow = ExecutionFlowWidget(id="execution-flow")
        yield self._exec_flow

    # -- RAG --

    def push_rag_citations(self, citations: list[RAGCitation]) -> None:
        """推送 RAG 引用数据"""
        if self._rag_heatmap:
            self._rag_heatmap.push_citations(citations)

    def clear_rag(self) -> None:
        if self._rag_heatmap:
            self._rag_heatmap.clear()

    # -- 执行流 --

    def add_step(self, **kwargs: Any) -> int:
        """添加执行步骤"""
        if self._exec_flow:
            return self._exec_flow.add_step(**kwargs)
        return -1

    def update_step(self, step_id: int, **kwargs: Any) -> bool:
        """更新步骤"""
        if self._exec_flow:
            return self._exec_flow.update_step(step_id, **kwargs)
        return False

    def clear_flow(self) -> None:
        if self._exec_flow:
            self._exec_flow.clear()

    # -- 便捷方法 --

    def add_thought(self, label: str, parent: int | None = None,
                    confidence: float = 0.0, detail: str = "") -> int:
        """添加思考节点"""
        return self.add_step(
            step_type="thought",
            label=label,
            detail=detail,
            state=StepState.RUNNING if parent is None else StepState.PENDING,
            confidence=confidence,
            parent_id=parent,
        )

    def add_tool_call(self, label: str, tool_name: str,
                      parent: int | None = None, confidence: float = 0.0) -> int:
        """添加工具调用节点"""
        return self.add_step(
            step_type="tool_call",
            label=label,
            state=StepState.RUNNING,
            confidence=confidence,
            tool_name=tool_name,
            parent_id=parent,
        )

    def add_observation(self, label: str, parent: int | None = None,
                        confidence: float = 0.0) -> int:
        """添加观察节点"""
        return self.add_step(
            step_type="observation",
            label=label,
            state=StepState.SUCCESS,
            confidence=confidence,
            parent_id=parent,
        )

    def add_recovery(self, label: str, parent: int | None = None,
                     detail: str = "") -> int:
        """添加恢复节点"""
        return self.add_step(
            step_type="recovery",
            label=label,
            detail=detail,
            state=StepState.RECOVERING,
            parent_id=parent,
        )


# ---------------------------------------------------------------------------
# ThinkingCanvasRich (纯 Rich 独立模式)
# ---------------------------------------------------------------------------


class ThinkingCanvasRich:
    """纯 Rich 渲染版本 — 无需 Textual

    适用于已用 ``rich.live.Live`` 的项目（如 ``src/cli/tui.py`` 的 ``LiveHUD``）。
    """

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console(force_terminal=True)
        self._live: Live | None = None
        self._rag_citations: list[RAGCitation] = []
        self._spark_history: list[float] = []
        self._steps: dict[int, ExecutionStep] = {}
        self._next_id: int = 0

    def start(self) -> None:
        """启动 Live 渲染"""
        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=4,
            screen=False,
        )
        self._live.start()

    def stop(self) -> None:
        """停止 Live 渲染"""
        if self._live:
            self._live.stop()
            self._live = None

    def _refresh(self) -> None:
        if self._live and self._live.is_started:
            self._live.update(self._render())

    # -- 公共接口 --

    def push_rag_citations(self, citations: list[RAGCitation]) -> None:
        self._rag_citations = sorted(citations, key=lambda c: c.weight, reverse=True)
        if citations:
            self._spark_history.append(max(c.weight for c in citations))
            self._spark_history = self._spark_history[-20:]
        self._refresh()

    def clear_rag(self) -> None:
        self._rag_citations.clear()
        self._spark_history.clear()
        self._refresh()

    def add_step(self, **kwargs: Any) -> int:
        sid = self._next_id
        self._next_id += 1
        step = ExecutionStep(step_id=sid, **kwargs)
        self._steps[sid] = step
        if step.parent_id is not None and step.parent_id in self._steps:
            self._steps[step.parent_id].children.append(sid)
        self._refresh()
        return sid

    def update_step(self, step_id: int, **kwargs: Any) -> bool:
        if step_id not in self._steps:
            return False
        step = self._steps[step_id]
        for k, v in kwargs.items():
            setattr(step, k, v)
        self._refresh()
        return True

    def clear_flow(self) -> None:
        self._steps.clear()
        self._next_id = 0
        self._refresh()

    def add_thought(self, label: str, parent: int | None = None,
                    confidence: float = 0.0, detail: str = "") -> int:
        return self.add_step(
            step_type="thought",
            label=label,
            detail=detail,
            state=StepState.RUNNING,
            confidence=confidence,
            parent_id=parent,
        )

    def add_tool_call(self, label: str, tool_name: str,
                      parent: int | None = None, confidence: float = 0.0) -> int:
        return self.add_step(
            step_type="tool_call",
            label=label,
            state=StepState.RUNNING,
            confidence=confidence,
            tool_name=tool_name,
            parent_id=parent,
        )

    def add_observation(self, label: str, parent: int | None = None,
                        confidence: float = 0.0) -> int:
        return self.add_step(
            step_type="observation",
            label=label,
            state=StepState.SUCCESS,
            confidence=confidence,
            parent_id=parent,
        )

    def add_recovery(self, label: str, parent: int | None = None,
                     detail: str = "") -> int:
        return self.add_step(
            step_type="recovery",
            label=label,
            detail=detail,
            state=StepState.RECOVERING,
            parent_id=parent,
        )

    # -- 渲染 --

    def _render(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="rag", size=12),
            Layout(name="flow"),
        )
        layout["rag"].update(self._render_rag())
        layout["flow"].update(self._render_flow())
        return layout

    def _render_rag(self) -> Panel:
        lines = [
            f"  {'权重':^8} {'置信度':^8} {'符号':<24} {'关系':<10} 位置",
            "  " + "\u2500" * 72,
        ]

        if self._spark_history:
            spark = _render_sparkline(self._spark_history, width=24)
            lines.insert(0, f"  权重趋势: {spark}")
            lines.insert(0, "")

        if not self._rag_citations:
            lines.append("")
            lines.append("  [dim]暂无引用数据[/]")
        else:
            for c in self._rag_citations:
                icon = _conf_color_icon(c.weight)
                bar = _heat_bar(c.weight)
                loc = c.file_path.split("/")[-1]
                loc += f":{c.line}" if c.line else ""
                rel = c.relation or "\u2014"
                sym = c.symbol_name[:22]
                lines.append(
                    f"  {icon} {c.weight:.2f}   {c.confidence:.2f}    {sym:<24} {rel:<10}  {loc}"
                )
                lines.append(f"     [{_weight_color_hex(c.weight)}]{bar}[/]")

        return Panel(
            Text.from_markup("\n".join(lines)),
            title="[bold cyan]RAG Heatmap",
            border_style="cyan",
        )

    def _render_flow(self) -> Panel:
        lines: list[str] = []
        roots = [s for s in self._steps.values() if s.parent_id is None]
        if not roots:
            lines.append("  [dim]等待执行流...[/]")
        else:
            for root in roots:
                lines.extend(self._render_flow_node(root, depth=0))

        return Panel(
            Text.from_markup("\n".join(lines)),
            title="[bold #9D4BDB]Execution Flow",
            border_style="#9D4BDB",
        )

    def _render_flow_node(self, step: ExecutionStep, depth: int) -> list[str]:
        indent = "  " * depth
        type_icon = STEP_ICONS.get(step.step_type, "\u00b7")
        state_icon = STATE_ICONS.get(step.state, "\u00b7")
        color = _step_type_color(step.step_type)
        sc = _state_color(step.state)
        conf_icon = _conf_color_icon(step.confidence)
        elapsed = f"{step.elapsed_ms:.0f}ms" if step.elapsed_ms > 0 else ""
        detail = f"  [dim]({step.detail})[/]" if step.detail else ""

        out = [
            f"{indent}{type_icon} [{sc}]{state_icon}[/] "
            f"[{color}]{step.label}[/]{detail}"
        ]

        meta: list[str] = []
        if step.tool_name:
            meta.append(f"tool=[bold {color}]{step.tool_name}[/]")
        if step.confidence > 0:
            meta.append(f"{conf_icon}{step.confidence:.0%}")
        if elapsed:
            meta.append(f"[dim]\u23f1 {elapsed}[/]")

        if meta:
            out.append(f"{indent}    {VBAR_SEP.join(meta)}")

        for c in step.rag_citations[:3]:
            cbar = _heat_bar(c.weight, width=6)
            out.append(
                f"{indent}    {LJUNCT_EXT}{c.symbol_name} "
                f"[{_weight_color_hex(c.weight)}]{cbar}[/] {c.weight:.2f}"
            )

        for cid in step.children:
            if cid in self._steps:
                out.extend(self._render_flow_node(self._steps[cid], depth=depth + 1))

        return out


# ---------------------------------------------------------------------------
# EventBus 监听器
# ---------------------------------------------------------------------------

# Re-export for backwards compatibility
__all__ = [
    "CONF_RANGES",
    "HLINE",
    "LJUNCT",
    "LJUNCT_EXT",
    "STATE_ICONS",
    # Constants
    "STEP_ICONS",
    "VBAR",
    "VBAR_SEP",
    "_STATE_COLORS",
    "_TYPE_COLORS",
    "ExecutionFlowWidget",
    "ExecutionStep",
    "RAGCitation",
    "RAGHeatmapWidget",
    "StepState",
    "ThinkingCanvas",
    "ThinkingCanvasRich",
    # Render utilities
    "_conf_color_icon",
    "_heat_bar",
    "_render_sparkline",
    "_state_color",
    "_step_type_color",
    "_weight_color_hex",
    "attach_event_bus_listeners",
]

# Also expose them at module level for backwards compatibility
from .thinking_models import (
    _STATE_COLORS,
    _TYPE_COLORS,
    CONF_RANGES,
    HLINE,
    LJUNCT,
    VBAR,
)


def attach_event_bus_listeners(canvas: ThinkingCanvas | ThinkingCanvasRich) -> None:
    """将 ThinkingCanvas 绑定到全局 EventBus

    自动订阅:
        - AGENT_TOOL_CALL_STARTED  -> add_tool_call
        - AGENT_STEP_STARTED       -> add_thought
        - RAG_SEARCH_COMPLETED     -> push_rag_citations
        - TOOL_EXEC_ERROR          -> add_recovery
    """
    from ..core.events import EventType, get_event_bus

    bus = get_event_bus()

    def _on_tool_started(event: Any) -> None:
        canvas.add_tool_call(
            label=f"Execute {event.data.get('tool_name', 'unknown')}",
            tool_name=str(event.data.get("tool_name", "")),
            confidence=event.data.get("confidence", 0.0),
        )

    def _on_step_started(event: Any) -> None:
        canvas.add_thought(
            label=str(event.data.get("goal", "")),
            confidence=event.data.get("confidence", 0.5),
            detail=str(event.data.get("phase", "")),
        )

    def _on_rag_search(event: Any) -> None:
        results = event.data.get("results", [])
        citations = [
            RAGCitation(
                symbol_name=str(r.get("symbol", "")),
                file_path=str(r.get("file_path", "")),
                weight=float(r.get("score", 0.0)),
                confidence=float(r.get("confidence", 0.0)),
            )
            for r in results[:10]
        ]
        if citations:
            canvas.push_rag_citations(citations)

    def _on_tool_error(event: Any) -> None:
        canvas.add_recovery(
            label=f"Tool error: {event.data.get('tool_name', '')}",
            detail=str(event.data.get("error", "")),
        )

    bus.subscribe(EventType.AGENT_TOOL_CALL_STARTED, _on_tool_started)
    bus.subscribe(EventType.AGENT_STEP_STARTED, _on_step_started)
    bus.subscribe(EventType.RAG_SEARCH_COMPLETED, _on_rag_search)
    bus.subscribe(EventType.TOOL_EXEC_ERROR, _on_tool_error)
