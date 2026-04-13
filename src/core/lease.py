import time
from dataclasses import dataclass
from typing import Dict, Optional
import uuid

@dataclass
class TaskLease:
    id: str
    task_id: str
    expires_at: float
    heartbeat_count: int = 0

class TaskLeaseManager:
    """任务租约管理器 (借鉴 goalx-main/cli/lease_loop.go)
    
    职责:
    - 为每个执行任务分配一个带生存时间的“租约” (Lease)
    - 定期心跳，如租约过期则强制触发自愈或中断
    """
    def __init__(self, default_duration: float = 300.0):
        self.default_duration = default_duration
        self.active_leases: Dict[str, TaskLease] = {}

    def acquire(self, task_id: str) -> str:
        lease_id = str(uuid.uuid4())
        expires = time.time() + self.default_duration
        self.active_leases[lease_id] = TaskLease(id=lease_id, task_id=task_id, expires_at=expires)
        return lease_id

    def heartbeat(self, lease_id: str):
        if lease_id in self.active_leases:
            self.active_leases[lease_id].expires_at = time.time() + self.default_duration
            self.active_leases[lease_id].heartbeat_count += 1
            return True
        return False

    def is_expired(self, lease_id: str) -> bool:
        if lease_id not in self.active_leases:
            return True
        return time.time() > self.active_leases[lease_id].expires_at

    def release(self, lease_id: str):
        if lease_id in self.active_leases:
            del self.active_leases[lease_id]
