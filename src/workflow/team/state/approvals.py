"""Team Approvals - 任务审批管理

汲取 oh-my-codex-main/src/team/state/approvals.ts (概念)

管理任务审批、人工确认流程。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


@dataclass
class TaskApproval:
    """任务审批请求"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    requested_by: str = ""
    approved_by: str | None = None
    status: str = "pending"  # pending|approved|rejected|timeout
    requested_at: datetime = field(default_factory=datetime.now)
    approved_at: datetime | None = None
    timeout_seconds: int = 300
    reason: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "requested_by": self.requested_by,
            "approved_by": self.approved_by,
            "status": self.status,
            "requested_at": self.requested_at.isoformat(),
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "timeout_seconds": self.timeout_seconds,
            "reason": self.reason,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaskApproval:
        approval = cls(
            id=data.get("id", str(uuid.uuid4())),
            task_id=data.get("task_id", ""),
            requested_by=data.get("requested_by", ""),
            approved_by=data.get("approved_by"),
            status=data.get("status", "pending"),
            timeout_seconds=data.get("timeout_seconds", 300),
            reason=data.get("reason"),
            metadata=data.get("metadata", {}),
        )
        if data.get("requested_at"):
            approval.requested_at = datetime.fromisoformat(data["requested_at"])
        if data.get("approved_at"):
            approval.approved_at = datetime.fromisoformat(data["approved_at"])
        return approval

    def is_expired(self) -> bool:
        """检查审批是否超时"""
        if self.status != "pending":
            return False
        expiry = self.requested_at + timedelta(seconds=self.timeout_seconds)
        return datetime.now() > expiry

    def approve(self, approver: str) -> None:
        """批准审批"""
        self.status = "approved"
        self.approved_by = approver
        self.approved_at = datetime.now()

    def reject(self, reason: str | None = None) -> None:
        """拒绝审批"""
        self.status = "rejected"
        self.reason = reason or "Rejected"


class ApprovalStore:
    """审批存储"""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir / "approvals"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _approval_path(self, approval_id: str) -> Path:
        return self.state_dir / f"{approval_id}.json"

    def create_approval(self, task_id: str, requested_by: str, **kwargs) -> TaskApproval:
        """创建审批请求"""
        approval = TaskApproval(
            task_id=task_id,
            requested_by=requested_by,
            **kwargs,
        )
        path = self._approval_path(approval.id)
        path.write_text(json.dumps(approval.to_dict(), indent=2))
        return approval

    def read_approval(self, approval_id: str) -> TaskApproval | None:
        """读取审批"""
        path = self._approval_path(approval_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return TaskApproval.from_dict(data)
        except Exception:
            return None

    def update_approval(self, approval: TaskApproval) -> None:
        """更新审批"""
        path = self._approval_path(approval.id)
        path.write_text(json.dumps(approval.to_dict(), indent=2))

    def list_pending_approvals(self, task_id: str | None = None) -> list[TaskApproval]:
        """列出待处理的审批"""
        approvals = []
        for path in self.state_dir.glob("*.json"):
            try:
                approval = TaskApproval.from_dict(json.loads(path.read_text()))
                if approval.status == "pending" and not approval.is_expired():
                    if task_id is None or approval.task_id == task_id:
                        approvals.append(approval)
            except Exception:
                continue
        return sorted(approvals, key=lambda a: a.requested_at)

    def list_task_approvals(self, task_id: str) -> list[TaskApproval]:
        """列出任务的审批历史"""
        approvals = []
        for path in self.state_dir.glob("*.json"):
            try:
                approval = TaskApproval.from_dict(json.loads(path.read_text()))
                if approval.task_id == task_id:
                    approvals.append(approval)
            except Exception:
                continue
        return sorted(approvals, key=lambda a: a.requested_at)


def write_task_approval(approval: TaskApproval, state_dir: Path | None = None) -> str:
    """写入任务审批"""
    if state_dir is None:
        state_dir = Path.cwd() / ".clawd"

    store = ApprovalStore(state_dir)
    store.create_approval(
        task_id=approval.task_id,
        requested_by=approval.requested_by,
        timeout_seconds=approval.timeout_seconds,
        reason=approval.reason,
        metadata=approval.metadata,
    )
    return approval.id


def read_task_approval(approval_id: str, state_dir: Path | None = None) -> TaskApproval | None:
    """读取任务审批"""
    if state_dir is None:
        state_dir = Path.cwd() / ".clawd"

    store = ApprovalStore(state_dir)
    return store.read_approval(approval_id)


def list_pending_approvals(task_id: str | None = None, state_dir: Path | None = None) -> list[TaskApproval]:
    """列出待处理审批"""
    if state_dir is None:
        state_dir = Path.cwd() / ".clawd"

    store = ApprovalStore(state_dir)
    return store.list_pending_approvals(task_id=task_id)
