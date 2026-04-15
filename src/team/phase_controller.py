"""
Phase Controller - 阶段控制器

从 oh-my-codex-main/src/team/phase-controller.ts 转换。
提供团队执行阶段控制和状态管理。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional


logger = logging.getLogger(__name__)


class PhaseType(Enum):
    """阶段类型"""
    INITIALIZE = "initialize"
    PLAN = "plan"
    EXECUTE = "execute"
    VERIFY = "verify"
    COMPLETE = "complete"
    CANCEL = "cancel"


class PhaseState(Enum):
    """阶段状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PhaseTransition:
    """阶段过渡"""
    from_phase: str
    to_phase: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: dict = field(default_factory=dict)


@dataclass
class PhaseContext:
    """阶段上下文"""
    phase: str
    state: str = PhaseState.PENDING.value
    started_at: str = ""
    ended_at: str = ""
    metadata: dict = field(default_factory=dict)
    artifacts: dict = field(default_factory=dict)
    error: str = ""


class PhaseController:
    """阶段控制器

    功能:
    - 阶段注册
    - 状态转换
    - 超时管理
    - 回调通知
    """

    def __init__(self):
        self._phases: dict[str, PhaseContext] = {}
        self._transitions: list[PhaseTransition] = []
        self._current_phase: Optional[str] = None
        self._on_transition: Optional[Callable[[str, str], None]] = None
        self._on_phase_complete: Optional[Callable[[str], None]] = None

    def register_phase(self, phase_name: str, metadata: Optional[dict] = None) -> PhaseContext:
        """注册阶段"""
        phase = PhaseContext(
            phase=phase_name,
            metadata=metadata or {},
        )
        self._phases[phase_name] = phase
        logger.debug(f"[Phase] Registered: {phase_name}")
        return phase

    def start_phase(self, phase_name: str) -> bool:
        """开始阶段"""
        if phase_name not in self._phases:
            logger.warning(f"[Phase] Unknown phase: {phase_name}")
            return False

        phase = self._phases[phase_name]
        old_phase = self._current_phase

        # 记录过渡
        if old_phase:
            self._transitions.append(PhaseTransition(
                from_phase=old_phase,
                to_phase=phase_name,
            ))

        # 更新状态
        phase.state = PhaseState.RUNNING.value
        phase.started_at = datetime.now().isoformat()
        self._current_phase = phase_name

        # 回调
        if self._on_transition and old_phase:
            try:
                self._on_transition(old_phase, phase_name)
            except Exception as e:
                logger.warning(f"[Phase] Transition callback failed: {e}")

        logger.info(f"[Phase] Started: {phase_name}")
        return True

    def complete_phase(self, phase_name: str, artifacts: Optional[dict] = None) -> bool:
        """完成阶段"""
        if phase_name not in self._phases:
            return False

        phase = self._phases[phase_name]
        phase.state = PhaseState.COMPLETED.value
        phase.ended_at = datetime.now().isoformat()

        if artifacts:
            phase.artifacts.update(artifacts)

        # 回调
        if self._on_phase_complete:
            try:
                self._on_phase_complete(phase_name)
            except Exception as e:
                logger.warning(f"[Phase] Complete callback failed: {e}")

        logger.info(f"[Phase] Completed: {phase_name}")
        return True

    def fail_phase(self, phase_name: str, error: str) -> bool:
        """失败阶段"""
        if phase_name not in self._phases:
            return False

        phase = self._phases[phase_name]
        phase.state = PhaseState.FAILED.value
        phase.ended_at = datetime.now().isoformat()
        phase.error = error

        logger.error(f"[Phase] Failed: {phase_name} - {error}")
        return True

    def skip_phase(self, phase_name: str) -> bool:
        """跳过阶段"""
        if phase_name not in self._phases:
            return False

        phase = self._phases[phase_name]
        phase.state = PhaseState.SKIPPED.value
        phase.ended_at = datetime.now().isoformat()

        logger.info(f"[Phase] Skipped: {phase_name}")
        return True

    def get_phase(self, phase_name: str) -> Optional[PhaseContext]:
        """获取阶段"""
        return self._phases.get(phase_name)

    def get_current_phase(self) -> Optional[PhaseContext]:
        """获取当前阶段"""
        if self._current_phase:
            return self._phases.get(self._current_phase)
        return None

    def get_transitions(self) -> list[PhaseTransition]:
        """获取过渡历史"""
        return self._transitions

    def set_transition_callback(self, callback: Callable[[str, str], None]) -> None:
        """设置过渡回调"""
        self._on_transition = callback

    def set_complete_callback(self, callback: Callable[[str], None]) -> None:
        """设置完成回调"""
        self._on_phase_complete = callback

    def is_all_completed(self) -> bool:
        """检查是否全部完成"""
        return all(
            p.state in (PhaseState.COMPLETED.value, PhaseState.SKIPPED.value)
            for p in self._phases.values()
        )

    def has_failures(self) -> bool:
        """检查是否有失败"""
        return any(p.state == PhaseState.FAILED.value for p in self._phases.values())


# 全局单例
_phase_controller: Optional[PhaseController] = None


def get_phase_controller() -> PhaseController:
    """获取全局阶段控制器"""
    global _phase_controller
    if _phase_controller is None:
        _phase_controller = PhaseController()
    return _phase_controller


# ===== 导出 =====
__all__ = [
    "PhaseType",
    "PhaseState",
    "PhaseTransition",
    "PhaseContext",
    "PhaseController",
    "get_phase_controller",
]
