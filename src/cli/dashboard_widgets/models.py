"""Dashboard Models — 数据模型模块

包含所有 dashboard 相关的 dataclass 模型。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class TelemetryData:
    """遥测指标数据"""
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    total_cost: float = 0.0
    llm_calls: int = 0
    tool_calls: int = 0
    avg_latency_ms: float = 0.0
    current_latency_ms: float = 0.0


@dataclass
class StepInfo:
    """工作流步骤信息"""
    name: str
    status: str = "pending"  # pending, running, success, error
    message: str = ""
    timestamp: float = 0.0


@dataclass
class ChatMessage:
    """聊天消息"""
    role: str  # user, assistant, system
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class DiffLine:
    """Diff 行数据"""
    type: str  # added, removed, context, header
    content: str
    line_number: int = 0


@dataclass
class HealingEvent:
    """自愈事件数据"""
    error_type: str
    error_message: str
    fix_strategy: str
    confidence: float = 0.0  # 0.0 - 1.0
    diff_lines: list[DiffLine] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    attempts: int = 0


@dataclass
class ConfidenceHistory:
    """信心历史轨迹"""
    values: list[float] = field(default_factory=list)
    timestamps: list[float] = field(default_factory=list)


@dataclass
class ReasoningStep:
    """推理步骤"""
    step_id: int
    thought: str
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)
    confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)
    children: list[int] = field(default_factory=list)
    parent_id: int | None = None
    status: str = "pending"  # pending, running, success, error


@dataclass
class ToolProbability:
    """工具选择概率"""
    tool_name: str
    probability: float
    reasoning: str = ""


@dataclass
class ResourceMetrics:
    """系统资源指标"""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class RAGMetrics:
    """RAG 索引指标"""
    total_files: int = 0
    indexed_files: int = 0
    total_terms: int = 0
    index_size_bytes: int = 0
    coverage_percent: float = 0.0
    last_update_time: float = field(default_factory=time.time)


@dataclass
class SelfHealingStats:
    """自愈统计数据"""
    total_errors_detected: int = 0
    total_fixes_attempted: int = 0
    total_fixes_successful: int = 0
    success_rate: float = 0.0
    avg_attempts_per_fix: float = 0.0
    last_fix_time: float = 0.0


# 导出所有模型
__all__ = [
    "ChatMessage",
    "ConfidenceHistory",
    "DiffLine",
    "HealingEvent",
    "ReasoningStep",
    "ResourceMetrics",
    "RAGMetrics",
    "SelfHealingStats",
    "StepInfo",
    "TelemetryData",
    "ToolProbability",
]
