"""Rich Console + 颜色系统封装 — 与现有 ANSI 系统共存

设计目标:
- 不替换现有 ANSI 颜色函数，而是共存
- 新增 Rich Console 单例 + HSL 标准色值主题
- 毛玻璃面板工厂函数
- Glassmorphism 质感通过半透明边框 + 圆角实现
- HSL Pulse 动态色彩系统 (V5.0 Omni-Glow)
"""
from __future__ import annotations

import math

from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

# ---------------------------------------------------------------------------
# HSL 标准色值 (V5.0 Omni-Glow)
# ---------------------------------------------------------------------------

# 基础色彩
BLUE = "#00d7ff"
GREEN = "#87ff00"
YELLOW = "#ffd700"
RED = "#ff5555"
PURPLE = "#af87ff"
CYAN = "#00ffff"
GRAY = "#8a8a8a"
DARK_GRAY = "#4a4a4a"
WHITE = "#ffffff"

# V5.0 HSL 状态色彩
HSL_IDLE = (230, 20, 15)       # 深智监护状态
HSL_THINKING = (260, 80, 25)   # 神经网络推理
HSL_ALERT = (0, 70, 20)        # 高度敏感核心组件
HSL_SUCCESS = (140, 60, 20)    # 任务达成感反馈
HSL_WARNING = (45, 80, 25)     # 警告状态

# 边框色彩
BORDER_PRIMARY = (190, 80, 50)  # Cyan glow
BORDER_GLOW = (260, 80, 60)     # Purple glow
BORDER_SUCCESS = (140, 60, 50)  # Green
BORDER_ALERT = (0, 70, 50)      # Red


def hsl_to_hex(h: float, s: float, l: float) -> str:
    """HSL 转 HEX 颜色

    参数:
        h: 色相 [0, 360]
        s: 饱和度 [0, 100]
        l: 亮度 [0, 100]

    返回:
        HEX 颜色字符串
    """
    s_norm = s / 100
    l_norm = l / 100
    a = s_norm * min(l_norm, 1 - l_norm)

    def f(n: float) -> float:
        k = (n + h / 30) % 12
        return l_norm - a * max(-1, min(k - 3, 9 - k, 1))

    return f"#{int(f(0) * 255):02x}{int(f(8) * 255):02x}{int(f(4) * 255):02x}"


def hsl_pulse(
    base_hsl: tuple[float, float, float],
    phase: float,
    intensity: float = 0.3
) -> str:
    """HSL 脉冲色彩 — 动态呼吸效果

    参数:
        base_hsl: 基础 HSL 颜色 (h, s, l)
        phase: 动画相位 [0, 1]
        intensity: 脉冲强度 [0, 1]

    返回:
        HEX 颜色字符串
    """
    h, s, l = base_hsl

    # 使用正弦波模拟呼吸效果
    pulse = math.sin(phase * 2 * math.pi) * 0.5 + 0.5

    # 调整亮度和饱和度
    new_l = min(100, l + pulse * intensity * 20)
    new_s = min(100, s + pulse * intensity * 15)

    return hsl_to_hex(h, new_s, new_l)


def get_state_color(
    state: str,
    phase: float | None = None
) -> str:
    """获取状态颜色 (支持动态脉冲)

    参数:
        state: 状态字符串 (idle, thinking, alert, success, warning)
        phase: 动画相位 (可选，用于脉冲效果)

    返回:
        HEX 颜色字符串
    """
    state_map = {
        "idle": HSL_IDLE,
        "thinking": HSL_THINKING,
        "alert": HSL_ALERT,
        "success": HSL_SUCCESS,
        "warning": HSL_WARNING,
    }

    hsl = state_map.get(state, HSL_IDLE)

    if phase is not None:
        return hsl_pulse(hsl, phase)

    return hsl_to_hex(*hsl)


# ---------------------------------------------------------------------------
# Rich Theme (V5.0 增强版)
# ---------------------------------------------------------------------------

RICH_THEME = Theme({
    "primary": BLUE,
    "success": GREEN,
    "warning": YELLOW,
    "error": RED,
    "info": PURPLE,
    "idle": CYAN,
    "dim": GRAY,
    "border": DARK_GRAY,
    # V5.0 新增
    "hsl_idle": hsl_to_hex(*HSL_IDLE),
    "hsl_thinking": hsl_to_hex(*HSL_THINKING),
    "hsl_alert": hsl_to_hex(*HSL_ALERT),
    "hsl_success": hsl_to_hex(*HSL_SUCCESS),
    "hsl_warning": hsl_to_hex(*HSL_WARNING),
    "border_glow": hsl_to_hex(*BORDER_PRIMARY),
    "border_alert": hsl_to_hex(*BORDER_ALERT),
})


# ---------------------------------------------------------------------------
# ClawGod Green Theme (V5.1)
# ---------------------------------------------------------------------------

def get_clawgod_green_theme() -> Theme:
    """获取 ClawGod 绿色主题的 Rich Theme 对象。

    绿色主题覆盖以下样式:
    - primary: #22c55e (ClawGod green)
    - success: #22c55e
    - border: #16a34a
    - warning: #eab308
    - error: #ef4444
    - info: #22c55e

    返回:
        Rich Theme 对象
    """
    return Theme({
        "primary": "#22c55e",
        "success": "#22c55e",
        "border": "#16a34a",
        "warning": "#eab308",
        "error": "#ef4444",
        "info": "#22c55e",
        "idle": "#4A7C59",
        "dim": GRAY,
        # V5.0 HSL 色彩覆盖为绿色系
        "hsl_idle": "#4A7C59",
        "hsl_thinking": "#22c55e",
        "hsl_alert": "#D94F4F",
        "hsl_success": "#22c55e",
        "hsl_warning": "#D9A84F",
        "border_glow": "#22c55e",
        "border_alert": "#D94F4F",
    })


def apply_green_theme_if_enabled() -> Theme:
    """检查 green_theme 功能标志，返回对应的 Rich Theme。

    当 green_theme 功能标志启用时返回 ClawGod 绿色主题，
    否则返回默认主题 RICH_THEME。

    返回:
        适用的 Rich Theme 对象
    """
    try:
        from .features import features
        if features.is_enabled("green_theme"):
            return get_clawgod_green_theme()
    except Exception:
        pass
    return RICH_THEME

# ---------------------------------------------------------------------------
# Console 单例
# ---------------------------------------------------------------------------

_console: Console | None = None


def get_console() -> Console:
    """获取或创建全局 Console 实例

    自动根据 green_theme 功能标志选择合适的主题。
    """
    global _console
    if _console is None:
        _console = Console(
            theme=apply_green_theme_if_enabled(),
            force_terminal=True,
            width=100,
        )
    return _console


def reset_console() -> None:
    """重置 Console 缓存（测试用）"""
    global _console
    _console = None

# ---------------------------------------------------------------------------
# Rich Text 便捷函数
# ---------------------------------------------------------------------------


def r_primary(text: str) -> Text:
    """科技蓝 — 标题/主色调"""
    return Text(text, style=f"bold {BLUE}")


def r_success(text: str) -> Text:
    """成功绿 — 完成状态"""
    return Text(text, style=f"bold {GREEN}")


def r_warning(text: str) -> Text:
    """警示黄 — 警告/思考中"""
    return Text(text, style=f"bold {YELLOW}")


def r_error(text: str) -> Text:
    """错误红 — 失败状态"""
    return Text(text, style=f"bold {RED}")


def r_info(text: str) -> Text:
    """紫罗兰 — 信息/AI 推理"""
    return Text(text, style=f"bold {PURPLE}")


def r_idle(text: str) -> Text:
    """青色 — 空闲/就绪"""
    return Text(text, style=CYAN)


def r_dim(text: str) -> Text:
    """灰色 — 次要文字"""
    return Text(text, style=f"dim {GRAY}")


def r_hsl_state(text: str, state: str, phase: float | None = None) -> Text:
    """V5.0 HSL 状态文本 — 支持动态色彩

    参数:
        text: 显示文本
        state: 状态 (idle, thinking, alert, success, warning)
        phase: 动画相位 (可选)

    返回:
        Rich Text 对象
    """
    color = get_state_color(state, phase)
    return Text(text, style=f"bold {color}")

# ---------------------------------------------------------------------------
# 面板工厂（Glassmorphism + V5.0 增强）
# ---------------------------------------------------------------------------


def glass_panel(
    content: RenderableType,
    title: str = "",
    border_style: str = BLUE,
    padding: tuple[int, int] = (0, 2),
    state: str | None = None,
    phase: float | None = None,
) -> Panel:
    """毛玻璃质感面板 — V5.0 增强版

    参数:
        content: 内容
        title: 标题
        border_style: 边框样式
        padding: 内边距
        state: 状态 (可选，自动选择边框颜色)
        phase: 动画相位 (可选，用于脉冲边框)

    返回:
        Rich Panel 对象
    """
    if state is not None:
        border_style = get_state_color(state, phase)

    return Panel(
        content,
        title=title,
        border_style=border_style,
        padding=padding,
        expand=True,
    )


def status_text(state: str) -> Text:
    """根据状态生成状态文字

    state: "idle" | "thinking" | "executing" | "done" | "error"
    """
    mapping: dict[str, tuple[str, str]] = {
        "idle": (CYAN, "就绪，等待输入"),
        "thinking": (YELLOW, "思考中..."),
        "executing": (BLUE, "执行工具调用..."),
        "done": (GREEN, "任务完成"),
        "error": (RED, "执行出错"),
    }
    color, text = mapping.get(state, (GRAY, "未知状态"))
    return Text(text, style=f"bold {color}")


def status_text_hsl(
    state: str,
    phase: float | None = None,
    custom_text: dict[str, str] | None = None
) -> Text:
    """V5.0 HSL 状态文本 — 支持动态色彩

    参数:
        state: 状态 (idle, thinking, alert, success, warning)
        phase: 动画相位 (可选)
        custom_text: 自定义状态文本映射

    返回:
        Rich Text 对象
    """
    default_text = {
        "idle": "🟢 系统处于深智监护状态",
        "thinking": "🟣 正在进行神经网络推理",
        "alert": "🔴 修改高度敏感核心组件",
        "success": "🟢 任务达成感反馈",
        "warning": "🟡 需要注意",
    }

    text_map = custom_text or default_text
    display_text = text_map.get(state, "⚪ 未知状态")

    color = get_state_color(state, phase)
    return Text(display_text, style=f"bold {color}")
