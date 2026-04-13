"""HUD 状态栏 — 汲取 oh-my-codex 组合式元素渲染器模式

提供 REPL 使用的底部状态栏，显示模型、token、成本、迭代等信息。
支持 minimal/focused/full 三种预设。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..utils.colors import (
    RESET,
    cyan,
    dim,
    format_token_count,
    get_progress_color,
    is_color_enabled,
    yellow,
)

# 分隔符
SEP = dim(' │ ') if is_color_enabled() else ' | '


@dataclass
class HudContext:
    """HUD 渲染所需的上下文数据"""
    model: str = ''
    provider: str = ''
    iteration: int = 0
    max_iterations: int = 10
    total_tokens: int = 0
    total_cost: float = 0.0
    session_turns: int = 0
    workflow_phase: str = ''
    git_branch: str = ''


# ============================================================================
# 元素渲染器（汲取 OMX 组合式模式）
# ============================================================================

def _render_model(ctx: HudContext) -> str | None:
    """渲染模型名"""
    if not ctx.model:
        return None
    # 截取模型名的最后部分
    short = ctx.model.split('/')[-1] if '/' in ctx.model else ctx.model
    return cyan(short)


def _render_iteration(ctx: HudContext) -> str | None:
    """渲染迭代进度（带进度着色）"""
    if ctx.max_iterations <= 0:
        return None
    if ctx.iteration <= 0 and ctx.max_iterations > 0:
        return None
    color = get_progress_color(ctx.iteration, ctx.max_iterations)
    text = f'iter:{ctx.iteration}/{ctx.max_iterations}'
    if not color:
        return text
    return f'{color}{text}{RESET}'


def _render_tokens(ctx: HudContext) -> str | None:
    """渲染 token 用量"""
    if ctx.total_tokens <= 0:
        return None
    return dim(f'tokens:{format_token_count(ctx.total_tokens)}')


def _render_cost(ctx: HudContext) -> str | None:
    """渲染成本"""
    if ctx.total_cost <= 0:
        return None
    return dim(f'${ctx.total_cost:.4f}')


def _render_turns(ctx: HudContext) -> str | None:
    """渲染会话轮次"""
    if ctx.session_turns <= 0:
        return None
    return dim(f'turns:{ctx.session_turns}')


def _render_workflow(ctx: HudContext) -> str | None:
    """渲染工作流阶段"""
    if not ctx.workflow_phase:
        return None
    return yellow(f'workflow:{ctx.workflow_phase}')


def _render_git(ctx: HudContext) -> str | None:
    """渲染 Git 分支"""
    if not ctx.git_branch:
        return None
    return cyan(ctx.git_branch)


# ============================================================================
# 预设配置（汲取 OMX minimal/focused/full 模式）
# ============================================================================

from collections.abc import Callable

ElementRenderer = Callable[[HudContext], str | None]

MINIMAL_ELEMENTS = [_render_model, _render_tokens]
FOCUSED_ELEMENTS = [_render_model, _render_iteration, _render_tokens, _render_cost, _render_turns]
FULL_ELEMENTS = [_render_git, _render_model, _render_iteration, _render_tokens, _render_cost, _render_turns, _render_workflow]


def render_hud(ctx: HudContext, preset: str = 'focused') -> str:
    """渲染 HUD 状态栏

    参数:
        ctx: HUD 上下文数据
        preset: 预设名 ('minimal', 'focused', 'full')

    返回:
        格式化的 ANSI 状态栏字符串
    """
    elements_map = {
        'minimal': MINIMAL_ELEMENTS,
        'focused': FOCUSED_ELEMENTS,
        'full': FULL_ELEMENTS,
    }
    elements = elements_map.get(preset, FOCUSED_ELEMENTS)

    sep = dim(' │ ') if is_color_enabled() else ' | '
    parts = []
    for renderer in elements:
        result = renderer(ctx)
        if result is not None:
            parts.append(result)

    if not parts:
        return ''

    return sep.join(parts)
