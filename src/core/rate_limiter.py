"""
智能限流中间件 - 整合自 New-API
令牌桶算法 + 滑动窗口，防止API滥用
"""

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass
class TokenBucket:
    """令牌桶"""
    capacity: int  # 桶容量
    tokens: float  # 当前令牌数
    refill_rate: float  # 补充速率（个/秒）
    last_refill_time: float  # 上次补充时间

    def consume(self, tokens: int = 1) -> bool:
        """
        消耗令牌

        Args:
            tokens: 要消耗的令牌数

        Returns:
            bool: 是否成功
        """
        # 补充令牌
        self._refill()

        # 检查是否有足够令牌
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True

        return False

    def _refill(self):
        """补充令牌"""
        now = time.time()
        elapsed = now - self.last_refill_time

        # 计算新增令牌
        new_tokens = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill_time = now


class SlidingWindowCounter:
    """滑动窗口计数器"""

    def __init__(self, window_size: int, max_requests: int):
        """
        初始化

        Args:
            window_size: 窗口大小（秒）
            max_requests: 窗口内最大请求数
        """
        self.window_size = window_size
        self.max_requests = max_requests
        self._requests: dict[str, list] = defaultdict(list)

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """
        检查是否允许请求

        Args:
            key: 限流键（如 IP、用户ID、渠道ID）

        Returns:
            Tuple[bool, int]: (是否允许, 剩余请求数)
        """
        now = time.time()
        window_start = now - self.window_size

        # 清理过期记录
        self._requests[key] = [
            t for t in self._requests[key]
            if t > window_start
        ]

        # 检查是否超过限制
        current_count = len(self._requests[key])
        remaining = max(0, self.max_requests - current_count)

        if current_count < self.max_requests:
            # 允许请求
            self._requests[key].append(now)
            return True, remaining - 1
        else:
            # 拒绝请求
            return False, 0

    def reset(self, key: str):
        """重置计数器"""
        self._requests.pop(key, None)


class RateLimiter:
    """
    智能限流器（整合自 New-API 的限流系统）

    功能:
    - 令牌桶算法（平滑限流）
    - 滑动窗口（精确限流）
    - 多维度限流（IP、用户、渠道）
    - 自动告警
    """

    def __init__(
        self,
        # 全局限流
        global_rps: int = 100,
        global_burst: int = 200,

        # 每渠道限流
        channel_rps: int = 30,
        channel_burst: int = 50,

        # 每用户限流
        user_rps: int = 10,
        user_burst: int = 20,

        # 滑动窗口限流（防止突发）
        window_size: int = 60,  # 60秒窗口
        channel_max_per_minute: int = 1000,
        user_max_per_minute: int = 100,
    ):
        """
        初始化限流器

        Args:
            global_rps: 全局每秒请求数
            global_burst: 全局突发容忍
            channel_rps: 每渠道每秒请求数
            channel_burst: 每渠道突发容忍
            user_rps: 每用户每秒请求数
            user_burst: 每用户突发容忍
            window_size: 滑动窗口大小
            channel_max_per_minute: 每渠道每分钟最大请求数
            user_max_per_minute: 每用户每分钟最大请求数
        """
        # 全局令牌桶
        self._global_bucket = TokenBucket(
            capacity=global_burst,
            tokens=global_burst,
            refill_rate=global_rps,
            last_refill_time=time.time()
        )

        # 渠道令牌桶
        self._channel_rps = channel_rps
        self._channel_burst = channel_burst
        self._channel_buckets: dict[str, TokenBucket] = {}

        # 用户令牌桶
        self._user_rps = user_rps
        self._user_burst = user_burst
        self._user_buckets: dict[str, TokenBucket] = {}

        # 滑动窗口计数器
        self._channel_window = SlidingWindowCounter(
            window_size=window_size,
            max_requests=channel_max_per_minute
        )
        self._user_window = SlidingWindowCounter(
            window_size=window_size,
            max_requests=user_max_per_minute
        )

        # 统计
        self._total_allowed = 0
        self._total_denied = 0

        logger.info(f"限流器已初始化 (全局RPS={global_rps}, 渠道RPS={channel_rps}, 用户RPS={user_rps})")

    def check_rate_limit(
        self,
        channel_id: str | None = None,
        user_id: str | None = None,
        ip: str | None = None
    ) -> tuple[bool, dict[str, Any]]:
        """
        检查限流

        Args:
            channel_id: 渠道ID
            user_id: 用户ID
            ip: IP地址

        Returns:
            Tuple[bool, Dict]: (是否允许, 限流信息)
        """
        rate_limit_info = {
            "channel_id": channel_id,
            "user_id": user_id,
            "ip": ip,
            "reason": None,
            "retry_after": 0,
        }

        # 1. 检查全局限流
        if not self._global_bucket.consume():
            self._total_denied += 1
            rate_limit_info["reason"] = "global_rate_limit_exceeded"
            rate_limit_info["retry_after"] = 1.0 / self._global_bucket.refill_rate
            logger.warning("全局限流触发")
            return False, rate_limit_info

        # 2. 检查渠道限流
        if channel_id:
            allowed, info = self._check_channel_limit(channel_id)
            if not allowed:
                self._total_denied += 1
                rate_limit_info.update(info)
                return False, rate_limit_info

        # 3. 检查用户限流
        if user_id:
            allowed, info = self._check_user_limit(user_id)
            if not allowed:
                self._total_denied += 1
                rate_limit_info.update(info)
                return False, rate_limit_info

        # 允许请求
        self._total_allowed += 1
        rate_limit_info["allowed"] = True

        return True, rate_limit_info

    def _check_channel_limit(self, channel_id: str) -> tuple[bool, dict[str, Any]]:
        """检查渠道限流"""
        # 获取或创建渠道桶
        if channel_id not in self._channel_buckets:
            self._channel_buckets[channel_id] = TokenBucket(
                capacity=self._channel_burst,
                tokens=self._channel_burst,
                refill_rate=self._channel_rps,
                last_refill_time=time.time()
            )

        bucket = self._channel_buckets[channel_id]

        # 令牌桶检查
        if not bucket.consume():
            retry_after = 1.0 / bucket.refill_rate
            logger.warning(f"渠道 {channel_id} 触发令牌桶限流")
            return False, {
                "reason": "channel_token_bucket_exhausted",
                "retry_after": retry_after,
            }

        # 滑动窗口检查
        allowed, _remaining = self._channel_window.is_allowed(channel_id)
        if not allowed:
            logger.warning(f"渠道 {channel_id} 触发滑动窗口限流")
            return False, {
                "reason": "channel_sliding_window_exceeded",
                "retry_after": 60.0,  # 1分钟窗口
            }

        return True, {}

    def _check_user_limit(self, user_id: str) -> tuple[bool, dict[str, Any]]:
        """检查用户限流"""
        # 获取或创建用户桶
        if user_id not in self._user_buckets:
            self._user_buckets[user_id] = TokenBucket(
                capacity=self._user_burst,
                tokens=self._user_burst,
                refill_rate=self._user_rps,
                last_refill_time=time.time()
            )

        bucket = self._user_buckets[user_id]

        # 令牌桶检查
        if not bucket.consume():
            retry_after = 1.0 / bucket.refill_rate
            logger.warning(f"用户 {user_id} 触发令牌桶限流")
            return False, {
                "reason": "user_token_bucket_exhausted",
                "retry_after": retry_after,
            }

        # 滑动窗口检查
        allowed, _remaining = self._user_window.is_allowed(user_id)
        if not allowed:
            logger.warning(f"用户 {user_id} 触发滑动窗口限流")
            return False, {
                "reason": "user_sliding_window_exceeded",
                "retry_after": 60.0,
            }

        return True, {}

    def get_stats(self) -> dict[str, Any]:
        """获取限流统计"""
        total = self._total_allowed + self._total_denied
        return {
            "total_requests": total,
            "allowed_requests": self._total_allowed,
            "denied_requests": self._total_denied,
            "denial_rate": round(
                (self._total_denied / max(1, total)) * 100, 2
            ),
            "active_channels": len(self._channel_buckets),
            "active_users": len(self._user_buckets),
        }

    def reset(self, channel_id: str | None = None, user_id: str | None = None):
        """重置限流"""
        if channel_id:
            self._channel_buckets.pop(channel_id, None)
            self._channel_window.reset(channel_id)

        if user_id:
            self._user_buckets.pop(user_id, None)
            self._user_window.reset(user_id)

        logger.info(f"限流已重置 (channel={channel_id}, user={user_id})")


# 全局限流器实例
rate_limiter = RateLimiter()


# ==================== 增强：Token 级别限流 ====================

class TokenRateLimiter:
    """
    Token 级别限流器（整合自 Onyx 的 Token 限流）

    按 Prompt Tokens 和 Completion Tokens 分别限流，
    支持按模型、用户、租户维度。
    """

    def __init__(self):
        # 存储限制配置
        self._limits: dict[str, dict[str, Any]] = {}

        # 滑动窗口（按分钟）
        self._windows: dict[str, dict[str, list]] = {}  # key -> {prompt: [], completion: []}

        # 默认限制
        self._default_limits = {
            "prompt_tokens_per_minute": 100000,
            "completion_tokens_per_minute": 50000,
        }

    def set_limit(
        self,
        key: str,
        prompt_tokens_per_minute: int = 100000,
        completion_tokens_per_minute: int = 50000,
    ):
        """设置限制"""
        self._limits[key] = {
            "prompt_tokens_per_minute": prompt_tokens_per_minute,
            "completion_tokens_per_minute": completion_tokens_per_minute,
        }
        self._windows[key] = {"prompt": [], "completion": []}
        logger.info(f"Token 限流已设置: {key}")

    def check_limit(
        self,
        key: str,
        prompt_tokens: int,
        completion_tokens: int = 0,
    ) -> tuple[bool, dict[str, Any]]:
        """
        检查 Token 限制

        Args:
            key: 限流键（如 user_id, tenant_id, model_name）
            prompt_tokens: Prompt Tokens
            completion_tokens: Completion Tokens

        Returns:
            Tuple[bool, Dict]: (是否允许, 限流信息)
        """
        # 获取限制配置
        limits = self._limits.get(key, self._default_limits)

        # 初始化窗口
        if key not in self._windows:
            self._windows[key] = {"prompt": [], "completion": []}

        now = time.time()
        window_start = now - 60  # 1分钟窗口

        # 清理过期记录
        self._windows[key]["prompt"] = [
            t for t in self._windows[key]["prompt"] if t > window_start
        ]
        self._windows[key]["completion"] = [
            t for t in self._windows[key]["completion"] if t > window_start
        ]

        # 计算当前使用量
        current_prompt = sum(self._windows[key]["prompt"])
        current_completion = sum(self._windows[key]["completion"])

        # 检查限制
        remaining_prompt = limits["prompt_tokens_per_minute"] - current_prompt
        remaining_completion = limits["completion_tokens_per_minute"] - current_completion

        if prompt_tokens > remaining_prompt:
            return False, {
                "reason": "prompt_tokens_limit_exceeded",
                "requested": prompt_tokens,
                "remaining": remaining_prompt,
                "limit": limits["prompt_tokens_per_minute"],
            }

        if completion_tokens > remaining_completion:
            return False, {
                "reason": "completion_tokens_limit_exceeded",
                "requested": completion_tokens,
                "remaining": remaining_completion,
                "limit": limits["completion_tokens_per_minute"],
            }

        # 记录使用
        self._windows[key]["prompt"].append(prompt_tokens)
        self._windows[key]["completion"].append(completion_tokens)

        return True, {
            "remaining_prompt": remaining_prompt - prompt_tokens,
            "remaining_completion": remaining_completion - completion_tokens,
        }

    def get_usage(self, key: str) -> dict[str, Any] | None:
        """获取使用量"""
        if key not in self._windows:
            return None

        limits = self._limits.get(key, self._default_limits)
        now = time.time()
        window_start = now - 60

        current_prompt = sum(
            t for t in self._windows[key]["prompt"] if t > window_start
        )
        current_completion = sum(
            t for t in self._windows[key]["completion"] if t > window_start
        )

        return {
            "prompt_tokens": current_prompt,
            "completion_tokens": current_completion,
            "prompt_limit": limits["prompt_tokens_per_minute"],
            "completion_limit": limits["completion_tokens_per_minute"],
            "prompt_percent": round(current_prompt / limits["prompt_tokens_per_minute"] * 100, 2),
            "completion_percent": round(current_completion / limits["completion_tokens_per_minute"] * 100, 2),
        }


# 全局 Token 限流器实例
token_rate_limiter = TokenRateLimiter()


# ==================== 增强：租户级别限流 ====================

class TenantRateLimiter:
    """
    租户级别限流器（整合自 Onyx 的多租户限流）

    支持租户级别的请求数、Token 数限制。
    """

    def __init__(self):
        self._limits: dict[str, dict[str, Any]] = {}
        self._usage: dict[str, dict[str, Any]] = {}

    def set_limit(
        self,
        tenant_id: str,
        requests_per_minute: int = 60,
        prompt_tokens_per_minute: int = 100000,
        completion_tokens_per_minute: int = 50000,
    ):
        """设置租户限制"""
        self._limits[tenant_id] = {
            "requests_per_minute": requests_per_minute,
            "prompt_tokens_per_minute": prompt_tokens_per_minute,
            "completion_tokens_per_minute": completion_tokens_per_minute,
        }
        logger.info(f"租户限流已设置: {tenant_id}")

    def check_limit(
        self,
        tenant_id: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> tuple[bool, dict[str, Any]]:
        """
        检查租户限制 (真实滑动窗口实现)

        Args:
            tenant_id: 租户ID
            prompt_tokens: Prompt Tokens
            completion_tokens: Completion Tokens

        Returns:
            Tuple[bool, Dict]: (是否允许, 限流信息)
        """
        limits = self._limits.get(tenant_id)
        if not limits:
            return True, {"tenant_id": tenant_id, "limited": False}

        now = time.time()
        window_start = now - 60

        if tenant_id not in self._usage:
            self._usage[tenant_id] = {
                "requests": [],
                "prompt_tokens": [],
                "completion_tokens": []
            }

        usage = self._usage[tenant_id]

        # 清理过期
        usage["requests"] = [t for t in usage["requests"] if t > window_start]
        usage["prompt_tokens"] = [t for t in usage["prompt_tokens"] if t[0] > window_start]
        usage["completion_tokens"] = [t for t in usage["completion_tokens"] if t[0] > window_start]

        # 1. 检查请求数
        if len(usage["requests"]) >= limits["requests_per_minute"]:
            return False, {"reason": "tenant_request_limit_exceeded", "limit": limits["requests_per_minute"]}

        # 2. 检查 Token 数
        current_prompt = sum(t[1] for t in usage["prompt_tokens"])
        current_completion = sum(t[1] for t in usage["completion_tokens"])

        if current_prompt + prompt_tokens > limits["prompt_tokens_per_minute"]:
            return False, {"reason": "tenant_prompt_tokens_limit_exceeded"}

        if current_completion + completion_tokens > limits["completion_tokens_per_minute"]:
            return False, {"reason": "tenant_completion_tokens_limit_exceeded"}

        # 记录使用
        usage["requests"].append(now)
        if prompt_tokens > 0: usage["prompt_tokens"].append((now, prompt_tokens))
        if completion_tokens > 0: usage["completion_tokens"].append((now, completion_tokens))

        return True, {"tenant_id": tenant_id, "limited": True, "remaining_requests": limits["requests_per_minute"] - len(usage["requests"])}

    def get_usage(self, tenant_id: str) -> dict[str, Any] | None:
        """获取租户使用量"""
        return self._usage.get(tenant_id)


# 全局租户限流器实例
tenant_rate_limiter = TenantRateLimiter()
