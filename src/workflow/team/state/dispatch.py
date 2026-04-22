"""Team Dispatch State - 任务分发状态管理

汲取 oh-my-codex-main/src/team/state/dispatch.ts (概念)

管理任务分发请求、状态转换和通知。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class DispatchRequest:
    """分发请求"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    worker_name: str = ""
    status: str = "pending"  # pending|dispatched|acknowledged|completed|failed
    dispatched_at: datetime | None = None
    acknowledged_at: datetime | None = None
    completed_at: datetime | None = None
    timeout_seconds: int = 300
    error_message: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "worker_name": self.worker_name,
            "status": self.status,
            "dispatched_at": self.dispatched_at.isoformat() if self.dispatched_at else None,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "timeout_seconds": self.timeout_seconds,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DispatchRequest:
        req = cls(
            id=data.get("id", str(uuid.uuid4())),
            task_id=data.get("task_id", ""),
            worker_name=data.get("worker_name", ""),
            status=data.get("status", "pending"),
            timeout_seconds=data.get("timeout_seconds", 300),
            error_message=data.get("error_message"),
            metadata=data.get("metadata", {}),
        )
        if data.get("dispatched_at"):
            req.dispatched_at = datetime.fromisoformat(data["dispatched_at"])
        if data.get("acknowledged_at"):
            req.acknowledged_at = datetime.fromisoformat(data["acknowledged_at"])
        if data.get("completed_at"):
            req.completed_at = datetime.fromisoformat(data["completed_at"])
        return req


class DispatchStore:
    """分发请求存储"""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir / "dispatch"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _request_path(self, request_id: str) -> Path:
        return self.state_dir / f"{request_id}.json"

    def create_request(self, task_id: str, worker_name: str, **kwargs) -> DispatchRequest:
        """创建分发请求"""
        req = DispatchRequest(
            task_id=task_id,
            worker_name=worker_name,
            dispatched_at=datetime.now(),
            **kwargs,
        )
        path = self._request_path(req.id)
        path.write_text(json.dumps(req.to_dict(), indent=2))
        return req

    def read_request(self, request_id: str) -> DispatchRequest | None:
        """读取分发请求"""
        path = self._request_path(request_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return DispatchRequest.from_dict(data)
        except Exception:
            return None

    def update_request(self, request: DispatchRequest) -> None:
        """更新分发请求"""
        path = self._request_path(request.id)
        path.write_text(json.dumps(request.to_dict(), indent=2))

    def list_requests(
        self,
        worker_name: str | None = None,
        status: str | None = None,
    ) -> list[DispatchRequest]:
        """列出分发请求"""
        requests = []
        for path in self.state_dir.glob("*.json"):
            try:
                req = DispatchRequest.from_dict(json.loads(path.read_text()))
                if worker_name and req.worker_name != worker_name:
                    continue
                if status and req.status != status:
                    continue
                requests.append(req)
            except Exception:
                continue
        return sorted(requests, key=lambda r: r.dispatched_at or datetime.now())


def enqueue_dispatch_request(
    task_id: str,
    worker_name: str,
    **kwargs,
) -> DispatchRequest:
    """入队分发请求"""
    store = DispatchStore(Path.cwd() / ".clawd")
    return store.create_request(task_id=task_id, worker_name=worker_name, **kwargs)


def list_dispatch_requests(
    worker_name: str | None = None,
    status: str | None = None,
) -> list[DispatchRequest]:
    """列出分发请求"""
    store = DispatchStore(Path.cwd() / ".clawd")
    return store.list_requests(worker_name=worker_name, status=status)


def read_dispatch_request(request_id: str) -> DispatchRequest | None:
    """读取分发请求"""
    store = DispatchStore(Path.cwd() / ".clawd")
    return store.read_request(request_id)


def transition_dispatch_request(
    request_id: str,
    new_status: str,
    error_message: str | None = None,
) -> DispatchRequest | None:
    """转换分发请求状态"""
    store = DispatchStore(Path.cwd() / ".clawd")
    req = store.read_request(request_id)
    if not req:
        return None

    req.status = new_status
    if new_status == "acknowledged":
        req.acknowledged_at = datetime.now()
    elif new_status == "completed":
        req.completed_at = datetime.now()
    elif new_status == "failed":
        req.error_message = error_message

    store.update_request(req)
    return req


def mark_dispatch_request_notified(request_id: str) -> bool:
    """标记分发请求已通知（设置notified标志）"""
    store = DispatchStore(Path.cwd() / ".clawd")
    req = store.read_request(request_id)
    if not req:
        return False
    req.metadata["notified"] = True
    store.update_request(req)
    return True


def mark_dispatch_request_delivered(request_id: str) -> bool:
    """标记分发请求已送达"""
    store = DispatchStore(Path.cwd() / ".clawd")
    req = store.read_request(request_id)
    if not req:
        return False
    req.metadata["delivered"] = True
    store.update_request(req)
    return True


# 状态常量
DISPATCH_STATUS_PENDING = "pending"
DISPATCH_STATUS_DISPATCHED = "dispatched"
DISPATCH_STATUS_ACKNOWLEDGED = "acknowledged"
DISPATCH_STATUS_COMPLETED = "completed"
DISPATCH_STATUS_FAILED = "failed"
