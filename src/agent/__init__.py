"""代理模块

v0.20.0 重构:
- AgentStep, AgentSession 移至 agent_session.py
- AgentStreamMixin (run_stream, run_structured) 移至 agent_stream.py

v0.45.0 新增（从 Aider 移植）:
- ChatChunks: 结构化消息管理
- SwitchCoder: 异常驱动的模式切换
"""
from __future__ import annotations

from .agent_stream import AgentStreamMixin
from .chat_chunks import ChatChunks
from .engine import AgentEngine
from .engine_session_data import AgentSession, AgentStep
from .factory import create_agent_engine
from .message_truncator import MessageTruncator
from .tool_executor import check_tool_call_loop, execute_tool, parse_tool_calls

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
