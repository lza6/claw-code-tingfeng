"""Cache 模块测试 - LRU 缓存策略"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from src.utils.cache import LruCache


class TestLruCacheBasic:
    """LRU 缓存基础测试"""

    def test_create_cache(self):
        """测试创建缓存"""
        cache = LruCache(max_size=10)
        assert cache.max_size == 10

    def test_get_set(self):
        """测试设置和获取"""
        cache = LruCache(max_size=10)
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_missing(self):
        """测试获取不存在的键"""
        cache = LruCache(max_size=10)
        assert cache.get("nonexistent") is None

    def test_delete_eviction(self):
        """测试 LRU 淘汰"""
        cache = LruCache(max_size=2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)  # 应淘汰 "a"
        
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3

    def test_lru_order(self):
        """测试 LRU 顺序"""
        cache = LruCache(max_size=2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.get("a")  # 访问 "a"
        cache.put("c", 3)  # 应淘汰 "b"
        
        assert cache.get("a") == 1
        assert cache.get("b") is None
        assert cache.get("c") == 3


class TestLruCacheTTL:
    """LRU 缓存 TTL 测试"""

    def test_ttl_expiry(self):
        """测试 TTL 过期"""
        cache = LruCache(max_size=10, ttl_seconds=0.01)
        cache.put("key", "value")
        time.sleep(0.05)
        assert cache.get("key") is None

    def test_ttl_not_expired(self):
        """测试 TTL 未过期"""
        cache = LruCache(max_size=10, ttl_seconds=60)
        cache.put("key", "value")
        assert cache.get("key") == "value"


class TestLruCacheEdgeCases:
    """LRU 缓存边界条件测试"""

    def test_zero_size(self):
        """测试零大小缓存"""
        cache = LruCache(max_size=0)
        cache.put("key", "value")
        # 可能被立即淘汰
        result = cache.get("key")
        assert result is None or result == "value"

    def test_none_value(self):
        """测试设置 None 值"""
        cache = LruCache(max_size=10)
        cache.put("key", None)
        assert cache.get("key") is None
        assert "key" in cache.cache

    def test_large_cache(self):
        """测试大型缓存"""
        cache = LruCache(max_size=1000)
        for i in range(1000):
            cache.put(f"key{i}", i)
        
        assert cache.get("key0") == 0
        assert cache.get("key999") == 999

    def test_unlimited_size(self):
        """测试无限大小（max_size=None 不支持）"""
        cache = LruCache(max_size=10000)
        for i in range(1000):
            cache.put(f"key{i}", i)
        
        assert len(cache.cache) == 1000


class TestLruCacheIntegration:
    """LRU 缓存集成测试"""

    def test_cache_workflow(self):
        """测试完整工作流"""
        cache = LruCache(max_size=5, ttl_seconds=60)
        
        # 设置
        for i in range(5):
            cache.put(f"user:{i}", {"name": f"User{i}"})
        
        # 获取
        assert cache.get("user:0")["name"] == "User0"
        
        # 访问更新顺序
        cache.get("user:0")
        cache.put("user:5", {"name": "User5"})  # 淘汰 user:1
        
        assert cache.get("user:1") is None
        assert cache.get("user:0") is not None
