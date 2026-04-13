"""
渠道缓存系统 - 整合自 New-API
内存+磁盘双层缓存，O(1)查询性能
"""

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class CacheEntry:
    """缓存条目"""
    value: Any
    created_at: float
    expires_at: float
    access_count: int = 0

    @property
    def is_expired(self) -> bool:
        """是否过期"""
        return time.time() > self.expires_at

    @property
    def ttl(self) -> float:
        """剩余生存时间（秒）"""
        return max(0, self.expires_at - time.time())


class ChannelCache:
    """
    渠道缓存（整合自 New-API 的内存+Redis双层缓存架构）
    适配为内存+磁盘双层缓存
    """

    def __init__(
        self,
        cache_dir: str = ".clawd/cache",
        default_ttl: int = 3600,
        max_size: int = 1000,
        enable_disk: bool = True
    ):
        """
        初始化缓存

        Args:
            cache_dir: 磁盘缓存目录
            default_ttl: 默认生存时间（秒）
            max_size: 最大缓存条目数
            enable_disk: 是否启用磁盘缓存
        """
        self._cache: dict[str, CacheEntry] = {}  # 内存缓存
        self._default_ttl = default_ttl
        self._max_size = max_size
        self._enable_disk = enable_disk
        self._cache_dir = Path(cache_dir)

        # 创建缓存目录
        if enable_disk:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()

        logger.info(f"渠道缓存已初始化 (TTL={default_ttl}s, 磁盘={enable_disk})")

    def get(self, key: str) -> Any | None:
        """
        获取缓存值

        Args:
            key: 缓存键

        Returns:
            缓存值，如果不存在或已过期返回 None
        """
        # 尝试从内存获取
        entry = self._cache.get(key)

        if entry is not None:
            if entry.is_expired:
                # 过期，删除
                self.delete(key)
                return None

            # 更新访问计数
            entry.access_count += 1
            return entry.value

        return None

    def set(self, key: str, value: Any, ttl: int | None = None):
        """
        设置缓存

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 生存时间（秒），使用默认值如果为 None
        """
        # 检查缓存大小
        if len(self._cache) >= self._max_size:
            self._evict()

        ttl = ttl or self._default_ttl
        now = time.time()

        entry = CacheEntry(
            value=value,
            created_at=now,
            expires_at=now + ttl
        )

        self._cache[key] = entry

        # 持久化到磁盘
        if self._enable_disk:
            self._save_to_disk(key, entry)

    def delete(self, key: str):
        """
        删除缓存

        Args:
            key: 缓存键
        """
        self._cache.pop(key, None)

        # 删除磁盘缓存
        if self._enable_disk:
            cache_file = self._cache_dir / f"{key}.json"
            if cache_file.exists():
                cache_file.unlink()

    def clear(self):
        """清空所有缓存"""
        self._cache.clear()

        # 清空磁盘缓存
        if self._enable_disk:
            for file in self._cache_dir.glob("*.json"):
                file.unlink()

        logger.info("缓存已清空")

    def get_stats(self) -> dict[str, Any]:
        """
        获取缓存统计

        Returns:
            Dict: 统计信息
        """
        total = len(self._cache)
        expired = sum(1 for entry in self._cache.values() if entry.is_expired)
        active = total - expired
        total_accesses = sum(entry.access_count for entry in self._cache.values())

        # 磁盘缓存大小
        disk_size = 0
        if self._enable_disk:
            disk_size = sum(
                f.stat().st_size
                for f in self._cache_dir.glob("*.json")
                if f.is_file()
            )

        return {
            "total_entries": total,
            "active_entries": active,
            "expired_entries": expired,
            "total_accesses": total_accesses,
            "hit_rate": round(total_accesses / max(1, total_accesses + expired) * 100, 2),
            "disk_cache_size_kb": round(disk_size / 1024, 2),
            "max_size": self._max_size,
        }

    def cleanup(self):
        """清理过期缓存"""
        expired_keys = [
            key for key, entry in self._cache.items()
            if entry.is_expired
        ]

        for key in expired_keys:
            self.delete(key)

        if expired_keys:
            logger.debug(f"清理了 {len(expired_keys)} 个过期缓存")

    def _evict(self):
        """淘汰缓存（LRU策略）"""
        if not self._cache:
            return

        # 找到最少访问的条目
        lru_key = min(
            self._cache.keys(),
            key=lambda k: self._cache[k].access_count
        )

        self.delete(lru_key)
        logger.debug(f"缓存已满，淘汰: {lru_key}")

    def _load_from_disk(self):
        """从磁盘加载缓存"""
        if not self._enable_disk:
            return

        for cache_file in self._cache_dir.glob("*.json"):
            try:
                with open(cache_file) as f:
                    data = json.load(f)

                entry = CacheEntry(**data)
                if not entry.is_expired:
                    self._cache[cache_file.stem] = entry
            except Exception as e:
                logger.warning(f"加载磁盘缓存失败: {cache_file} - {e}")

    def _save_to_disk(self, key: str, entry: CacheEntry):
        """保存缓存到磁盘"""
        if not self._enable_disk:
            return

        try:
            cache_file = self._cache_dir / f"{key}.json"
            with open(cache_file, 'w') as f:
                json.dump(asdict(entry), f)
        except Exception as e:
            logger.warning(f"保存磁盘缓存失败: {key} - {e}")


# 全局缓存实例
channel_cache = ChannelCache()
