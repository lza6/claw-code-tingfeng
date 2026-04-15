"""
Allocation Policy - 资源分配策略

从 oh-my-codex-main/src/team/allocation-policy.ts 转换。
提供 Worker 资源分配策略管理。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


logger = logging.getLogger(__name__)


class AllocationStrategy(Enum):
    """分配策略"""
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    RANDOM = "random"
    PRIORITY = "priority"
    WEIGHTED = "weighted"


class ResourceType(Enum):
    """资源类型"""
    CPU = "cpu"
    MEMORY = "memory"
    TOKEN = "token"
    CONCURRENT = "concurrent"


@dataclass
class WorkerCapacity:
    """Worker 容量"""
    worker_id: str
    max_concurrent: int = 5
    current_load: int = 0
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    token_budget: int = 100000
    available: bool = True


@dataclass
class AllocationPolicy:
    """分配策略配置"""
    strategy: str = AllocationStrategy.ROUND_ROBIN.value
    max_retries: int = 3
    timeout_ms: int = 5000
    weight_map: dict[str, int] = field(default_factory=dict)


class AllocationPolicyManager:
    """分配策略管理器

    功能:
    - Worker 注册
    - 策略选择
    - 负载均衡
    - 容量管理
    """

    def __init__(self, policy: Optional[AllocationPolicy] = None):
        self.policy = policy or AllocationPolicy()
        self._workers: dict[str, WorkerCapacity] = {}

    def register_worker(self, worker_id: str, capacity: WorkerCapacity) -> None:
        """注册 Worker"""
        self._workers[worker_id] = capacity
        logger.debug(f"[Allocation] Registered worker: {worker_id}")

    def unregister_worker(self, worker_id: str) -> bool:
        """注销 Worker"""
        if worker_id in self._workers:
            del self._workers[worker_id]
            logger.debug(f"[Allocation] Unregistered worker: {worker_id}")
            return True
        return False

    def get_worker(self, worker_id: str) -> Optional[WorkerCapacity]:
        """获取 Worker"""
        return self._workers.get(worker_id)

    def select_worker(self) -> Optional[str]:
        """选择 Worker"""
        available = [w for w in self._workers.values() if w.available]
        if not available:
            return None

        strategy = self.policy.strategy

        if strategy == AllocationStrategy.ROUND_ROBIN.value:
            return self._select_round_robin(available)
        elif strategy == AllocationStrategy.LEAST_LOADED.value:
            return self._select_least_loaded(available)
        elif strategy == AllocationStrategy.RANDOM.value:
            return self._select_random(available)
        elif strategy == AllocationStrategy.WEIGHTED.value:
            return self._select_weighted(available)

        return available[0].worker_id

    def _select_round_robin(self, workers: list[WorkerCapacity]) -> str:
        """轮询选择"""
        return workers[0].worker_id

    def _select_least_loaded(self, workers: list[WorkerCapacity]) -> str:
        """最低负载选择"""
        return min(workers, key=lambda w: w.current_load).worker_id

    def _select_random(self, workers: list[WorkerCapacity]) -> str:
        """随机选择"""
        import random
        return random.choice(workers).worker_id

    def _select_weighted(self, workers: list[WorkerCapacity]) -> str:
        """加权选择"""
        weights = []
        for w in workers:
            weight = self.policy.weight_map.get(w.worker_id, 1)
            weights.extend([w.worker_id] * weight)

        import random
        return random.choice(weights)

    def update_load(self, worker_id: str, load: int) -> None:
        """更新负载"""
        if worker_id in self._workers:
            self._workers[worker_id].current_load = load

    def get_available_workers(self) -> list[str]:
        """获取可用 Workers"""
        return [
            w.worker_id for w in self._workers.values()
            if w.available and w.current_load < w.max_concurrent
        ]

    def set_worker_available(self, worker_id: str, available: bool) -> None:
        """设置 Worker 可用性"""
        if worker_id in self._workers:
            self._workers[worker_id].available = available


# 全局单例
_allocation_manager: Optional[AllocationPolicyManager] = None


def get_allocation_manager() -> AllocationPolicyManager:
    """获取全局分配管理器"""
    global _allocation_manager
    if _allocation_manager is None:
        _allocation_manager = AllocationPolicyManager()
    return _allocation_manager


# ===== 导出 =====
__all__ = [
    "AllocationStrategy",
    "ResourceType",
    "WorkerCapacity",
    "AllocationPolicy",
    "AllocationPolicyManager",
    "get_allocation_manager",
]
