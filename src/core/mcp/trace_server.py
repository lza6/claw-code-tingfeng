"""MCP 服务器: Trace Server (执行追踪)

参考: oh-my-codex-main/src/mcp/trace_server.ts
记录和分析 Agent 执行轨迹、工具调用、事件流。

数据: .clawd/trace/
    traces/     追踪数据 (JSON)
    spans/      跨度数据
    events/     事件日志
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Span:
    """追踪跨度"""
    trace_id: str
    span_id: str
    parent_id: str | None = None
    name: str = ""
    kind: str = "AGENT"  # AGENT, TOOL, LLM, WORKFLOW
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)

    def duration_ms(self) -> float | None:
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return None


class TraceServer:
    """MCP Trace Server - OpenTelemetry 风格的追踪"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.trace_dir = project_root / ".clawd" / "trace"
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        (self.trace_dir / "spans").mkdir(exist_ok=True)
        (self.trace_dir / "traces").mkdir(exist_ok=True)
        (self.trace_dir / "events").mkdir(exist_ok=True)

        self.active_spans: dict[str, Span] = {}
        self.root_trace: str | None = None

    def start_trace(self, name: str, trace_id: str | None = None) -> str:
        """开始新的追踪"""
        import uuid

        trace_id = trace_id or f"trace_{uuid.uuid4().hex[:12]}"
        span_id = f"span_{uuid.uuid4().hex[:12]}"

        span = Span(
            trace_id=trace_id,
            span_id=span_id,
            name=name,
            start_time=time.time(),
        )
        self.active_spans[span_id] = span
        self.root_trace = trace_id

        logger.debug(f"Started trace: {trace_id} (span: {span_id})")
        return span_id

    def start_span(
        self,
        name: str,
        parent_id: str | None = None,
        kind: str = "AGENT",
        attributes: dict | None = None,
    ) -> str:
        """开始新跨度"""
        import uuid

        span_id = f"span_{uuid.uuid4().hex[:12]}"

        span = Span(
            trace_id=self.root_trace or span_id,
            span_id=span_id,
            parent_id=parent_id,
            name=name,
            kind=kind,
            start_time=time.time(),
            attributes=attributes or {},
        )
        self.active_spans[span_id] = span
        return span_id

    def end_span(
        self,
        span_id: str,
        status: str = "OK",
        message: str = "",
    ) -> None:
        """结束跨度"""
        span = self.active_spans.get(span_id)
        if span:
            span.end_time = time.time()
            span.attributes["status"] = status
            if message:
                span.attributes["message"] = message

            # 持久化
            self._persist_span(span)
            del self.active_spans[span_id]

    def add_event(
        self,
        span_id: str,
        name: str,
        attributes: dict | None = None,
    ) -> None:
        """添加事件到跨度"""
        span = self.active_spans.get(span_id)
        if span:
            event = {
                "name": name,
                "timestamp": time.time(),
                "attributes": attributes or {},
            }
            span.events.append(event)

    def _persist_span(self, span: Span) -> None:
        """持久化跨度数据"""
        data = {
            "trace_id": span.trace_id,
            "span_id": span.span_id,
            "parent_id": span.parent_id,
            "name": span.name,
            "kind": span.kind,
            "start_time": span.start_time,
            "end_time": span.end_time,
            "duration_ms": span.duration_ms(),
            "attributes": span.attributes,
            "events": span.events,
        }
        path = self.trace_dir / "spans" / f"{span.span_id}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def get_trace(self, trace_id: str) -> list[dict]:
        """获取追踪的所有跨度"""
        spans = []
        for p in (self.trace_dir / "spans").glob("*.json"):
            data = json.loads(p.read_text())
            if data.get("trace_id") == trace_id:
                spans.append(data)
        return sorted(spans, key=lambda s: s["start_time"])

    def get_recent_traces(self, limit: int = 10) -> list[dict[str, Any]]:
        """获取最近的追踪"""
        trace_files = list((self.trace_dir / "traces").glob("*.json"))
        trace_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        traces = []
        for p in trace_files[:limit]:
            traces.append(json.loads(p.read_text()))
        return traces

    def export_trace(self, trace_id: str, format: str = "json") -> str:
        """导出追踪数据 (支持 Jaeger/OTLP 格式)"""
        if format == "json":
            spans = self.get_trace(trace_id)
            return json.dumps(spans, indent=2)
        # 可以扩展为 jaeger-json 等
        raise ValueError(f"Unsupported format: {format}")

    def summarize_trace(self, trace_id: str) -> dict[str, Any]:
        """生成追踪摘要"""
        spans = self.get_trace(trace_id)
        if not spans:
            return {"error": "Trace not found"}

        total_duration = sum(s.get("duration_ms", 0) or 0 for s in spans)
        by_kind = {}
        for span in spans:
            kind = span.get("kind", "UNKNOWN")
            by_kind[kind] = by_kind.get(kind, 0) + 1

        return {
            "trace_id": trace_id,
            "span_count": len(spans),
            "total_duration_ms": total_duration,
            "by_kind": by_kind,
            "spans": [
                {
                    "name": s["name"],
                    "kind": s["kind"],
                    "duration_ms": s.get("duration_ms"),
                }
                for s in spans
            ],
        }


def create_trace_server(project_root: Path | None = None) -> TraceServer:
    """工厂函数: 创建 Trace Server"""
    if project_root is None:
        project_root = Path.cwd()
    return TraceServer(project_root)


# MCP 工具
TRACE_SERVER_TOOLS = {
    "start_trace": {
        "name": "start_trace",
        "description": "Start a new execution trace",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Trace name"},
            },
            "required": ["name"],
        },
    },
    "start_span": {
        "name": "start_span",
        "description": "Start a new span within a trace",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "parent_id": {"type": "string"},
                "kind": {"type": "string", "enum": ["AGENT", "TOOL", "LLM", "WORKFLOW"]},
                "attributes": {"type": "object"},
            },
            "required": ["name"],
        },
    },
    "end_span": {
        "name": "end_span",
        "description": "End a span",
        "inputSchema": {
            "type": "object",
            "properties": {
                "span_id": {"type": "string"},
                "status": {"type": "string", "default": "OK"},
            },
            "required": ["span_id"],
        },
    },
    "get_trace": {
        "name": "get_trace",
        "description": "Get trace by ID",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace_id": {"type": "string"},
            },
            "required": ["trace_id"],
        },
    },
    "summarize_trace": {
        "name": "sumsummarize_trace",
        "description": "Summarize a trace",
        "inputSchema": {
            "type": "object",
            "properties": {"trace_id": {"type": "string"}},
            "required": ["trace_id"],
        },
    },
}

__all__ = [
    "TRACE_SERVER_TOOLS",
    "Span",
    "TraceServer",
    "create_trace_server",
]
