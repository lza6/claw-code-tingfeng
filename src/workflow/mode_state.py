"""
Mode State 管理系统

从 oh-my-codex-main 汲取的 Mode State 系统。
用于持久化管道、团队和技能模式的运行状态。

支持的状态类型:
- pipeline: 管道执行状态
- team: 团队协作状态
- skill: 技能执行状态
- autopilot: 自动驾驶模式状态
- ralph: RALPH 持久循环状态
- ultrawork: 手动控制模式状态

特性（从 oh-my-codex 汲取）:
- 独占模式互斥检查：autopilot, autoresearch, ralph, ultrawork 不能同时运行
- 状态校验与规范化
- 跨会话状态恢复
"""

from __future__ import annotations

import json
import os
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 独占模式（不能同时运行）
EXCLUSIVE_MODES = {"autopilot", "autoresearch", "ralph", "ultrawork"}

# 所有支持的状态类型
ALL_SUPPORTED_MODES = {"pipeline", "team", "skill", "autopilot", "ralph", "ultrawork", "deep-interview", "autoresearch"}

# 所有支持的状态类型
ALL_SUPPORTED_MODES = {"pipeline", "team", "skill", "autopilot", "ralph", "ultrawork", "deep-interview", "autoresearch"}

# Mode 类型
class ModeType(str):
    PIPELINE = "pipeline"
    TEAM = "team"
    SKILL = "skill"
    AUTOPILOT = "autopilot"
    RALPH = "ralph"
    AUTORESEARCH = "autoresearch"
    ULTRAWORK = "ultrawork"
    DEEP_INTERVIEW = "deep-interview"


# 状态文件路径
def get_mode_state_path(mode: str, cwd: str = ".") -> Path:
    """获取模式状态文件路径"""
    state_root = Path(cwd) / ".clawd" / "state"
    state_root.mkdir(parents=True, exist_ok=True)
    return state_root / f"mode-{mode}.json"


@dataclass
class ModeState:
    """模式状态"""
    mode: str
    task: str
    current_phase: str = ""
    started_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "mode": self.mode,
            "task": self.task,
            "current_phase": self.current_phase,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModeState:
        """从字典创建"""
        return cls(
            mode=data.get("mode", ""),
            task=data.get("task", ""),
            current_phase=data.get("current_phase", ""),
            started_at=data.get("started_at", ""),
            updated_at=data.get("updated_at", ""),
            metadata=data.get("metadata", {}),
        )


class ModeStateManager:
    """模式状态管理器

    负责读取、写入和管理各种运行模式的持久化状态。
    """

    def __init__(self, cwd: str = "."):
        self._cwd = cwd

    def start_mode(self, mode: str, task: str, metadata: dict[str, Any] = None) -> ModeState:
        """启动新模式状态"""
        now = datetime.now().isoformat()
        state = ModeState(
            mode=mode,
            task=task,
            current_phase=f"mode:{mode}:started",
            started_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        self._write_state(state)
        logger.info(f"[ModeState] Started mode: {mode}, task: {task}")
        return state

    def read_state(self, mode: str) -> Optional[ModeState]:
        """读取模式状态"""
        path = get_mode_state_path(mode, self._cwd)
        if not path.exists():
            return None

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return ModeState.from_dict(data)
        except Exception as e:
            logger.warning(f"[ModeState] Failed to read state from {path}: {e}")
            return None

    def update_state(self, mode: str, updates: dict[str, Any]) -> Optional[ModeState]:
        """更新模式状态"""
        state = self.read_state(mode)
        if not state:
            logger.warning(f"[ModeState] No existing state for mode: {mode}")
            return None

        # 应用更新
        for key, value in updates.items():
            if hasattr(state, key):
                setattr(state, key, value)
            else:
                state.metadata[key] = value

        state.updated_at = datetime.now().isoformat()
        self._write_state(state)
        logger.debug(f"[ModeState] Updated mode: {mode}, phase: {state.current_phase}")
        return state

    def cancel_mode(self, mode: str, reason: str = "") -> bool:
        """取消模式状态"""
        path = get_mode_state_path(mode, self._cwd)
        if not path.exists():
            return False

        try:
            # 读取当前状态并标记为取消
            state = self.read_state(mode)
            if state:
                state.current_phase = f"mode:{mode}:cancelled"
                state.metadata["cancel_reason"] = reason
                state.updated_at = datetime.now().isoformat()
                self._write_state(state)
                logger.info(f"[ModeState] Cancelled mode: {mode}, reason: {reason}")
                return True
        except Exception as e:
            logger.error(f"[ModeState] Failed to cancel mode: {e}")

        return False

    def can_resume(self, mode: str) -> bool:
        """检查是否可以恢复模式"""
        state = self.read_state(mode)
        if not state:
            return False

        # 可以恢复的条件：不是已取消且有有效的开始时间
        return "cancelled" not in state.current_phase and state.started_at

    def check_mode_conflict(self, mode: str) -> Optional[str]:
        """检查模式冲突（从 oh-my-codex 汲取）

        独占模式不能同时运行。返回冲突的模式名称，如果没有冲突则返回 None。
        """
        if mode not in EXCLUSIVE_MODES:
            return None

        for other_mode in EXCLUSIVE_MODES:
            if other_mode == mode:
                continue
            other_state = self.read_state(other_mode)
            if other_state and other_state.metadata.get("active"):
                return other_mode
        return None

    async def assert_mode_start_allowed(self, mode: str) -> None:
        """断言模式允许启动，如果有独占模式冲突则抛出异常（从 oh-my-codex/base.ts 汲取）"""
        if mode not in EXCLUSIVE_MODES:
            return

        for other_mode in EXCLUSIVE_MODES:
            if other_mode == mode:
                continue
            other_state = self.read_state(other_mode)
            if other_state and other_state.metadata.get("active"):
                raise RuntimeError(
                    f"Cannot start {mode}: {other_mode} is already active. "
                    f"Run cancel first or use --force to override."
                )

    async def assert_mode_start_allowed(self, mode: str) -> None:
        """断言模式允许启动，如果有独占模式冲突则抛出异常（从 oh-my-codex/base.ts 汲取）"""
        if mode not in EXCLUSIVE_MODES:
            return

        for other_mode in EXCLUSIVE_MODES:
            if other_mode == mode:
                continue
            other_state = self.read_state(other_mode)
            if other_state and other_state.metadata.get("active"):
                raise RuntimeError(
                    f"Cannot start {mode}: {other_mode} is already active. "
                    f"Run cancel first or use --force to override."
                )

    def assert_mode_allowed(self, mode: str) -> None:
        """断言模式允许启动，如果冲突则抛出异常"""
        conflict = self.check_mode_conflict(mode)
        if conflict:
            raise RuntimeError(
                f"Cannot start {mode}: {conflict} is already active. "
                f"Run cancel first or use --force to override."
            )

    def list_active_modes(self) -> list[str]:
        """列出所有当前活跃的模式"""
        active = []
        for mode in ["pipeline", "team", "skill", "autopilot", "ralph", "ultrawork", "deep-interview"]:
            state = self.read_state(mode)
            if state and state.metadata.get("active"):
                active.append(mode)
        return active


# ===== 便捷函数 =====
def start_mode(mode: str, task: str, cwd: str = ".", metadata: dict[str, Any] = None) -> ModeState:
    """启动模式的便捷函数"""
    manager = ModeStateManager(cwd)
    return manager.start_mode(mode, task, metadata)


def read_mode_state(mode: str, cwd: str = ".") -> Optional[ModeState]:
    """读取模式状态的便捷函数"""
    manager = ModeStateManager(cwd)
    return manager.read_state(mode)


def update_mode_state(mode: str, updates: dict[str, Any], cwd: str = ".") -> Optional[ModeState]:
    """更新模式状态的便捷函数"""
    manager = ModeStateManager(cwd)
    return manager.update_state(mode, updates)


def cancel_mode(mode: str, cwd: str = ".", reason: str = "") -> bool:
    """取消模式的便捷函数"""
    manager = ModeStateManager(cwd)
    return manager.cancel_mode(mode, reason)


def can_resume_mode(mode: str, cwd: str = ".") -> bool:
    """检查是否可以恢复模式的便捷函数"""
    manager = ModeStateManager(cwd)
    return manager.can_resume(mode)


def check_mode_conflict(mode: str, cwd: str = ".") -> Optional[str]:
    """检查模式冲突"""
    manager = ModeStateManager(cwd)
    return manager.check_mode_conflict(mode)


def assert_mode_allowed(mode: str, cwd: str = ".") -> None:
    """断言模式允许启动"""
    manager = ModeStateManager(cwd)
    manager.assert_mode_allowed(mode)


def list_active_modes(cwd: str = ".") -> list[str]:
    """列出所有当前活跃的模式"""
    manager = ModeStateManager(cwd)
    return manager.list_active_modes()


# ===== 导出 =====
__all__ = [
    "EXCLUSIVE_MODES",
    "ModeType",
    "ModeState",
    "ModeStateManager",
    "get_mode_state_path",
    "start_mode",
    "read_mode_state",
    "update_mode_state",
    "cancel_mode",
    "can_resume_mode",
    "check_mode_conflict",
    "assert_mode_allowed",
    "list_active_modes",
]