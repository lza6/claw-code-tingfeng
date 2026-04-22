"""MCP 服务器: State Server (状态持久化)

参考: oh-my-codex-main/src/mcp/state_server.ts
提供项目状态、会话状态、工具使用历史的 MCP 接口。

数据存储: .clawd/state/
    - sessions/   会话状态
    - surfaces/    表面 (Surfaces)
    - tasks/       任务注册表
"""
from __future__ import annotations

import json
from pathlib import Path

from src.core.events import EventBus
from src.utils.logger import get_logger

logger = get_logger(__name__)


class StateServer:
    """MCP State Server - 状态管理服务器"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.state_dir = project_root / ".clawd" / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # 子目录
        (self.state_dir / "sessions").mkdir(exist_ok=True)
        (self.state_dir / "surfaces").mkdir(exist_ok=True)
        (self.state_dir / "tasks").mkdir(exist_ok=True)
        (self.state_dir / "events").mkdir(exist_ok=True)

        self.event_bus = EventBus()

    def get_session_state(self, session_id: str) -> dict | None:
        """获取会话状态"""
        path = self.state_dir / "sessions" / f"{session_id}.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def set_session_state(self, session_id: str, state: dict) -> None:
        """设置会话状态"""
        path = self.state_dir / "sessions" / f"{session_id}.json"
        path.write_text(json.dumps(state, indent=2, ensure_ascii=False))

    def list_sessions(self) -> list[str]:
        """列出所有会话"""
        sessions_dir = self.state_dir / "sessions"
        return [p.stem for p in sessions_dir.glob("*.json")]

    def get_surface(self, name: str) -> dict | None:
        """获取 Surface 数据"""
        path = self.state_dir / "surfaces" / f"{name}.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def set_surface(self, name: str, data: dict) -> None:
        """设置 Surface 数据"""
        path = self.state_dir / "surfaces" / f"{name}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def get_task_state(self, task_id: str) -> dict | None:
        """获取任务状态"""
        path = self.state_dir / "tasks" / f"{task_id}.json"
        if path.exists():
            return json.loads(path.read_text())
        return None

    def set_task_state(self, task_id: str, data: dict) -> None:
        """设置任务状态"""
        path = self.state_dir / "tasks" / f"{task_id}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def log_event(self, event_type: str, data: dict) -> None:
        """记录事件"""
        import datetime

        event = {
            "type": event_type,
            "timestamp": datetime.datetime.now().isoformat(),
            "data": data,
        }
        path = self.state_dir / "events" / "log.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def clear_session(self, session_id: str) -> None:
        """清除会话状态"""
        path = self.state_dir / "sessions" / f"{session_id}.json"
        if path.exists():
            path.unlink()

    def cleanup_old_sessions(self, max_age_days: int = 7) -> int:
        """清理旧会话"""
        from datetime import datetime, timedelta

        cutoff = datetime.now() - timedelta(days=max_age_days)
        cleaned = 0
        for p in (self.state_dir / "sessions").glob("*.json"):
            # 使用文件修改时间
            import os
            mtime = datetime.fromtimestamp(os.path.getmtime(p))
            if mtime < cutoff:
                p.unlink()
                cleaned += 1
        return cleaned


def create_state_server(project_root: Path | None = None) -> StateServer:
    """工厂函数: 创建 State Server"""
    if project_root is None:
        project_root = Path.cwd()
    return StateServer(project_root)


# MCP 工具注册 (模拟 MCP SDK 接口)
STATE_SERVER_TOOLS = {
    "get_session_state": {
        "name": "get_session_state",
        "description": "Get session state by session ID",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID"},
            },
            "required": ["session_id"],
        },
    },
    "set_session_state": {
        "name": "set_session_state",
        "description": "Set session state",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "state": {"type": "object"},
            },
            "required": ["session_id", "state"],
        },
    },
    "list_sessions": {
        "name": "list_sessions",
        "description": "List all session IDs",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "get_surface": {
        "name": "get_surface",
        "description": "Get a durable surface value",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Surface name"},
            },
            "required": ["name"],
        },
    },
    "set_surface": {
        "name": "set_surface",
        "description": "Set a durable surface value",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "data": {"type": "object"},
            },
            "required": ["name", "data"],
        },
    },
    "cleanup_old_sessions": {
        "name": "cleanup_old_sessions",
        "description": "Clean up old session files",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_age_days": {"type": "integer", "default": 7},
            },
        },
    },
}

__all__ = [
    "STATE_SERVER_TOOLS",
    "StateServer",
    "create_state_server",
]
