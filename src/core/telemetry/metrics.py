"""专用指标采集器 — 借鉴 Onyx metrics 体系

添加专用指标采集器，覆盖:
- API 请求指标（延迟、错误率、慢请求）
- LLM 调用指标（token用量、成本、延迟）
- Agent/工具执行指标
- 内存/连接池指标

用法:
    from src.core.metrics_exporter import get_metrics_collector
    from src.core.metrics import api_metrics

    # 记录API请求
    api_metrics.record_request(method="GET", path="/chat", status=200, duration=0.15)

    # 记录LLM调用
    llm_metrics.record_call(model="gpt-4o", provider="openai", tokens=1500, cost=0.03)
"""
from __future__ import annotations

import threading
import time
from typing import Any

from src.core.cost_estimator.cost_estimator import MODEL_PRICING, ModelPricing, get_model_pricing
from src.utils.logger import get_logger

from .exporter import MetricsCollector, get_metrics_collector

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# API 请求指标（参考 Onyx slow_requests.py）
# ---------------------------------------------------------------------------

class APIMetricsCollector:
    """API 请求指标采集器

    追踪请求延迟、错误率、慢请求。
    参考 Onyx slow_requests.py 设计。
    """

    SLOW_REQUEST_THRESHOLD = 1.0  # 秒

    def __init__(self, collector: MetricsCollector | None = None):
        self._collector = collector or get_metrics_collector()
        self._lock = threading.Lock()
        self._slow_requests: list[dict[str, Any]] = []

    def record_request(
        self,
        method: str,
        path: str,
        status: int,
        duration: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """记录API请求指标

        Args:
            method: HTTP方法
            path: 请求路径
            status: 状态码
            duration: 请求耗时（秒）
            labels: 额外标签
        """
        request_labels = labels or {}
        request_labels.setdefault("method", method)
        request_labels.setdefault("path", path)
        request_labels.setdefault("status", str(status))

        # 记录请求总数
        self._collector.increment_counter(
            "http_requests_total",
            value=1.0,
            labels=request_labels,
        )

        # 记录请求延迟
        self._collector.observe_histogram(
            "http_request_duration_seconds",
            value=duration,
            labels=request_labels,
        )

        # 记录错误
        if status >= 400:
            self._collector.increment_counter(
                "http_errors_total",
                value=1.0,
                labels=request_labels,
            )

        # 记录慢请求
        if duration >= self.SLOW_REQUEST_THRESHOLD:
            with self._lock:
                self._slow_requests.append({
                    "method": method,
                    "path": path,
                    "status": status,
                    "duration": duration,
                    "timestamp": time.time(),
                })
                # 仅保留最近100个慢请求
                if len(self._slow_requests) > 100:
                    self._slow_requests = self._slow_requests[-100:]

            logger.warning(
                f"Slow request: {method} {path} took {duration:.3f}s "
                f"(status={status})"
            )

    def get_slow_requests(self) -> list[dict[str, Any]]:
        """获取慢请求列表"""
        with self._lock:
            return list(self._slow_requests)

    def clear_slow_requests(self) -> None:
        """清除慢请求记录"""
        with self._lock:
            self._slow_requests.clear()


# ---------------------------------------------------------------------------
# LLM 调用指标（参考 Onyx cost.py + provider metrics）
# ---------------------------------------------------------------------------

class LLMMetricsCollector:
    """LLM 调用指标采集器

    追踪 token 用量、成本、延迟、错误。
    参考 Onyx llm/cost.py 和 metrics 设计。
    """

    def __init__(self, collector: MetricsCollector | None = None):
        self._collector = collector or get_metrics_collector()

    def record_call(
        self,
        model: str,
        provider: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        cost: float = 0.0,
        duration: float = 0.0,
        status: str = "success",
        labels: dict[str, str] | None = None,
    ) -> None:
        """记录LLM调用指标

        Args:
            model: 模型名称
            provider: 提供商名称
            prompt_tokens: 输入 token 数
            completion_tokens: 输出 token 数
            total_tokens: 总 token 数
            cost: 成本（美元）
            duration: 调用耗时（秒）
            status: 调用状态
            labels: 额外标签
        """
        call_labels = labels or {}
        call_labels.setdefault("model", model)
        call_labels.setdefault("provider", provider)
        call_labels.setdefault("status", status)

        # 记录调用次数
        self._collector.increment_counter(
            "llm_calls_total",
            value=1.0,
            labels=call_labels,
        )

        # 记录 token 用量
        if prompt_tokens > 0:
            self._collector.increment_counter(
                "llm_tokens_prompt",
                value=float(prompt_tokens),
                labels=call_labels,
            )
        if completion_tokens > 0:
            self._collector.increment_counter(
                "llm_tokens_completion",
                value=float(completion_tokens),
                labels=call_labels,
            )
        if total_tokens > 0:
            self._collector.increment_counter(
                "llm_tokens_total",
                value=float(total_tokens),
                labels=call_labels,
            )

        # 记录成本
        if cost > 0:
            self._collector.increment_counter(
                "llm_cost_usd",
                value=cost,
                labels=call_labels,
            )

        # 记录延迟
        if duration > 0:
            self._collector.observe_histogram(
                "llm_latency_seconds",
                value=duration,
                labels=call_labels,
            )

    def record_error(
        self,
        model: str,
        provider: str,
        error_type: str,
        labels: dict[str, str] | None = None,
    ) -> None:
        """记录LLM错误

        Args:
            model: 模型名称
            provider: 提供商名称
            error_type: 错误类型
            labels: 额外标签
        """
        error_labels = labels or {}
        error_labels.setdefault("model", model)
        error_labels.setdefault("provider", provider)
        error_labels.setdefault("error_type", error_type)

        self._collector.increment_counter(
            "llm_errors_total",
            value=1.0,
            labels=error_labels,
        )


# ---------------------------------------------------------------------------
# Agent/工具执行指标
# ---------------------------------------------------------------------------

class AgentMetricsCollector:
    """Agent 执行指标采集器

    追踪 Agent 执行时间、工具调用、步骤数。
    """

    def __init__(self, collector: MetricsCollector | None = None):
        self._collector = collector or get_metrics_collector()

    def record_execution(
        self,
        agent_type: str,
        duration: float,
        steps: int = 0,
        status: str = "success",
        labels: dict[str, str] | None = None,
    ) -> None:
        """记录Agent执行指标

        Args:
            agent_type: Agent类型
            duration: 执行耗时（秒）
            steps: 执行步骤数
            status: 执行状态
            labels: 额外标签
        """
        exec_labels = labels or {}
        exec_labels.setdefault("agent_type", agent_type)
        exec_labels.setdefault("status", status)

        # 记录执行次数
        self._collector.increment_counter(
            "agent_executions_total",
            value=1.0,
            labels=exec_labels,
        )

        # 记录执行延迟
        self._collector.observe_histogram(
            "agent_execution_duration_seconds",
            value=duration,
            labels=exec_labels,
        )

        # 记录步骤数
        if steps > 0:
            self._collector.observe_histogram(
                "agent_steps_per_execution",
                value=float(steps),
                labels=exec_labels,
            )

    def record_tool_call(
        self,
        tool_name: str,
        duration: float,
        status: str = "success",
        labels: dict[str, str] | None = None,
    ) -> None:
        """记录工具调用指标

        Args:
            tool_name: 工具名称
            duration: 调用耗时（秒）
            status: 调用状态
            labels: 额外标签
        """
        tool_labels = labels or {}
        tool_labels.setdefault("tool_name", tool_name)
        tool_labels.setdefault("status", status)

        # 记录调用次数
        self._collector.increment_counter(
            "tool_calls_total",
            value=1.0,
            labels=tool_labels,
        )

        # 记录延迟
        self._collector.observe_histogram(
            "tool_call_duration_seconds",
            value=duration,
            labels=tool_labels,
        )


# ---------------------------------------------------------------------------
# 系统资源指标
# ---------------------------------------------------------------------------

class SystemMetricsCollector:
    """系统资源指标采集器

    追踪内存、文件描述符、线程数等。
    参考 Onyx postgres_connection_pool.py 设计模式。
    """

    def __init__(self, collector: MetricsCollector | None = None):
        self._collector = collector or get_metrics_collector()

    def record_memory_usage(
        self,
        rss_mb: float,
        vms_mb: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """记录内存使用

        Args:
            rss_mb: 常驻内存（MB）
            vms_mb: 虚拟内存（MB）
            labels: 额外标签
        """
        mem_labels = labels or {}
        self._collector.set_gauge(
            "process_memory_rss_mb",
            value=rss_mb,
            labels=mem_labels,
        )
        self._collector.set_gauge(
            "process_memory_vms_mb",
            value=vms_mb,
            labels=mem_labels,
        )

    def record_active_threads(
        self,
        count: int,
        labels: dict[str, str] | None = None,
    ) -> None:
        """记录活跃线程数

        Args:
            count: 线程数
            labels: 额外标签
        """
        self._collector.set_gauge(
            "process_active_threads",
            value=float(count),
            labels=labels,
        )

    def record_open_files(
        self,
        count: int,
        labels: dict[str, str] | None = None,
    ) -> None:
        """记录打开的文件数

        Args:
            count: 文件数
            labels: 额外标签
        """
        self._collector.set_gauge(
            "process_open_files",
            value=float(count),
            labels=labels,
        )


# ---------------------------------------------------------------------------
# 全局专用采集器实例
# ---------------------------------------------------------------------------

_api_metrics: APIMetricsCollector | None = None
_llm_metrics: LLMMetricsCollector | None = None
_agent_metrics: AgentMetricsCollector | None = None
_system_metrics: SystemMetricsCollector | None = None
_init_lock = threading.Lock()


def get_api_metrics() -> APIMetricsCollector:
    """获取API指标采集器"""
    global _api_metrics
    if _api_metrics is None:
        with _init_lock:
            if _api_metrics is None:
                _api_metrics = APIMetricsCollector()
    return _api_metrics


def get_llm_metrics() -> LLMMetricsCollector:
    """获取LLM指标采集器"""
    global _llm_metrics
    if _llm_metrics is None:
        with _init_lock:
            if _llm_metrics is None:
                _llm_metrics = LLMMetricsCollector()
    return _llm_metrics


def get_agent_metrics() -> AgentMetricsCollector:
    """获取Agent指标采集器"""
    global _agent_metrics
    if _agent_metrics is None:
        with _init_lock:
            if _agent_metrics is None:
                _agent_metrics = AgentMetricsCollector()
    return _agent_metrics


def get_system_metrics() -> SystemMetricsCollector:
    """获取系统指标采集器"""
    global _system_metrics
    if _system_metrics is None:
        with _init_lock:
            if _system_metrics is None:
                _system_metrics = SystemMetricsCollector()
    return _system_metrics


def reset_all_metrics() -> None:
    """重置所有指标采集器"""
    from .exporter import reset_metrics_collector
    reset_metrics_collector()
    global _api_metrics, _llm_metrics, _agent_metrics, _system_metrics
    with _init_lock:
        _api_metrics = None
        _llm_metrics = None
        _agent_metrics = None
        _system_metrics = None


__all__ = [
    "MODEL_PRICING",
    "APIMetricsCollector",
    "AgentMetricsCollector",
    "LLMMetricsCollector",
    "ModelPricing",
    "SystemMetricsCollector",
    "get_agent_metrics",
    "get_api_metrics",
    "get_llm_metrics",
    "get_model_pricing",
    "get_system_metrics",
    "reset_all_metrics",
]
