"""
Mode State Context - 模式状态上下文

从 oh-my-codex-main/src/state/mode-state-context.ts 转换而来。
提供模式运行时上下文管理。
"""

import datetime
import os
from dataclasses import dataclass
from typing import Any


@dataclass
class ModeStateContext:
    """模式状态上下文"""
    active: bool = False
    tmux_pane_id: str | None = None
    tmux_pane_set_at: str | None = None
    extra: dict[str, Any] = None

    def __post_init__(self):
        if self.extra is None:
            self.extra = {}


def capture_tmux_pane_from_env(env: dict | None = None) -> str | None:
    """从环境变量捕获 tmux pane"""
    env = env or os.environ
    pane = env.get("TMUX_PANE")
    if pane and isinstance(pane, str):
        return pane.strip() if pane.strip() else None
    return None


def has_non_empty_string(value: Any) -> bool:
    """检查是否有非空字符串"""
    return isinstance(value, str) and value.strip() != ""


def with_mode_runtime_context(
    existing: ModeStateContext,
    next_state: ModeStateContext,
    env: dict | None = None,
    now_iso: str | None = None,
) -> ModeStateContext:
    """合并模式运行时上下文"""
    env = env or os.environ
    now_iso = now_iso or datetime.datetime.utcnow().isoformat()

    was_active = existing.active is True
    is_active = next_state.active is True
    has_pane = has_non_empty_string(next_state.tmux_pane_id)

    # 如果激活且之前未激活或没有 pane，则尝试捕获
    if is_active and (not was_active or not has_pane):
        pane = capture_tmux_pane_from_env(env)
        if pane:
            next_state.tmux_pane_id = pane
            if not has_non_empty_string(next_state.tmux_pane_set_at):
                next_state.tmux_pane_set_at = now_iso

    return next_state
