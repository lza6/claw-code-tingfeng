"""CLI 启动横幅 — 类 Claude Code 风格的欢迎界面

汲取 oh-my-codex HUD 的组合式渲染模式，
为 Clawd Code 打造专业的终端启动体验。
"""
from __future__ import annotations

import os

from .. import __version__
from ..utils.colors import (
    bold_cyan,
    bold_green,
    dim,
    green,
)


def _get_brand_color() -> callable:
    """获取当前品牌色函数。

    当 green_theme 功能标志启用时返回 bold_green，
    否则返回默认的 bold_cyan。

    返回:
        颜色包装函数
    """
    try:
        from ..utils.features import features
        if features.is_enabled("green_theme"):
            return bold_green
    except Exception:
        pass
    return bold_cyan


def _get_version() -> str:
    """获取版本号"""
    return __version__


def _get_model_info() -> tuple[str, str]:
    """获取当前 LLM 提供商和模型"""
    provider = os.environ.get('LLM_PROVIDER', 'openai')
    model_map = {
        'openai': 'OPENAI_MODEL',
        'anthropic': 'ANTHROPIC_MODEL',
        'google': 'GOOGLE_MODEL',
        'groq': 'GROQ_MODEL',
        'together': 'TOGETHER_MODEL',
        'mistral': 'MISTRAL_MODEL',
        'deepseek': 'DEEPSEEK_MODEL',
    }
    model_key = model_map.get(provider, 'OPENAI_MODEL')
    model = os.environ.get(model_key, '未设置')
    return provider, model


def _get_workdir() -> str:
    """获取工作目录"""
    workdir = os.environ.get('WORK_DIR', '')
    if not workdir:
        workdir = os.getcwd()
    return workdir


def render_banner() -> str:
    """渲染启动横幅

    返回类 Claude Code 风格的欢迎信息字符串。
    当 green_theme 功能标志启用时，品牌色使用绿色。
    """
    version = _get_version()
    provider, model = _get_model_info()
    workdir = _get_workdir()
    brand = _get_brand_color()

    lines = [
        '',
        f'  {brand("Clawd Code")} {dim(f"v{version}")}',
        f'  {dim(f"{provider}")} {green(model)}',
        f'  {dim(workdir)}',
        '',
        f'  {dim("输入任务描述开始编程，/help 查看命令")}',
        '',
    ]
    return '\n'.join(lines)


def render_compact_banner() -> str:
    """渲染紧凑横幅（用于已启动过的场景）

    当 green_theme 功能标志启用时，品牌色使用绿色。
    """
    version = _get_version()
    provider, model = _get_model_info()
    brand = _get_brand_color()
    return f'{brand("Clawd Code")} {dim(f"v{version}")} · {dim(provider)} {green(model)}'
