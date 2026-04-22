"""HUD 渲染器

汲取 oh-my-codex-main/src/hud/render.ts

将 HudRenderContext 渲染为 ANSI 字符串。
"""

from __future__ import annotations

from datetime import datetime

from .colors import (
    ANSI,
    ColorSupport,
    cyan,
    dim,
    get_ralph_color,
    green,
    yellow,
)
from .constants import SEPARATOR, format_token_count
from .types import HudRenderContext

# 控制字符正则
CONTROL_CHARS_RE = r"[\u0000-\u001f\u007f-\u009f]"


def sanitize_dynamic_text(value: str) -> str:
    """清理动态文本中的控制字符"""
    import re

    return re.sub(CONTROL_CHARS_RE, "", value)


def render_git_branch(ctx: HudRenderContext) -> str | None:
    """渲染 Git 分支"""
    if not ctx.git_branch:
        return None
    git_branch = sanitize_dynamic_text(ctx.git_branch)
    if not git_branch:
        return None
    return cyan(git_branch)


def render_ralph(ctx: HudRenderContext) -> str | None:
    """渲染 Ralph 循环状态"""
    if not ctx.ralph or not ctx.ralph.active:
        return None
    iteration = ctx.ralph.iteration
    max_iterations = ctx.ralph.max_iterations

    if not ColorSupport.is_color_enabled():
        return f"ralph:{iteration}/{max_iterations}"

    color = get_ralph_color(iteration, max_iterations)
    return f"{color}ralph:{iteration}/{max_iterations}{ANSI.RESET}"


def render_ultrawork(ctx: HudRenderContext) -> str | None:
    """渲染 Ultrawork 状态"""
    if not ctx.ultrawork or not ctx.ultrawork.active:
        return None
    return cyan("ultrawork")


def render_autopilot(ctx: HudRenderContext) -> str | None:
    """渲染 Autopilot 状态"""
    if not ctx.autopilot or not ctx.autopilot.active:
        return None
    phase = sanitize_dynamic_text(ctx.autopilot.current_phase or "active") or "active"
    return yellow(f"autopilot:{phase}")


def render_ralplan(ctx: HudRenderContext) -> str | None:
    """渲染 Ralplan 状态"""
    if not ctx.ralplan or not ctx.ralplan.active:
        return None
    iteration = ctx.ralplan.iteration
    planning_complete = ctx.ralplan.planning_complete

    if iteration is not None and isinstance(iteration, int) and iteration > 0:
        max_val = iteration if planning_complete else "?"
        return cyan(f"ralplan:{iteration}/{max_val}")
    else:
        phase = sanitize_dynamic_text(ctx.ralplan.current_phase or "active") or "active"
        return cyan(f"ralplan:{phase}")


def render_deep_interview(ctx: HudRenderContext) -> str | None:
    """渲染 Deep Interview 状态"""
    if not ctx.deep_interview or not ctx.deep_interview.active:
        return None
    phase = sanitize_dynamic_text(ctx.deep_interview.current_phase or "active") or "active"
    lock_suffix = ":lock" if ctx.deep_interview.input_lock_active else ""
    return yellow(f"interview:{phase}{lock_suffix}")


def render_autoresearch(ctx: HudRenderContext) -> str | None:
    """渲染 Autoresearch 状态"""
    if not ctx.autoresearch or not ctx.autoresearch.active:
        return None
    phase = sanitize_dynamic_text(ctx.autoresearch.current_phase or "active") or "active"
    return cyan(f"research:{phase}")


def render_ultraqa(ctx: HudRenderContext) -> str | None:
    """渲染 Ultraqa 状态"""
    if not ctx.ultraqa or not ctx.ultraqa.active:
        return None
    phase = sanitize_dynamic_text(ctx.ultraqa.current_phase or "active") or "active"
    return green(f"qa:{phase}")


def render_team(ctx: HudRenderContext) -> str | None:
    """渲染 Team 状态"""
    if not ctx.team or not ctx.team.active:
        return None
    count = ctx.team.agent_count
    name = sanitize_dynamic_text(ctx.team.team_name or "")

    if count is not None and count > 0:
        return green(f"team:{count} workers")
    if name:
        return green(f"team:{name}")
    return green("team")


def render_turns(ctx: HudRenderContext) -> str | None:
    """渲染 Turns 计数"""
    if not ctx.metrics:
        return None

    # 检查是否是当前会话的指标
    if ctx.session and ctx.session.started_at and ctx.metrics.last_activity:
        session_start = ctx.session.started_at
        last_activity = ctx.metrics.last_activity
        if isinstance(session_start, datetime) and isinstance(last_activity, datetime):
            if last_activity < session_start:
                return None

    return dim(f"turns:{ctx.metrics.session_turns}")


def render_tokens(ctx: HudRenderContext) -> str | None:
    """渲染 Token 计数"""
    if not ctx.metrics:
        return None

    total = (
        ctx.metrics.session_total_tokens
        or (ctx.metrics.session_input_tokens or 0)
        + (ctx.metrics.session_output_tokens or 0)
    )

    if not total or total <= 0:
        return None

    return dim(f"tokens:{format_token_count(total)}")


def render_hud(
    ctx: HudRenderContext,
    config: HudConfig | None = None,
) -> str:
    """渲染完整 HUD 显示

    Args:
        ctx: 渲染上下文
        config: HUD 配置（默认使用全局配置）

    Returns:
        渲染后的 ANSI 字符串
    """
    if config is None:
        from .state import HudStateManager

        config = HudStateManager.get_instance().get_config()

    # 收集组件渲染结果
    components = []

    # 按配置的顺序渲染组件
    for component_name in config.components:
        render_func = RENDERER_MAP.get(component_name)
        if render_func:
            result = render_func(ctx)
            if result:
                components.append(result)

    # 如果没有配置组件，返回空
    if not components:
        return ""

    # 用分隔符连接
    return SEPARATOR.join(components)


# 组件名称到渲染函数的映射
RENDERER_MAP = {
    "git_branch": render_git_branch,
    "ralph": render_ralph,
    "ultrawork": render_ultrawork,
    "autopilot": render_autopilot,
    "ralplan": render_ralplan,
    "deep_interview": render_deep_interview,
    "autoresearch": render_autoresearch,
    "ultraqa": render_ultraqa,
    "team": render_team,
    "turns": render_turns,
    "tokens": render_tokens,
}


def watch_render_loop(
    render_fn,
    interval_ms: int = 1000,
    signal=None,
    on_error=None,
) -> None:
    """HUD 监视渲染循环

    参考: oh-my-codex-main/src/hud/index.ts::watchRenderLoop

    Args:
        render_fn: 渲染函数（异步）
        interval_ms: 刷新间隔（毫秒）
        signal: 中止信号
        on_error: 错误处理回调
    """
    import asyncio
    import time

    while not (signal and signal.aborted):
        started_at = time.time()
        try:
            import asyncio

            asyncio.run(render_fn())
        except Exception as e:
            if on_error:
                on_error(e)

        # 计算等待时间
        elapsed = time.time() - started_at
        wait_time = max(0, (interval_ms / 1000) - elapsed)
        time.sleep(wait_time)
