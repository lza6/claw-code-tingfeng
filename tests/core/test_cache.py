"""Cache 模块单元测试"""
import sys
import time
import pytest
from unittest.mock import patch, MagicMock
from src.core.cache import (
    CacheBackend,
    CacheConfig,
    BaseCache,
    MemoryCache,
    RedisCache,
    CacheManager,
    get_cache,
    cache_get,
    cache_set,
    cache_delete,
    cached,
)


class TestCacheBackend:
    """CacheBackend 枚举测试"""

    def test_memory_backend(self):
        assert CacheBackend.MEMORY.value == "memory"

    def test_redis_backend(self):
        assert CacheBackend.REDIS.value == "redis"

    def test_postgres_backend(self):
        assert CacheBackend.POSTGRES.value == "postgres"


class TestCacheConfig:
    """CacheConfig 测试"""

    def test_defaults(self):
        """默认配置"""
        config = CacheConfig()
        assert config.backend == CacheBackend.MEMORY
        assert config.redis_host == "localhost"
        assert config.redis_port == 6379
        assert config.redis_db == 0
        assert config.redis_password is None
        assert config.redis_max_connections == 50
        assert config.postgres_host == "127.0.0.1"
        assert config.postgres_port == 5432
        assert config.postgres_db == "postgres"
        assert config.default_ttl == 3600
        assert config.key_prefix == "clawd:"

    @patch.dict("os.environ", {
        "CACHE_BACKEND": "redis",
        "REDIS_HOST": "myredis",
        "REDIS_PORT": "6380",
        "REDIS_DB": "2",
        "REDIS_PASSWORD": "secret",
    })
    def test_from_env_redis(self):
        """从环境变量加载 Redis 配置"""
        config = CacheConfig.from_env()
        assert config.backend == CacheBackend.REDIS
        assert config.redis_host == "myredis"
        assert config.redis_port == 6380
        assert config.redis_db == 2
        assert config.redis_password == "secret"

    @patch.dict("os.environ", {"CACHE_BACKEND": "memory"})
    def test_from_env_memory(self):
        """从环境变量加载 Memory 配置"""
        config = CacheConfig.from_env()
        assert config.backend == CacheBackend.MEMORY

    @patch.dict("os.environ", {"CACHE_BACKEND": "invalid"}, clear=True)
    def test_from_env_invalid_backend(self):
        """无效后端默认到 memory"""
        config = CacheConfig.from_env()
        assert config.backend == CacheBackend.MEMORY


class TestMemoryCache:
    """MemoryCache 测试"""

    @pytest.fixture
    def cache(self):
        return MemoryCache(CacheConfig())

    def test_set_and_get(self, cache):
        """设置和获取"""
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_nonexistent(self, cache):
        """获取不存在的键"""
        assert cache.get("nonexistent") is None

    def test_set_overwrite(self, cache):
        """覆盖设置"""
        cache.set("key", "old")
        cache.set("key", "new")
        assert cache.get("key") == "new"

    def test_delete_existing(self, cache):
        """删除存在的键"""
        cache.set("key", "value")
        assert cache.delete("key") is True
        assert cache.get("key") is None

    def test_delete_nonexistent(self, cache):
        """删除不存在的键"""
        assert cache.delete("nonexistent") is False

    def test_clear(self, cache):
        """清空缓存"""
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.clear()
        assert cache.get("k1") is None
        assert cache.get("k2") is None

    def test_clear_resets_stats(self, cache):
        """清空重置统计"""
        cache.set("key", "value")
        cache.get("key")
        cache.get("missing")
        cache.clear()
        assert cache.get_stats() == {"hits": 0, "misses": 0, "sets": 0}

    def test_ttl_expiry(self, cache):
        """TTL 过期"""
        cache.set("key", "value", ttl=1)
        assert cache.get("key") == "value"
        time.sleep(1.1)
        assert cache.get("key") is None

    def test_ttl_zero_means_no_expiry(self, cache):
        """TTL=0 表示永不过期"""
        cache.set("key", "value", ttl=0)
        assert cache.get("key") == "value"

    def test_stats_hits_misses(self, cache):
        """统计: hits/misses"""
        cache.set("key", "value")
        cache.get("key")
        cache.get("missing")
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["sets"] == 1

    def test_complex_value(self, cache):
        """复杂值存储"""
        data = {"nested": {"key": "value"}, "list": [1, 2, 3]}
        cache.set("complex", data)
        assert cache.get("complex") == data

    def test_default_ttl(self, cache):
        """使用默认 TTL"""
        config = CacheConfig(default_ttl=2)
        c = MemoryCache(config)
        c.set("key", "value")
        assert c.get("key") == "value"
        time.sleep(2.1)
        assert c.get("key") is None


class TestRedisCache:
    """RedisCache 测试"""

    @pytest.fixture
    def config(self):
        return CacheConfig(backend=CacheBackend.REDIS)

    @pytest.fixture
    def cache(self, config):
        return RedisCache(config)

    def test_ensure_client_fallback_no_redis(self, cache, monkeypatch):
        """Redis 模块不可用时回退到内存缓存"""
        # 移除 redis 模块以模拟未安装
        monkeypatch.setitem(sys.modules, 'redis', None)
        cache._ensure_client()
        assert cache._client is None

    def test_get_without_client(self, cache):
        """无客户端 get 返回 None"""
        assert cache.get("key") is None

    @patch("redis.Redis")
    def test_get_with_client(self, mock_redis_class, cache):
        """有客户端 get 正常工作"""
        mock_client = MagicMock()
        mock_client.get.return_value = '{"data": "value"}'
        mock_client.ping.return_value = True
        mock_redis_class.return_value = mock_client

        result = cache.get("test_key")
        assert result == {"data": "value"}

    def test_set_without_client(self, cache):
        """无客户端 set 不抛异常"""
        cache.set("key", "value")
        # Note: stats might have hits if Redis is running, so just check no exception

    @patch("redis.Redis")
    def test_delete_without_client_mocked(self, mock_redis_class, config):
        """无客户端 delete 返回 False - 使用 mock 模拟无 redis 场景"""
        # 设置 mock 抛出异常模拟连接失败
        mock_redis_class.side_effect = Exception("Connection failed")
        cache = RedisCache(config)
        result = cache.delete("key")
        assert result is False

    def test_clear_without_client(self, cache):
        """无客户端 clear 不抛异常"""
        cache.clear()

    @patch("redis.Redis")
    def test_redis_connection_success(self, mock_redis_class, config):
        """Redis 连接成功"""
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis_class.return_value = mock_client

        cache = RedisCache(config)
        cache._ensure_client()
        assert cache._client is not None

    @patch("redis.Redis")
    def test_redis_get(self, mock_redis_class, config):
        """Redis get"""
        mock_client = MagicMock()
        mock_client.get.return_value = '{"data": "value"}'
        mock_client.ping.return_value = True
        mock_redis_class.return_value = mock_client

        cache = RedisCache(config)
        result = cache.get("test_key")
        assert result == {"data": "value"}
        assert cache._stats["hits"] == 1

    @patch("redis.Redis")
    def test_redis_set(self, mock_redis_class, config):
        """Redis set"""
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis_class.return_value = mock_client

        cache = RedisCache(config)
        cache.set("test_key", {"data": "value"}, ttl=60)
        assert cache._stats["sets"] == 1
        mock_client.setex.assert_called_once()

    @patch("redis.Redis")
    def test_redis_delete(self, mock_redis_class, config):
        """Redis delete"""
        mock_client = MagicMock()
        mock_client.delete.return_value = 1
        mock_client.ping.return_value = True
        mock_redis_class.return_value = mock_client

        cache = RedisCache(config)
        result = cache.delete("test_key")
        assert result is True


class TestCacheManager:
    """CacheManager 测试"""

    def setup_method(self):
        CacheManager._instance = None
        CacheManager._config = None

    def teardown_method(self):
        CacheManager._instance = None
        CacheManager._config = None

    def test_initialize_memory(self):
        """初始化 Memory 缓存"""
        config = CacheConfig(backend=CacheBackend.MEMORY)
        cache = CacheManager.initialize(config)
        assert isinstance(cache, MemoryCache)
        assert CacheManager.get_cache() is cache

    def test_initialize_default_from_env(self, monkeypatch):
        """默认从环境变量初始化"""
        monkeypatch.setenv("CACHE_BACKEND", "memory")
        cache = CacheManager.get_cache()
        assert isinstance(cache, MemoryCache)

    def test_singleton(self):
        """单例模式"""
        config = CacheConfig(backend=CacheBackend.MEMORY)
        c1 = CacheManager.initialize(config)
        c2 = CacheManager.get_cache()
        assert c1 is c2


class TestCacheConvenienceFunctions:
    """便捷函数测试"""

    def setup_method(self):
        CacheManager._instance = None
        CacheManager._config = None
        from src.core import cache as cache_mod
        cache_mod._instance = None

    def teardown_method(self):
        CacheManager._instance = None
        from src.core import cache as cache_mod
        cache_mod._instance = None

    def test_cache_set_get(self):
        """cache_set/cache_get"""
        cache_set("test_key", "test_value")
        assert cache_get("test_key") == "test_value"

    def test_cache_delete(self):
        """cache_delete"""
        cache_set("del_key", "value")
        assert cache_delete("del_key") is True
        assert cache_get("del_key") is None

    def test_cached_decorator(self):
        """cached 装饰器"""
        call_count = 0

        @cached(ttl=60)
        def expensive_function(x, y):
            nonlocal call_count
            call_count += 1
            return x + y

        result1 = expensive_function(1, 2)
        result2 = expensive_function(1, 2)
        assert result1 == 3
        assert result2 == 3
        assert call_count == 1

    def test_cached_decorator_with_key_func(self):
        """cached 带自定义 key_func"""
        call_count = 0

        def my_key_func(x, y):
            return f"custom:{x}:{y}"

        @cached(ttl=60, key_func=my_key_func)
        def another_function(x, y):
            nonlocal call_count
            call_count += 1
            return x * y

        result1 = another_function(3, 4)
        result2 = another_function(3, 4)
        assert result1 == 12
        assert result2 == 12
        assert call_count == 1

    def test_get_cache_singleton(self):
        """get_cache 单例"""
        c1 = get_cache()
        c2 = get_cache()
        assert c1 is c2
