"""
Memory Server - 记忆服务器

从 oh-my-codex-main/src/mcp/memory-server.ts 转换。
提供记忆存储、检索和元数据验证。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    """记忆条目"""
    id: str
    content: str
    type: str = "general"  # 'general' | 'context' | 'knowledge'
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = ""
    metadata: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


@dataclass
class MemoryIndex:
    """记忆索引"""
    entries: dict[str, MemoryEntry] = field(default_factory=dict)
    total_count: int = 0
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())


class MemoryServer:
    """记忆服务器

    功能:
    - 记忆存储
    - 记忆检索
    - 标签管理
    - 持久化
    """

    def __init__(self, storage_dir: str | None = None):
        self.storage_dir = storage_dir
        self._index = MemoryIndex()

    def store(self, entry: MemoryEntry) -> bool:
        """存储记忆"""
        try:
            entry.updated_at = datetime.now().isoformat()
            self._index.entries[entry.id] = entry
            self._index.total_count = len(self._index.entries)
            self._index.last_updated = datetime.now().isoformat()
            logger.debug(f"[Memory] Stored: {entry.id}")
            return True
        except Exception as e:
            logger.error(f"[Memory] Store failed: {e}")
            return False

    def retrieve(self, entry_id: str) -> MemoryEntry | None:
        """检索记忆"""
        return self._index.entries.get(entry_id)

    def search(self, query: str, limit: int = 10) -> list[MemoryEntry]:
        """搜索记忆"""
        query_lower = query.lower()
        results = []

        for entry in self._index.entries.values():
            if query_lower in entry.content.lower():
                results.append(entry)
                if len(results) >= limit:
                    break

        return results

    def search_by_tag(self, tag: str, limit: int = 10) -> list[MemoryEntry]:
        """按标签搜索"""
        results = []

        for entry in self._index.entries.values():
            if tag in entry.tags:
                results.append(entry)
                if len(results) >= limit:
                    break

        return results

    def delete(self, entry_id: str) -> bool:
        """删除记忆"""
        if entry_id in self._index.entries:
            del self._index.entries[entry_id]
            self._index.total_count = len(self._index.entries)
            logger.debug(f"[Memory] Deleted: {entry_id}")
            return True
        return False

    def get_index(self) -> MemoryIndex:
        """获取索引"""
        return self._index

    def save_to_file(self, path: str | None = None) -> bool:
        """保存到文件"""
        save_path = path or (self.storage_dir and f"{self.storage_dir}/memory.json")
        if not save_path:
            return False

        try:
            data = {
                "entries": {
                    k: {
                        "id": v.id,
                        "content": v.content,
                        "type": v.type,
                        "created_at": v.created_at,
                        "updated_at": v.updated_at,
                        "metadata": v.metadata,
                        "tags": v.tags,
                    }
                    for k, v in self._index.entries.items()
                }
            }
            Path(save_path).write_text(json.dumps(data, indent=2))
            logger.info(f"[Memory] Saved to {save_path}")
            return True
        except Exception as e:
            logger.error(f"[Memory] Save failed: {e}")
            return False

    def load_from_file(self, path: str) -> bool:
        """从文件加载"""
        try:
            data = json.loads(Path(path).read_text())
            entries = {}

            for k, v in data.get("entries", {}).items():
                entries[k] = MemoryEntry(
                    id=v["id"],
                    content=v["content"],
                    type=v.get("type", "general"),
                    created_at=v.get("created_at", ""),
                    updated_at=v.get("updated_at", ""),
                    metadata=v.get("metadata", {}),
                    tags=v.get("tags", []),
                )

            self._index = MemoryIndex(
                entries=entries,
                total_count=len(entries),
            )
            logger.info(f"[Memory] Loaded from {path}")
            return True
        except Exception as e:
            logger.error(f"[Memory] Load failed: {e}")
            return False


# 全局单例
_memory_server: MemoryServer | None = None


def get_memory_server() -> MemoryServer:
    """获取全局记忆服务器"""
    global _memory_server
    if _memory_server is None:
        _memory_server = MemoryServer()
    return _memory_server


# ===== 导出 =====
__all__ = [
    "MemoryEntry",
    "MemoryIndex",
    "MemoryServer",
    "get_memory_server",
]
