"""代理模块

v0.20.0 重构:
- AgentStep, AgentSession 移至 agent_session.py
- AgentStreamMixin (run_stream, run_structured) 移至 agent_stream.py

v0.45.0 新增（从 Aider 移植）:
- ChatChunks: 结构化消息管理
- SwitchCoder: 异常驱动的模式切换

## 惰性导出（v0.57.0）

本包原先在 `__init__` 顶层导入整个 Agent 栈（engine / factory / tool_executor），
而 `engine` 又会拉起 `src.llm`（channel_cache → loguru）。结果是：只想读
`AGENT_DEFINITIONS` 的 `clawd agent list` 也要先加载半个框架。

改为 PEP 562 惰性属性，`from src.agent import AgentEngine` 仍照常可用。
"""
from __future__ import annotations

import importlib
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AgentStreamMixin": (".agent_stream", "AgentStreamMixin"),
    "ChatChunks": (".chat_chunks", "ChatChunks"),
    "AgentEngine": (".engine", "AgentEngine"),
    "AgentSession": (".engine_session_data", "AgentSession"),
    "AgentStep": (".engine_session_data", "AgentStep"),
    "create_agent_engine": (".factory", "create_agent_engine"),
    "MessageTruncator": (".message_truncator", "MessageTruncator"),
    "check_tool_call_loop": (".tool_executor", "check_tool_call_loop"),
    "execute_tool": (".tool_executor", "execute_tool"),
    "parse_tool_calls": (".tool_executor", "parse_tool_calls"),
}


def __getattr__(name: str) -> Any:
    """PEP 562：按需导入。"""
    if name in _LAZY_EXPORTS:
        module_path, attr = _LAZY_EXPORTS[name]
        module = importlib.import_module(module_path, __name__)
        return getattr(module, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = [
    "AgentEngine",
    "AgentSession",
    "AgentStep",
    "AgentStreamMixin",
    "ChatChunks",  # 从 Aider 移植
    "MessageTruncator",
    "check_tool_call_loop",
    "create_agent_engine",
    "execute_tool",
    "parse_tool_calls",
]
