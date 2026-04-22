"""Team Task State Management

汲取 oh-my-codex-main/src/team/state/tasks.ts (概念)

管理团队任务的状态转换、声明、释放等操作。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


@dataclass
class TeamTaskClaim:
    """任务声明记录"""

    owner: str
    token: str
    leased_until: datetime

    def is_expired(self) -> bool:
        """检查声明是否过期"""
        return datetime.now() > self.leased_until

    def to_dict(self) -> dict:
        return {
            "owner": self.owner,
            "token": self.token,
            "leased_until": self.leased_until.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> TeamTaskClaim:
        return cls(
            owner=data["owner"],
            token=data["token"],
            leased_until=datetime.fromisoformat(data["leased_until"]),
        )


@dataclass
class TeamTask:
    """团队任务"""

    id: str
    subject: str
    description: str
    status: str  # 'pending'|'blocked'|'in_progress'|'completed'|'failed'
    requires_code_change: bool = False
    role: str | None = None
    owner: str | None = None
    result: str | None = None
    error: str | None = None
    blocked_by: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    version: int = 0
    claim: TeamTaskClaim | None = None
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None

    # 状态常量
    STATUS_PENDING = "pending"
    STATUS_BLOCKED = "blocked"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    def to_dict(self) -> dict:
        result = asdict(self)
        result["created_at"] = self.created_at.isoformat()
        result["completed_at"] = self.completed_at.isoformat() if self.completed_at else None
        if self.claim:
            result["claim"] = self.claim.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict) -> TeamTask:
        claim_data = data.pop("claim", None)
        created_at = datetime.fromisoformat(data.pop("created_at")) if "created_at" in data else datetime.now()
        completed_at = datetime.fromisoformat(data.pop("completed_at")) if data.get("completed_at") else None

        task = cls(
            id=data["id"],
            subject=data["subject"],
            description=data["description"],
            status=data.get("status", cls.STATUS_PENDING),
            requires_code_change=data.get("requires_code_change", False),
            role=data.get("role"),
            owner=data.get("owner"),
            result=data.get("result"),
            error=data.get("error"),
            blocked_by=data.get("blocked_by", []),
            depends_on=data.get("depends_on", []),
            version=data.get("version", 0),
            created_at=created_at,
            completed_at=completed_at,
        )

        if claim_data:
            task.claim = TeamTaskClaim.from_dict(claim_data)

        return task


class TaskStateStore:
    """任务状态存储（文件系统版）"""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir / "tasks"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _task_path(self, task_id: str) -> Path:
        return self.state_dir / f"{task_id}.json"

    def read_task(self, task_id: str) -> TeamTask | None:
        """读取任务"""
        path = self._task_path(task_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return TeamTask.from_dict(data)
        except Exception:
            return None

    def write_task(self, task: TeamTask) -> None:
        """写入任务"""
        path = self._task_path(task.id)
        path.write_text(json.dumps(task.to_dict(), indent=2))

    def list_tasks(self, status: str | None = None) -> list[TeamTask]:
        """列出所有任务，可选按状态过滤"""
        tasks = []
        for path in self.state_dir.glob("*.json"):
            try:
                task = TeamTask.from_dict(json.loads(path.read_text()))
                if status is None or task.status == status:
                    tasks.append(task)
            except Exception:
                continue
        return tasks

    def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        path = self._task_path(task_id)
        if path.exists():
            path.unlink()
            return True
        return False


# 任务状态转换验证
VALID_TRANSITIONS = {
    TeamTask.STATUS_PENDING: [TeamTask.STATUS_BLOCKED, TeamTask.STATUS_IN_PROGRESS],
    TeamTask.STATUS_BLOCKED: [TeamTask.STATUS_PENDING, TeamTask.STATUS_IN_PROGRESS],
    TeamTask.STATUS_IN_PROGRESS: [TeamTask.STATUS_COMPLETED, TeamTask.STATUS_FAILED, TeamTask.STATUS_BLOCKED],
    TeamTask.STATUS_COMPLETED: [],
    TeamTask.STATUS_FAILED: [TeamTask.STATUS_PENDING],
}


def can_transition_task_status(current: str, next_status: str) -> bool:
    """检查任务状态转换是否合法"""
    return next_status in VALID_TRANSITIONS.get(current, [])


def is_terminal_task_status(status: str) -> bool:
    """检查是否为终止状态"""
    return status in (TeamTask.STATUS_COMPLETED, TeamTask.STATUS_FAILED)


# 任务声明锁管理
def claim_task(
    task_id: str,
    owner: str,
    lease_seconds: int = 60,
    token: str | None = None,
) -> TeamTaskClaim | None:
    """声明一个任务（乐观锁）

    Args:
        task_id: 任务ID
        owner: 声明者
        lease_seconds: 租约秒数
        token: 用于CAS的token（可选）

    Returns:
        如果声明成功，返回声明记录；否则返回None
    """
    import random
    import string

    store = TaskStateStore(Path.cwd() / ".clawd")
    task = store.read_task(task_id)
    if not task:
        return None

    # 检查任务是否可以声明
    if task.status not in (TeamTask.STATUS_PENDING, TeamTask.STATUS_BLOCKED):
        return None

    # 检查现有声明是否过期
    if task.claim and not task.claim.is_expired():
        return None

    # 生成新的声明token
    new_token = token or "".join(random.choices(string.ascii_letters + string.digits, k=16))
    lease_until = datetime.now() + timedelta(seconds=lease_seconds)

    claim = TeamTaskClaim(owner=owner, token=new_token, leased_until=lease_until)
    task.claim = claim
    task.status = TeamTask.STATUS_IN_PROGRESS
    store.write_task(task)

    return claim


def release_task_claim(task_id: str, owner: str, token: str) -> bool:
    """释放任务声明"""
    store = TaskStateStore(Path.cwd() / ".clawd")
    task = store.read_task(task_id)
    if not task or not task.claim:
        return False

    if task.claim.owner != owner or task.claim.token != token:
        return False

    task.claim = None
    task.status = TeamTask.STATUS_PENDING
    task.owner = None
    store.write_task(task)

    return True


def reclaim_expired_task_claims() -> list[str]:
    """回收所有过期的任务声明，返回被回收的任务ID列表"""
    store = TaskStateStore(Path.cwd() / ".clawd")
    reclaimed = []

    for task in store.list_tasks():
        if task.claim and task.claim.is_expired():
            task.claim = None
            task.status = TeamTask.STATUS_PENDING
            task.owner = None
            store.write_task(task)
            reclaimed.append(task.id)

    return reclaimed
