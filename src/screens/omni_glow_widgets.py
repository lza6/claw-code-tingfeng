"""Omni-Glow V5.0 自定义 Widgets

包含:
- MirrorPane: Shadow Preview 影子预览面板 (40% 宽度右侧弹出)
- ThinkingTree: 实时思维树 (盲文/2x2 Block 字符渲染)
- CodeStreamView: 代码流式预览 (打字机效果)
- RiskIndicator: SIP 高风险行警示
- OmniGlowApp: 主应用入口 (Ctl+B 中断)

注意: 此模块已拆分为更小的模块。导入路径保持向后兼容。
    - omni_glow_models: 数据模型和主题
    - omni_glow_rendering: 渲染工具
    - omni_glow_mirror: MirrorPane
    - omni_glow_tree: ThinkingTree
    - omni_glow_stream: CodeStreamView
    - omni_glow_indicators: RiskIndicator, StatusIndicator
    - omni_glow_app: OmniGlowApp 和启动函数
"""
from __future__ import annotations

# 组件
from .omni_glow_app import OmniGlowApp, start_omni_glow_tui
from .omni_glow_indicators import RiskIndicator, StatusIndicator
from .omni_glow_mirror import MirrorPane

# 重新导出所有公共接口以保持向后兼容
# 主题和颜色
# 数据模型
from .omni_glow_models import (
    COLOR_ALERT,
    COLOR_BORDER_GLOW,
    COLOR_BORDER_PRIMARY,
    COLOR_IDLE,
    COLOR_SUCCESS,
    COLOR_THINKING,
    COLOR_WARNING,
    CodeChunk,
    RiskAlert,
    ThinkingNode,
    _get_theme_colors,
)

# 渲染工具
from .omni_glow_rendering import (
    BLOCK_CHARS,
    BRAILLE_DOTS,
    render_block_progress,
    render_braille_connection,
)
from .omni_glow_stream import CodeStreamView
from .omni_glow_tree import ThinkingTree

# 版本信息
__version__ = "5.0"
__all__ = [  # noqa: RUF022
    # 主题颜色
    "_get_theme_colors",
    "COLOR_ALERT",
    "COLOR_BORDER_GLOW",
    "COLOR_BORDER_PRIMARY",
    "COLOR_IDLE",
    "COLOR_SUCCESS",
    "COLOR_THINKING",
    "COLOR_WARNING",
    # 数据模型
    "CodeChunk",
    "RiskAlert",
    "ThinkingNode",
    # 渲染工具
    "BLOCK_CHARS",
    "BRAILLE_DOTS",
    "render_block_progress",
    "render_braille_connection",
    # 组件
    "CodeStreamView",
    "MirrorPane",
    "OmniGlowApp",
    "RiskIndicator",
    "start_omni_glow_tui",
    "StatusIndicator",
    "ThinkingTree",
]
