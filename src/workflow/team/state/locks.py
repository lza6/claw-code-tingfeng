"""Team Locks - 团队锁管理

汲取 oh-my-codex-main/src/team/state/locks.ts (概念)

提供各种锁机制:
- with_team_lock: 团队级锁
- with_task_claim_lock: 任务声明锁
- with_mailbox_lock: 邮箱锁
"""

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any

from ...core.exceptions import ClawdError, ErrorCode


@dataclass
class LockInfo:
    """锁信息"""

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
    def from_dict(cls, data: dict) -> LockInfo:
        return cls(
            lock_id=data["lock_id"],
            owner=data["owner"],
            acquired_at=datetime.fromisoformat(data["acquired_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
            metadata=data.get("metadata", {}),
        )


class LockStore:
    """锁存储基类"""

    def __init__(self, state_dir: Path, lock_type: str):
        self.lock_dir = state_dir / f"{lock_type}_locks"
        self.lock_dir.mkdir(parents=True, exist_ok=True)

    def _lock_path(self, lock_id: str) -> Path:
        return self.lock_dir / f"{lock_id}.json"

    def acquire(
        self,
        lock_id: str,
        owner: str,
        ttl_seconds: int = 30,
    ) -> LockInfo | None:
        """获取锁"""
        path = self._lock_path(lock_id)

        # 检查现有锁
        if path.exists():
            try:
                data = json.loads(path.read_text())
                existing = LockInfo.from_dict(data)
                if not existing.is_expired() and existing.owner != owner:
                    return None  # 锁被占用
            except Exception:
                pass

        # 创建新锁
        now = datetime.now()
        lock = LockInfo(
            lock_id=lock_id,
            owner=owner,
            acquired_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        path.write_text(json.dumps(lock.to_dict(), indent=2))
        return lock

    def renew(self, lock_id: str, owner: str, ttl_seconds: int = 30) -> LockInfo | None:
        """续租锁"""
        return self.acquire(lock_id, owner, ttl_seconds)

    def release(self, lock_id: str, owner: str) -> bool:
        """释放锁"""
        path = self._lock_path(lock_id)
        if not path.exists():
            return False

        try:
            data = json.loads(path.read_text())
            lock = LockInfo.from_dict(data)
            if lock.owner != owner:
                return False
            path.unlink()
            return True
        except Exception:
            return False

    def get(self, lock_id: str) -> LockInfo | None:
        """获取锁信息"""
        path = self._lock_path(lock_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return LockInfo.from_dict(data)
        except Exception:
            return None


@contextmanager
def with_team_lock(
    team_name: str,
    owner: str,
    ttl_seconds: int = 30,
    state_dir: Path | None = None,
) -> Generator[None, None, None]:
    """团队锁上下文管理器"""
    if state_dir is None:
        state_dir = Path.cwd() / ".clawd"

    store = LockStore(state_dir, "team")
    lock_id = f"team_{team_name}"
    lock = store.acquire(lock_id, owner, ttl_seconds)
    if not lock:
        raise ClawdError(
            ErrorCode.CONFLICT,
            f"Could not acquire team lock: {team_name}",
        )
    try:
        yield
    finally:
        store.release(lock_id, owner)


@contextmanager
def with_task_claim_lock(
    task_id: str,
    owner: str,
    ttl_seconds: int = 30,
    state_dir: Path | None = None,
) -> Generator[None, None, None]:
    """任务声明锁上下文管理器"""
    if state_dir is None:
        state_dir = Path.cwd() / ".clawd"

    store = LockStore(state_dir, "task_claim")
    lock_id = f"task_claim_{task_id}"
    lock = store.acquire(lock_id, owner, ttl_seconds)
    if not lock:
        raise ClawdError(
            ErrorCode.CONFLICT,
            f"Could not acquire task claim lock: {task_id}",
        )
    try:
        yield
    finally:
        store.release(lock_id, owner)


@contextmanager
def with_mailbox_lock(
    agent_id: str,
    owner: str,
    ttl_seconds: int = 10,
    state_dir: Path | None = None,
) -> Generator[None, None, None]:
    """邮箱锁上下文管理器（短租期）"""
    if state_dir is None:
        state_dir = Path.cwd() / ".clawd"

    store = LockStore(state_dir, "mailbox")
    lock_id = f"mailbox_{agent_id}"
    lock = store.acquire(lock_id, owner, ttl_seconds)
    if not lock:
        raise ClawdError(
            ErrorCode.CONFLICT,
            f"Could not acquire mailbox lock: {agent_id}",
        )
    try:
        yield
    finally:
        store.release(lock_id, owner)


def with_scaling_lock(
    lock_id: str,
    owner: str,
    ttl_seconds: int = 30,
):
    """装饰器：在执行函数时持有扩展锁"""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            state_dir = Path.cwd() / ".clawd"
            store = LockStore(state_dir, "scaling")
            lock = store.acquire(lock_id, owner, ttl_seconds)
            if not lock:
                raise ClawdError(
                    ErrorCode.CONFLICT,
                    f"Could not acquire scaling lock: {lock_id}",
                )
            try:
                return func(*args, **kwargs)
            finally:
                store.release(lock_id, owner)

        return wrapper

    return decorator


def with_task_claim_lock_decorator(
    task_id: str,
    owner: str,
    ttl_seconds: int = 30,
):
    """装饰器：持有任务声明锁"""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            state_dir = Path.cwd() / ".clawd"
            store = LockStore(state_dir, "task_claim")
            lock_id = f"task_claim_{task_id}"
            lock = store.acquire(lock_id, owner, ttl_seconds)
            if not lock:
                raise ClawdError(
                    ErrorCode.CONFLICT,
                    f"Could not acquire task claim lock: {task_id}",
                )
            try:
                return func(*args, **kwargs)
            finally:
                store.release(lock_id, owner)

        return wrapper

    return decorator


def with_mailbox_lock_decorator(
    agent_id: str,
    owner: str,
    ttl_seconds: int = 10,
):
    """装饰器：持有邮箱锁"""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            state_dir = Path.cwd() / ".clawd"
            store = LockStore(state_dir, "mailbox")
            lock_id = f"mailbox_{agent_id}"
            lock = store.acquire(lock_id, owner, ttl_seconds)
            if not lock:
                raise ClawdError(
                    ErrorCode.CONFLICT,
                    f"Could not acquire mailbox lock: {agent_id}",
                )
            try:
                return func(*args, **kwargs)
            finally:
                store.release(lock_id, owner)

        return wrapper

    return decorator
