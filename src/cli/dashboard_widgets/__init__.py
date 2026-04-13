"""Dashboard Widgets — Dashboard 组件模块

用于重构 textual_dashboard.py 的组件集合。

模块结构:
- models.py: 数据模型 (TelemetryData, StepInfo, etc.)
- animations.py: 动画工具函数
- telemetry.py: 遥测面板和进度条
- step_tracker.py: 步骤追踪器
- healing.py: Diff视图、信心渐变、自愈面板
- __init__.py: 统一导出
"""
from .animations import (
    COLOR_CYAN,
    COLOR_DEEP_PURPLE,
    COLOR_GRAY,
    COLOR_GREEN,
    COLOR_RED,
    COLOR_YELLOW,
    ease_in_out,
    ease_out_cubic,
    hsl_to_hex,
    lerp,
)
from .healing import (
    ConfidenceGradient,
    DiffView,
    SelfHealingPanel,
    SelfHealingStatsPanel,
)
from .models import (
    ChatMessage,
    ConfidenceHistory,
    DiffLine,
    HealingEvent,
    ReasoningStep,
    ResourceMetrics,
    StepInfo,
    TelemetryData,
    ToolProbability,
)
from .step_tracker import StepTracker
from .telemetry import (
    AnimatedProgressBar,
    TelemetryPanel,
)

__all__ = [
    # Animations
    "COLOR_CYAN",
    "COLOR_DEEP_PURPLE",
    "COLOR_GRAY",
    "COLOR_GREEN",
    "COLOR_RED",
    "COLOR_YELLOW",
    # Widgets
    "AnimatedProgressBar",
    # Models
    "ChatMessage",
    "ConfidenceGradient",
    "ConfidenceHistory",
    "DiffLine",
    "DiffView",
    "HealingEvent",
    "ReasoningStep",
    "ResourceMetrics",
    "SelfHealingPanel",
    "SelfHealingStatsPanel",
    "StepInfo",
    "StepTracker",
    "TelemetryData",
    "TelemetryPanel",
    "ToolProbability",
    "ease_in_out",
    "ease_out_cubic",
    "hsl_to_hex",
    "lerp",
]
