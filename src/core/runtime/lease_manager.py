"""Lease Manager - 运行时租约管理器 (从 GoalX lease_loop.go 汲取)

用于监控 Agent 进程的存活状态，防止僵尸进程或意外崩溃导致的资源锁定。
- Heartbeat: 定期更新租约时间戳
- Lease: 租约包含 holder, run_id, epoch, ttl, pid 等信息
- Detection: 检测租约是否过期
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Lease:
    """租约定义"""
    holder: str
    run_id: str
    epoch: int
    ttl_seconds: int
    pid: int
    transport: str = "local"
    updated_at: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        """检查租约是否已过期"""
        return time.time() > (self.updated_at + self.ttl_seconds)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "holder": self.holder,
            "run_id": self.run_id,
            "epoch": self.epoch,
            "ttl_seconds": self.ttl_seconds,
            "pid": self.pid,
            "transport": self.transport,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Lease:
        """从字典创建 Lease"""
        return cls(
            holder=data.get("holder", ""),
            run_id=data.get("run_id", ""),
            epoch=data.get("epoch", 0),
            ttl_seconds=data.get("ttl_seconds", 30),
            pid=data.get("pid", 0),
            transport=data.get("transport", "local"),
            updated_at=data.get("updated_at", time.time()),
        )


class LeaseManager:
    """租约管理器"""

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.lease_dir = run_dir / "control" / "leases"
        self.lease_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger("core.runtime.lease")

    def acquire(self, holder: str, run_id: str, epoch: int, ttl: int = 30, transport: str = "local") -> Lease:
        """获取或更新租约"""
        lease = Lease(
            holder=holder,
            run_id=run_id,
            epoch=epoch,
            ttl_seconds=ttl,
            pid=os.getpid(),
            transport=transport,
            updated_at=time.time()
        )
        self.save_lease(lease)
        return lease

    def save_lease(self, lease: Lease) -> None:
        """持久化租约"""
        path = self.lease_dir / f"{lease.holder}.json"
        tmp_path = path.with_suffix(".tmp")

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(lease.to_dict(), f, indent=2)
            tmp_path.replace(path)
        except Exception as e:
            self.logger.error(f"保存租约失败 {lease.holder}: {e}")

    def load_lease(self, holder: str) -> Lease | None:
        """加载租约"""
        path = self.lease_dir / f"{holder}.json"
        if not path.exists():
            return None

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                return Lease.from_dict(data)
        except Exception as e:
            self.logger.error(f"加载租约失败 {holder}: {e}")
            return None

    def renew(self, holder: str) -> bool:
        """续约"""
        lease = self.load_lease(holder)
        if not lease:
            return False

        # 校验 PID 是否一致 (如果是同一进程续约)
        if lease.pid == os.getpid():
            lease.updated_at = time.time()
            self.save_lease(lease)
            return True

        return False

    def check_liveness(self, holder: str) -> tuple[bool, str]:
        """[汲取 GoalX liveness.go] 检查租约持有者是否存活"""
        lease = self.load_lease(holder)
        if not lease:
            return False, "lease_missing"

        if lease.is_expired():
            # 租约时间过期，但仍需检查进程是否真的消失
            if not self._is_process_alive(lease.pid):
                return False, "process_dead"
            return False, "lease_expired"

        # 租约有效，且进程存活
        if not self._is_process_alive(lease.pid):
            return False, "process_ghost"  # 租约没过期但进程没了 (异常崩溃)

        return True, "healthy"

    def _is_process_alive(self, pid: int) -> bool:
        """检查进程是否存活"""
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def list_leases(self) -> list[Lease]:
        """列出所有活跃租约"""
        leases = []
        for p in self.lease_dir.glob("*.json"):
            lease = self.load_lease(p.stem)
            if lease:
                leases.append(lease)
        return leases

    def expire(self, holder: str) -> None:
        """手动使其过期 (强制释放)"""
        path = self.lease_dir / f"{holder}.json"
        if path.exists():
            path.unlink()
            self.logger.info(f"已手动释放租约: {holder}")
