"""性能指标导出器 — 支持 Prometheus 和 OpenTelemetry 格式

提供企业级性能监控指标导出能力，便于接入外部监控系统。
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricPoint:
    """单个指标点"""
    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class MetricsCollector:
    """性能指标采集器

    线程安全的指标采集，支持多种导出格式。
    """

    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._metrics: list[MetricPoint] = []
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}

    def increment_counter(self, name: str, value: float = 1.0, labels: dict[str, str] | None = None) -> None:
        """增加计数器

        参数:
            name: 指标名称
            value: 增量值
            labels: 标签字典
        """
        with self._lock:
            key = self._make_key(name, labels)
            self._counters[key] = self._counters.get(key, 0) + value
            self._metrics.append(MetricPoint(name=name, value=value, labels=labels or {}))

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """设置仪表盘值

        参数:
            name: 指标名称
            value: 当前值
            labels: 标签字典
        """
        with self._lock:
            key = self._make_key(name, labels)
            self._gauges[key] = value
            self._metrics.append(MetricPoint(name=name, value=value, labels=labels or {}))

    def observe_histogram(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """记录直方图观测值

        参数:
            name: 指标名称
            value: 观测值
            labels: 标签字典
        """
        with self._lock:
            key = self._make_key(name, labels)
            if key not in self._histograms:
                self._histograms[key] = []
            self._histograms[key].append(value)
            self._metrics.append(MetricPoint(name=name, value=value, labels=labels or {}))

    def get_counters(self) -> dict[str, float]:
        """获取所有计数器值"""
        return dict(self._counters)

    def get_gauges(self) -> dict[str, float]:
        """获取所有仪表盘值"""
        return dict(self._gauges)

    def get_histograms(self) -> dict[str, list[float]]:
        """获取所有直方图值"""
        return dict(self._histograms)

    def get_summary(self) -> dict[str, Any]:
        """获取指标摘要"""
        summary: dict[str, Any] = {
            'counters': self.get_counters(),
            'gauges': self.get_gauges(),
            'histograms': {},
        }
        for name, values in self._histograms.items():
            if values:
                summary['histograms'][name] = {
                    'count': len(values),
                    'sum': sum(values),
                    'avg': sum(values) / len(values),
                    'min': min(values),
                    'max': max(values),
                }
        return summary

    def export_prometheus(self) -> str:
        """导出为 Prometheus 文本格式

        返回:
            Prometheus 格式的指标文本
        """
        lines: list[str] = []

        # 导出计数器
        for key, value in self._counters.items():
            name, labels = self._parse_key(key)
            label_str = self._format_labels(labels)
            lines.append(f'# TYPE {name} counter')
            lines.append(f'{name}{label_str} {value}')

        # 导出仪表盘
        for key, value in self._gauges.items():
            name, labels = self._parse_key(key)
            label_str = self._format_labels(labels)
            lines.append(f'# TYPE {name} gauge')
            lines.append(f'{name}{label_str} {value}')

        # 导出直方图摘要
        for key, values in self._histograms.items():
            if values:
                name, labels = self._parse_key(key)
                label_str = self._format_labels(labels)
                lines.append(f'# TYPE {name}_count gauge')
                lines.append(f'{name}_count{label_str} {len(values)}')
                lines.append(f'# TYPE {name}_sum counter')
                lines.append(f'{name}_sum{label_str} {sum(values)}')

        return '\n'.join(lines) + '\n'

    def export_opentelemetry(self) -> dict[str, Any]:
        """导出为 OpenTelemetry 格式

        返回:
            OpenTelemetry 兼容的指标字典
        """
        resource_metrics: list[dict[str, Any]] = []

        # 构建指标列表
        metrics: list[dict[str, Any]] = []

        for key, value in self._counters.items():
            name, labels = self._parse_key(key)
            metrics.append({
                'name': name,
                'description': f'Counter metric: {name}',
                'unit': '1',
                'data': {
                    'data_points': [{
                        'attributes': labels,
                        'time_unix_nano': int(time.time() * 1e9),
                        'value': value,
                    }],
                    'aggregation_temporality': 'AGGREGATION_TEMPORALITY_CUMULATIVE',
                    'is_monotonic': True,
                },
            })

        for key, value in self._gauges.items():
            name, labels = self._parse_key(key)
            metrics.append({
                'name': name,
                'description': f'Gauge metric: {name}',
                'unit': '1',
                'data': {
                    'data_points': [{
                        'attributes': labels,
                        'time_unix_nano': int(time.time() * 1e9),
                        'value': value,
                    }],
                },
            })

        resource_metrics.append({
            'resource': {
                'attributes': {
                    'service.name': 'clawd-code',
                    'service.version': '0.39.0',
                },
            },
            'scope_metrics': [{
                'scope': {'name': 'clawd-code.metrics'},
                'metrics': metrics,
            }],
        })

        return {'resource_metrics': resource_metrics}

    def export_json(self) -> str:
        """导出为 JSON 格式"""
        return json.dumps(self.get_summary(), ensure_ascii=False, indent=2)

    def reset(self) -> None:
        """重置所有指标"""
        with self._lock:
            self._metrics.clear()
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()

    @staticmethod
    def _make_key(name: str, labels: dict[str, str] | None) -> str:
        """生成内部键"""
        if not labels:
            return name
        label_parts = ','.join(f'{k}={v}' for k, v in sorted(labels.items()))
        return f'{name}{{{label_parts}}}'

    @staticmethod
    def _parse_key(key: str) -> tuple[str, dict[str, str]]:
        """解析内部键为名称和标签"""
        if '{' not in key:
            return key, {}
        name, label_part = key.split('{', 1)
        label_part = label_part.rstrip('}')
        labels: dict[str, str] = {}
        for pair in label_part.split(','):
            if '=' in pair:
                k, v = pair.split('=', 1)
                labels[k.strip()] = v.strip()
        return name, labels

    @staticmethod
    def _format_labels(labels: dict[str, str]) -> str:
        """格式化标签为 Prometheus 格式"""
        if not labels:
            return ''
        parts = ','.join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f'{{{parts}}}'


# 全局指标采集器实例 (thread-safe lazy initialization)
_global_collector: MetricsCollector | None = None
_collector_lock = threading.Lock()


def get_metrics_collector() -> MetricsCollector:
    """获取全局指标采集器 (thread-safe)"""
    global _global_collector
    if _global_collector is None:
        with _collector_lock:
            if _global_collector is None:
                _global_collector = MetricsCollector()
    return _global_collector


def reset_metrics_collector() -> None:
    """重置全局指标采集器"""
    global _global_collector
    with _collector_lock:
        _global_collector = MetricsCollector()
