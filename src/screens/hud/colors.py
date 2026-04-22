"""HUD 颜色工具

汲取 oh-my-codex-main/src/hud/colors.ts
"""

from __future__ import annotations

import sys

from .constants import ANSI


class ColorSupport:
    """终端颜色支持检测"""

    _enabled: bool = True
    _force: bool | None = None

    @classmethod
    def is_color_enabled(cls) -> bool:
        """检测终端是否支持颜色"""
        if cls._force is not None:
            return cls._force
        if not cls._enabled:
            return False

        # 检查环境变量
        no_color = (
            os.getenv("NO_COLOR") is not None
            or os.getenv("TERM") == "dumb"
            or not sys.stdout.isatty()
        )
        return not no_color

    @classmethod
    def set_force_enabled(cls, enabled: bool) -> None:
        """强制启用/禁用颜色（用于测试）"""
        cls._force = enabled


def colorize(text: str, color: str) -> str:
    """为文本添加颜色"""
    if ColorSupport.is_color_enabled():
        return f"{color}{text}{ANSI.RESET}"
    return text


def green(text: str) -> str:
    """绿色"""
    return colorize(text, ANSI.GREEN)


def yellow(text: str) -> str:
    """黄色"""
    return colorize(text, ANSI.YELLOW)


def cyan(text: str) -> str:
    """青色"""
    return colorize(text, ANSI.CYAN)


def dim(text: str) -> str:
    """暗色/灰色"""
    return colorize(text, ANSI.DIM)


def bold(text: str) -> str:
    """粗体"""
    return colorize(text, ANSI.BOLD)


def get_ralph_color(iteration: int, max_iterations: int) -> str:
    """根据Ralph进度返回颜色

    参考: oh-my-codex-main/src/hud/colors.ts::getRalphColor
    """
    if max_iterations <= 0:
        return ANSI.GREEN

    ratio = iteration / max_iterations

    if ratio < 0.3:
        return ANSI.GREEN
    if ratio < 0.7:
        return ANSI.YELLOW
    return ANSI.RED


import os  # 添加os模块导入，用于环境变量检测
