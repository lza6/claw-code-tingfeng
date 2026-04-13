"""Rate Limiter — 速率限制器（参考 Onyx）"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RateLimitConfig:
    """速率限制配置"""
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    requests_per_day: int = 10000
    burst_limit: int = 10  # 突发限制
    token_limit: int | None = None  # Token 限制


@dataclass
class RateLimitStats:
    """速率限制统计"""
    total_requests: int = 0
    rejected_requests: int = 0
    last_reset: datetime = field(default_factory=datetime.utcnow)


class RateLimiter:
    """令牌桶速率限制器"""

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._lock = threading.Lock()

        # 滑动窗口计数器
        self._minute_window: dict[str, list[float]] = defaultdict(list)
        self._hour_window: dict[str, list[float]] = defaultdict(list)
        self._day_window: dict[str, list[float]] = defaultdict(list)

        # 令牌桶
        self._tokens: dict[str, float] = {}
        self._last_refill: dict[str, float] = {}

        # 统计
        self._stats: dict[str, RateLimitStats] = defaultdict(RateLimitStats)

    def _clean_window(self, window: list[float], cutoff: float):
        """清理过期的时间戳"""
        window[:] = [ts for ts in window if ts > cutoff]

    def _get_minute_window(self, key: str) -> list[float]:
        """获取分钟窗口"""
        cutoff = time.time() - 60
        self._clean_window(self._minute_window[key], cutoff)
        return self._minute_window[key]

    def _get_hour_window(self, key: str) -> list[float]:
        """获取小时窗口"""
        cutoff = time.time() - 3600
        self._clean_window(self._hour_window[key], cutoff)
        return self._hour_window[key]

    def _get_day_window(self, key: str) -> list[float]:
        """获取天窗口"""
        cutoff = time.time() - 86400
        self._clean_window(self._day_window[key], cutoff)
        return self._day_window[key]

    def _refill_tokens(self, key: str):
        """补充令牌"""
        now = time.time()
        last = self._last_refill.get(key, now)
        elapsed = now - last

        # 每秒补充 tokens
        refill_rate = self.config.requests_per_minute / 60.0
        current_tokens = self._tokens.get(key, self.config.burst_limit)

        new_tokens = min(
            current_tokens + elapsed * refill_rate,
            self.config.burst_limit
        )

        self._tokens[key] = new_tokens
        self._last_refill[key] = now

    def check(self, key: str, cost: int = 1) -> tuple[bool, dict]:
        """检查请求是否允许

        Returns: (allowed, info)
        """
        with self._lock:
            now = time.time()

            # 检查各窗口限制
            minute_requests = len(self._get_minute_window(key))
            hour_requests = len(self._get_hour_window(key))
            day_requests = len(self._get_day_window(key))

            allowed = True
            reason = ""

            # 分钟限制
            if minute_requests >= self.config.requests_per_minute:
                allowed = False
                reason = "minute_limit"

            # 小时限制
            if hour_requests >= self.config.requests_per_hour:
                allowed = False
                reason = "hour_limit"

            # 天限制
            if day_requests >= self.config.requests_per_day:
                allowed = False
                reason = "day_limit"

            # 令牌桶检查
            self._refill_tokens(key)
            tokens = self._tokens.get(key, self.config.burst_limit)

            if tokens < cost:
                allowed = False
                reason = "rate_limit"

            # 记录请求
            if allowed:
                self._minute_window[key].append(now)
                self._hour_window[key].append(now)
                self._day_window[key].append(now)
                self._tokens[key] = tokens - cost

                self._stats[key].total_requests += 1
            else:
                self._stats[key].rejected_requests += 1

            info = {
                "allowed": allowed,
                "reason": reason,
                "minute_remaining": self.config.requests_per_minute - minute_requests - 1,
                "hour_remaining": self.config.requests_per_hour - hour_requests - 1,
                "day_remaining": self.config.requests_per_day - day_requests - 1,
                "tokens_remaining": int(self._tokens.get(key, 0)),
            }

            return allowed, info

    def reset(self, key: str):
        """重置限制"""
        with self._lock:
            self._minute_window.pop(key, None)
            self._hour_window.pop(key, None)
            self._day_window.pop(key, None)
            self._tokens.pop(key, None)
            self._stats.pop(key, None)

    def get_stats(self, key: str) -> dict:
        """获取统计"""
        stats = self._stats.get(key, RateLimitStats())

        return {
            "total_requests": stats.total_requests,
            "rejected_requests": stats.rejected_requests,
            "rejection_rate": stats.rejected_requests / max(stats.total_requests, 1),
            "minute_requests": len(self._minute_window.get(key, [])),
            "hour_requests": len(self._hour_window.get(key, [])),
            "day_requests": len(self._day_window.get(key, [])),
        }


class TokenRateLimiter(RateLimiter):
    """基于 Token 的速率限制器"""

    def __init__(self, config: RateLimitConfig):
        super().__init__(config)

    def check_tokens(self, key: str, tokens: int) -> tuple[bool, dict]:
        """检查 Token 使用"""
        return self.check(key, cost=tokens)


# 全局实例
_rate_limiter: RateLimiter | None = None
_token_rate_limiter: TokenRateLimiter | None = None


def get_rate_limiter(config: RateLimitConfig | None = None) -> RateLimiter:
    """获取全局速率限制器"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(config or RateLimitConfig())
    return _rate_limiter


def get_token_rate_limiter(config: RateLimitConfig | None = None) -> TokenRateLimiter:
    """获取 Token 速率限制器"""
    global _token_rate_limiter
    if _token_rate_limiter is None:
        _token_rate_limiter = TokenRateLimiter(config or RateLimitConfig())
    return _token_rate_limiter


__all__ = [
    "RateLimitConfig",
    "RateLimitStats",
    "RateLimiter",
    "TokenRateLimiter",
    "get_rate_limiter",
    "get_token_rate_limiter",
]
