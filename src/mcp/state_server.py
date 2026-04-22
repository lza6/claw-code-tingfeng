"""MCP State Server - 状态管理服务器

借鉴 oh-my-codex 的状态管理 MCP 服务器。
提供标准化的状态读写接口，支持多模式状态管理。

功能:
- state_read: 读取指定模式的状态
- state_write: 写入/更新状态
- state_clear: 清除状态
- state_list_active: 列出所有活跃模式
- state_get_status: 获取详细状态

支持模式:
- autopilot
- team
- ralph
- ultrawork
- ultraqa
- ralplan
- deep-interview
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class Mode(str, Enum):
    """支持的工作流模式"""
    AUTOPILOT = "autopilot"
    TEAM = "team"
    RALPH = "ralph"
    ULTRAWORK = "ultrawork"
    ULTRAQA = "ultraqa"
    RALPLAN = "ralplan"
    DEEP_INTERVIEW = "deep-interview"


SUPPORTED_MODES = [m.value for m in Mode]


@dataclass
class ModeState:
    """工作流模式状态"""
    mode: str
    active: bool = False
    iteration: int = 0
    max_iterations: int = 10
    current_phase: str = ""
    task_description: str = ""
    started_at: str = ""
    completed_at: str = ""
    error: str = ""
    # 自定义字段
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "mode": self.mode,
            "active": self.active,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "current_phase": self.current_phase,
            "task_description": self.task_description,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            **self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModeState:
        """从字典创建"""
        known_fields = {
            "mode", "active", "iteration", "max_iterations",
            "current_phase", "task_description", "started_at",
            "completed_at", "error"
        }
        metadata = {k: v for k, v in data.items() if k not in known_fields}
        return cls(
            mode=data.get("mode", ""),
            active=data.get("active", False),
            iteration=data.get("iteration", 0),
            max_iterations=data.get("max_iterations", 10),
            current_phase=data.get("current_phase", ""),
            task_description=data.get("task_description", ""),
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at", ""),
            error=data.get("error", ""),
            metadata=metadata,
        )


class StateServer:
    """状态管理服务器

    提供跨会话的工作流状态持久化。
    """

    def __init__(self, base_dir: Path | None = None):
        """
        初始化状态服务器

        Args:
            base_dir: 状态文件存储目录，默认为 .omx/state/
        """
        self.base_dir = base_dir or Path.cwd() / ".clawd" / "state"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_state_path(self, mode: str, session_id: str | None = None) -> Path:
        """获取状态文件路径"""
        if session_id:
            return self.base_dir / f"{mode}-state-{session_id}.json"
        return self.base_dir / f"{mode}-state.json"

    def _list_state_files(self) -> list[Path]:
        """列出所有状态文件"""
        return list(self.base_dir.glob("*-state*.json"))

    def read_state(
        self,
        mode: str,
        session_id: str | None = None,
    ) -> ModeState | None:
        """
        读取指定模式的状态

        Args:
            mode: 工作流模式
            session_id: 可选的会话 ID

        Returns:
            ModeState 或 None (如果不存在)
        """
        if mode not in SUPPORTED_MODES:
            raise ValueError(f"Unsupported mode: {mode}. Supported: {SUPPORTED_MODES}")

        state_path = self._get_state_path(mode, session_id)
        if not state_path.exists():
            return None

        try:
            data = json.loads(state_path.read_text())
            return ModeState.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None

    def write_state(
        self,
        mode: str,
        state: ModeState | dict[str, Any],
        session_id: str | None = None,
    ) -> ModeState:
        """
        写入/更新状态

        Args:
            mode: 工作流模式
            state: 状态对象或字典
            session_id: 可选的会话 ID

        Returns:
            写入的 ModeState
        """
        if mode not in SUPPORTED_MODES:
            raise ValueError(f"Unsupported mode: {mode}. Supported: {SUPPORTED_MODES}")

        # 转换为 ModeState
        if isinstance(state, dict):
            state = ModeState.from_dict({**state, "mode": mode})
        else:
            state.mode = mode

        state_path = self._get_state_path(mode, session_id)
        state_path.parent.mkdir(parents=True, exist_ok=True)

        # 原子写入
        tmp_path = state_path.with_suffix(f".tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
        try:
            tmp_path.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
            tmp_path.replace(state_path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise

        return state

    def clear_state(
        self,
        mode: str,
        session_id: str | None = None,
    ) -> bool:
        """
        清除状态

        Args:
            mode: 工作流模式
            session_id: 可选的会话 ID

        Returns:
            是否成功清除
        """
        state_path = self._get_state_path(mode, session_id)
        if state_path.exists():
            state_path.unlink()
            return True
        return False

    def list_active_modes(self, session_id: str | None = None) -> list[str]:
        """
        列出所有活跃模式

        Args:
            session_id: 可选的会话 ID

        Returns:
            活跃模式列表
        """
        active = []
        for mode in SUPPORTED_MODES:
            state = self.read_state(mode, session_id)
            if state and state.active:
                active.append(mode)
        return active

    def get_status(
        self,
        mode: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """
        获取状态详情

        Args:
            mode: 可选的模式过滤
            session_id: 可选的会话 ID

        Returns:
            状态详情字典
        """
        if mode:
            state = self.read_state(mode, session_id)
            if state:
                return {"mode": mode, "state": state.to_dict()}
            return {"mode": mode, "state": None}

        # 返回所有模式状态
        result = {}
        for m in SUPPORTED_MODES:
            state = self.read_state(m, session_id)
            result[m] = state.to_dict() if state else None
        return result

    # ==================== 便捷方法 ====================

    def start_workflow(
        self,
        mode: str,
        task_description: str,
        max_iterations: int = 10,
        phases: list[str] | None = None,
        session_id: str | None = None,
    ) -> ModeState:
        """
        启动工作流

        Args:
            mode: 工作流模式
            task_description: 任务描述
            max_iterations: 最大迭代次数
            phases: 阶段列表
            session_id: 会话 ID

        Returns:
            初始状态
        """
        phases = phases or ["planning", "execution", "verification"]
        state = ModeState(
            mode=mode,
            active=True,
            iteration=0,
            max_iterations=max_iterations,
            current_phase=phases[0] if phases else "",
            task_description=task_description,
            started_at=datetime.now().isoformat(),
            metadata={"phases": phases},
        )
        return self.write_state(mode, state, session_id)

    def advance_phase(
        self,
        mode: str,
        session_id: str | None = None,
    ) -> ModeState | None:
        """
        推进到下一阶段

        Args:
            mode: 工作流模式
            session_id: 会话 ID

        Returns:
            更新后的状态
        """
        state = self.read_state(mode, session_id)
        if not state:
            return None

        phases = state.metadata.get("phases", [])
        if not phases:
            return state

        current_idx = phases.index(state.current_phase) if state.current_phase in phases else -1
        if current_idx < len(phases) - 1:
            state.current_phase = phases[current_idx + 1]

        return self.write_state(mode, state, session_id)

    def complete_workflow(
        self,
        mode: str,
        error: str = "",
        session_id: str | None = None,
    ) -> ModeState | None:
        """
        完成工作流

        Args:
            mode: 工作流模式
            error: 错误信息 (如果有)
            session_id: 会话 ID

        Returns:
            最终状态
        """
        state = self.read_state(mode, session_id)
        if not state:
            return None

        state.active = False
        state.completed_at = datetime.now().isoformat()
        if error:
            state.error = error

        return self.write_state(mode, state, session_id)

    def increment_iteration(
        self,
        mode: str,
        session_id: str | None = None,
    ) -> ModeState | None:
        """
        增加迭代计数

        Args:
            mode: 工作流模式
            session_id: 会话 ID

        Returns:
            更新后的状态
        """
        state = self.read_state(mode, session_id)
        if not state:
            return None

        state.iteration += 1
        return self.write_state(mode, state, session_id)


# ==================== MCP 工具接口 ====================

def build_mcp_tools() -> list[dict[str, Any]]:
    """
    构建 MCP 工具列表

    返回符合 Model Context Protocol 规范的工具定义
    """
    return [
        {
            "name": "state_read",
            "description": "Read state for a specific mode. Returns JSON state data or indicates no state exists.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": SUPPORTED_MODES,
                        "description": "The mode to read state for",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Optional session scope ID",
                    },
                },
                "required": ["mode"],
            },
        },
        {
            "name": "state_write",
            "description": "Write/update state for a specific mode.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": SUPPORTED_MODES,
                    },
                    "active": {"type": "boolean"},
                    "iteration": {"type": "number"},
                    "max_iterations": {"type": "number"},
                    "current_phase": {"type": "string"},
                    "task_description": {"type": "string"},
                    "started_at": {"type": "string"},
                    "completed_at": {"type": "string"},
                    "error": {"type": "string"},
                    "session_id": {"type": "string"},
                },
                "required": ["mode"],
            },
        },
        {
            "name": "state_clear",
            "description": "Clear/delete state for a specific mode.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": SUPPORTED_MODES,
                    },
                    "session_id": {"type": "string"},
                },
                "required": ["mode"],
            },
        },
        {
            "name": "state_list_active",
            "description": "List all currently active modes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                },
            },
        },
        {
            "name": "state_get_status",
            "description": "Get detailed status for a specific mode or all modes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": SUPPORTED_MODES,
                    },
                    "session_id": {"type": "string"},
                },
            },
        },
    ]


# ==================== 全局实例 ====================

_default_server: StateServer | None = None


def get_state_server(base_dir: Path | None = None) -> StateServer:
    """获取全局状态服务器实例"""
    global _default_server
    if _default_server is None:
        _default_server = StateServer(base_dir)
    return _default_server


# 导出
__all__ = [
    'SUPPORTED_MODES',
    'Mode',
    'ModeState',
    'StateServer',
    'build_mcp_tools',
    'get_state_server',
]
