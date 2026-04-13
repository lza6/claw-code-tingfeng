"""Dashboard — 仪表盘组件模块

模块结构:
- panels.py: 面板组件 (BreathingPanel, StreamingMarkdownView)
- thinking.py: 思维画布组件 (ThinkingCanvas, ReasoningChain, ExecutionTree, ResourceMonitorChart)
- animations.py: 微动效组件 (TypewriterEffect, ParallaxScrollContainer)

导出:
- 所有组件统一从本模块导出
"""
# 从 dashboard_widgets 重导出 (保持向后兼容)
from ..dashboard_widgets import (
    AnimatedProgressBar,
    SelfHealingPanel,
    SelfHealingStatsPanel,
    StepTracker,
    TelemetryPanel,
)
from .animations import (
    ParallaxScrollContainer,
    TypewriterEffect,
)
from .panels import (
    BreathingPanel,
    StreamingMarkdownView,
)
from .thinking import (
    ExecutionTree,
    ReasoningChain,
    ResourceMonitorChart,
    ThinkingCanvas,
)

__all__ = [
    # Re-exports from dashboard_widgets
    "AnimatedProgressBar",
    # Panels
    "BreathingPanel",
    # Thinking
    "ExecutionTree",
    # Animations
    "ParallaxScrollContainer",
    "ReasoningChain",
    "ResourceMonitorChart",
    "SelfHealingPanel",
    "SelfHealingStatsPanel",
    "StepTracker",
    "StreamingMarkdownView",
    "TelemetryPanel",
    "ThinkingCanvas",
    "TypewriterEffect",
]
