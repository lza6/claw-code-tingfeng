"""Memory Storage - 记忆持久化存储

从 claude-code-rust-master 汲取的架构优点:
- 独立存储层,支持多种后端
- 异步 I/O 操作
- JSON 序列化

存储路径: 项目目录/.clawd/memory/
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ..core.project_context import ProjectContext
from .models import (
    EpisodicMemory,
    MemoryEntry,
    SemanticPattern,
    WorkingMemory,
)


class MemoryStorage:
    """记忆持久化存储

    负责将记忆保存到文件系统,以及从文件系统加载记忆。

    """

    def __init__(self, memory_dir: Path | None = None, project_ctx: ProjectContext | None = None) -> None:
        """初始化记忆存储

        Args:
            memory_dir: 记忆目录（显式指定时优先使用）
            project_ctx: 项目上下文（用于自动推导路径）
        """
        if memory_dir is not None:
            self.memory_dir = memory_dir
        elif project_ctx is not None:
            self.memory_dir = project_ctx.memory_dir
        else:
            self.memory_dir = Path('.clawd') / 'memory'

        self._entries_file = self.memory_dir / "entries.json"
        self._patterns_file = self.memory_dir / "patterns.json"
        self._episodic_dir = self.memory_dir / "episodic"
        self._working_file = self.memory_dir / "working.json"

    def _ensure_dirs(self) -> None:
        """确保目录存在"""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._episodic_dir.mkdir(parents=True, exist_ok=True)

    async def save_entries(self, entries: list[MemoryEntry]) -> None:
        """保存记忆条目"""
        self._ensure_dirs()
        data = [e.to_dict() for e in entries]
        await asyncio.to_thread(
            self._entries_file.write_text,
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    async def load_entries(self) -> list[MemoryEntry]:
        """加载记忆条目"""
        if not self._entries_file.exists():
            return []
        content = await asyncio.to_thread(self._entries_file.read_text, encoding="utf-8")
        data = json.loads(content)
        return [MemoryEntry.from_dict(d) for d in data]

    async def save_patterns(self, patterns: list[SemanticPattern]) -> None:
        """保存语义模式"""
        self._ensure_dirs()
        data = [p.to_dict() for p in patterns]
        await asyncio.to_thread(
            self._patterns_file.write_text,
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    async def load_patterns(self) -> list[SemanticPattern]:
        """加载语义模式"""
        if not self._patterns_file.exists():
            return []
        content = await asyncio.to_thread(self._patterns_file.read_text, encoding="utf-8")
        data = json.loads(content)
        return [
            SemanticPattern(**{k: v for k, v in d.items() if k in SemanticPattern.__dataclass_fields__})
            for d in data
        ]

    async def save_episodic(self, memory: EpisodicMemory) -> None:
        """保存情景记忆"""
        self._ensure_dirs()
        path = self._episodic_dir / f"{memory.id}.json"
        await asyncio.to_thread(
            path.write_text,
            json.dumps(memory.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    async def load_episodic(self, episodic_id: str) -> EpisodicMemory | None:
        """加载情景记忆"""
        path = self._episodic_dir / f"{episodic_id}.json"
        if not path.exists():
            return None
        content = await asyncio.to_thread(path.read_text, encoding="utf-8")
        data = json.loads(content)
        return EpisodicMemory(**{k: v for k, v in data.items() if k in EpisodicMemory.__dataclass_fields__})

    async def list_episodic(self) -> list[EpisodicMemory]:
        """列出所有情景记忆"""
        if not self._episodic_dir.exists():
            return []

        def _list_dir() -> list[EpisodicMemory]:
            result: list[EpisodicMemory] = []
            for f in self._episodic_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    result.append(EpisodicMemory(**{
                        k: v for k, v in data.items() if k in EpisodicMemory.__dataclass_fields__
                    }))
                except (json.JSONDecodeError, KeyError):
                    continue
            return result

        return await asyncio.to_thread(_list_dir)

    async def save_working(self, memory: WorkingMemory) -> None:
        """保存工作记忆"""
        self._ensure_dirs()
        await asyncio.to_thread(
            self._working_file.write_text,
            json.dumps(memory.data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    async def load_working(self) -> WorkingMemory:
        """加载工作记忆"""
        memory = WorkingMemory()
        if not self._working_file.exists():
            return memory
        content = await asyncio.to_thread(self._working_file.read_text, encoding="utf-8")
        memory.data = json.loads(content)
        return memory

    async def get_storage_size(self) -> int:
        """获取存储大小(字节)"""
        if not self.memory_dir.exists():
            return 0
        total = 0
        for f in self.memory_dir.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
        return total
