"""LRU Cache Utility — Ported from Project B

A simple Least Recently Used (LRU) cache.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")

class LruCache(Generic[K, V]):
    """A high-performance LRU (Least Recently Used) cache with TTL support.

    Enhanced from Project B's LruCache.ts with TTL.
    """

    def __init__(self, max_size: int = 100, ttl_seconds: float | None = None):
        self.cache: OrderedDict[K, V] = OrderedDict()
        self.expirations: dict[K, float] = {}
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds

    def get(self, key: K) -> V | None:
        """Get value for key, checking TTL and updating recency."""
        if key not in self.cache:
            return None

        # Check TTL
        if self.ttl_seconds is not None and time.time() > self.expirations.get(key, 0):
            self._evict(key)
            return None

        # Move to end (most recent)
        self.cache.move_to_end(key)
        return self.cache[key]

    def put(self, key: K, value: V) -> None:
        """Put value for key, evicting oldest if max_size reached."""
        if key in self.cache:
            self.cache.move_to_end(key)

        self.cache[key] = value
        if self.ttl_seconds is not None:
            self.expirations[key] = time.time() + self.ttl_seconds

        if len(self.cache) > self.max_size:
            # Evict first (oldest)
            oldest_key = next(iter(self.cache))
            self._evict(oldest_key)

    def _evict(self, key: K) -> None:
        """Helper to remove a key from all structures."""
        self.cache.pop(key, None)
        self.expirations.pop(key, None)

    def set(self, key: K, value: V) -> None:
        """Alias for put() to match Project B naming convention."""
        self.put(key, value)

    def clear(self) -> None:
        """Clear the cache."""
        self.cache.clear()
        self.expirations.clear()

    def __len__(self) -> int:
        return len(self.cache)

    def __contains__(self, key: K) -> bool:
        # Note: __contains__ doesn't update recency or check TTL for performance
        # Use get() if TTL freshness is required.
        return key in self.cache

    @property
    def size(self) -> int:
        """Get current size of the cache."""
        return len(self.cache)
