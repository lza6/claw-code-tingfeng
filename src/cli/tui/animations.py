"""TUI 动画工具函数

从 textual_dashboard.py 拆分出来
包含: 缓动函数、颜色转换、插值等
"""
from __future__ import annotations

import math


def ease_in_out(t: float) -> float:
    """Ease-in-out 缓动函数 (Sigmoid 风格)

    参数:
        t: 输入值 [0, 1]

    返回:
        缓动后的值 [0, 1]
    """
    return t * t * (3 - 2 * t)


def ease_out_cubic(t: float) -> float:
    """Ease-out cubic 缓动函数

    参数:
        t: 输入值 [0, 1]

    返回:
        缓动后的值 [0, 1]
    """
    return 1 - math.pow(1 - t, 3)


def lerp(start: float, end: float, t: float) -> float:
    """线性插值

    参数:
        start: 起始值
        end: 结束值
        t: 插值因子 [0, 1]

    返回:
        插值结果
    """
    return start + (end - start) * t


def hsl_to_hex(h: float, s: float, l: float) -> str:
    """HSL 转 HEX 颜色

    参数:
        h: 色相 [0, 360]
        s: 饱和度 [0, 1]
        l: 亮度 [0, 1]

    返回:
        HEX 颜色字符串
    """
    s /= 100
    l /= 100
    a = s * min(l, 1 - l)

    def f(n: float) -> float:
        k = (n + h / 30) % 12
        return l - a * max(-1, min(k - 3, 9 - k, 1))

    return f"#{int(f(0) * 255):02x}{int(f(8) * 255):02x}{int(f(4) * 255):02x}"


# 颜色常量 (HSL 呼吸灯)
COLOR_CYAN = "#00BCD4"
COLOR_DEEP_PURPLE = "#673AB7"
COLOR_GREEN = "#4CAF50"
COLOR_YELLOW = "#FFC107"
COLOR_RED = "#F44336"
COLOR_GRAY = "#607D8B"
