"""LLM 响应缓存 - LRU+TTL 智能缓存

从 llm/__init__.py 拆分出来
支持: 响应缓存、键生成、LRU淘汰、TTL过期、持久化
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    response: Any
    created_at: float = field(default_factory=time.time)
    last_accessed: float = 0.0
    access_count: int = 0
    ttl: float = 3600  # TTL in seconds

    def touch(self) -> None:
        """更新访问时间"""
        self.last_accessed = time.time()
        self.access_count += 1

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl


@dataclass
class CacheStats:
    """缓存统计"""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    total_size: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": f"{self.hit_rate * 100:.1f}%",
            "total_size": self.total_size,
        }


class LLMCache:
    """LLM 响应缓存（LRU + TTL + 持久化）"""

    def __init__(
        self,
        max_size: int = 100,
        ttl_seconds: int = 3600,
        persist_path: Path | None = None,
    ):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.persist_path = persist_path
        self._enabled = True
        self._cache: dict[str, CacheEntry] = {}
        self._order: list[str] = []  # LRU 顺序
        self._lock = threading.Lock()
        self._stats = CacheStats()

        # 自动加载持久化缓存
        if self.persist_path and self.persist_path.exists():
            self.load()

    def disable(self) -> None:
        """禁用缓存"""
        self._enabled = False

    def enable(self) -> None:
        """启用缓存"""
        self._enabled = True

    def _generate_key(self, messages: list, model: str, temperature: float = 0.7) -> str:
        """生成缓存键"""
        msg_hashes = hashlib.md5(
            json.dumps([{"role": m.role, "content": m.content} for m in messages], sort_keys=True).encode()
        ).hexdigest()
        return f"{model}:{msg_hashes}:{temperature}"

    def get(self, messages: list, model: str, temperature: float = 0.7) -> Any | None:
        """获取缓存的响应"""
        if not self._enabled:
            return None

        key = self._generate_key(messages, model, temperature)

        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if not entry.is_expired:  # is_expired is a property now
                    entry.touch()
                    # 更新 LRU 顺序：将访问的条目移到最后
                    if key in self._order:
                        self._order.remove(key)
                    self._order.append(key)
                    self._stats.hits += 1
                    return entry.response
                else:
                    del self._cache[key]
                    self._order.remove(key)
                    self._stats.evictions += 1

            self._stats.misses += 1
            return None

    def put(self, messages: list, model: str, response: Any, temperature: float = 0.7) -> None:
        """存储响应到缓存"""
        if not self._enabled:
            return

        key = self._generate_key(messages, model, temperature)

        with self._lock:
            # 如果键已存在，更新
            if key in self._cache:
                old_entry = self._cache[key]
                self._cache[key] = CacheEntry(
                    key=key,
                    response=response,
                    ttl=self.ttl_seconds,
                    access_count=old_entry.access_count,
                )
                return

            # LRU 淘汰
            if len(self._cache) >= self.max_size:
                lru_key = self._order.pop(0)
                del self._cache[lru_key]
                self._stats.evictions += 1

            self._cache[key] = CacheEntry(key=key, response=response, ttl=self.ttl_seconds)
            self._order.append(key)
            self._stats.total_size = len(self._cache)

    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._order.clear()
            self._stats = CacheStats()

    def get_stats(self) -> dict:
        """获取统计信息"""
        with self._lock:
            self._stats.total_size = len(self._cache)
            return self._stats.to_dict()

    def save(self) -> None:
        """持久化缓存到文件"""
        if not self.persist_path:
            return

        with self._lock:
            data = {
                "entries": {
                    key: {
                        "response": {
                            "content": entry.response.content,
                            "model": entry.response.model,
                            "thinking": entry.response.thinking,
                            "usage": entry.response.usage,
                            "finish_reason": entry.response.finish_reason,
                        },
                        "created_at": entry.created_at,
                        "access_count": entry.access_count,
                    }
                    for key, entry in self._cache.items()
                }
            }

            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            self.persist_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def load(self) -> None:
        """从文件加载缓存"""
        if not self.persist_path or not self.persist_path.exists():
            return

        with self._lock:
            data = json.loads(self.persist_path.read_text())

            for key, entry_data in data.get("entries", {}).items():
                from src.llm import LLMResponse
                response = LLMResponse(**entry_data["response"])
                self._cache[key] = CacheEntry(
                    key=key,
                    response=response,
                    created_at=entry_data["created_at"],
                    access_count=entry_data["access_count"],
                )
                self._order.append(key)

            self._stats.total_size = len(self._cache)


# 全局单例
_global_cache: LLMCache | None = None
_cache_lock = threading.Lock()


def get_global_cache() -> LLMCache:
    """获取全局缓存实例"""
    global _global_cache
    if _global_cache is None:
        with _cache_lock:
            if _global_cache is None:
                _global_cache = LLMCache()
    return _global_cache


def reset_global_cache() -> None:
    """重置全局缓存"""
    global _global_cache
    with _cache_lock:
        _global_cache = None


# 向后兼容别名
from collections import OrderedDict

_client_cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
_CLIENT_CACHE_TTL = 3600
_CLIENT_CACHE_MAX_SIZE = 32
import threading

_client_cache_lock = threading.Lock()
