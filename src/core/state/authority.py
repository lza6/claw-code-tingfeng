"""Authority Lease 租约机制 - 移植自 oh-my-codex-main/crates/omx-runtime-core/authority.rs

Exactly-One 语义的租约管理器，用于保证同一时刻只有一个 worker 能执行关键操作。

核心特性：
1. 租约获取：acquire(owner, ttl) - 原子性获取租约
2. 租约续期：renew(owner, ttl) - 续期现有租约
3. 租约释放：release() / force_release() - 正常或强制释放
4. 过期检测：is_stale() 检查租约是否过期
5. 状态标记：mark_stale(reason) 记录过期原因

租约状态：
- Active: 租约有效，owner 可执行操作
- Expired: 租约过期，可被任何 worker 抢占
- Released: 租约已释放，可被重新获取

线程安全：所有操作通过 RLock 保护
持久化：通过 RuntimeSnapshot.authority 字段序列化
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.core.state.command_event import AuthoritySnapshot

# ========== 异常定义 ==========


class AuthorityError(Exception):
    """Authority 操作相关异常基类"""
    pass


class LeaseAcquisitionFailed(AuthorityError):
    """租约获取失败"""
    pass


class LeaseRenewalFailed(AuthorityError):
    """租约续期失败"""
    pass


class LeaseAlreadyHeldError(AuthorityError):
    """租约已被持有（尝试重复获取）"""
    pass


class LeaseNotHeldError(AuthorityError):
    """租约未持有（尝试释放或续期）"""
    pass


class UnauthorizedRenewalError(AuthorityError):
    """非持有者尝试续期"""
    pass


# ========== 数据类 ==========


@dataclass(frozen=True, slots=True)
class LeaseInfo:
    """
    租约详细信息

    Attributes:
        owner: 持有者标识（worker_id）
        lease_id: 租约唯一标识（UUID）
        granted_at: 租约授予时间（UTC）
        expires_at: 租约过期时间（ISO 8601）
    """
    owner: str
    lease_id: str
    granted_at: datetime
    expires_at: datetime

    def is_expired(self, now: datetime | None = None) -> bool:
        """检查租约是否已过期"""
        if now is None:
            now = datetime.now(timezone.utc)
        return now >= self.expires_at

    def remaining_ttl(self, now: datetime | None = None) -> float:
        """计算剩余 TTL（秒）"""
        if now is None:
            now = datetime.now(timezone.utc)
        if self.is_expired(now):
            return 0.0
        delta = self.expires_at - now
        return delta.total_seconds()

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（用于快照持久化）"""
        return {
            'owner': self.owner,
            'lease_id': self.lease_id,
            'granted_at': self.granted_at.isoformat(),
            'expires_at': self.expires_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LeaseInfo:
        """从字典反序列化"""
        return cls(
            owner=data['owner'],
            lease_id=data['lease_id'],
            granted_at=datetime.fromisoformat(data['granted_at']),
            expires_at=datetime.fromisoformat(data['expires_at']),
        )


# ========== 核心实现 ==========


class AuthorityLease:
    """
    Authority 租约管理器 - Exactly-One 语义

    使用场景：
    1. 防止多个 worker 同时修改共享状态
    2. 保证 task dispatch 的顺序性
    3. 实现 leader election 的轻量级版本

    设计要点：
    - 租约具有 TTL，需要定期续期
    - 过期租约自动失效，允许抢占
    - 所有操作线程安全
    - 支持快照持久化恢复

    示例：
    ```python
    lease = AuthorityLease()

    # Worker-1 获取租约
    info = lease.acquire("worker-1", ttl=300)
    assert info.owner == "worker-1"

    # Worker-2 尝试获取会被拒绝
    try:
        lease.acquire("worker-2", ttl=300)
    except LeaseAcquisitionFailed:
        pass  # 预期行为

    # Worker-1 续期
    lease.renew("worker-1", ttl=300)

    # 完成工作后释放
    lease.release()

    # 检查租约状态
    if lease.is_stale():
        print("租约已过期")
    ```
    """

    def __init__(self):
        """初始化空租约"""
        self._lease: LeaseInfo | None = None
        self._stale_reason: str | None = None
        self._lock = threading.RLock()

    # ========== 查询操作 ==========

    def is_held(self) -> bool:
        """
        检查租约是否被持有且未过期

        Returns:
            True: 租约有效且未过期
            False: 无租约或租约已过期
        """
        with self._lock:
            if self._lease is None:
                return False
            return not self._lease.is_expired()

    def is_stale(self) -> bool:
        """
        检查租约是否过期

        Returns:
            True: 租约存在但已过期
            False: 无租约或租约有效
        """
        with self._lock:
            if self._lease is None:
                return False
            return self._lease.is_expired()

    def get_stale_reason(self) -> str | None:
        """获取过期原因（如果有）"""
        with self._lock:
            return self._stale_reason

    def get_owner(self) -> str | None:
        """获取当前租约持有者（可能已过期）"""
        with self._lock:
            return self._lease.owner if self._lease else None

    def get_lease_info(self) -> LeaseInfo | None:
        """获取完整租约信息（可能已过期）"""
        with self._lock:
            return self._lease

    def get_remaining_ttl(self) -> float:
        """
        获取剩余 TTL（秒）

        Returns:
            剩余秒数，无租约或已过期返回 0.0
        """
        with self._lock:
            if self._lease is None:
                return 0.0
            return self._lease.remaining_ttl()

    # ========== 修改操作 ==========

    def acquire(self, owner: str, ttl: int = 300) -> LeaseInfo:
        """
        获取租约

        Args:
            owner: 请求租约的 worker 标识
            ttl: 租约有效期（秒），默认 300

        Returns:
            LeaseInfo: 新租约信息

        Raises:
            LeaseAcquisitionFailed: 获取失败（被其他 worker 持有且未过期）
            LeaseAlreadyHeldError: 尝试重复获取（自己持有）
        """
        with self._lock:
            # 情况1：无租约 - 直接创建
            if self._lease is None:
                now = datetime.now(timezone.utc)
                lease_info = LeaseInfo(
                    owner=owner,
                    lease_id=str(uuid.uuid4()),
                    granted_at=now,
                    expires_at=now + timedelta(seconds=ttl)
                )
                self._lease = lease_info
                self._stale_reason = None
                return lease_info

            # 情况2：有租约但已过期 - 替换为新的
            if self._lease.is_expired():
                now = datetime.now(timezone.utc)
                lease_info = LeaseInfo(
                    owner=owner,
                    lease_id=str(uuid.uuid4()),
                    granted_at=now,
                    expires_at=now + timedelta(seconds=ttl)
                )
                self._lease = lease_info
                self._stale_reason = None
                return lease_info

            # 情况3：租约有效且被他人持有 - 拒绝
            if self._lease.owner != owner:
                raise LeaseAcquisitionFailed(
                    f"lease already held by '{self._lease.owner}' "
                    f"(expires at {self._lease.expires_at.isoformat()})"
                )

            # 情况4：自己已持有 - 不允许重复获取
            raise LeaseAlreadyHeldError(
                f"worker '{owner}' already holds the lease"
            )

    def renew(self, owner: str, ttl: int = 300) -> LeaseInfo:
        """
        续期租约

        Args:
            owner: 续期请求者（必须是当前持有者）
            ttl: 新的 TTL（秒），默认 300

        Returns:
            LeaseInfo: 续期后的租约信息

        Raises:
            LeaseNotHeldError: 当前无租约
            UnauthorizedRenewalError: 非持有者尝试续期
        """
        with self._lock:
            if self._lease is None:
                raise LeaseNotHeldError("no lease exists to renew")

            # 租约已过期，需要重新 acquire
            if self._lease.is_expired():
                raise LeaseNotHeldError(
                    "lease has expired, use acquire() to obtain a new one"
                )

            # 验证持有者身份
            if self._lease.owner != owner:
                raise UnauthorizedRenewalError(
                    f"only '{self._lease.owner}' can renew this lease "
                    f"(requested by '{owner}')"
                )

            # 续期：更新过期时间
            now = datetime.now(timezone.utc)
            new_expires_at = now + timedelta(seconds=ttl)
            self._lease = LeaseInfo(
                owner=self._lease.owner,
                lease_id=self._lease.lease_id,  # 保持同一 ID
                granted_at=self._lease.granted_at,  # 保持原始授予时间
                expires_at=new_expires_at
            )
            self._stale_reason = None
            return self._lease

    def release(self) -> None:
        """
        释放租约（仅持有者可调用）

        Raises:
            LeaseNotHeldError: 当前无租约
        """
        with self._lock:
            if self._lease is None:
                raise LeaseNotHeldError("no lease exists to release")
            self._lease = None
            self._stale_reason = None

    def force_release(self) -> None:
        """
        强制释放租约（清除所有状态）

        即使租约过期或未被持有，也会强制清空。
        用于管理员干预或异常恢复场景。
        """
        with self._lock:
            self._lease = None
            self._stale_reason = None

    def mark_stale(self, reason: str) -> None:
        """
        标记租约为过期（记录原因）

        适用于检测到持有者故障的场景：
        - worker 进程崩溃
        - worker 网络分区
        - worker 长期无响应

        标记后：
        - is_stale() 返回 True
        - is_held() 返回 False
        - 租约仍然保留用于审计

        Args:
            reason: 过期原因描述
        """
        with self._lock:
            self._stale_reason = reason
            # 即使 lease 物理上未过期，逻辑上也标记为不可用
            # 通过设置过期时间为过去实现
            if self._lease:
                # 创建一个已过期的租约记录，便于审计追踪
                self._lease = LeaseInfo(
                    owner=self._lease.owner,
                    lease_id=self._lease.lease_id,
                    granted_at=self._lease.granted_at,
                    expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
                )

    # ========== 快照持久化 ==========

    def export_snapshot(self) -> AuthoritySnapshot:
        """
        导出快照（用于 RuntimeSnapshot 持久化）

        Returns:
            AuthoritySnapshot: 当前状态快照
        """
        with self._lock:
            if self._lease:
                return AuthoritySnapshot(
                    owner=self._lease.owner,
                    lease_id=self._lease.lease_id,
                    leased_until=self._lease.expires_at.isoformat(),
                    is_stale=self._lease.is_expired(),
                    stale_reason=self._stale_reason
                )
            return AuthoritySnapshot()

    def import_snapshot(self, snapshot: AuthoritySnapshot) -> None:
        """
        从快照恢复状态

        Args:
            snapshot: 之前导出的快照
        """
        with self._lock:
            if snapshot.owner and snapshot.lease_id and snapshot.leased_until:
                self._lease = LeaseInfo(
                    owner=snapshot.owner,
                    lease_id=snapshot.lease_id,
                    granted_at=datetime.now(timezone.utc),  # 恢复时授予时间未知，设为当前
                    expires_at=datetime.fromisoformat(snapshot.leased_until)
                )
            else:
                self._lease = None
            self._stale_reason = snapshot.stale_reason

    # ========== 上下文管理器 ==========

    def __enter__(self) -> AuthorityLease:
        """上下文管理器入口 - 自动获取租约"""
        # 需要在上下文外指定 owner 和 ttl，这里提供占位实现
        raise RuntimeError(
            "use acquire() explicitly before entering context, "
            "or use LeaseContext(lease, owner, ttl) helper"
        )

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """上下文管理器退出 - 自动释放租约"""
        with self._lock:
            self._lease = None
            self._stale_reason = None


class LeaseContext:
    """
    AuthorityLease 的上下文管理器封装

    示例：
    ```python
    lease = AuthorityLease()
    with LeaseContext(lease, "worker-1", ttl=300):
        # 在此代码块内持有租约
        do_critical_work()
    # 退出时自动释放
    ```
    """

    def __init__(self, lease: AuthorityLease, owner: str, ttl: int = 300):
        self.lease = lease
        self.owner = owner
        self.ttl = ttl
        self._lease_info: LeaseInfo | None = None

    def __enter__(self) -> LeaseContext:
        self._lease_info = self.lease.acquire(self.owner, self.ttl)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            if exc_type:
                # 发生异常时标记过期原因
                self.lease.mark_stale(f"exception: {exc_type.__name__}: {exc_val}")
        finally:
            try:
                self.lease.release()
            except LeaseNotHeldError:
                pass  # 已经被 force_release，忽略


# 延迟导入，避免循环依赖
import uuid
from typing import Any
