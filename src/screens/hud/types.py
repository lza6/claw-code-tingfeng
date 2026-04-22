"""HUD 类型定义

汲取 oh-my-codex-main/src/hud/types.ts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RalphStateForHud:
    """Ralph 循环状态"""
    active: bool
    iteration: int = 0
    max_iterations: int = 10


@dataclass
class UltraworkStateForHud:
    """Ultrawork 状态"""
    active: bool
    reinforcement_count: int | None = None


@dataclass
class AutopilotStateForHud:
    """Autopilot 状态"""
    active: bool
    current_phase: str | None = None


@dataclass
class RalplanStateForHud:
    """Ralplan 状态"""
    active: bool
    current_phase: str | None = None
    iteration: int | None = None
    planning_complete: bool | None = None


@dataclass
class DeepInterviewStateForHud:
    """Deep Interview 状态"""
    active: bool
    current_phase: str | None = None
    input_lock_active: bool = False


@dataclass
class AutoresearchStateForHud:
    """Autoresearch 状态"""
    active: bool
    current_phase: str | None = None


@dataclass
class UltraqaStateForHud:
    """Ultraqa 状态"""
    active: bool
    current_phase: str | None = None


@dataclass
class TeamStateForHud:
    """团队状态"""
    active: bool
    current_phase: str | None = None
    agent_count: int | None = None
    team_name: str | None = None


@dataclass
class HudMetrics:
    """HUD 指标"""
    total_turns: int = 0
    session_turns: int = 0
    last_activity: datetime | None = None
    session_input_tokens: int | None = None
    session_output_tokens: int | None = None
    session_total_tokens: int | None = None


@dataclass
class HudNotifyState:
    """HUD 通知状态"""
    last_turn_at: datetime
    turn_count: int
    last_agent_output: str | None = None


@dataclass
class SessionStateForHud:
    """会话状态"""
    session_id: str
    started_at: datetime
    agent: str | None = None


@dataclass
class GitStateForHud:
    """Git 状态"""
    branch: str | None = None
    commit: str | None = None
    dirty: bool = False


@dataclass
class HudRenderContext:
    """HUD 渲染上下文"""

    # 核心状态
    session: SessionStateForHud | None = None
    git_branch: str | None = None
    metrics: HudMetrics | None = None

    # 工作流状态
    ralph: RalphStateForHud | None = None
    ultrawork: UltraworkStateForHud | None = None
    autopilot: AutopilotStateForHud | None = None
    ralplan: RalplanStateForHud | None = None
    deep_interview: DeepInterviewStateForHud | None = None
    autoresearch: AutoresearchStateForHud | None = None
    ultraqa: UltraqaStateForHud | None = None
    team: TeamStateForHud | None = None

    # 配置
    preset: str = "full"
    color_enabled: bool = True
    width: int | None = None


@dataclass
class HudConfig:
    """HUD 配置"""

    preset: str = "full"
    components: list[str] = field(default_factory=list)
    show_turns: bool = True
    show_tokens: bool = True
    show_git: bool = True
    color_enabled: bool = True
    width: int = 120


# HUD 预设配置
HUD_PRESETS = {
    HUD_PRESET_MINIMAL: HudConfig(
        preset=HUD_PRESET_MINIMAL,
        components=["git_branch", "turns"],
        show_tokens=False,
        show_git=True,
    ),
    HUD_PRESET_FOCUSED: HudConfig(
        preset=HUD_PRESET_FOCUSED,
        components=["git_branch", "ralph", "team", "turns"],
        show_tokens=True,
        show_git=True,
    ),
    HUD_PRESET_FULL: HudConfig(
        preset=HUD_PRESET_FULL,
        components=[
            "git_branch",
            "ralph",
            "ultrawork",
            "autopilot",
            "ralplan",
            "team",
            "turns",
            "tokens",
        ],
        show_tokens=True,
        show_git=True,
    ),
}
