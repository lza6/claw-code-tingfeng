"""CircuitBreaker 渠道熔断器测试。

背景: 该模块此前 **0% 覆盖率**，却位于每次 LLM 调用的热路径上
（`src/llm/channel_selector.py` / `channel_health.py` 依赖它做故障隔离）。
熔断器逻辑错误在生产环境的后果很具体：
- 该熔断的不熔断 → 持续打爆故障渠道
- 不该熔断的熔断 → 全部请求被拒，服务"看起来挂了"

本文件锁定完整状态机 CLOSED → OPEN → HALF_OPEN → CLOSED。
"""

from __future__ import annotations

import time

import pytest
from src.llm.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerManager,
    CircuitState,
)


@pytest.fixture
def config() -> CircuitBreakerConfig:
    """小阈值配置，便于快速驱动状态机"""
    return CircuitBreakerConfig(
        failure_threshold=3,
        success_threshold=2,
        timeout=1,          # 1 秒，测试中可直接 sleep 跨过
        half_open_max_requests=2,
    )


@pytest.fixture
def breaker(config: CircuitBreakerConfig) -> CircuitBreaker:
    return CircuitBreaker("test-channel", config)


# ---------------------------------------------------------------------------
# 初始状态
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_starts_closed_and_available(self, breaker: CircuitBreaker):
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_available is True

    def test_starts_with_zero_counters(self, breaker: CircuitBreaker):
        stats = breaker.get_stats()
        assert stats["failure_count"] == 0
        assert stats["success_count"] == 0
        assert stats["channel_id"] == "test-channel"

    def test_default_config_when_none_given(self):
        b = CircuitBreaker("c")
        assert b.config.failure_threshold == 5
        assert b.config.timeout == 60


# ---------------------------------------------------------------------------
# CLOSED -> OPEN
# ---------------------------------------------------------------------------


class TestClosedToOpen:
    def test_stays_closed_below_threshold(self, breaker: CircuitBreaker, config):
        for _ in range(config.failure_threshold - 1):
            breaker.record_failure("boom")
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_available is True

    def test_opens_at_threshold(self, breaker: CircuitBreaker, config):
        for _ in range(config.failure_threshold):
            breaker.record_failure("boom")
        assert breaker.state == CircuitState.OPEN
        assert breaker.is_available is False

    def test_success_resets_consecutive_failure_count(self, breaker: CircuitBreaker, config):
        """关键语义：阈值衡量的是**连续**失败，成功必须清零计数。

        若实现漏了这个重置，偶发失败累积到阈值也会误熔断。
        """
        breaker.record_failure("a")
        breaker.record_failure("b")
        breaker.record_success()          # 中断连续失败
        breaker.record_failure("c")

        assert breaker.state == CircuitState.CLOSED, "成功之后失败计数应已清零，不该熔断"

    def test_open_circuit_blocks_new_requests(self, breaker: CircuitBreaker, config):
        for _ in range(config.failure_threshold):
            breaker.record_failure()
        assert breaker.is_available is False


# ---------------------------------------------------------------------------
# OPEN -> HALF_OPEN
# ---------------------------------------------------------------------------


class TestOpenToHalfOpen:
    def test_transitions_after_timeout(self, breaker: CircuitBreaker, config):
        for _ in range(config.failure_threshold):
            breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        time.sleep(config.timeout + 0.05)

        assert breaker.state == CircuitState.HALF_OPEN
        assert breaker.is_available is True

    def test_stays_open_before_timeout(self, breaker: CircuitBreaker):
        for _ in range(3):
            breaker.record_failure()
        # 不等待，立即读取
        assert breaker.state == CircuitState.OPEN

    def test_half_open_resets_counters(self, breaker: CircuitBreaker, config):
        for _ in range(config.failure_threshold):
            breaker.record_failure()
        time.sleep(config.timeout + 0.05)

        assert breaker.state == CircuitState.HALF_OPEN
        stats = breaker.get_stats()
        assert stats["failure_count"] == 0
        assert stats["success_count"] == 0


# ---------------------------------------------------------------------------
# HALF_OPEN -> CLOSED
# ---------------------------------------------------------------------------


class TestHalfOpenToClosed:
    def test_recovers_after_enough_successes(self, breaker: CircuitBreaker, config):
        for _ in range(config.failure_threshold):
            breaker.record_failure()
        time.sleep(config.timeout + 0.05)
        assert breaker.state == CircuitState.HALF_OPEN

        for _ in range(config.success_threshold):
            breaker.record_success()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_available is True

    def test_partial_success_keeps_half_open(self, breaker: CircuitBreaker, config):
        for _ in range(config.failure_threshold):
            breaker.record_failure()
        time.sleep(config.timeout + 0.05)

        breaker.record_success()   # 少于 success_threshold
        assert breaker.state == CircuitState.HALF_OPEN


# ---------------------------------------------------------------------------
# HALF_OPEN -> OPEN（试探失败立即重新熔断）
# ---------------------------------------------------------------------------


class TestHalfOpenToOpen:
    def test_single_failure_reopens_immediately(self, breaker: CircuitBreaker, config):
        """半开态失败必须立即回到 OPEN，而不是等下一次阈值累积。

        否则故障渠道会在"半开"状态下被持续放行试探，恢复被无限推迟。
        """
        for _ in range(config.failure_threshold):
            breaker.record_failure()
        time.sleep(config.timeout + 0.05)
        assert breaker.state == CircuitState.HALF_OPEN

        breaker.record_failure("still broken")

        assert breaker.state == CircuitState.OPEN
        assert breaker.is_available is False


# ---------------------------------------------------------------------------
# 半开态请求限流（已知缺陷的锁定测试）
# ---------------------------------------------------------------------------


class TestHalfOpenRequestLimit:
    def test_limit_blocks_after_max_requests(self, breaker: CircuitBreaker, config):
        """半开态达到 half_open_max_requests 后应停止放行"""
        for _ in range(config.failure_threshold):
            breaker.record_failure()
        time.sleep(config.timeout + 0.05)
        assert breaker.state == CircuitState.HALF_OPEN

        # success_threshold(2) == half_open_max_requests(2)，走满即恢复
        for _ in range(config.half_open_max_requests):
            assert breaker.is_available is True
            breaker.record_success()

        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.xfail(
        reason="已知缺陷：_half_open_requests 只在 record_success() 中递增，"
               "失败路径与'请求发起'路径都不计数。因此半开态下并发探测不受限——"
               "half_open_max_requests 形同虚设。修复后本测试应转为 xpass。",
        strict=False,
    )
    def test_failed_probes_also_consume_quota(self, breaker: CircuitBreaker, config):
        for _ in range(config.failure_threshold):
            breaker.record_failure()
        time.sleep(config.timeout + 0.05)
        assert breaker.state == CircuitState.HALF_OPEN

        # 一次失败试探后，额度应被消耗（实际实现不会）
        breaker.record_failure("probe failed")
        assert breaker._half_open_requests > 0


# ---------------------------------------------------------------------------
# reset / stats
# ---------------------------------------------------------------------------


class TestResetAndStats:
    def test_reset_restores_closed(self, breaker: CircuitBreaker, config):
        for _ in range(config.failure_threshold):
            breaker.record_failure()
        assert breaker.state == CircuitState.OPEN

        breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_available is True
        stats = breaker.get_stats()
        assert stats["failure_count"] == 0
        assert stats["opened_at"] is None

    def test_stats_time_until_retry_counts_down(self, breaker: CircuitBreaker, config):
        for _ in range(config.failure_threshold):
            breaker.record_failure()

        first = breaker.get_stats()["time_until_retry"]
        assert first > 0

        time.sleep(0.2)
        second = breaker.get_stats()["time_until_retry"]
        assert second < first

    def test_time_until_retry_zero_when_closed(self, breaker: CircuitBreaker):
        assert breaker.get_stats()["time_until_retry"] == 0


# ---------------------------------------------------------------------------
# CircuitBreakerManager
# ---------------------------------------------------------------------------


class TestCircuitBreakerManager:
    def test_missing_channel_is_available_by_default(self):
        """未注册的渠道不应被当作熔断"""
        mgr = CircuitBreakerManager()
        assert mgr.is_available("never-seen") is True

    def test_get_or_create_is_idempotent(self):
        mgr = CircuitBreakerManager()
        a = mgr.get_or_create("c1")
        b = mgr.get_or_create("c1")
        assert a is b

    def test_per_channel_isolation(self, config):
        """一个渠道熔断不应影响其它渠道 —— 这是熔断器的全部意义"""
        mgr = CircuitBreakerManager()
        b1 = mgr.get_or_create("bad", config)
        mgr.get_or_create("good", config)

        for _ in range(config.failure_threshold):
            b1.record_failure()

        assert mgr.is_available("bad") is False
        assert mgr.is_available("good") is True

    def test_record_on_missing_channel_is_noop(self):
        """记录到未注册渠道不应抛异常，也不应静默创建熔断器"""
        mgr = CircuitBreakerManager()
        mgr.record_success("ghost")
        mgr.record_failure("ghost", "err")
        assert mgr.get_all_stats() == {}

    def test_summary_counts_states(self, config):
        mgr = CircuitBreakerManager()
        mgr.get_or_create("ok", config)
        broken = mgr.get_or_create("broken", config)
        for _ in range(config.failure_threshold):
            broken.record_failure()

        summary = mgr.get_summary()
        assert summary["total_channels"] == 2
        assert summary["healthy_channels"] == 1
        assert summary["circuit_open_channels"] == 1
        assert summary["health_rate"] == 50.0

    def test_summary_empty_manager_does_not_divide_by_zero(self):
        summary = CircuitBreakerManager().get_summary()
        assert summary["total_channels"] == 0
        assert summary["health_rate"] == 0.0

    def test_reset_channel_only_affects_target(self, config):
        mgr = CircuitBreakerManager()
        a = mgr.get_or_create("a", config)
        b = mgr.get_or_create("b", config)
        for _ in range(config.failure_threshold):
            a.record_failure()
            b.record_failure()

        mgr.reset_channel("a")

        assert a.state == CircuitState.CLOSED
        assert b.state == CircuitState.OPEN

    def test_reset_all(self, config):
        mgr = CircuitBreakerManager()
        for name in ("a", "b"):
            br = mgr.get_or_create(name, config)
            for _ in range(config.failure_threshold):
                br.record_failure()

        mgr.reset_all()

        assert all(b.state == CircuitState.CLOSED for b in (mgr.get_or_create("a"), mgr.get_or_create("b")))
