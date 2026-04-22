"""MCP 服务器: Team Server (团队协调)

参考: oh-my-codex-main/src/mcp/team_server.ts
提供团队模式下的协调服务:
    - 共享任务板
    - 消息传递 (Mailbox)
    - 状态同步
    - worker 注册/心跳

数据: .clawd/team/
    board/         任务板
    mailboxes/     Agent 邮箱
    state/         团队状态
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Task:
    """团队任务"""
    id: str
    description: str
    assignee: str | None = None
    status: str = "pending"  # pending, in_progress, done, blocked
    priority: int = 0
    dependencies: list[str] = field(default_factory=list)
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    result: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MailboxMessage:
    """邮箱消息"""
    id: str
    from_agent: str
    to_agent: str
    subject: str
    body: str
    created_at: str
    read: bool = False


class TeamServer:
    """MCP Team Server - 团队协作协调"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.team_dir = project_root / ".clawd" / "team"
        self.team_dir.mkdir(parents=True, exist_ok=True)

        # 子目录
        (self.team_dir / "tasks").mkdir(exist_ok=True)
        (self.team_dir / "mailboxes").mkdir(exist_ok=True)
        (self.team_dir / "workers").mkdir(exist_ok=True)
        (self.team_dir / "board").mkdir(exist_ok=True)

        # 全局状态
        self.state_path = self.team_dir / "state.json"
        self._ensure_state()

    def _ensure_state(self) -> None:
        """确保状态文件存在"""
        if not self.state_path.exists():
            state = {
                "team_name": "default",
                "leader": None,
                "workers": [],
                "created_at": datetime.now().isoformat(),
            }
            self.state_path.write_text(json.dumps(state, indent=2))

    def _read_state(self) -> dict:
        return json.loads(self.state_path.read_text())

    def _write_state(self, state: dict) -> None:
        self.state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))

    # ==================== 任务板 ====================

    def create_task(self, description: str, **kwargs) -> str:
        """创建任务"""
        import uuid

        task_id = kwargs.get("id") or f"task_{uuid.uuid4().hex[:12]}"
        task = Task(
            id=task_id,
            description=description,
            created_at=datetime.now().isoformat(),
            **{k: v for k, v in kwargs.items() if k in Task.__dataclass_fields__},
        )
        path = self.team_dir / "tasks" / f"{task_id}.json"
        path.write_text(json.dumps(asdict(task), indent=2, ensure_ascii=False))
        logger.info(f"Created task: {task_id}")
        return task_id

    def get_task(self, task_id: str) -> Task | None:
        """获取任务"""
        path = self.team_dir / "tasks" / f"{task_id}.json"
        if path.exists():
            data = json.loads(path.read_text())
            return Task(**data)
        return None

    def update_task(self, task_id: str, **updates) -> Task | None:
        """更新任务"""
        task = self.get_task(task_id)
        if not task:
            return None
        for k, v in updates.items():
            if hasattr(task, k):
                setattr(task, k, v)
        path = self.team_dir / "tasks" / f"{task_id}.json"
        path.write_text(json.dumps(asdict(task), indent=2, ensure_ascii=False))
        return task

    def list_tasks(self, status: str | None = None) -> list[Task]:
        """列出任务"""
        tasks = []
        for p in (self.team_dir / "tasks").glob("*.json"):
            data = json.loads(p.read_text())
            if status is None or data.get("status") == status:
                tasks.append(Task(**data))
        return tasks

    def assign_task(self, task_id: str, assignee: str) -> bool:
        """分配任务"""
        task = self.get_task(task_id)
        if not task:
            return False
        task.assignee = assignee
        task.status = "in_progress"
        task.started_at = datetime.now().isoformat()
        path = self.team_dir / "tasks" / f"{task_id}.json"
        path.write_text(json.dumps(asdict(task), indent=2, ensure_ascii=False))
        logger.info(f"Task {task_id} assigned to {assignee}")
        return True

    # ==================== 邮箱 ====================

    def send_message(
        self,
        from_agent: str,
        to_agent: str,
        subject: str,
        body: str,
    ) -> str:
        """发送消息"""
        import uuid

        msg_id = f"msg_{uuid.uuid4().hex[:12]}"
        msg = MailboxMessage(
            id=msg_id,
            from_agent=from_agent,
            to_agent=to_agent,
            subject=subject,
            body=body,
            created_at=datetime.now().isoformat(),
        )
        # 存储到收件人邮箱
        mailbox_dir = self.team_dir / "mailboxes" / to_agent
        mailbox_dir.mkdir(parents=True, exist_ok=True)
        path = mailbox_dir / f"{msg_id}.json"
        path.write_text(json.dumps(asdict(msg), indent=2, ensure_ascii=False))
        logger.info(f"Message sent: {from_agent} -> {to_agent}: {subject}")
        return msg_id

    def get_mailbox(self, agent_name: str, unread_only: bool = False) -> list[MailboxMessage]:
        """获取邮箱消息"""
        mailbox_dir = self.team_dir / "mailboxes" / agent_name
        if not mailbox_dir.exists():
            return []

        messages = []
        for p in mailbox_dir.glob("*.json"):
            data = json.loads(p.read_text())
            if unread_only and data.get("read"):
                continue
            messages.append(MailboxMessage(**data))
        return sorted(messages, key=lambda m: m.created_at)

    def mark_read(self, agent_name: str, msg_id: str) -> bool:
        """标记消息已读"""
        path = self.team_dir / "mailboxes" / agent_name / f"{msg_id}.json"
        if path.exists():
            data = json.loads(path.read_text())
            data["read"] = True
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            return True
        return False

    def clear_mailbox(self, agent_name: str) -> int:
        """清空邮箱"""
        mailbox_dir = self.team_dir / "mailboxes" / agent_name
        if not mailbox_dir.exists():
            return 0
        count = 0
        for p in mailbox_dir.glob("*.json"):
            p.unlink()
            count += 1
        return count

    # ==================== Worker 注册 ====================

    def register_worker(
        self,
        agent_name: str,
        role: str,
        pid: int | None = None,
    ) -> str:
        """注册 Worker"""
        worker_id = f"worker_{agent_name}_{uuid.uuid4().hex[:8]}"
        worker = {
            "id": worker_id,
            "agent_name": agent_name,
            "role": role,
            "pid": pid,
            "status": "starting",
            "registered_at": datetime.now().isoformat(),
            "last_heartbeat": datetime.now().isoformat(),
        }
        path = self.team_dir / "workers" / f"{worker_id}.json"
        path.write_text(json.dumps(worker, indent=2, ensure_ascii=False))

        # 更新团队状态
        state = self._read_state()
        state["workers"].append(worker)
        self._write_state(state)

        logger.info(f"Worker registered: {agent_name} -> {worker_id}")
        return worker_id

    def heartbeat(self, worker_id: str) -> bool:
        """Worker 心跳"""
        path = self.team_dir / "workers" / f"{worker_id}.json"
        if path.exists():
            data = json.loads(path.read_text())
            data["last_heartbeat"] = datetime.now().isoformat()
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            return True
        return False

    def list_workers(self) -> list[dict]:
        """列出所有 Workers"""
        workers = []
        for p in (self.team_dir / "workers").glob("*.json"):
            workers.append(json.loads(p.read_text()))
        return workers

    def unregister_worker(self, worker_id: str) -> bool:
        """注销 Worker"""
        path = self.team_dir / "workers" / f"{worker_id}.json"
        if path.exists():
            data = json.loads(path.read_text())
            data["status"] = "stopped"
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            return True
        return False


def create_team_server(project_root: Path | None = None) -> TeamServer:
    """工厂函数: 创建 Team Server"""
    if project_root is None:
        project_root = Path.cwd()
    return TeamServer(project_root)


# MCP 工具
TEAM_SERVER_TOOLS = {
    "create_task": {
        "name": "create_task",
        "description": "Create a team task",
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "assignee": {"type": "string"},
                "priority": {"type": "integer", "default": 0},
            },
            "required": ["description"],
        },
    },
    "list_tasks": {
        "name": "list_tasks",
        "description": "List all tasks",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
            },
        },
    },
    "assign_task": {
        "name": "assign_task",
        "description": "Assign task to an agent",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "assignee": {"type": "string"},
            },
            "required": ["task_id", "assignee"],
        },
    },
    "send_message": {
        "name": "send_message",
        "description": "Send message to agent's mailbox",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to_agent": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to_agent", "subject", "body"],
        },
    },
    "get_mailbox": {
        "name": "get_mailbox",
        "description": "Get agent's mailbox messages",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent": {"type": "string"},
                "unread_only": {"type": "boolean", "default": False},
            },
            "required": ["agent"],
        },
    },
    "list_workers": {
        "name": "list_workers",
        "description": "List all registered workers",
        "inputSchema": {"type": "object", "properties": {}},
    },
}

__all__ = [
    "TEAM_SERVER_TOOLS",
    "MailboxMessage",
    "Task",
    "TeamServer",
    "create_team_server",
]
