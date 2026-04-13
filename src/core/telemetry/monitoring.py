"""
监控指标模块 - 整合自 Onyx 的监控能力

提供:
- Prometheus 指标导出
- 连接池监控
- 自定义指标
- 健康检查
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class MetricsBackend(str, Enum):
    """指标后端"""
    PROMETHEUS = "prometheus"
    STATSD = "statsd"
    NONE = "none"


@dataclass
class MetricValue:
    """指标值"""
    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class MetricsCollector:
    """指标收集器"""

    def __init__(self, backend: MetricsBackend = MetricsBackend.PROMETHEUS):
        self.backend = backend
        self._metrics: dict[str, MetricValue] = {}
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list] = {}

        if backend == MetricsBackend.PROMETHEUS:
            self._init_prometheus()

    def _init_prometheus(self):
        """初始化 Prometheus"""
        try:
            from prometheus_client import Counter  # noqa: F401
            self._prom = True
            logger.info("Prometheus 指标已启用")
        except ImportError:
            logger.warning("prometheus_client 未安装，使用简单指标")
            self._prom = False

    # ===== Counter =====
    def inc_counter(self, name: str, value: float = 1, labels: dict | None = None) -> None:
        """增加计数器"""
        key = self._make_key(name, labels)
        self._counters[key] = self._counters.get(key, 0) + value

    def get_counter(self, name: str, labels: dict | None = None) -> float:
        """获取计数器值"""
        key = self._make_key(name, labels)
        return self._counters.get(key, 0)

    # ===== Gauge =====
    def set_gauge(self, name: str, value: float, labels: dict | None = None) -> None:
        """设置仪表值"""
        key = self._make_key(name, labels)
        self._gauges[key] = value

    def get_gauge(self, name: str, labels: dict | None = None) -> float:
        """获取仪表值"""
        key = self._make_key(name, labels)
        return self._gauges.get(key, 0)

    # ===== Histogram =====
    def observe_histogram(self, name: str, value: float, labels: dict | None = None) -> None:
        """观察直方图值"""
        key = self._make_key(name, labels)
        if key not in self._histograms:
            self._histograms[key] = []
        self._histograms[key].append(value)

    def get_histogram_stats(self, name: str, labels: dict | None = None) -> dict[str, float]:
        """获取直方图统计"""
        key = self._make_key(name, labels)
        values = self._histograms.get(key, [])

        if not values:
            return {"count": 0, "sum": 0, "min": 0, "max": 0, "avg": 0}

        return {
            "count": len(values),
            "sum": sum(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
        }

    # ===== 辅助方法 =====
    def _make_key(self, name: str, labels: dict | None = None) -> str:
        """生成指标键"""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def get_all_metrics(self) -> dict[str, Any]:
        """获取所有指标"""
        return {
            "counters": self._counters.copy(),
            "gauges": self._gauges.copy(),
            "histograms": {
                k: self.get_histogram_stats(k.split("{")[0])
                for k in self._histograms
            },
        }

    def reset(self) -> None:
        """重置所有指标"""
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()


class PostgresPoolMonitor:
    """PostgreSQL 连接池监控"""

    def __init__(self):
        self._metrics = MetricsCollector()

    def record_connection_acquire(self, duration_ms: float) -> None:
        """记录连接获取时间"""
        self._metrics.observe_histogram("postgres_connection_acquire_duration_ms", duration_ms)
        self._metrics.inc_counter("postgres_connections_acquired_total")

    def record_connection_release(self) -> None:
        """记录连接释放"""
        self._metrics.inc_counter("postgres_connections_released_total")

    def set_active_connections(self, count: int) -> None:
        """设置活跃连接数"""
        self._metrics.set_gauge("postgres_active_connections", count)

    def set_idle_connections(self, count: int) -> None:
        """设置空闲连接数"""
        self._metrics.set_gauge("postgres_idle_connections", count)

    def set_pool_size(self, size: int) -> None:
        """设置连接池大小"""
        self._metrics.set_gauge("postgres_pool_size", size)

    def get_metrics(self) -> dict[str, Any]:
        """获取指标"""
        return self._metrics.get_all_metrics()


class RedisPoolMonitor:
    """Redis 连接池监控"""

    def __init__(self):
        self._metrics = MetricsCollector()

    def record_command(self, command: str, duration_ms: float) -> None:
        """记录命令执行"""
        self._metrics.observe_histogram(f"redis_{command}_duration_ms", duration_ms)
        self._metrics.inc_counter("redis_commands_total", labels={"command": command})

    def set_connected(self, connected: bool) -> None:
        """设置连接状态"""
        self._metrics.set_gauge("redis_connected", 1 if connected else 0)

    def set_active_connections(self, count: int) -> None:
        """设置活跃连接数"""
        self._metrics.set_gauge("redis_active_connections", count)


class LLMMonitor:
    """LLM 调用监控"""

    def __init__(self):
        self._metrics = MetricsCollector()

    def record_request(
        self,
        model: str,
        latency_ms: float,
        tokens: int,
        success: bool = True
    ) -> None:
        """记录 LLM 请求"""
        labels = {"model": model, "success": "true" if success else "false"}

        self._metrics.observe_histogram("llm_request_latency_ms", latency_ms, labels)
        self._metrics.inc_counter("llm_requests_total", labels=labels)
        self._metrics.inc_counter("llm_tokens_total", tokens, labels={"model": model})

    def record_error(self, model: str, error_type: str) -> None:
        """记录 LLM 错误"""
        labels = {"model": model, "error_type": error_type}
        self._metrics.inc_counter("llm_errors_total", labels=labels)

    def set_active_requests(self, count: int) -> None:
        """设置活跃请求数"""
        self._metrics.set_gauge("llm_active_requests", count)

    def get_metrics(self) -> dict[str, Any]:
        """获取指标"""
        return self._metrics.get_all_metrics()


class HealthChecker:
    """健康检查"""

    def __init__(self):
        self._checks: dict[str, Callable] = {}

    def register_check(self, name: str, check_fn: Callable[[], bool]) -> None:
        """注册检查"""
        self._checks[name] = check_fn

    async def check_all(self) -> dict[str, Any]:
        """执行所有检查"""
        results = {}
        for name, check_fn in self._checks.items():
            try:
                result = check_fn() if not asyncio.iscoroutinefunction(check_fn) else await check_fn()
                results[name] = {"status": "healthy" if result else "unhealthy", "checked_at": time.time()}
            except Exception as e:
                results[name] = {"status": "unhealthy", "error": str(e), "checked_at": time.time()}

        overall = "healthy" if all(r.get("status") == "healthy" for r in results.values()) else "unhealthy"
        return {"overall": overall, "checks": results}


class MonitoringSystem:
    """Monitoring System facade for high-level metrics access."""
    def __init__(self, collector: MetricsCollector | None = None) -> None:
        self.collector = collector or get_metrics()

    def get_recent_metrics(self, duration: int = 3600) -> list[dict[str, Any]]:
        """Get recent metrics for optimization analysis."""
        # Simple implementation using in-memory stats
        all_stats = self.collector.get_all_metrics()
        results = []

        # Extract latency bottlenecks from histograms
        for name, stats in all_stats.get("histograms", {}).items():
            if stats.get("max", 0) > 1000:
                results.append({
                    "operation": name,
                    "latency": stats["max"],
                    "avg_latency": stats["avg"],
                    "count": stats["count"]
                })
        return results


# 全局实例
_metrics: MetricsCollector | None = None
_postgres_monitor: PostgresPoolMonitor | None = None
_redis_monitor: RedisPoolMonitor | None = None
_llm_monitor: LLMMonitor | None = None
_health_checker: HealthChecker | None = None


def get_metrics() -> MetricsCollector:
    """获取指标收集器"""
    global _metrics
    if _metrics is None:
        backend = MetricsBackend(os.environ.get("METRICS_BACKEND", "none").lower())
        _metrics = MetricsCollector(backend)
    return _metrics


def get_postgres_monitor() -> PostgresPoolMonitor:
    """获取 Postgres 监控"""
    global _postgres_monitor
    if _postgres_monitor is None:
        _postgres_monitor = PostgresPoolMonitor()
    return _postgres_monitor


def get_redis_monitor() -> RedisPoolMonitor:
    """获取 Redis 监控"""
    global _redis_monitor
    if _redis_monitor is None:
        _redis_monitor = RedisPoolMonitor()
    return _redis_monitor


def get_llm_monitor() -> LLMMonitor:
    """获取 LLM 监控"""
    global _llm_monitor
    if _llm_monitor is None:
        _llm_monitor = LLMMonitor()
    return _llm_monitor


def get_health_checker() -> HealthChecker:
    """获取健康检查器"""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker


@contextmanager
def track_latency(metric_name: str, labels: dict | None = None):
    """追踪延迟上下文管理器"""
    start = time.time()
    try:
        yield
    finally:
        duration_ms = (time.time() - start) * 1000
        get_metrics().observe_histogram(metric_name, duration_ms, labels)
