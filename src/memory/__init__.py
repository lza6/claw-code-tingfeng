"""Memory Module - 多层记忆管理系统

从 claude-code-rust-master 汲取的架构优点:
- 语义记忆 (Semantic): 抽象知识/模式/规则
- 情景记忆 (Episodic): 具体经验/事件
- 工作记忆 (Working): 当前会话上下文
- 记忆整合引擎

使用方式:
    from src.memory import MemoryManager

    mgr = MemoryManager()
    await mgr.initialize()
    await mgr.add_memory(MemoryEntry(content="...", memory_type=MemoryType.SEMANTIC))
"""
from __future__ import annotations

from .chat_summary import ChatSummary, SummaryResult, compress_messages
from .manager import MemoryManager
from .models import (
    EpisodicMemory,
    MemoryEntry,
    MemorySource,
    MemoryStatus,
    MemoryType,
    SemanticPattern,
    WorkingMemory,
)
from .sqlite_store import SQLiteMemoryStorage
from .storage import MemoryStorage

__all__ = [
    # Chat Summary (from aider)
    "ChatSummary",
    "EpisodicMemory",
    "MemoryEntry",
    "MemoryManager",
    "MemorySource",
    "MemoryStatus",
    "MemoryStorage",
    "SQLiteMemoryStorage",
    "MemoryType",
    "SemanticPattern",
    "SummaryResult",
    "WorkingMemory",
    "compress_messages",
]
