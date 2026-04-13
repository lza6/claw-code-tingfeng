"""
渠道熔断机制 - 整合自 New-API
自动降级、故障恢复、健康检查
"""

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from loguru import logger


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"  # 关闭（正常）
    OPEN = "open"  # 打开（熔断）
    HALF_OPEN = "half_open"  # 半开（试探）


@dataclass
class CircuitBreakerConfig:
    """熔断器配置"""
    failure_threshold: int = 5  # 失败阈值（连续失败次数）
    success_threshold: int = 3  # 成功阈值（连续成功次数，用于恢复）
    timeout: int = 60  # 熔断超时时间（秒）
    half_open_max_requests: int = 3  # 半开状态最大试探请求数


class CircuitBreaker:
    """
    熔断器（整合自 New-API 的自动熔断机制）

    状态转换:
    CLOSED -> OPEN: 连续失败达到阈值
    OPEN -> HALF_OPEN: 超时时间到达
    HALF_OPEN -> CLOSED: 连续成功达到阈值
    HALF_OPEN -> OPEN: 再次失败
    """

    def __init__(
        self,
        channel_id: str,
        config: CircuitBreakerConfig | None = None
    ):
        """
        初始化熔断器

        Args:
            channel_id: 渠道ID
            config: 熔断器配置
        """
        self.channel_id = channel_id
        self.config = config or CircuitBreakerConfig()

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._opened_at: float | None = None
        self._half_open_requests = 0

        logger.info(f"熔断器已初始化: {channel_id}")

    @property
    def state(self) -> CircuitState:
        """获取当前状态"""
        # 检查是否应该从 OPEN 转换到 HALF_OPEN
        if self._state == CircuitState.OPEN and self._opened_at:
            elapsed = time.time() - self._opened_at
            if elapsed >= self.config.timeout:
                self._transition_to_half_open()

        return self._state

    @property
    def is_available(self) -> bool:
        """是否可用"""
        state = self.state

        if state == CircuitState.CLOSED:
            return True
        elif state == CircuitState.OPEN:
            return False
        elif state == CircuitState.HALF_OPEN:
            # 半开状态允许有限请求
            return self._half_open_requests < self.config.half_open_max_requests

        return False

    def record_success(self):
        """记录成功"""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            self._half_open_requests += 1

            # 检查是否应该恢复到 CLOSED
            if self._success_count >= self.config.success_threshold:
                self._transition_to_closed()
        else:
            # 重置失败计数
            self._failure_count = 0
            self._success_count = 0

        logger.debug(f"渠道 {self.channel_id} 记录成功 (state={self._state.value})")

    def record_failure(self, error: str | None = None):
        """记录失败"""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            # 半开状态失败，立即回到 OPEN
            self._transition_to_open()
            logger.warning(f"渠道 {self.channel_id} 半开状态失败，重新熔断")
        elif self._state == CircuitState.CLOSED:
            # 检查是否达到阈值
            if self._failure_count >= self.config.failure_threshold:
                self._transition_to_open()
                logger.warning(
                    f"渠道 {self.channel_id} 触发熔断 "
                    f"(连续失败 {self._failure_count} 次)"
                )

        logger.debug(f"渠道 {self.channel_id} 记录失败 (state={self._state.value}, error={error})")

    def _transition_to_open(self):
        """转换到 OPEN 状态"""
        self._state = CircuitState.OPEN
        self._opened_at = time.time()
        self._success_count = 0
        self._half_open_requests = 0

        logger.warning(f"渠道 {self.channel_id} -> OPEN (熔断)")

    def _transition_to_half_open(self):
        """转换到 HALF_OPEN 状态"""
        self._state = CircuitState.HALF_OPEN
        self._success_count = 0
        self._failure_count = 0
        self._half_open_requests = 0

        logger.info(f"渠道 {self.channel_id} -> HALF_OPEN (试探恢复)")

    def _transition_to_closed(self):
        """转换到 CLOSED 状态"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at = None
        self._half_open_requests = 0

        logger.info(f"渠道 {self.channel_id} -> CLOSED (恢复正常)")

    def get_stats(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            "channel_id": self.channel_id,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "is_available": self.is_available,
            "opened_at": self._opened_at,
            "time_until_retry": max(0, self.config.timeout - (time.time() - self._opened_at)) if self._opened_at else 0,
        }

    def reset(self):
        """重置熔断器"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        self._opened_at = None
        self._half_open_requests = 0

        logger.info(f"渠道 {self.channel_id} 熔断器已重置")


class CircuitBreakerManager:
    """
    熔断器管理器
    """

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}
        self._default_config = CircuitBreakerConfig()

    def get_or_create(self, channel_id: str, config: CircuitBreakerConfig | None = None) -> CircuitBreaker:
        """
        获取或创建熔断器

        Args:
            channel_id: 渠道ID
            config: 配置

        Returns:
            CircuitBreaker: 熔断器实例
        """
        if channel_id not in self._breakers:
            self._breakers[channel_id] = CircuitBreaker(channel_id, config or self._default_config)

        return self._breakers[channel_id]

    def is_available(self, channel_id: str) -> bool:
        """检查渠道是否可用"""
        breaker = self._breakers.get(channel_id)
        if breaker:
            return breaker.is_available
        return True  # 没有熔断器，默认可用

    def record_success(self, channel_id: str):
        """记录成功"""
        breaker = self._breakers.get(channel_id)
        if breaker:
            breaker.record_success()

    def record_failure(self, channel_id: str, error: str | None = None):
        """记录失败"""
        breaker = self._breakers.get(channel_id)
        if breaker:
            breaker.record_failure(error)

    def get_all_stats(self) -> dict[str, Any]:
        """获取所有熔断器统计"""
        return {
            channel_id: breaker.get_stats()
            for channel_id, breaker in self._breakers.items()
        }

    def get_summary(self) -> dict[str, Any]:
        """获取汇总统计"""
        total = len(self._breakers)
        closed = sum(1 for b in self._breakers.values() if b.state == CircuitState.CLOSED)
        open_count = sum(1 for b in self._breakers.values() if b.state == CircuitState.OPEN)
        half_open = sum(1 for b in self._breakers.values() if b.state == CircuitState.HALF_OPEN)

        return {
            "total_channels": total,
            "healthy_channels": closed,
            "circuit_open_channels": open_count,
            "recovering_channels": half_open,
            "health_rate": round((closed / max(1, total)) * 100, 2),
        }

    def reset_channel(self, channel_id: str):
        """重置渠道熔断器"""
        if channel_id in self._breakers:
            self._breakers[channel_id].reset()

    def reset_all(self):
        """重置所有熔断器"""
        for breaker in self._breakers.values():
            breaker.reset()
        logger.info("所有熔断器已重置")


# 全局熔断器管理器
circuit_breaker_manager = CircuitBreakerManager()
