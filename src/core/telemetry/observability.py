"""Structured Observability — 企业级结构化日志与性能监控

整合 Onyx 的遥测设计:
- 结构化日志 + JSON 输出
- 性能指标采集
- 审计日志
- 追踪上下文
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

logger = logging.getLogger('observability')

# 追踪上下文
_tracing_context: ContextVar[dict[str, Any]] = ContextVar('tracing_context', default={})


def get_tracing_context() -> dict[str, Any]:
    """获取当前追踪上下文"""
    return _tracing_context.get({})


def set_tracing_context(**kwargs) -> None:
    """设置追踪上下文"""
    ctx = get_tracing_context()
    ctx.update(kwargs)
    _tracing_context.set(ctx)


def clear_tracing_context() -> None:
    """清除追踪上下文"""
    _tracing_context.set({})


@dataclass
class LogEntry:
    timestamp: str
    level: str
    component: str
    event: str
    data: dict[str, Any]
    duration_ms: float | None = None
    trace_id: str | None = None
    span_id: str | None = None


class StructuredLogger:
    """结构化日志管理器，支持 JSON 输出且具备自动轮转能力。

    整合 Onyx 遥测设计:
    - JSON 格式输出
    - 自动追踪 ID 注入
    - 性能计时
    - 审计日志
    """

    def __init__(
        self,
        component: str,
        log_file: Path | None = None,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 5
    ) -> None:
        self.component = component
        self._start_times: dict[str, float] = {}
        self.logger = logging.getLogger(f'clawd.{component}')
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

        # 清除现有处理器
        if self.logger.hasHandlers():
            self.logger.handlers.clear()

        # 添加 JSON 处理器 (输出到文件)
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            self.logger.addHandler(handler)

        # 同时添加控制台处理器 (可选，根据需求)
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        self.logger.addHandler(console)

    def _log(self, level: int, event: str, data: dict[str, Any], duration_ms: float | None = None) -> None:
        """Log a structured entry with automatic trace ID injection."""
        # 获取追踪上下文
        ctx = get_tracing_context()
        trace_id = ctx.get("trace_id") or str(uuid.uuid4())[:8]
        span_id = ctx.get("span_id")

        log_data = {**data}
        if trace_id:
            log_data["trace_id"] = trace_id
        if span_id:
            log_data["span_id"] = span_id

        entry = LogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            level=logging.getLevelName(level),
            component=self.component,
            event=event,
            data=log_data,
            duration_ms=duration_ms,
            trace_id=trace_id,
            span_id=span_id,
        )
        log_msg = json.dumps(asdict(entry), ensure_ascii=False)
        self.logger.log(level, log_msg)

    def info(self, event: str, **kwargs) -> None:
        self._log(logging.INFO, event, kwargs)

    def error(self, event: str, error: Exception | str, **kwargs) -> None:
        data = kwargs
        data['error'] = str(error)
        self._log(logging.ERROR, event, data)

    def warning(self, event: str, **kwargs) -> None:
        self._log(logging.WARNING, event, kwargs)

    def debug(self, event: str, **kwargs) -> None:
        self._log(logging.DEBUG, event, kwargs)

    def start_timer(self, label: str) -> None:
        self._start_times[label] = time.perf_counter()

    def stop_timer(self, label: str, event: str | None = None, **kwargs) -> None:
        if label in self._start_times:
            duration = (time.perf_counter() - self._start_times.pop(label)) * 1000
            self._log(logging.INFO, event or label, kwargs, duration_ms=round(duration, 2))


# ==================== 增强：指标采集器 ====================

class MetricsCollector:
    """
    指标采集器（整合自 Onyx 的遥测系统）

    支持:
    - 计数器 (Counter)
    - 仪表盘 (Gauge)
    - 直方图 (Histogram)
    - 计量 (Meter)
    """

    def __init__(self):
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def increment(self, name: str, value: int = 1) -> None:
        """计数器 +1"""
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def decrement(self, name: str, value: int = 1) -> None:
        """计数器 -1"""
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) - value

    def gauge(self, name: str, value: float) -> None:
        """设置仪表盘值"""
        with self._lock:
            self._gauges[name] = value

    def histogram(self, name: str, value: float) -> None:
        """记录直方图值"""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = []
            self._histograms[name].append(value)
            # 保持最近 1000 个样本
            if len(self._histograms[name]) > 1000:
                self._histograms[name] = self._histograms[name][-1000:]

    def get_metrics(self) -> dict[str, Any]:
        """获取所有指标"""
        with self._lock:
            result = {}

            # 计数器
            for name, value in self._counters.items():
                result[name] = {"type": "counter", "value": value}

            # 仪表盘
            for name, value in self._gauges.items():
                result[name] = {"type": "gauge", "value": value}

            # 直方图
            for name, values in self._histograms.items():
                if values:
                    result[name] = {
                        "type": "histogram",
                        "count": len(values),
                        "min": min(values),
                        "max": max(values),
                        "avg": sum(values) / len(values),
                    }

            return result

    def reset(self) -> None:
        """重置所有指标"""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


# ==================== 增强：审计日志 ====================

class AuditLogger:
    """
    审计日志记录器（整合自 Onyx 的审计日志）

    记录:
    - 用户登录/登出
    - API Key 操作
    - 配置变更
    - 敏感操作
    """

    def __init__(self, log_file: Path | None = None):
        self.log_file = log_file
        self.logger = logging.getLogger('clawd.audit')
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

        if self.logger.hasHandlers():
            self.logger.handlers.clear()

        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                log_file,
                maxBytes=50 * 1024 * 1024,  # 50MB
                backup_count=10,
                encoding='utf-8'
            )
            self.logger.addHandler(handler)

    def log_event(
        self,
        event_type: str,
        user_id: str | None = None,
        tenant_id: str | None = None,
        resource: str | None = None,
        action: str | None = None,
        result: str = "success",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """记录审计事件"""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "resource": resource,
            "action": action,
            "result": result,
            "metadata": metadata or {},
        }
        self.logger.info(json.dumps(entry, ensure_ascii=False))

    def log_login(self, user_id: str, method: str = "password") -> None:
        """记录登录事件"""
        self.log_event("user_login", user_id=user_id, action=method)

    def log_logout(self, user_id: str) -> None:
        """记录登出事件"""
        self.log_event("user_logout", user_id=user_id)

    def log_api_key_created(self, user_id: str, key_id: str) -> None:
        """记录 API Key 创建"""
        self.log_event("api_key_created", user_id=user_id, resource=key_id)

    def log_api_key_deleted(self, user_id: str, key_id: str) -> None:
        """记录 API Key 删除"""
        self.log_event("api_key_deleted", user_id=user_id, resource=key_id)

    def log_config_changed(self, user_id: str, config_key: str, old_value: Any, new_value: Any) -> None:
        """记录配置变更"""
        self.log_event(
            "config_changed",
            user_id=user_id,
            resource=config_key,
            metadata={"old_value": str(old_value), "new_value": str(new_value)},
        )

    def log_rate_limit_exceeded(
        self,
        user_id: str | None,
        tenant_id: str | None,
        limit_type: str,
    ) -> None:
        """记录限流触发"""
        self.log_event(
            "rate_limit_exceeded",
            user_id=user_id,
            tenant_id=tenant_id,
            action=limit_type,
            result="denied",
        )


# 全局指标采集器
metrics_collector = MetricsCollector()


# ==================== 便捷函数 ====================

def create_logger(component: str, log_file: Path | None = None) -> StructuredLogger:
    """创建结构化日志器"""
    return StructuredLogger(component, log_file)


def create_audit_logger(log_file: Path | None = None) -> AuditLogger:
    """创建审计日志器"""
    return AuditLogger(log_file)
