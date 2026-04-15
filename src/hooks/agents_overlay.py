"""
Agents Overlay - Agent 遮罩覆盖逻辑

从 oh-my-codex-main/src/hooks/agents-overlay.ts 转换。
提供 Agent 遮罩、覆盖和层叠管理能力。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum


logger = logging.getLogger(__name__)


class OverlayLayer(Enum):
    """遮罩层级"""
    BASE = "base"
    SYSTEM = "system"
    USER = "user"
    TOOL = "tool"
    AGENT = "agent"


@dataclass
class AgentOverlay:
    """Agent 遮罩"""
    layer: OverlayLayer
    agent_id: str
    active: bool = True
    priority: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    expires_at: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class OverlayState:
    """遮罩状态"""
    overlays: list[AgentOverlay] = field(default_factory=list)
    active_count: int = 0
    last_update: str = field(default_factory=lambda: datetime.now().isoformat())


class AgentsOverlayManager:
    """Agent 遮罩管理器

    功能:
    - 注册/注销遮罩
    - 层级管理
    - 优先级排序
    - 过期自动清理
    """

    def __init__(self):
        self._overlays: dict[str, AgentOverlay] = {}
        self._layer_order = [
            OverlayLayer.BASE,
            OverlayLayer.SYSTEM,
            OverlayLayer.USER,
            OverlayLayer.TOOL,
            OverlayLayer.AGENT,
        ]

    def register(
        self,
        agent_id: str,
        layer: OverlayLayer,
        priority: int = 0,
        metadata: Optional[dict] = None,
    ) -> AgentOverlay:
        """注册遮罩"""
        overlay = AgentOverlay(
            layer=layer,
            agent_id=agent_id,
            priority=priority,
            metadata=metadata or {},
        )
        self._overlays[agent_id] = overlay
        logger.debug(f"[Overlay] Registered {agent_id} at layer {layer.value}")
        return overlay

    def unregister(self, agent_id: str) -> bool:
        """注销遮罩"""
        if agent_id in self._overlays:
            del self._overlays[agent_id]
            logger.debug(f"[Overlay] Unregistered {agent_id}")
            return True
        return False

    def get(self, agent_id: str) -> Optional[AgentOverlay]:
        """获取遮罩"""
        return self._overlays.get(agent_id)

    def get_active(self) -> list[AgentOverlay]:
        """获取所有活跃遮罩"""
        return [o for o in self._overlays.values() if o.active]

    def get_by_layer(self, layer: OverlayLayer) -> list[AgentOverlay]:
        """按层级获取遮罩"""
        return [
            o for o in self._overlays.values()
            if o.layer == layer and o.active
        ]

    def apply_overlay(self, agent_id: str) -> dict:
        """应用遮罩效果"""
        overlay = self.get(agent_id)
        if not overlay or not overlay.active:
            return {"applied": False}

        return {
            "applied": True,
            "layer": overlay.layer.value,
            "priority": overlay.priority,
            "metadata": overlay.metadata,
        }

    def clear_expired(self) -> int:
        """清理过期遮罩"""
        now = datetime.now()
        expired = []

        for agent_id, overlay in self._overlays.items():
            if overlay.expires_at:
                expiry = datetime.fromisoformat(overlay.expires_at)
                if now > expiry:
                    expired.append(agent_id)

        for agent_id in expired:
            self.unregister(agent_id)

        return len(expired)

    def get_state(self) -> OverlayState:
        """获取状态"""
        active = self.get_active()
        return OverlayState(
            overlays=active,
            active_count=len(active),
            last_update=datetime.now().isoformat(),
        )


# 全局单例
_overlay_manager: Optional[AgentsOverlayManager] = None


def get_overlay_manager() -> AgentsOverlayManager:
    """获取全局遮罩管理器"""
    global _overlay_manager
    if _overlay_manager is None:
        _overlay_manager = AgentsOverlayManager()
    return _overlay_manager


# ===== 导出 =====
__all__ = [
    "OverlayLayer",
    "AgentOverlay",
    "OverlayState",
    "AgentsOverlayManager",
    "get_overlay_manager",
]
