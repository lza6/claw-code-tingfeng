"""Dispatch Lock - 分发锁管理

汲取 oh-my-codex-main/src/team/state/dispatch-lock.ts

提供任务分发的互斥锁，防止重复分发。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


@dataclass
class DispatchLock:
    """分发锁记录"""

    lock_id: str
    owner: str
    acquired_at: datetime
    expires_at: datetime
    metadata: dict = field(default_factory=dict)

    def is_expired(self) -> bool:
        return datetime.now() > self.expires_at

    def to_dict(self) -> dict:
        return {
            "lock_id": self.lock_id,
            "owner": self.owner,
            "acquired_at": self.acquired_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DispatchLock:
        return cls(
            lock_id=data["lock_id"],
            owner=data["owner"],
            acquired_at=datetime.fromisoformat(data["acquired_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
            metadata=data.get("metadata", {}),
        )


class DispatchLockStore:
    """分发锁存储"""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir / "dispatch_locks"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _lock_path(self, lock_id: str) -> Path:
        return self.state_dir / f"{lock_id}.json"

    def acquire_lock(
        self,
        lock_id: str,
        owner: str,
        ttl_seconds: int = 30,
    ) -> DispatchLock | None:
        """尝试获取锁（CAS）"""
        path = self._lock_path(lock_id)

        # 如果锁文件存在，检查是否过期
        if path.exists():
            try:
                data = json.loads(path.read_text())
                existing = DispatchLock.from_dict(data)
                if not existing.is_expired():
                    # 锁被占用
                    return None
                # 锁已过期，可以覆盖
            except Exception:
                pass

        # 创建新锁
        now = datetime.now()
        lock = DispatchLock(
            lock_id=lock_id,
            owner=owner,
            acquired_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        path.write_text(json.dumps(lock.to_dict(), indent=2))
        return lock

    def renew_lock(self, lock_id: str, owner: str, ttl_seconds: int = 30) -> DispatchLock | None:
        """续租锁"""
        lock = self.acquire_lock(lock_id, owner, ttl_seconds)
        return lock

    def release_lock(self, lock_id: str, owner: str) -> bool:
        """释放锁（只有所有者可以释放）"""
        path = self._lock_path(lock_id)
        if not path.exists():
            return False

        try:
            data = json.loads(path.read_text())
            lock = DispatchLock.from_dict(data)
            if lock.owner != owner:
                return False
            path.unlink()
            return True
        except Exception:
            return False

    def get_lock(self, lock_id: str) -> DispatchLock | None:
        """获取锁信息"""
        path = self._lock_path(lock_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return DispatchLock.from_dict(data)
        except Exception:
            return None


def with_dispatch_lock(
    lock_id: str,
    owner: str,
    ttl_seconds: int = 30,
):
    """装饰器：在执行函数时持有分发锁"""

    def decorator(func):
        def wrapper(*args, **kwargs):
            store = DispatchLockStore(Path.cwd() / ".clawd")
            lock = store.acquire_lock(lock_id, owner, ttl_seconds)
            if not lock:
                raise ClawdError(
                    ErrorCode.CONFLICT,
                    f"Could not acquire dispatch lock: {lock_id}",
                )
            try:
                return func(*args, **kwargs)
            finally:
                store.release_lock(lock_id, owner)

        return wrapper

    return decorator
