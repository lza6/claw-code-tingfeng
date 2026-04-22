"""HUD 状态管理

汲取 oh-my-codex-main/src/hud/state.ts
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .constants import HUD_PRESETS
from .types import (
    HudConfig,
    HudRenderContext,
)


@dataclass
class HudState:
    """HUD 运行时状态"""

    context: HudRenderContext = field(default_factory=HudRenderContext)
    config: HudConfig = field(default_factory=lambda: HUD_PRESETS["full"])
    last_update: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "context": self._serialize_context(),
            "config": asdict(self.config),
            "last_update": self.last_update.isoformat(),
        }

    def _serialize_context(self) -> dict:
        """序列化渲染上下文"""
        ctx = self.context
        result = {
            "preset": ctx.preset,
            "color_enabled": ctx.color_enabled,
            "width": ctx.width,
        }

        # 可选字段
        if ctx.session:
            result["session"] = {
                "session_id": ctx.session.session_id,
                "started_at": ctx.session.started_at.isoformat(),
                "agent": ctx.session.agent,
            }
        if ctx.git_branch:
            result["git_branch"] = ctx.git_branch
        if ctx.metrics:
            result["metrics"] = {
                "total_turns": ctx.metrics.total_turns,
                "session_turns": ctx.metrics.session_turns,
                "last_activity": ctx.metrics.last_activity.isoformat()
                if ctx.metrics.last_activity
                else None,
                "session_input_tokens": ctx.metrics.session_input_tokens,
                "session_output_tokens": ctx.metrics.session_output_tokens,
                "session_total_tokens": ctx.metrics.session_total_tokens,
            }

        # 工作流状态
        for attr in [
            "ralph",
            "ultrawork",
            "autopilot",
            "ralplan",
            "deep_interview",
            "autoresearch",
            "ultraqa",
            "team",
        ]:
            val = getattr(ctx, attr)
            if val:
                result[attr] = asdict(val)

        return result


class HudStateManager:
    """HUD 状态管理器 - 单例模式"""

    _instance: HudStateManager | None = None
    _state: HudState

    def __init__(self, state_file: Path | None = None):
        self._state = HudState()
        self._state_file = state_file or Path.home() / ".clawd" / "hud_state.json"
        self._load_state()

    @classmethod
    def get_instance(cls) -> HudStateManager:
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_state(self) -> None:
        """从磁盘加载状态"""
        if not self._state_file.exists():
            return

        try:
            with open(self._state_file) as f:
                data = json.load(f)
            # TODO: 反序列化到 self._state
        except Exception:
            pass  # 忽略错误，使用默认状态

    def _save_state(self) -> None:
        """保存状态到磁盘"""
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._state_file, "w") as f:
                json.dump(self._state.to_dict(), f, indent=2)
        except Exception:
            pass  # 忽略保存错误

    def update_context(self, **kwargs) -> None:
        """更新HUD上下文"""
        for key, value in kwargs.items():
            if hasattr(self._state.context, key):
                setattr(self._state.context, key, value)

        self._state.last_update = datetime.now()
        self._save_state()

    def get_context(self) -> HudRenderContext:
        """获取当前渲染上下文"""
        return self._state.context

    def get_config(self) -> HudConfig:
        """获取当前配置"""
        return self._state.config

    def set_config(self, config: HudConfig) -> None:
        """设置配置"""
        self._state.config = config
        self._save_state()

    def set_preset(self, preset: str) -> None:
        """应用预设配置"""
        if preset in HUD_PRESETS:
            self._state.config = HUD_PRESETS[preset]
            self._state.context.preset = preset
            self._save_state()

    def clear_state(self) -> None:
        """清除状态（用于重置）"""
        self._state = HudState()
        self._save_state()
