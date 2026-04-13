"""
多Key轮询机制 - 整合自 New-API
支持单渠道多API Key，自动轮询和故障转移
"""

import time
from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass
class ApiKeyInfo:
    """API Key 信息"""
    key: str
    enabled: bool = True
    success_count: int = 0
    failure_count: int = 0
    last_used_time: float | None = None
    rate_limited_until: float | None = None  # 限流解除时间

    @property
    def is_available(self) -> bool:
        """是否可用"""
        if not self.enabled:
            return False

        # 检查是否被限流
        return not (self.rate_limited_until and time.time() < self.rate_limited_until)

    @property
    def success_rate(self) -> float:
        """成功率"""
        total = self.success_count + self.failure_count
        if total == 0:
            return 100.0
        return (self.success_count / total) * 100

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "key_masked": self.key[:8] + "..." + self.key[-4:],
            "enabled": self.enabled,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": round(self.success_rate, 2),
            "is_available": self.is_available,
        }


class MultiKeyRotator:
    """
    多Key轮询器（整合自 New-API 的多Key模式）

    功能:
    - 单渠道配置多个API Key
    - 自动轮询使用
    - 故障自动跳过
    - 限流自动等待
    """

    def __init__(self, channel_id: str, keys: list[str]):
        """
        初始化

        Args:
            channel_id: 渠道ID
            keys: API Key列表
        """
        self.channel_id = channel_id
        self._keys = [ApiKeyInfo(key=key) for key in keys]
        self._current_index = 0
        self._lock = False  # 简单锁机制

        logger.info(f"多Key轮询器已初始化: {channel_id} ({len(keys)} 个Key)")

    def get_next_key(self) -> str | None:
        """
        获取下一个可用的API Key（轮询策略）

        策略:
        1. 从当前位置开始查找
        2. 跳过不可用的Key
        3. 如果所有Key都不可用，返回None

        Returns:
            API Key，如果没有可用Key返回None
        """
        if not self._keys:
            return None

        total = len(self._keys)

        # 遍历所有Key
        for i in range(total):
            index = (self._current_index + i) % total
            key_info = self._keys[index]

            if key_info.is_available:
                # 更新当前位置
                self._current_index = (index + 1) % total
                key_info.last_used_time = time.time()

                logger.debug(f"选择Key: {key_info.key[:8]}... (索引={index})")
                return key_info.key

        logger.warning(f"所有Key都不可用: {self.channel_id}")
        return None

    def record_success(self, key: str):
        """
        记录成功请求

        Args:
            key: 使用的API Key
        """
        for key_info in self._keys:
            if key_info.key == key:
                key_info.success_count += 1
                break

    def record_failure(self, key: str, is_rate_limited: bool = False, retry_after: int | None = None):
        """
        记录失败请求

        Args:
            key: 使用的API Key
            is_rate_limited: 是否被限流
            retry_after: 重试等待时间（秒）
        """
        for key_info in self._keys:
            if key_info.key == key:
                key_info.failure_count += 1

                # 如果限流，设置等待时间
                if is_rate_limited:
                    wait_time = retry_after or 60  # 默认60秒
                    key_info.rate_limited_until = time.time() + wait_time
                    logger.warning(f"Key {key[:8]}... 被限流，等待 {wait_time} 秒")

                break

    def add_key(self, key: str):
        """
        添加新的API Key

        Args:
            key: API Key
        """
        if not any(k.key == key for k in self._keys):
            self._keys.append(ApiKeyInfo(key=key))
            logger.info(f"已添加Key到 {self.channel_id}: {key[:8]}...")

    def remove_key(self, key: str):
        """
        移除API Key

        Args:
            key: API Key
        """
        self._keys = [k for k in self._keys if k.key != key]
        logger.info(f"已从 {self.channel_id} 移除Key: {key[:8]}...")

    def enable_key(self, key: str):
        """启用Key"""
        for key_info in self._keys:
            if key_info.key == key:
                key_info.enabled = True
                logger.info(f"已启用Key: {key[:8]}...")
                break

    def disable_key(self, key: str):
        """禁用Key"""
        for key_info in self._keys:
            if key_info.key == key:
                key_info.enabled = False
                logger.info(f"已禁用Key: {key[:8]}...")
                break

    def get_stats(self) -> dict[str, Any]:
        """
        获取统计信息

        Returns:
            Dict: 统计信息
        """
        total = len(self._keys)
        available = sum(1 for k in self._keys if k.is_available)
        total_success = sum(k.success_count for k in self._keys)
        total_failure = sum(k.failure_count for k in self._keys)

        return {
            "channel_id": self.channel_id,
            "total_keys": total,
            "available_keys": available,
            "unavailable_keys": total - available,
            "total_success": total_success,
            "total_failure": total_failure,
            "overall_success_rate": round(
                (total_success / max(1, total_success + total_failure)) * 100, 2
            ),
            "keys": [k.to_dict() for k in self._keys],
        }

    def get_all_keys(self) -> list[str]:
        """获取所有Key（掩码）"""
        return [k.key[:8] + "..." + k.key[-4:] for k in self._keys]


# 全局多Key管理器
class MultiKeyManager:
    """多Key管理器"""

    def __init__(self):
        self._rotators: dict[str, MultiKeyRotator] = {}

    def register_channel(self, channel_id: str, keys: list[str]):
        """
        注册渠道的多Key

        Args:
            channel_id: 渠道ID
            keys: API Key列表
        """
        self._rotators[channel_id] = MultiKeyRotator(channel_id, keys)

    def get_rotator(self, channel_id: str) -> MultiKeyRotator | None:
        """
        获取轮询器

        Args:
            channel_id: 渠道ID

        Returns:
            MultiKeyRotator: 轮询器实例
        """
        return self._rotators.get(channel_id)

    def get_key(self, channel_id: str) -> str | None:
        """
        获取下一个可用Key

        Args:
            channel_id: 渠道ID

        Returns:
            API Key
        """
        rotator = self._rotators.get(channel_id)
        if rotator:
            return rotator.get_next_key()
        return None

    def get_stats(self) -> dict[str, Any]:
        """获取所有渠道的统计"""
        return {
            channel_id: rotator.get_stats()
            for channel_id, rotator in self._rotators.items()
        }


# 全局实例
multi_key_manager = MultiKeyManager()
