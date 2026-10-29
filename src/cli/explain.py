"""`clawd explain` —— 用中文讲清「这一轮它到底做了什么」

审计 P3 指出：CLI 没有 `explain/why` 这类"讲人话"入口，用户只能自己翻 JSONL 日志。
本模块**不调用 LLM**（零成本、可离线验证），只把会话存储里的事实摊开：

- 目标是什么、用了哪个模型、花了多少 token / 多少钱
- 调了哪些工具、各自成功还是失败
- 哪一步失败了（带原始错误片段）
- 最终答案原文（截断，便于核对）

设计原则：**没有记录就说没有记录**，不要用"看起来没问题"糊过去。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core import session_bridge
from ..utils.logger import get_logger

logger = get_logger(__name__)

#: 单个字段在终端里的展示上限（避免刷屏）
MAX_TEXT_CHARS = 800
#: 最多展示多少次工具调用
MAX_TOOLS = 20


def _text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


@dataclass
class ToolCall:
    name: str
    arguments: str = ""
    result: str = ""
    ok: bool | None = None  # None = 没有结果记录（不能算成功）

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "arguments": _text(self.arguments, 300),
            "result": _text(self.result, 300),
            "ok": self.ok,
        }


@dataclass
class Explanation:
    session_id: str
    title: str = ""
    status: str = ""
    provider: str = ""
    model: str = ""
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    message_count: int = 0
    tool_calls: list[ToolCall] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    final_answer: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def ok_tools(self) -> int:
        return sum(1 for t in self.tool_calls if t.ok is True)

    @property
    def failed_tools(self) -> int:
        return sum(1 for t in self.tool_calls if t.ok is False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "turns": self.turns,
            "tokens": {"input": self.input_tokens, "output": self.output_tokens},
            "cost": round(self.cost, 6),
            "message_count": self.message_count,
            "tools": [t.to_dict() for t in self.tool_calls[:MAX_TOOLS]],
            "tools_ok": self.ok_tools,
            "tools_failed": self.failed_tools,
            "failures": self.failures,
            "final_answer": _text(self.final_answer),
            "notes": self.notes,
        }

    def to_text(self) -> str:
        lines: list[str] = []
        lines.append(f"会话 {self.session_id}" + (f" — {_text(self.title, 60)}" if self.title else ""))
        lines.append(
            f"  状态: {self.status or '未知'} · 模型: "
            f"{(self.provider + '/') if self.provider else ''}{self.model or '未知'}"
            f" · 轮次: {self.turns} · 消息: {self.message_count}"
        )
        lines.append(
            f"  用量: 输入 {self.input_tokens} / 输出 {self.output_tokens} tokens"
            f" · 成本 ${self.cost:.4f}"
        )

        if self.tool_calls:
            lines.append(f"  工具调用 {len(self.tool_calls)} 次（成功 {self.ok_tools} / 失败 {self.failed_tools}）:")
            for call in self.tool_calls[:MAX_TOOLS]:
                mark = "ok" if call.ok else ("err" if call.ok is False else "?")
                lines.append(f"    [{mark}] {call.name} {_text(call.arguments, 160)}")
                if call.ok is False and call.result:
                    lines.append(f"          → {_text(call.result, 200)}")
            if len(self.tool_calls) > MAX_TOOLS:
                lines.append(f"    … 还有 {len(self.tool_calls) - MAX_TOOLS} 次未列出")
        else:
            lines.append("  工具调用: 没有记录（纯问答，或该引擎未记录工具调用）")

        if self.failures:
            lines.append("  失败/异常:")
            for item in self.failures[:5]:
                lines.append(f"    - {_text(item, 240)}")

        if self.final_answer:
            lines.append("  最终回答:")
            lines.append("    " + _text(self.final_answer).replace("\n", "\n    "))
        else:
            lines.append("  最终回答: （没有记录到最终文本）")

        for note in self.notes:
            lines.append(f"  提示: {note}")
        return "\n".join(lines)


def _extract_tool_calls(messages: list[dict[str, Any]]) -> list[ToolCall]:
    """从消息流里提取工具调用（兼容原生 function calling 与文本协议两种记录）"""
    calls: list[ToolCall] = []
    pending: dict[str, ToolCall] = {}

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")

        # 1) assistant 原生 tool_calls
        for raw in (message.get("tool_calls") or []):
            if not isinstance(raw, dict):
                continue
            fn = raw.get("function") if isinstance(raw.get("function"), dict) else raw
            name = str(fn.get("name") or raw.get("name") or "").strip()
            if not name:
                continue
            call = ToolCall(name=name, arguments=str(fn.get("arguments") or ""))
            calls.append(call)
            key = str(raw.get("id") or "")
            if key:
                pending[key] = call

        # 2) role=tool 的结果回填
        if role == "tool":
            key = str(message.get("tool_call_id") or "")
            content = _text(message.get("content"), 600)
            target = pending.get(key)
            if target is not None:
                target.result = content
                target.ok = _result_ok(content)
            else:
                name = str(message.get("name") or "tool").strip() or "tool"
                calls.append(ToolCall(name=name, result=content, ok=_result_ok(content)))
    return calls


#: 失败标志（只看输出开头 400 字符：错误通常在最前面，避免"文件内容里恰好出现 error"被误判）
_FAILURE_MARKERS = (
    "traceback (most recent call last)",
    "permission denied",
    "command not found",
    "exit code 1",
    "error:",
    "exception:",
    "错误:",
    "失败:",
)


def _result_ok(content: str) -> bool:
    """从工具输出里判断成功与否

    启发式而非确定性：只扫描前 400 字符的失败标志。
    误判方向刻意选"宁可放过"—— 所以 `ok` 只用于展示，不用于对外声称"通过"。
    """
    text = (content or "").strip()
    if not text:
        return True  # 空结果不算失败
    head = text[:400].lower()
    return not any(marker in head for marker in _FAILURE_MARKERS)


def _collect_failures(messages: list[dict[str, Any]]) -> list[str]:
    """找出错误的原始片段（带 role，便于定位是谁出的问题）"""
    failures: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = str(message.get("content") or "")
        role = str(message.get("role") or "?")
        stripped = content.strip()
        if not stripped:
            continue
        if "Traceback (most recent call last)" in stripped:
            failures.append(f"[{role}] " + stripped.splitlines()[-1][:300])
        elif stripped.startswith(("Error:", "错误:", "Exception:")):
            failures.append(f"[{role}] {stripped[:300]}")
    return failures


def _final_answer(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if isinstance(message, dict) and str(message.get("role") or "") == "assistant":
            content = str(message.get("content") or "").strip()
            if content:
                return content
    return ""


def explain_session(
    session_id: str | None = None,
    directory: Path | str | None = None,
) -> Explanation:
    """生成一份中文说明（缺省取最近一次会话）

    Raises:
        FileNotFoundError: 指定的/任何会话都不存在
    """
    if session_id is None:
        views = session_bridge.list_all(directory)
        if not views:
            raise FileNotFoundError("还没有任何会话记录（先跑一次 clawd run / clawd chat）")
        view = views[0]
    else:
        view = session_bridge.load(session_id, directory)

    messages = [m for m in (view.messages or []) if isinstance(m, dict)]
    explanation = Explanation(
        session_id=view.session_id,
        title=" ".join((view.title or "").split())[:120],  # 标题压成单行
        status=view.status or "",
        provider=view.provider or "",
        model=view.model or "",
        turns=view.turn_count or 0,
        input_tokens=view.input_tokens or 0,
        output_tokens=view.output_tokens or 0,
        cost=float(view.total_cost or 0.0),
        message_count=len(messages),
    )
    explanation.tool_calls = _extract_tool_calls(messages)
    explanation.failures = _collect_failures(messages)
    explanation.final_answer = _final_answer(messages)

    unknown_results = sum(1 for t in explanation.tool_calls if t.ok is None)
    if unknown_results:
        explanation.notes.append(
            f"{unknown_results} 次工具调用没有结果记录（不算成功，也不算失败）"
        )
    if view.status and view.status.lower() not in ("completed", "complete", "done", "success"):
        explanation.notes.append(f"会话状态是 {view.status}，不是 completed")
    if view.fmt == "legacy":
        explanation.notes.append("该会话是历史格式（legacy），字段可能不全")

    return explanation


__all__ = ["Explanation", "ToolCall", "explain_session"]
