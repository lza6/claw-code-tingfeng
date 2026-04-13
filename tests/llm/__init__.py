"""Tests for LLM cache module"""
import time
import pytest
from pathlib import Path
from src.llm.cache import LLMCache, CacheEntry, CacheStats, get_global_cache, reset_global_cache
from src.llm import LLMMessage, LLMResponse


@pytest.fixture
def fresh_cache():
    """Creates a fresh in-memory cache for each test"""
    return LLMCache(max_size=5, ttl_seconds=60)


@pytest.fixture
def sample_messages():
    return [LLMMessage(role="user", content="Hello"), LLMMessage(role="assistant", content="Hi!")]


@pytest.fixture
def sample_response():
    return LLMResponse(
        content="Hello back!",
        model="test-model",
        thinking="Thinking process",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        finish_reason="stop",
    )


class TestCacheStats:
    def test_hit_rate_empty(self):
        stats = CacheStats()
        assert stats.hit_rate == 0.0

    def test_hit_rate_all_hits(self):
        stats = CacheStats(hits=10, misses=0)
        assert stats.hit_rate == 1.0

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


class TestCacheEntry:
    def test_touch_updates_access(self):
        entry = CacheEntry(key="test", response=LLMResponse(content="x", model="m"), created_at=time.time())
        assert entry.access_count == 0
        entry.touch()
        assert entry.access_count == 1
        assert entry.last_accessed > 0


class TestLLMCacheGetPut:
    def test_put_and_get(self, fresh_cache, sample_messages, sample_response):
        fresh_cache.put(sample_messages, "gpt-4", sample_response, temperature=0.7)
        result = fresh_cache.get(sample_messages, "gpt-4", temperature=0.7)
        assert result is not None
        assert result.content == "Hello back!"

    def test_get_missing_key(self, fresh_cache, sample_messages):
        result = fresh_cache.get(sample_messages, "missing-model")
        assert result is None

    def test_get_with_different_temperature(self, fresh_cache, sample_messages, sample_response):
        fresh_cache.put(sample_messages, "gpt-4", sample_response, temperature=0.7)
        result = fresh_cache.get(sample_messages, "gpt-4", temperature=0.9)
        assert result is None  # Different temperature = different key

    def test_get_with_different_model(self, fresh_cache, sample_messages, sample_response):
        fresh_cache.put(sample_messages, "gpt-4", sample_response)
        result = fresh_cache.get(sample_messages, "gpt-3.5")
        assert result is None

    def test_cache_disabled_returns_none(self, fresh_cache, sample_messages, sample_response):
        fresh_cache.put(sample_messages, "gpt-4", sample_response)
        fresh_cache.disable()
        result = fresh_cache.get(sample_messages, "gpt-4")
        assert result is None

    def test_put_when_disabled(self, fresh_cache, sample_messages, sample_response):
        fresh_cache.disable()
        fresh_cache.put(sample_messages, "gpt-4", sample_response)
        assert len(fresh_cache._cache) == 0

    def test_lru_eviction(self, fresh_cache, sample_messages, sample_response):
        """Test that LRU eviction works when cache is full (max_size=5)"""
        for i in range(6):
            msgs = [LLMMessage(role="user", content=f"msg{i}")]
            resp = LLMResponse(content=f"resp{i}", model="test")
            fresh_cache.put(msgs, "model", resp)
        assert len(fresh_cache._cache) == 5  # Should not exceed max_size

    def test_clear_resets_stats(self, fresh_cache, sample_messages, sample_response):
        fresh_cache.put(sample_messages, "gpt-4", sample_response)
        fresh_cache.get(sample_messages, "gpt-4")  # trigger a hit
        fresh_cache.clear()
        stats = fresh_cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["total_size"] == 0

    def test_ttl_expiration(self, sample_messages, sample_response):
        """Test that entries expire after TTL"""
        cache = LLMCache(max_size=10, ttl_seconds=1)
        cache.put(sample_messages, "gpt-4", sample_response)
        time.sleep(1.1)  # Wait for TTL to expire
        result = cache.get(sample_messages, "gpt-4")
        assert result is None

    def test_key_generation_deterministic(self, fresh_cache, sample_messages):
        key1 = fresh_cache._generate_key(sample_messages, "gpt-4", 0.7)
        key2 = fresh_cache._generate_key(sample_messages, "gpt-4", 0.7)
        assert key1 == key2

    def test_key_generation_different_messages(self, fresh_cache):
        msgs1 = [LLMMessage(role="user", content="hello")]
        msgs2 = [LLMMessage(role="user", content="world")]
        key1 = fresh_cache._generate_key(msgs1, "gpt-4", 0.7)
        key2 = fresh_cache._generate_key(msgs2, "gpt-4", 0.7)
        assert key1 != key2

    def test_overwrite_existing_key(self, fresh_cache, sample_messages):
        """Putting the same key twice should update, not duplicate"""
        resp1 = LLMResponse(content="first", model="m")
        resp2 = LLMResponse(content="second", model="m")
        fresh_cache.put(sample_messages, "gpt-4", resp1)
        fresh_cache.put(sample_messages, "gpt-4", resp2)
        result = fresh_cache.get(sample_messages, "gpt-4")
        assert result.content == "second"


class TestCachePersistence:
    def test_save_and_load(self, tmp_path, sample_messages, sample_response):
        persist_path = tmp_path / "cache.json"
        cache = LLMCache(max_size=10, ttl_seconds=3600, persist_path=persist_path)
        cache.put(sample_messages, "gpt-4", sample_response)
        cache.save()
        assert persist_path.exists()

        # Load into a new cache instance
        cache2 = LLMCache(max_size=10, ttl_seconds=3600, persist_path=persist_path)
        result = cache2.get(sample_messages, "gpt-4")
        assert result is not None
        assert result.content == "Hello back!"

    def test_save_no_persist_path(self, sample_messages, sample_response):
        cache = LLMCache(max_size=10, ttl_seconds=60)  # No persist_path
        cache.put(sample_messages, "gpt-4", sample_response)
        cache.save()  # Should not raise


class TestGlobalCache:
    def test_get_global_cache_returns_instance(self):
        reset_global_cache()
        cache = get_global_cache()
        assert isinstance(cache, LLMCache)

    def test_get_global_cache_is_singleton(self):
        reset_global_cache()
        c1 = get_global_cache()
        c2 = get_global_cache()
        assert c1 is c2

    def test_reset_global_cache(self):
        reset_global_cache()
        c1 = get_global_cache()
        reset_global_cache()
        c2 = get_global_cache()
        assert c1 is not c2
