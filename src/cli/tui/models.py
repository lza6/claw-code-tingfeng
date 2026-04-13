"""TUI 数据模型

从 textual_dashboard.py 拆分出来
包含: 遥测数据、步骤信息、聊天消息等
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TelemetryData:
    """遥测指标数据"""
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
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
    started_at: float = 0.0
    completed_at: float = 0.0


@dataclass
class ChatMessage:
    """聊天消息"""
    role: str  # user, assistant, system
    content: str
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiffLine:
    """Diff 行"""
    text: str
    line_type: str = "context"  # added, removed, context
    line_number: int = 0


@dataclass
class HealingEvent:
    """自愈事件"""
    error_type: str
    fix_strategy: str
    success: bool
    timestamp: float = 0.0
    duration_ms: float = 0.0


@dataclass
class ConfidenceHistory:
    """信心历史"""
    values: list[float] = field(default_factory=list)
    timestamps: list[float] = field(default_factory=list)


@dataclass
class ReasoningStep:
    """推理步骤"""
    step_type: str  # thought, action, observation, reflection
    content: str
    confidence: float = 0.5
    timestamp: float = 0.0


@dataclass
class ToolProbability:
    """工具执行概率"""
    tool_name: str
    probability: float = 0.0
    execution_time_ms: float = 0.0


@dataclass
class ResourceMetrics:
    """资源指标"""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_used_mb: float = 0.0
    disk_io_read: float = 0.0
    disk_io_write: float = 0.0
    network_in: float = 0.0
    network_out: float = 0.0
