"""
缓存模块 - 整合自 Onyx 的缓存接口

支持:
- Redis 缓存
- PostgreSQL 缓存
- 内存缓存 (本地)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CacheBackend(str, Enum):
    """缓存后端"""
    MEMORY = "memory"
    REDIS = "redis"
    POSTGRES = "postgres"


@dataclass
class CacheConfig:
    """缓存配置"""
    backend: CacheBackend = CacheBackend.MEMORY
    # Redis 配置
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None
    redis_max_connections: int = 50
    # PostgreSQL 配置
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "postgres"
    # 通用配置
    default_ttl: int = 3600  # 1小时
    key_prefix: str = "clawd:"

    @classmethod
    def from_env(cls) -> CacheConfig:
        """从环境变量加载"""
        config = cls()
        backend_str = os.environ.get("CACHE_BACKEND", "memory").lower()
        if backend_str in [b.value for b in CacheBackend]:
            config.backend = CacheBackend(backend_str)

        config.redis_host = os.environ.get("REDIS_HOST", config.redis_host)
        config.redis_port = int(os.environ.get("REDIS_PORT", config.redis_port))
        config.redis_db = int(os.environ.get("REDIS_DB", config.redis_db))
        config.redis_password = os.environ.get("REDIS_PASSWORD")

        return config


class BaseCache:
    """缓存基类"""

    def __init__(self, config: CacheConfig):
        self.config = config
        self._stats = {"hits": 0, "misses": 0, "sets": 0}

    def get(self, key: str) -> Any | None:
        """获取值"""
        raise NotImplementedError

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """设置值"""
        raise NotImplementedError

    def delete(self, key: str) -> None:
        """删除值"""
        raise NotImplementedError

    def clear(self) -> None:
        """清空缓存"""
        raise NotImplementedError

    def get_stats(self) -> dict[str, int]:
        """获取统计"""
        return self._stats.copy()


class MemoryCache(BaseCache):
    """内存缓存 (简单实现)"""

    def __init__(self, config: CacheConfig):
        super().__init__(config)
        self._cache: dict[str, tuple[Any, float | None]] = {}

    def get(self, key: str) -> Any | None:
        """获取值"""
        import time
        value, expiry = self._cache.get(key, (None, None))

        if value is None:
            self._stats["misses"] += 1
            return None

        # 检查过期
        if expiry is not None and time.time() > expiry:
            del self._cache[key]
            self._stats["misses"] += 1
            return None

        self._stats["hits"] += 1
        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """设置值"""
        import time
        expiry = None
        if ttl is None:
            ttl = self.config.default_ttl
        if ttl > 0:
            expiry = time.time() + ttl

        self._cache[key] = (value, expiry)
        self._stats["sets"] += 1

    def delete(self, key: str) -> bool:
        """删除值"""
        return self._cache.pop(key, None) is not None

    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()
        self._stats = {"hits": 0, "misses": 0, "sets": 0}


class RedisCache(BaseCache):
    """Redis 缓存"""

    def __init__(self, config: CacheConfig):
        super().__init__(config)
        self._pool = None
        self._client = None

    def _ensure_client(self):
        """确保 Redis 客户端已连接 (线程安全连接池版)"""
        if self._client is None:
            try:
                import redis
                self._pool = redis.ConnectionPool(
                    host=self.config.redis_host,
                    port=self.config.redis_port,
                    db=self.config.redis_db,
                    password=self.config.redis_password,
                    max_connections=self.config.redis_max_connections,
                    decode_responses=True,
                )
                self._client = redis.Redis(connection_pool=self._pool)
                self._client.ping()
                logger.info("Redis 缓存池已建立")
            except ImportError:
                logger.error("redis-py 未安装，缓存将受限")
                self._client = None
            except Exception as e:
                logger.error(f"Redis 连接失败: {e}，启用回退模式")
                self._client = None

    def get(self, key: str) -> Any | None:
        """获取值"""
        self._ensure_client()
        if self._client is None:
            return None

        full_key = f"{self.config.key_prefix}{key}"
        try:
            value = self._client.get(full_key)
            if value is None:
                self._stats["misses"] += 1
                return None

            self._stats["hits"] += 1
            return json.loads(value)
        except Exception as e:
            logger.warning(f"Redis get 失败: {e}")
            return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """设置值"""
        self._ensure_client()
        if self._client is None:
            return

        full_key = f"{self.config.key_prefix}{key}"
        if ttl is None:
            ttl = self.config.default_ttl

        try:
            serialized = json.dumps(value)
            if ttl > 0:
                self._client.setex(full_key, ttl, serialized)
            else:
                self._client.set(full_key, serialized)
            self._stats["sets"] += 1
        except Exception as e:
            logger.warning(f"Redis set 失败: {e}")

    def delete(self, key: str) -> bool:
        """删除值"""
        self._ensure_client()
        if self._client is None:
            return False

        full_key = f"{self.config.key_prefix}{key}"
        try:
            return self._client.delete(full_key) > 0
        except Exception as e:
            logger.warning(f"Redis delete 失败: {e}")
            return False

    def clear(self) -> None:
        """清空缓存"""
        self._ensure_client()
        if self._client is None:
            return

        try:
            pattern = f"{self.config.key_prefix}*"
            keys = self._client.keys(pattern)
            if keys:
                self._client.delete(*keys)
            self._stats = {"hits": 0, "misses": 0, "sets": 0}
        except Exception as e:
            logger.warning(f"Redis clear 失败: {e}")


class PostgresCache(BaseCache):
    """PostgreSQL 缓存 (利用 UNLOGGED TABLE 优化性能)"""

    def __init__(self, config: CacheConfig):
        super().__init__(config)
        self._conn = None
        self._table = f"{config.key_prefix}cache"

    def _ensure_table(self):
        """确保缓存表存在"""
        if self._conn is None:
            try:
                import psycopg2
                self._pool = psycopg2.pool.SimpleConnectionPool(
                    1, 20,
                    host=self.config.postgres_host,
                    port=self.config.postgres_port,
                    database=self.config.postgres_db,
                    user=os.environ.get("POSTGRES_USER", "postgres"),
                    password=os.environ.get("POSTGRES_PASSWORD", "")
                )
                self._conn = self._pool.getconn()
                self._conn.autocommit = True
                with self._conn.cursor() as cur:
                    cur.execute(f"""
                        CREATE UNLOGGED TABLE IF NOT EXISTS {self._table} (
                            key TEXT PRIMARY KEY,
                            value JSONB,
                            expiry DOUBLE PRECISION
                        );
                        CREATE INDEX IF NOT EXISTS idx_{self._table}_expiry ON {self._table}(expiry);
                    """)
                logger.info("Postgres 缓存表已就绪")
            except Exception as e:
                logger.error(f"Postgres 缓存初始化失败: {e}")
                self._conn = None

    def get(self, key: str) -> Any | None:
        self._ensure_table()
        if not self._conn: return None
        import time
        try:
            with self._conn.cursor() as cur:
                cur.execute(f"SELECT value, expiry FROM {self._table} WHERE key = %s", (key,))
                row = cur.fetchone()
                if row:
                    val, expiry = row
                    if expiry and time.time() > expiry:
                        self.delete(key)
                        self._stats["misses"] += 1
                        return None
                    self._stats["hits"] += 1
                    return val
                self._stats["misses"] += 1
        except Exception:
            self._conn = None
        return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._ensure_table()
        if not self._conn: return
        import time
        expiry = time.time() + (ttl or self.config.default_ttl)
        try:
            with self._conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {self._table} (key, value, expiry)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, expiry = EXCLUDED.expiry
                """, (key, json.dumps(value), expiry))
                self._stats["sets"] += 1
        except Exception:
            self._conn = None

    def delete(self, key: str) -> bool:
        self._ensure_table()
        if not self._conn: return False
        try:
            with self._conn.cursor() as cur:
                cur.execute(f"DELETE FROM {self._table} WHERE key = %s", (key,))
                return cur.rowcount > 0
        except Exception:
            return False

    def clear(self) -> None:
        self._ensure_table()
        if not self._conn: return
        try:
            with self._conn.cursor() as cur:
                cur.execute(f"TRUNCATE TABLE {self._table}")
                self._stats = {"hits": 0, "misses": 0, "sets": 0}
        except Exception:
            pass


class CacheManager:
    """缓存管理器"""

    _instance: BaseCache | None = None
    _config: CacheConfig | None = None

    @classmethod
    def initialize(cls, config: CacheConfig | None = None) -> BaseCache:
        """初始化缓存"""
        if config is None:
            config = CacheConfig.from_env()

        cls._config = config

        if config.backend == CacheBackend.REDIS:
            cls._instance = RedisCache(config)
            # 测试连接，失败则回退
            try:
                cls._instance._ensure_client()
                if cls._instance._client is None:
                    cls._instance = MemoryCache(config)
            except Exception:
                cls._instance = MemoryCache(config)
        elif config.backend == CacheBackend.POSTGRES:
            cls._instance = PostgresCache(config)
            try:
                cls._instance._ensure_table()
                if cls._instance._conn is None:
                    cls._instance = MemoryCache(config)
            except Exception:
                cls._instance = MemoryCache(config)
        else:
            cls._instance = MemoryCache(config)

        logger.info(f"缓存已初始化: {config.backend.value}")
        return cls._instance

    @classmethod
    def get_cache(cls) -> BaseCache:
        """获取缓存实例"""
        if cls._instance is None:
            cls._instance = cls.initialize()
        return cls._instance


# 便捷函数
def get_cache() -> BaseCache:
    """获取缓存"""
    return CacheManager.get_cache()


def cache_get(key: str) -> Any | None:
    """获取缓存"""
    return get_cache().get(key)


def cache_set(key: str, value: Any, ttl: int | None = None) -> None:
    """设置缓存"""
    get_cache().set(key, value, ttl)


def cache_delete(key: str) -> bool:
    """删除缓存"""
    return get_cache().delete(key)


def cached(ttl: int = 3600, key_func: Callable | None = None):
    """缓存装饰器

    Args:
        ttl: 过期时间(秒)
        key_func: 自定义key函数，默认使用函数名+参数
    """
    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            cache = get_cache()

            # 生成key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                key_str = f"{func.__name__}:{args!s}:{kwargs!s}"
                cache_key = hashlib.md5(key_str.encode()).hexdigest()

            # 尝试从缓存获取
            result = cache.get(cache_key)
            if result is not None:
                return result

            # 执行函数
            result = func(*args, **kwargs)

            # 存入缓存
            cache.set(cache_key, result, ttl)

            return result
        return wrapper
    return decorator
