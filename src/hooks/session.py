"""
Session - 会话状态管理

从 oh-my-codex-main/src/hooks/session.ts 转换。
提供会话生命周期管理、状态持久化。
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class SessionState(Enum):
    """会话状态"""
    ACTIVE = "active"
    IDLE = "idle"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


@dataclass
class SessionContext:
    """会话上下文"""
    session_id: str
    cwd: str = ""
    started_at: str = ""
    last_active: str = ""
    state: str = "active"
    metadata: dict = field(default_factory=dict)


@dataclass
class SessionMetadata:
    """会话元数据"""
    turn_count: int = 0
    token_usage: int = 0
    files_modified: list[str] = field(default_factory=list)
    commands_executed: int = 0
    errors_count: int = 0


class SessionManager:
    """会话管理器

    功能:
    - 会话创建/恢复
    - 状态持久化
    - 元数据跟踪
    - 自动保存
    """

    def __init__(self, storage_path: str | None = None):
        self.storage_path = storage_path
        self._current: SessionContext | None = None
        self._metadata = SessionMetadata()

    def create(self, session_id: str, cwd: str = "") -> SessionContext:
        """创建会话"""
        now = datetime.now().isoformat()
        self._current = SessionContext(
            session_id=session_id,
            cwd=cwd,
            started_at=now,
            last_active=now,
        )
        self._metadata = SessionMetadata()
        logger.info(f"[Session] Created session: {session_id}")
        return self._current

    def get_current(self) -> SessionContext | None:
        """获取当前会话"""
        return self._current

    def update_state(self, state: str) -> None:
        """更新状态"""
        if self._current:
            self._current.state = state
            self._current.last_active = datetime.now().isoformat()

    def increment_turn(self) -> int:
        """增加回合计数"""
        self._metadata.turn_count += 1
        return self._metadata.turn_count

    def add_token_usage(self, tokens: int) -> None:
        """添加 Token 使用"""
        self._metadata.token_usage += tokens

    def add_file_modified(self, filepath: str) -> None:
        """记录修改的文件"""
        if filepath not in self._metadata.files_modified:
            self._metadata.files_modified.append(filepath)

    def increment_commands(self) -> int:
        """增加命令计数"""
        self._metadata.commands_executed += 1
        return self._metadata.commands_executed

    def increment_errors(self) -> int:
        """增加错误计数"""
        self._metadata.errors_count += 1
        return self._metadata.errors_count

    def get_metadata(self) -> SessionMetadata:
        """获取元数据"""
        return self._metadata

    def save(self, path: str | None = None) -> bool:
        """保存会话"""
        save_path = path or self.storage_path
        if not save_path or not self._current:
            return False

        try:
            data = {
                "context": asdict(self._current),
                "metadata": asdict(self._metadata),
            }
            Path(save_path).write_text(json.dumps(data, indent=2))
            logger.info(f"[Session] Saved to {save_path}")
            return True
        except Exception as e:
            logger.error(f"[Session] Save failed: {e}")
            return False

    def load(self, path: str) -> bool:
        """加载会话"""
        try:
            data = json.loads(Path(path).read_text())
            self._current = SessionContext(**data["context"])
            self._metadata = SessionMetadata(**data["metadata"])
            logger.info(f"[Session] Loaded from {path}")
            return True
        except Exception as e:
            logger.error(f"[Session] Load failed: {e}")
            return False

    def terminate(self) -> None:
        """终止会话"""
        if self._current:
            self.update_state("terminated")
            logger.info(f"[Session] Terminated: {self._current.session_id}")
            self._current = None
            self._metadata = SessionMetadata()


# ===== 独占模式管理 =====
EXCLUSIVE_MODES = ["autopilot", "autoresearch", "ralph", "ultrawork"]

MODE_NAME_ALIASES: dict[str, str] = {
    "ultrapilot": "team",
    "pipeline": "team",
    "ecomode": "ultrawork",
}


def get_deprecation_warning(mode: str) -> str | None:
    """检查模式是否已弃用并返回警告信息"""
    if mode in MODE_NAME_ALIASES:
        new_mode = MODE_NAME_ALIASES[mode]
        return f"[DEPRECATED] Mode '{mode}' is deprecated. Use '{new_mode}' instead."
    return None


def resolve_mode_name(mode: str) -> str:
    """解析模式名称，处理弃用别名"""
    return MODE_NAME_ALIASES.get(mode, mode)


# ===== 全局单例 =====
_state_dir: str | None = None
_session_manager: SessionManager | None = None


def set_state_directory(path: str) -> None:
    """设置状态目录"""
    global _state_dir
    _state_dir = path


def get_state_directory() -> str | None:
    """获取状态目录"""
    return _state_dir


def get_mode_state_path(mode: str, project_root: str | None = None) -> str:
    """获取指定模式的状态文件路径"""
    base_dir = project_root or _state_dir or ".clawd"
    return f"{base_dir}/state/{mode}-state.json"


async def assert_mode_start_allowed(
    mode: str,
    project_root: str | None = None,
) -> None:
    """断言模式启动是否允许（独占模式互斥检查）

    源自 oh-my-codex-main/src/modes/base.ts assertModeStartAllowed
    独占模式（autopilot, autoresearch, ralph, ultrawork）不能同时运行
    """
    if mode not in EXCLUSIVE_MODES:
        return

    for other_mode in EXCLUSIVE_MODES:
        if other_mode == mode:
            continue

        state_path = get_mode_state_path(other_mode, project_root)
        state_file = Path(state_path)

        if not state_file.exists():
            continue

        try:
            content = json.loads(state_file.read_text(encoding="utf-8"))
            if content.get("active"):
                raise RuntimeError(
                    f"Cannot start {mode}: {other_mode} is already active. "
                    f"Run cancel first."
                )
        except json.JSONDecodeError:
            raise RuntimeError(
                f"Cannot start {mode}: {other_mode} state file is malformed. "
                f"Run cancel or repair the state file."
            )
        except RuntimeError:
            raise


def get_session_manager() -> SessionManager:
    """获取全局会话管理器"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


# ===== 导出 =====
__all__ = [
    # Mode 管理
    "EXCLUSIVE_MODES",
    "SessionContext",
    "SessionManager",
    "SessionMetadata",
    "SessionState",
    "assert_mode_start_allowed",
    "get_deprecation_warning",
    "get_mode_state_path",
    "get_session_manager",
    "get_state_directory",
    "resolve_mode_name",
    "set_state_directory",
]
