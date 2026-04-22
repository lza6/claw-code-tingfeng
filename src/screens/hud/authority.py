"""HUD 权限检查和自治系统

汲取 oh-my-codex-main/src/hud/authority.ts
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .state import HudStateManager
from .types import HudRenderContext


class HudAuthority:
    """HUD 权限管理器 - 决定何时可以自主执行操作"""

    def __init__(self):
        self._last_check: datetime | None = None
        self._check_interval = timedelta(seconds=30)
        self._enabled = True

    async def should_allow_autonomous_action(
        self,
        action_type: str,
        context: HudRenderContext | None = None,
    ) -> bool:
        """检查是否允许自主执行特定操作

        Args:
            action_type: 操作类型 (例如: "code_edit", "file_write", "command_run")
            context: 可选的 HUD 上下文

        Returns:
            True 如果允许自主执行
        """
        if not self._enabled:
            return False

        # 检查是否到了检查时间
        now = datetime.now()
        if (
            self._last_check
            and (now - self._last_check) < self._check_interval
            and context is not None
        ):
            # 使用缓存的上下文进行快速检查
            return await self._check_conditions(action_type, context)

        self._last_check = now
        return await self._check_conditions(action_type, context or HudStateManager.get_instance().get_context())

    async def _check_conditions(
        self,
        action_type: str,
        context: HudRenderContext,
    ) -> bool:
        """检查具体条件"""
        # 基础安全检查
        if not context.session:
            return False

        # 根据操作类型应用不同的策略
        if action_type == "code_edit":
            return await self._check_code_edit_conditions(context)
        elif action_type == "file_write":
            return await self._check_file_write_conditions(context)
        elif action_type == "command_run":
            return await self._check_command_run_conditions(context)
        else:
            # 默认保守策略
            return False

    async def _check_code_edit_conditions(self, context: HudRenderContext) -> bool:
        """检查代码编辑条件"""
        # 简单策略：只有在没有激进的工作流时才允许
        if context.autopilot and context.autopilot.active:
            # Autopilot 激活时限制代码编辑
            return False

        if context.ralph and context.ralph.active:
            # Ralph 循环中允许有限的编辑
            return context.ralph.iteration < context.ralph.max_iterations * 0.8

        return True

    async def _check_file_write_conditions(self, context: HudRenderContext) -> bool:
        """检查文件写入条件"""
        # 类似代码编辑但更严格
        if context.autopilot and context.autopilot.active:
            return False

        return True

    async def _check_command_run_conditions(self, context: HudRenderContext) -> bool:
        """检查命令执行条件"""
        # 命令执行通常更安全
        return not (context.autopilot and context.autopilot.active)

    def enable(self) -> None:
        """启用权限检查"""
        self._enabled = True

    def disable(self) -> None:
        """禁用权限检查"""
        self._enabled = False

    def set_check_interval(self, seconds: int) -> None:
        """设置检查间隔"""
        self._check_interval = timedelta(seconds=seconds)


# 全局单例
_hud_authority: HudAuthority | None = None


def get_hud_authority() -> HudAuthority:
    """获取 HUD 权限管理器单例"""
    global _hud_authority
    if _hud_authority is None:
        _hud_authority = HudAuthority()
    return _hud_authority
