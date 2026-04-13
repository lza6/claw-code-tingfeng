"""LLM Cache 模块单元测试"""
import time
import pytest
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.llm.cache import (
    CacheEntry,
    CacheStats,
    LLMCache,
    get_global_cache,
    reset_global_cache,
)


class TestCacheEntry:
    """CacheEntry 测试"""

    def test_defaults(self):
        entry = CacheEntry(key="test", response="data")
        assert entry.key == "test"
        assert entry.response == "data"
        assert entry.access_count == 0
        assert entry.ttl == 3600

    def test_touch(self):
        entry = CacheEntry(key="test", response="data")
        old_accessed = entry.last_accessed
        time.sleep(0.01)
        entry.touch()
        assert entry.last_accessed > old_accessed
        assert entry.access_count == 1

    def test_touch_multiple_times(self):
        entry = CacheEntry(key="test", response="data")
        entry.touch()
        entry.touch()
        entry.touch()
        assert entry.access_count == 3

    def test_is_expired_false(self):
        entry = CacheEntry(key="test", response="data", ttl=3600)
        assert entry.is_expired is False

    def test_is_expired_true(self):
        entry = CacheEntry(key="test", response="data", ttl=0)
        time.sleep(0.01)
        assert entry.is_expired is True

    def test_is_expired_custom_ttl(self):
        entry = CacheEntry(key="test", response="data", ttl=1)
        assert entry.is_expired is False
        time.sleep(1.1)
        assert entry.is_expired is True


class TestCacheStats:
    """CacheStats 测试"""

    def test_defaults(self):
        stats = CacheStats()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.evictions == 0
        assert stats.total_size == 0

    def test_hit_rate_zero_when_no_requests(self):
        stats = CacheStats()
        assert stats.hit_rate == 0.0

    def test_hit_rate_all_hits(self):
        stats = CacheStats(hits=10, misses=0)
        assert stats.hit_rate == 1.0

    def test_hit_rate_no_hits(self):
        stats = CacheStats(hits=0, misses=10)
        assert stats.hit_rate == 0.0

    def test_hit_rate_mixed(self):
        stats = CacheStats(hits=3, misses=7)
        assert stats.hit_rate == 0.3

    def test_to_dict(self):
        stats = CacheStats(hits=5, misses=5, evictions=2, total_size=10)
        d = stats.to_dict()
        assert d["hits"] == 5
        assert d["misses"] == 5
        assert d["evictions"] == 2
        assert d["hit_rate"] == "50.0%"
        assert d["total_size"] == 10


class TestLLMCacheInit:
    """LLMCache 初始化测试"""

    def test_defaults(self):
        cache = LLMCache()
        assert cache.max_size == 100
        assert cache.ttl_seconds == 3600
        assert cache.persist_path is None
        assert cache._enabled is True
        assert len(cache._cache) == 0

    def test_custom_params(self):
        cache = LLMCache(max_size=50, ttl_seconds=1800)
        assert cache.max_size == 50
        assert cache.ttl_seconds == 1800

    def test_persist_path(self, tmp_path):
        persist_file = tmp_path / "cache.json"
        cache = LLMCache(persist_path=persist_file)
        assert cache.persist_path == persist_file


class TestLLMCacheEnableDisable:
    """启用/禁用测试"""

    def test_disable(self):
        cache = LLMCache()
        cache.disable()
        assert cache._enabled is False

    def test_enable(self):
        cache = LLMCache()
        cache.disable()
        cache.enable()
        assert cache._enabled is True

    def test_get_disabled_returns_none(self):
        cache = LLMCache()
        cache.disable()
        assert cache.get([], "gpt-4") is None

    def test_put_disabled_does_nothing(self):
        cache = LLMCache()
        cache.disable()
        cache.put([], "gpt-4", "response")
        assert len(cache._cache) == 0


class TestLLMCacheGetPut:
    """Get/Put 操作测试"""

    def test_basic_get_put(self):
        cache = LLMCache()

        # 模拟消息对象
        messages = [MagicMock(role="user", content="hello")]
        response = MagicMock(content="hi", model="gpt-4", thinking=None, usage=None, finish_reason="stop")

        cache.put(messages, "gpt-4", response)
        result = cache.get(messages, "gpt-4")

        assert result is response

    def test_cache_miss(self):
        cache = LLMCache()
        messages = [MagicMock(role="user", content="test")]
        result = cache.get(messages, "gpt-4")
        assert result is None

    def test_different_models_separate_cache(self):
        cache = LLMCache()
        messages = [MagicMock(role="user", content="hello")]
        response = MagicMock(content="hi", model="gpt-4", thinking=None, usage=None, finish_reason="stop")

        cache.put(messages, "gpt-4", response)

        # 不同模型名，缓存未命中
        result = cache.get(messages, "claude-3")
        assert result is None

    def test_different_temperature_separate_cache(self):
        cache = LLMCache()
        messages = [MagicMock(role="user", content="hello")]
        response = MagicMock(content="hi", model="gpt-4", thinking=None, usage=None, finish_reason="stop")

        cache.put(messages, "gpt-4", response, temperature=0.7)

        # 不同温度，缓存未命中
        result = cache.get(messages, "gpt-4", temperature=0.9)
        assert result is None


class TestLLMCacheLRU:
    """LRU 淘汰测试"""

    def test_lru_eviction(self):
        cache = LLMCache(max_size=3)
        responses = []

        for i in range(4):
            messages = [MagicMock(role="user", content=f"msg{i}")]
            response = MagicMock(content=f"resp{i}", model="gpt-4", thinking=None, usage=None, finish_reason="stop")
            responses.append(response)
            cache.put(messages, "gpt-4", response)

        # 应该有 3 个条目 (max_size)
        assert len(cache._cache) == 3

        # 最早的条目被淘汰
        first_messages = [MagicMock(role="user", content="msg0")]
        result = cache.get(first_messages, "gpt-4")
        assert result is None

    def test_access_refreshes_lru(self):
        cache = LLMCache(max_size=3)

        # 插入 3 个条目
        for i in range(3):
            messages = [MagicMock(role="user", content=f"msg{i}")]
            response = MagicMock(content=f"resp{i}", model="gpt-4", thinking=None, usage=None, finish_reason="stop")
            cache.put(messages, "gpt-4", response)

        # 访问第一个条目 (使其变为最近使用)
        first_messages = [MagicMock(role="user", content="msg0")]
        cache.get(first_messages, "gpt-4")

        # 插入第 4 个
        new_messages = [MagicMock(role="user", content="msg3")]
        new_response = MagicMock(content="resp3", model="gpt-4", thinking=None, usage=None, finish_reason="stop")
        cache.put(new_messages, "gpt-4", new_response)

        # 第一个条目仍然在 (因为被访问过)
        result = cache.get(first_messages, "gpt-4")
        assert result is not None


class TestLLMCacheTTL:
    """TTL 过期测试"""

    def test_ttl_expiry(self):
        cache = LLMCache(ttl_seconds=1)
        messages = [MagicMock(role="user", content="hello")]
        response = MagicMock(content="hi", model="gpt-4", thinking=None, usage=None, finish_reason="stop")

        cache.put(messages, "gpt-4", response)
        assert cache.get(messages, "gpt-4") == response

        time.sleep(1.1)
        assert cache.get(messages, "gpt-4") is None

    def test_ttl_eviction_count(self):
        cache = LLMCache(ttl_seconds=1)
        messages = [MagicMock(role="user", content="hello")]
        response = MagicMock(content="hi", model="gpt-4", thinking=None, usage=None, finish_reason="stop")

        cache.put(messages, "gpt-4", response)
        time.sleep(1.1)
        cache.get(messages, "gpt-4")  # 触发过期检测

        stats = cache.get_stats()
        assert stats["evictions"] >= 1


class TestLLMCacheClear:
    """清空缓存测试"""

    def test_clear(self):
        cache = LLMCache()
        messages = [MagicMock(role="user", content="hello")]
        response = MagicMock(content="hi", model="gpt-4", thinking=None, usage=None, finish_reason="stop")

        cache.put(messages, "gpt-4", response)
        cache.clear()

        assert len(cache._cache) == 0
        assert len(cache._order) == 0
        stats = cache.get_stats()
        assert stats["total_size"] == 0


class TestLLMCacheStats:
    """统计信息测试"""

    def test_hits_and_misses(self):
        cache = LLMCache()
        messages = [MagicMock(role="user", content="hello")]
        response = MagicMock(content="hi", model="gpt-4", thinking=None, usage=None, finish_reason="stop")

        cache.put(messages, "gpt-4", response)
        cache.get(messages, "gpt-4")  # hit
        cache.get(messages, "gpt-4", temperature=0.9)  # miss

        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] >= 1


class TestLLMCachePersistence:
    """持久化测试"""

    def test_save_and_load(self, tmp_path):
        persist_file = tmp_path / "cache.json"

        # 创建缓存并写入
        cache1 = LLMCache(persist_path=persist_file)
        messages = [MagicMock(role="user", content="hello")]
        response = MagicMock(content="hi", model="gpt-4", thinking=None, usage={"total": 10}, finish_reason="stop")

        cache1.put(messages, "gpt-4", response)
        cache1.save()

        assert persist_file.exists()

    def test_load_nonexistent(self, tmp_path):
        persist_file = tmp_path / "cache.json"
        cache = LLMCache(persist_path=persist_file)
        # 文件不存在时不报错
        cache.load()
        assert len(cache._cache) == 0


class TestGlobalCache:
    """全局缓存测试"""

    def teardown_method(self):
        reset_global_cache()

    def test_get_global_cache_singleton(self):
        c1 = get_global_cache()
        c2 = get_global_cache()
        assert c1 is c2

    def test_reset_global_cache(self):
        c1 = get_global_cache()
        reset_global_cache()
        c2 = get_global_cache()
        assert c1 is not c2
