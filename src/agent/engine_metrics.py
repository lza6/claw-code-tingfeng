"""Agent Engine Metrics — 引擎性能指标管理模块"""
from __future__ import annotations

import asyncio
from typing import Any


class EngineMetrics:
    """管理 Agent 的性能指标与延迟统计"""

    def __init__(self, collector: Any = None) -> None:
        self._perf_metrics: dict[str, Any] = {
            'llm_call_count': 0,
            'llm_total_latency': 0.0,
            'tool_call_count': 0,
            'tool_total_latency': 0.0,
            'tool_error_count': 0,
            'llm_retry_count': 0,
        }
        self._lock = asyncio.Lock()
        self._collector = collector

    async def record_llm_call(self, latency: float, is_retry: bool = False) -> None:
        """记录一次 LLM 调用"""
        async with self._lock:
            self._perf_metrics['llm_call_count'] += 1
            self._perf_metrics['llm_total_latency'] += latency
            if is_retry:
                self._perf_metrics['llm_retry_count'] += 1

        if self._collector and hasattr(self._collector, 'record_latency'):
            self._collector.record_latency('llm', latency)

    async def record_tool_call(self, latency: float, is_error: bool = False) -> None:
        """记录一次工具调用"""
        async with self._lock:
            self._perf_metrics['tool_call_count'] += 1
            self._perf_metrics['tool_total_latency'] += latency
            if is_error:
                self._perf_metrics['tool_error_count'] += 1

    def get_metrics_copy(self) -> dict[str, Any]:
        """获取指标副本"""
        return self._perf_metrics.copy()

    def get_summary(self) -> str:
        """获取性能摘要字符串"""
        m = self._perf_metrics
        llm_avg = m['llm_total_latency'] / max(m['llm_call_count'], 1)
        tool_avg = m['tool_total_latency'] / max(m['tool_call_count'], 1)

        return (
            f'[性能摘要]\n{"=" * 40}\n'
            f'LLM 调用: {m["llm_call_count"]} 次, 总延迟 {m["llm_total_latency"]:.2f}s, 平均 {llm_avg:.3f}s\n'
            f'工具调用: {m["tool_call_count"]} 次, 总延迟 {m["tool_total_latency"]:.2f}s, 平均 {tool_avg:.3f}s\n'
            f'工具错误: {m["tool_error_count"]} 次\n'
            f'LLM 重试: {m["llm_retry_count"]} 次\n{"=" * 40}'
        )
