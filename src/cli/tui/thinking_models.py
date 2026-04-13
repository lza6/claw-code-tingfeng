"""ThinkingCanvas 数据模型与渲染工具

导出:
    StepState, RAGCitation, ExecutionStep

用法:
    from src.cli.tui.thinking_models import RAGCitation, StepState
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


class StepState(str, Enum):
    """执行步骤状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    RECOVERING = "recovering"


@dataclass
class RAGCitation:
    """RAG 引用条目"""
    symbol_name: str
    file_path: str
    weight: float = 0.0       # 0.0 ~ 1.0 GraphRAG 权重
    relation: str = ""        # calls / extends / uses / implements
    line: int = 0
    confidence: float = 0.0   # 检索置信度


@dataclass
class ExecutionStep:
    """执行流单步"""
    step_type: str            # goal / thought / tool_call / observation / recovery
    label: str
    detail: str = ""
    state: StepState = StepState.PENDING
    confidence: float = 0.0
    elapsed_ms: float = 0.0
    tool_name: str = ""
    rag_citations: list[RAGCitation] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    children: list[int] = field(default_factory=list)
    parent_id: int | None = None
    step_id: int = -1         # Assigned by container


# ---------------------------------------------------------------------------
# 渲染工具函数
# ---------------------------------------------------------------------------

# 置信度范围映射 (lo <= weight < hi -> icon)
CONF_RANGES: list[tuple[float, float, str]] = [
    (0.8, 1.01, "\U0001f7e2"),
    (0.5, 0.8,  "\U0001f7e1"),
    (0.0, 0.5,  "\U0001f534"),
]

# Box-drawing constants (avoiding backslash-in-fstring issue)
VBAR = "\u2502"    # │
HLINE = "\u2500"   # ─
LJUNCT = "\u2514"  # └
LJUNCT_EXT = f"{LJUNCT}{HLINE}{HLINE} "  # └──
VBAR_SEP = f" {VBAR} "  #  │  # └──

# 步骤类型图标
STEP_ICONS: dict[str, str] = {
    "goal":        "\u25c6",
    "thought":     "\u25c9",
    "tool_call":   "\u26a1",
    "observation": "\u25c7",
    "recovery":    "\u27f3",
}

# 状态图标
STATE_ICONS: dict[StepState, str] = {
    StepState.PENDING:    "\u25cb",
    StepState.RUNNING:    "\u25c9",
    StepState.SUCCESS:    "\u2713",
    StepState.ERROR:      "\u2717",
    StepState.RECOVERING: "\u27f3",
}

# 颜色映射
_TYPE_COLORS: dict[str, str] = {
    "goal":        "#00BCD4",
    "thought":     "#9D4BDB",
    "tool_call":   "#FFC107",
    "observation": "#4CAF50",
    "recovery":    "#F44336",
}
_STATE_COLORS: dict[StepState, str] = {
    StepState.PENDING:    "#6B7B8D",
    StepState.RUNNING:    "#9D4BDB",
    StepState.SUCCESS:    "#4CAF50",
    StepState.ERROR:      "#F44336",
    StepState.RECOVERING: "#FF9800",
}

log = logging.getLogger(__name__)


def _conf_color_icon(weight: float) -> str:
    """根据权重返回置信度图标"""
    for lo, hi, icon in CONF_RANGES:
        if lo <= weight < hi:
            return icon
    return "\u26aa"


def _heat_bar(value: float, width: int = 12) -> str:
    """模拟热力条"""
    width = max(1, width)
    filled = max(0, min(width, int(value * width)))
    return "\u2588" * filled + "\u2591" * (width - filled)


def _step_type_color(step_type: str) -> str:
    """按步骤类型返回颜色"""
    return _TYPE_COLORS.get(step_type, "#607D8B")


def _state_color(state: StepState) -> str:
    """按状态返回颜色"""
    return _STATE_COLORS.get(state, "#6B7B8D")


def _weight_color_hex(weight: float) -> str:
    """权重 -> 色值 HEX"""
    if weight >= 0.8:
        return "#4CAF50"
    if weight >= 0.5:
        return "#FFC107"
    return "#F44336"


def _render_sparkline(values: list[float], width: int = 24) -> str:
    """用 Unicode sparkline 字符渲染 mini sparkline"""
    chars = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
    width = max(1, width)
    if not values:
        return " " * width
    if len(values) > width:
        step = len(values) / width
        sampled = [values[int(i * step)] for i in range(width)]
    else:
        sampled = values + [0.0] * (width - len(values))
    return "".join(chars[min(int(v * 7), 7)] for v in sampled)
