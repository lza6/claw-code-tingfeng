"""Omni-Glow 数据模型和主题系统

包含:
- 主题颜色系统 (支持 green_theme 动态切换)
- 数据模型 (ThinkingNode, CodeChunk, RiskAlert)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

# ============================================================================
# 主题颜色系统 — 支持绿色主题动态切换
# ============================================================================

def _get_theme_colors() -> dict[str, str]:
    """获取当前主题颜色配置。

    当 green_theme 功能标志启用时返回 ClawGod 绿色主题颜色，
    否则返回默认的紫色/青色主题颜色。

    返回:
        包含所有主题颜色键值对的字典
    """
    try:
        from .utils.features import features
        if features.is_enabled("green_theme"):
            return {
                "idle": "#4A7C59",           # green-muted
                "thinking": "#22c55e",       # ClawGod green
                "alert": "#D94F4F",          # keep red
                "success": "#22c55e",        # ClawGod green
                "warning": "#D9A84F",        # keep yellow
                "border_glow": "#22c55e",    # ClawGod green glow
                "border_primary": "#16a34a", # ClawGod green primary
            }
    except Exception:
        pass

    # 默认主题
    return {
        "idle": "#6B7B8D",           # hsl(230, 20%, 45%)
        "thinking": "#9D4BDB",       # hsl(260, 80%, 55%)
        "alert": "#D94F4F",          # hsl(0, 70%, 55%)
        "success": "#4FAF6F",        # hsl(140, 60%, 50%)
        "warning": "#D9A84F",        # hsl(45, 80%, 55%)
        "border_glow": "#7B68EE",    # Purple glow
        "border_primary": "#00BCD4", # Cyan
    }


# ============================================================================
# 颜色常量 (HSL Pulse) — 初始化为默认主题
# ============================================================================

_THEME = _get_theme_colors()

COLOR_IDLE = _THEME["idle"]
COLOR_THINKING = _THEME["thinking"]
COLOR_ALERT = _THEME["alert"]
COLOR_SUCCESS = _THEME["success"]
COLOR_WARNING = _THEME["warning"]
COLOR_BORDER_GLOW = _THEME["border_glow"]
COLOR_BORDER_PRIMARY = _THEME["border_primary"]

# ============================================================================
# 数据模型
# ============================================================================


@dataclass
class ThinkingNode:
    """思维树节点"""
    node_id: int
    label: str
    confidence: float = 0.0
    status: str = "pending"  # pending, running, success, error
    children: list[int] = field(default_factory=list)
    parent_id: int | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class CodeChunk:
    """代码块数据"""
    content: str
    language: str = "python"
    is_risky: bool = False
    risk_reason: str = ""
    line_start: int = 0
    line_end: int = 0


@dataclass
class RiskAlert:
    """SIP 风险警示"""
    severity: str  # low, medium, high, critical
    message: str
    affected_files: list[str] = field(default_factory=list)
    line_numbers: list[int] = field(default_factory=list)
