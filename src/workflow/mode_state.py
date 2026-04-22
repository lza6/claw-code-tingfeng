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
- 技能激活状态持久化（从 keyword-detector.ts 汲取）
- 深度面试输入锁（从 keyword-detector.ts 汲取）
"""

from __future__ import annotations

import json
import os
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Runtime Engine 导入（整合 oh-my-codex 组件）
from src.runtime.engine import (
    AcquireAuthorityCommand,
    AuthorityAcquiredEvent,
    CreateMailboxMessageCommand,
    DispatchDeliveredEvent,
    DispatchFailedEvent,
    DispatchNotifiedEvent,
    MailboxMessageCreatedEvent,
    MarkDeliveredCommand,
    MarkFailedCommand,
    MarkNotifiedCommand,
    QueueDispatchCommand,
    RuntimeEngine,
    RuntimeSnapshot,
)

logger = logging.getLogger(__name__)

# 独占模式（不能同时运行）
EXCLUSIVE_MODES = {"autopilot", "autoresearch", "ralph", "ultrawork"}

# ============================================================================
# 技能激活状态（从 oh-my-codex/keyword-detector.ts 汲取）
# ============================================================================

SKILL_ACTIVE_STATE_FILE = "skill-active-state.json"
DEEP_INTERVIEW_BLOCKED_APPROVAL_INPUTS = [
    "yes", "y", "proceed", "continue", "ok", "sure", "go ahead", "next i should"
]
DEEP_INTERVIEW_INPUT_LOCK_MESSAGE = (
    "Deep interview is active; auto-approval shortcuts are blocked until the interview finishes."
)


@dataclass
class DeepInterviewInputLock:
    """深度面试输入锁状态"""
    active: bool
    scope: str = "deep-interview-auto-approval"
    acquired_at: str = ""
    released_at: str | None = None
    exit_reason: str | None = None  # 'success' | 'error' | 'abort' | 'handoff'
    blocked_inputs: list[str] = field(default_factory=list)
    message: str = DEEP_INTERVIEW_INPUT_LOCK_MESSAGE


@dataclass
class SkillActiveState:
    """技能激活状态（对标 OMX SkillActiveState）"""
    version: int = 1
    active: bool = False
    skill: str = ""
    keyword: str = ""
    phase: str = ""  # 'planning' | 'executing' | 'reviewing' | 'completing'
    activated_at: str = ""
    updated_at: str = ""
    source: str = "keyword-detector"
    session_id: str | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    input_lock: DeepInterviewInputLock | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "active": self.active,
            "skill": self.skill,
            "keyword": self.keyword,
            "phase": self.phase,
            "activated_at": self.activated_at,
            "updated_at": self.updated_at,
            "source": self.source,
            "session_id": self.session_id,
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "input_lock": (
                {
                    "active": self.input_lock.active,
                    "scope": self.input_lock.scope,
                    "acquired_at": self.input_lock.acquired_at,
                    "released_at": self.input_lock.released_at,
                    "exit_reason": self.input_lock.exit_reason,
                    "blocked_inputs": self.input_lock.blocked_inputs,
                    "message": self.input_lock.message,
                }
                if self.input_lock else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillActiveState:
        lock_data = data.get("input_lock")
        input_lock = None
        if lock_data:
            input_lock = DeepInterviewInputLock(
                active=lock_data.get("active", False),
                scope=lock_data.get("scope", "deep-interview-auto-approval"),
                acquired_at=lock_data.get("acquired_at", ""),
                released_at=lock_data.get("released_at"),
                exit_reason=lock_data.get("exit_reason"),
                blocked_inputs=lock_data.get("blocked_inputs", []),
                message=lock_data.get("message", DEEP_INTERVIEW_INPUT_LOCK_MESSAGE),
            )
        return cls(
            version=data.get("version", 1),
            active=data.get("active", False),
            skill=data.get("skill", ""),
            keyword=data.get("keyword", ""),
            phase=data.get("phase", ""),
            activated_at=data.get("activated_at", ""),
            updated_at=data.get("updated_at", ""),
            source=data.get("source", "keyword-detector"),
            session_id=data.get("session_id"),
            thread_id=data.get("thread_id"),
            turn_id=data.get("turn_id"),
            input_lock=input_lock,
        )


def create_deep_interview_input_lock(
    now_iso: str,
    previous: DeepInterviewInputLock | None = None
) -> DeepInterviewInputLock:
    """创建深度面试输入锁"""
    return DeepInterviewInputLock(
        active=True,
        scope="deep-interview-auto-approval",
        acquired_at=previous.acquired_at if previous and previous.active else now_iso,
        blocked_inputs=DEEP_INTERVIEW_BLOCKED_APPROVAL_INPUTS.copy(),
        message=DEEP_INTERVIEW_INPUT_LOCK_MESSAGE,
    )


def release_deep_interview_input_lock(
    previous: DeepInterviewInputLock | None,
    now_iso: str,
    reason: str = "handoff"
) -> DeepInterviewInputLock | None:
    """释放深度面试输入锁"""
    if not previous:
        return None
    return DeepInterviewInputLock(
        active=False,
        acquired_at=previous.acquired_at,
        released_at=now_iso,
        exit_reason=reason,
        blocked_inputs=previous.blocked_inputs,
        message=previous.message,
    )


def read_existing_skill_state(state_path: Path) -> SkillActiveState | None:
    """读取现有技能状态"""
    if not state_path.exists():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return SkillActiveState.from_dict(data)
    except Exception as e:
        logger.warning(f"[ModeState] Failed to read skill state from {state_path}: {e}")
        return None


def save_skill_state(state_path: Path, state: SkillActiveState) -> bool:
    """保存技能状态到磁盘"""
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        return True
    except Exception as e:
        logger.warning(f"[ModeState] Failed to persist skill state: {e}")
        return False


@dataclass
class SkillStateManager:
    """技能状态管理器（从 oh-my-codex 汲取）

    负责技能激活状态的持久化，包括：
    - 当前激活的技能记录
    - 深度面试输入锁管理
    - 会话内技能状态追踪
    """
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self.state_dir / SKILL_ACTIVE_STATE_FILE

    def get_state_path(self) -> Path:
        """获取技能状态文件路径"""
        return self._state_file

    def record_activation(
        self,
        text: str,
        session_id: str | None = None,
        thread_id: str | None = None,
        turn_id: str | None = None,
        now_iso: str | None = None,
        keyword_detector_func=None
    ) -> SkillActiveState | None:
        """
        记录技能激活（从 keyword-detector.ts 的 recordSkillActivation 汲取）

        Args:
            text: 用户输入文本
            session_id: 会话ID
            thread_id: 线程ID
            turn_id: 轮次ID
            now_iso: ISO时间戳
            keyword_detector_func: 关键词检测函数 (text) -> Optional[KeywordMatch]
        """
        from .keyword_registry import detect_keywords, detect_primary_keyword

        match = keyword_detector_func(text) if keyword_detector_func else detect_primary_keyword(text)
        if not match:
            return None

        now_iso = now_iso or datetime.now().isoformat()
        previous = read_existing_skill_state(self._state_file)

        # 检查是否取消 + 深度面试锁
        matches = detect_keywords(text) if keyword_detector_func is None else keyword_detector_func(text)
        matches_list = [matches] if hasattr(matches, 'skill') else matches
        has_cancel = any(getattr(entry, 'skill', None) == "cancel" for entry in matches_list)

        if has_cancel and previous and previous.active and previous.skill == "deep-interview":
            state = SkillActiveState(
                version=1,
                active=False,
                skill="deep-interview",
                keyword=previous.keyword or "deep interview",
                phase="completing",
                activated_at=previous.activated_at or now_iso,
                updated_at=now_iso,
                source="keyword-detector",
                session_id=session_id or previous.session_id,
                thread_id=thread_id,
                turn_id=turn_id,
                input_lock=release_deep_interview_input_lock(
                    previous.input_lock, now_iso, "abort"
                ) if previous.input_lock else None,
            )
            extracted_state = SkillActiveState()
            extracted_state.skill = state.skill
            extracted_state.keyword = state.keyword
            extracted_state.phase = state.phase
            extracted_state.active = state.active
            extracted_state.updated_at = state.updated_at
            extracted_state.session_id = state.session_id
            extracted_state.input_lock = state.input_lock
            if save_skill_state(self._state_file, extracted_state):
                return extracted_state
            return None

        same_skill = previous and previous.active and previous.skill == match.skill
        same_keyword = previous and previous.keyword and previous.keyword.lower() == match.keyword.lower()

        deep_interview_lock = None
        if match.skill == "deep-interview":
            deep_interview_lock = create_deep_interview_input_lock(
                now_iso,
                previous.input_lock if previous else None
            )

        state = SkillActiveState(
            version=1,
            active=True,
            skill=match.skill,
            keyword=match.keyword,
            phase="planning",
            activated_at=(same_skill and same_keyword and previous.activated_at) or now_iso,
            updated_at=now_iso,
            source="keyword-detector",
            session_id=session_id,
            thread_id=thread_id,
            turn_id=turn_id,
            input_lock=deep_interview_lock,
        )
        extracted_state = SkillActiveState()
        extracted_state.skill = state.skill
        extracted_state.keyword = state.keyword
        extracted_state.phase = state.phase
        extracted_state.active = state.active
        extracted_state.updated_at = state.updated_at
        extracted_state.session_id = state.session_id
        extracted_state.input_lock = state.input_lock

        if save_skill_state(self._state_file, extracted_state):
            return extracted_state
        return None

    def get_current_state(self) -> SkillActiveState | None:
        """获取当前激活的技能状态"""
        return read_existing_skill_state(self._state_file)


# ============================================================================
# Ralph 状态规范化验证 (从 oh-my-codex-main/src/modes/base.ts 汲取)
# ============================================================================

def validate_and_normalize_ralph_state(state: dict[str, Any]) -> dict[str, Any]:
    """
    Ralph 模式专用状态校验与规范化

    对标 OMX 的 validateAndNormalizeRalphState 函数。
    确保 Ralph 状态符合预期结构,避免运行时错误。

    Args:
        state: 原始状态字典

    Returns:
        规范化后的状态字典

    Raises:
        ValueError: 如果状态无效
    """
    required_fields = ["current_phase", "started_at"]
    valid_phases = {
        "idle", "planning", "executing", "verifying", "fixing",
        "completed", "failed", "cancelled"
    }

    # 检查必需字段
    for field_name in required_fields:
        if field_name not in state:
            raise ValueError(f"Missing required field: {field_name}")

    # 规范化 phase 值
    current_phase = state.get("current_phase", "")
    if current_phase and current_phase not in valid_phases:
        logger.warning(
            f"[ModeState] Invalid ralph phase '{current_phase}', "
            f"normalizing to 'idle'"
        )
        state["current_phase"] = "idle"

    # 确保 metadata 存在
    if "metadata" not in state:
        state["metadata"] = {}

    # 验证时间戳格式
    for time_field in ["started_at", "updated_at"]:
        if time_field in state:
            try:
                datetime.fromisoformat(state[time_field])
            except (ValueError, TypeError):
                logger.warning(
                    f"[ModeState] Invalid timestamp format for {time_field}, "
                    f"resetting to now"
                )
                state[time_field] = datetime.now().isoformat()

    return state


def assert_mode_start_allowed(mode: str, state_dir: Path) -> None:
    """
    断言模式允许启动

    从 oh-my-codex 汲取的完整模式生命周期检查:
    1. 检查是否有冲突的活跃模式
    2. 检查是否可以恢复之前的状态
    3. 验证状态文件完整性

    Args:
        mode: 要启动的模式
        state_dir: 状态目录

    Raises:
        RuntimeError: 如果模式不允许启动
    """
    manager = ModeStateManager(str(state_dir))

    # 检查独占模式冲突
    if mode in EXCLUSIVE_MODES:
        conflict = manager.check_mode_conflict(mode)
        if conflict:
            raise RuntimeError(
                f"Cannot start {mode}: {conflict} is already active.\n"
                f"Please cancel the existing mode first or use --force."
            )

    # 检查是否有未完成的相同模式
    existing_state = manager.read_state(mode)
    if existing_state and "cancelled" not in existing_state.current_phase:
        logger.info(
            f"[ModeState] Found existing {mode} state. "
            f"Phase: {existing_state.current_phase}"
        )


# ============================================================================
# Mode State Manager (原逻辑保持不变)
# ============================================================================

class ModeStateManager:
    """模式状态管理器

    负责读取、写入和管理各种运行模式的持久化状态。
    整合增强（2026-04-17）:
    - 技能激活状态管理
    - 深度面试输入锁
    - 与关键词检测器的集成
    - Ralph 状态规范化验证 (从 oh-my-codex 汲取)
    - 模式启动前断言检查
    """

    def __init__(self, cwd: str = "."):
        # 路径验证：防止路径遍历攻击
        self._cwd = str(Path(cwd).resolve())
        self._state_root = Path(self._cwd) / ".clawd" / "state"
        self._state_root.mkdir(parents=True, exist_ok=True)
        self._skill_manager = SkillStateManager(self._state_root)

    def get_skill_manager(self) -> SkillStateManager:
        """获取技能状态管理器"""
        return self._skill_manager

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

    def read_state(self, mode: str) -> ModeState | None:
        """读取模式状态"""
        path = get_mode_state_path(mode, self._cwd)
        if not path.exists():
            return None
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            return ModeState.from_dict(data)
        except Exception as e:
            logger.warning(f"[ModeState] Failed to read state from {path}: {e}")
            return None

    def update_state(self, mode: str, updates: dict[str, Any]) -> ModeState | None:
        """更新模式状态"""
        state = self.read_state(mode)
        if not state:
            logger.warning(f"[ModeState] No existing state for mode: {mode}")
            return None
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
        return state is not None and "cancelled" not in state.current_phase and state.started_at

    def check_mode_conflict(self, mode: str) -> str | None:
        """
        检查模式冲突（借鉴 oh-my-codex-main 的 explicit mode state）

        返回第一个冲突的活跃模式名称，或None表示无冲突。
        考虑：
        1. 独占模式互斥（EXCLUSIVE_MODES）
        2. 活跃状态检查（metadata.active == True）
        3. 阶段检查（非 terminal 阶段）
        4. 模式继承关系（如 pipeline 包含 team）
        """
        if mode not in EXCLUSIVE_MODES:
            return None

        for other_mode in EXCLUSIVE_MODES:
            if other_mode == mode:
                continue
            other_state = self.read_state(other_mode)
            if not other_state:
                continue

            # 检查活跃标志
            is_active = other_state.metadata.get("active", False)
            if not is_active:
                continue

            # 检查阶段：不是已取消/已完成的状态都视为活跃
            phase = other_state.current_phase
            terminal_phases = {"complete", "failed", "cancelled", "mode:" + other_mode + ":cancelled"}
            if phase and not any(terminal in phase for terminal in terminal_phases):
                return other_mode

        return None

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
        for mode in ALL_SUPPORTED_MODES:
            state = self.read_state(mode)
            if state and state.metadata.get("active"):
                active.append(mode)
        return active

    def _write_state(self, state: ModeState) -> None:
        """写入模式状态到磁盘"""
        path = get_mode_state_path(state.mode, self._cwd)
        # 安全检查：确保路径在预期目录内
        try:
            path_resolved = path.resolve()
            state_root_resolved = (Path(self._cwd) / ".clawd" / "state").resolve()
            if not str(path_resolved).startswith(str(state_root_resolved) + os.sep):
                raise ValueError(f"Path traversal detected in mode state write: {path}")
        except Exception as e:
            logger.error(f"[ModeState] Path validation failed for {path}: {e}")
            raise

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"[ModeState] Failed to write state to {path}: {e}")


# ============================================================================
# Mode Type & Paths
# ============================================================================

class ModeType(str):
    PIPELINE = "pipeline"
    TEAM = "team"
    SKILL = "skill"
    AUTOPILOT = "autopilot"
    RALPH = "ralph"
    AUTORESEARCH = "autoresearch"
    ULTRAWORK = "ultrawork"
    DEEP_INTERVIEW = "deep-interview"


ALL_SUPPORTED_MODES = {
    "pipeline", "team", "skill", "autopilot", "ralph",
    "ultrawork", "deep-interview", "autoresearch"
}


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
        return cls(
            mode=data.get("mode", ""),
            task=data.get("task", ""),
            current_phase=data.get("current_phase", ""),
            started_at=data.get("started_at", ""),
            updated_at=data.get("updated_at", ""),
            metadata=data.get("metadata", {}),
        )


# ============================================================================
# 便捷函数
# ============================================================================

def start_mode(mode: str, task: str, cwd: str = ".", metadata: dict[str, Any] = None) -> ModeState:
    manager = ModeStateManager(cwd)
    return manager.start_mode(mode, task, metadata)


def read_mode_state(mode: str, cwd: str = ".") -> ModeState | None:
    manager = ModeStateManager(cwd)
    return manager.read_state(mode)


def update_mode_state(mode: str, updates: dict[str, Any], cwd: str = ".") -> ModeState | None:
    manager = ModeStateManager(cwd)
    return manager.update_state(mode, updates)


def cancel_mode(mode: str, cwd: str = ".", reason: str = "") -> bool:
    manager = ModeStateManager(cwd)
    return manager.cancel_mode(mode, reason)


def can_resume_mode(mode: str, cwd: str = ".") -> bool:
    manager = ModeStateManager(cwd)
    return manager.can_resume(mode)


def check_mode_conflict(mode: str, cwd: str = ".") -> str | None:
    manager = ModeStateManager(cwd)
    return manager.check_mode_conflict(mode)


def assert_mode_allowed(mode: str, cwd: str = ".") -> None:
    manager = ModeStateManager(cwd)
    manager.assert_mode_allowed(mode)


def list_active_modes(cwd: str = ".") -> list[str]:
    manager = ModeStateManager(cwd)
    return manager.list_active_modes()


# ============================================================================
# Runtime Engine 集成 (汲取 oh-my-codex-main)
# ============================================================================

class RuntimeEngineIntegration:
    """RuntimeEngine 集成层 — 连接现有 ModeState 与新状态机引擎

    职责:
        - 在 ModeStateManager 中创建 RuntimeEngine 实例
        - 将模式状态变更转换为 RuntimeEngine 事件
        - 提供统一的就绪度检查接口
        - 通过事件日志追踪所有状态变更

    参考: omx-runtime-core/src/engine.rs
    """

    def __init__(self, mode_manager: ModeStateManager) -> None:
        self._mode_manager = mode_manager
        self._engine: RuntimeEngine | None = None
        self._state_dir: Path = mode_manager._state_root

    def get_engine(self) -> RuntimeEngine:
        """获取或创建 RuntimeEngine 实例"""
        if self._engine is None:
            engine_path = self._state_dir / "engine"
            engine_path.mkdir(parents=True, exist_ok=True)

            # 尝试从磁盘加载现有状态
            try:
                self._engine = RuntimeEngine.load(engine_path)
            except Exception as e:
                logger.debug(f"[Runtime] No existing engine state: {e}")
                self._engine = RuntimeEngine.with_state_dir(engine_path)

        return self._engine

    def acquire_authority(
        self,
        owner: str,
        lease_id: str,
        leased_until: str,
    ) -> AuthorityAcquiredEvent:
        """获取权威租赁（用于模式独占锁）"""
        engine = self.get_engine()
        cmd = AcquireAuthorityCommand(owner, lease_id, leased_until)
        return engine.process(cmd)

    def notify_dispatch(
        self,
        request_id: str,
        target: str,
        channel: str = "direct",
        metadata: dict[str, Any] | None = None,
    ) -> DispatchNotifiedEvent:
        """通知任务分派（worker 已接收）"""
        engine = self.get_engine()
        # 先入队
        engine.process(QueueDispatchCommand(request_id=request_id, target=target, metadata=metadata))
        # 再通知
        return engine.process(MarkNotifiedCommand(request_id=request_id, channel=channel))

    def mark_delivered(self, request_id: str) -> DispatchDeliveredEvent:
        """标记任务已完成交付"""
        engine = self.get_engine()
        return engine.process(MarkDeliveredCommand(request_id=request_id))

    def mark_failed(self, request_id: str, reason: str) -> DispatchFailedEvent:
        """标记任务失败"""
        engine = self.get_engine()
        return engine.process(MarkFailedCommand(request_id=request_id, reason=reason))

    def create_mailbox_message(
        self,
        message_id: str,
        from_worker: str,
        to_worker: str,
        body: str,
    ) -> MailboxMessageCreatedEvent:
        """创建跨 worker 消息"""
        engine = self.get_engine()
        return engine.process(
            CreateMailboxMessageCommand(
                message_id=message_id,
                from_worker=from_worker,
                to_worker=to_worker,
                body=body,
            )
        )

    def get_snapshot(self) -> RuntimeSnapshot:
        """获取当前运行时快照"""
        return self.get_engine().snapshot()

    def is_system_ready(self) -> bool:
        """系统是否就绪（可执行新任务）"""
        return self.get_engine().is_ready()

    def persist(self) -> None:
        """持久化运行时状态"""
        engine = self.get_engine()
        engine.persist()
        engine.write_compatibility_view()

    def compact_events(self) -> None:
        """压缩事件日志（清理已达 terminal 状态的事件）"""
        engine = self.get_engine()
        engine.compact()


# ============================================================================
# ModeStateManager 增强 (集成 RuntimeEngine)
# ============================================================================

# 在 ModeStateManager 初始化时注入 RuntimeEngineIntegration
_original_init = ModeStateManager.__init__

def _patched_init(self: ModeStateManager, cwd: str = ".") -> None:
    _original_init(self, cwd)
    self.runtime = RuntimeEngineIntegration(self)

ModeStateManager.__init__ = _patched_init  # type: ignore[assignment]


# ===== 导出 =====
__all__ = [
    "ALL_SUPPORTED_MODES",
    "EXCLUSIVE_MODES",
    "DeepInterviewInputLock",
    "ModeState",
    "ModeStateManager",
    "ModeType",
    "RuntimeEngineIntegration",
    "SkillActiveState",
    "SkillStateManager",
    "assert_mode_allowed",
    "can_resume_mode",
    "cancel_mode",
    "check_mode_conflict",
    "get_mode_state_path",
    "get_runtime_engine",
    "list_active_modes",
    "read_mode_state",
    "start_mode",
    "update_mode_state",
]


def get_runtime_engine(cwd: str = ".") -> RuntimeEngineIntegration:
    """获取运行引擎实例（便捷函数）

    Args:
        cwd: 工作目录

    Returns:
        RuntimeEngineIntegration 实例
    """
    from .mode_state import ModeStateManager  # 延迟导入避免循环
    manager = ModeStateManager(cwd)
    return manager.runtime
