"""Architect Agent — 全局规划与状态锁定"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ...llm import LLMConfig
from ..engine import AgentEngine
from ..factory import create_agent_engine
from .base_agent import BaseAgent
from .message_bus import AgentMessage, MessageBus, MessageType
from .roles import AgentRole

logger = logging.getLogger(__name__)


class LockType(str, Enum):
    """锁类型"""
    EXCLUSIVE = "exclusive"      # 排他锁 (独占)
    SHARED = "shared"            # 共享锁 (可并发读)
    ADVISORY = "advisory"        # 建议锁 (软锁)


@dataclass
class StateLock:
    """状态锁"""
    lock_id: str
    resource: str               # 锁定的资源 (文件名、模块名)
    lock_type: LockType
    owner_id: str               # 锁持有者
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0     # 过期时间 (0 表示不过期)
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """检查锁是否过期"""
        if self.expires_at == 0:
            return False
        return time.time() > self.expires_at


@dataclass
class ArchitecturePlan:
    """架构规划"""
    plan_id: str
    goal: str
    modules: list[dict[str, Any]] = field(default_factory=list)
    dependencies: list[tuple[str, str]] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    risk_assessment: str = ""
    implementation_order: list[str] = field(default_factory=list)


class StateLockManager:
    """状态锁管理器 — 管理并发访问

    防止多个 Agent 同时修改同一资源
    """

    def __init__(self) -> None:
        self._locks: dict[str, StateLock] = {}
        self._lock_timeout: float = 300.0  # 5 分钟默认超时

    def acquire(
        self,
        resource: str,
        owner_id: str,
        lock_type: LockType = LockType.EXCLUSIVE,
        timeout: float | None = None,
    ) -> StateLock | None:
        """获取锁

        参数:
            resource: 资源名称
            owner_id: 锁持有者
            lock_type: 锁类型
            timeout: 超时时间

        返回:
            StateLock 或 None (获取失败)
        """
        # 清理过期锁
        self._cleanup_expired()

        # 检查是否已有锁
        existing_lock = self._locks.get(resource)

        if existing_lock and not existing_lock.is_expired():
            # 共享锁可以多个同时持有
            if lock_type == LockType.SHARED and existing_lock.lock_type == LockType.SHARED:
                return existing_lock

            # 同一个 Agent 可以重入
            if existing_lock.owner_id == owner_id:
                return existing_lock

            # 其他情况获取失败
            logger.warning(f"资源 {resource} 已被 {existing_lock.owner_id} 锁定")
            return None

        # 创建新锁
        lock = StateLock(
            lock_id=f"lock-{resource}-{int(time.time())}",
            resource=resource,
            lock_type=lock_type,
            owner_id=owner_id,
            expires_at=time.time() + (timeout or self._lock_timeout),
        )
        self._locks[resource] = lock
        return lock

    def release(self, resource: str, owner_id: str) -> bool:
        """释放锁"""
        lock = self._locks.get(resource)
        if lock and lock.owner_id == owner_id:
            del self._locks[resource]
            return True
        return False

    def is_locked(self, resource: str) -> bool:
        """检查资源是否被锁定"""
        lock = self._locks.get(resource)
        if lock and lock.is_expired():
            del self._locks[resource]
            return False
        return lock is not None

    def get_lock(self, resource: str) -> StateLock | None:
        """获取锁信息"""
        lock = self._locks.get(resource)
        if lock and lock.is_expired():
            del self._locks[resource]
            return None
        return lock

    def _cleanup_expired(self) -> None:
        """清理过期锁"""
        expired = [r for r, lock in self._locks.items() if lock.is_expired()]
        for resource in expired:
            logger.warning(f"锁 {resource} 已过期，自动释放")
            del self._locks[resource]

    def get_stats(self) -> dict[str, Any]:
        """获取锁统计"""
        return {
            "active_locks": len([lock for lock in self._locks.values() if not lock.is_expired()]),
            "resources": list(self._locks.keys()),
        }


class ArchitectAgent(BaseAgent):
    """Architect Agent — 全局规划与状态锁定

    职责:
    1. 全局架构规划
    2. 模块依赖分析
    3. 资源状态锁定
    4. 并发冲突解决
    """

    def __init__(
        self,
        agent_id: str = "architect-1",
        message_bus: MessageBus | None = None,
        llm_config: LLMConfig | None = None,
        workdir: Path | None = None,
    ) -> None:
        # 使用 Orchestrator 角色
        super().__init__(agent_id=agent_id, role=AgentRole.ORCHESTRATOR, message_bus=message_bus)
        self.llm_config = llm_config
        self.workdir = workdir
        self._lock_manager = StateLockManager()
        self._engine: AgentEngine | None = None

    def _get_engine(self) -> AgentEngine:
        """获取 AgentEngine"""
        if self._engine is None:
            self._engine = create_agent_engine(
                workdir=self.workdir,
            )
        return self._engine

    async def plan_architecture(self, goal: str) -> ArchitecturePlan:
        """规划架构

        参数:
            goal: 任务目标

        返回:
            ArchitecturePlan 对象
        """
        engine = self._get_engine()

        prompt = f"""作为架构师，请分析以下任务并制定架构规划:

目标: {goal}

请输出以下内容:
1. 模块划分 (模块名、职责、接口)
2. 模块间依赖关系
3. 实现约束和风险
4. 实现顺序

请用 JSON 格式输出。"""

        await engine.run(prompt)

        # 解析结果 (简化处理)
        plan = ArchitecturePlan(
            plan_id=f"plan-{int(time.time())}",
            goal=goal,
        )

        return plan

    def lock_resource(
        self,
        resource: str,
        owner_id: str,
        lock_type: LockType = LockType.EXCLUSIVE,
        timeout: float | None = None,
    ) -> StateLock | None:
        """锁定资源

        参数:
            resource: 资源名称
            owner_id: 锁持有者
            lock_type: 锁类型
            timeout: 超时时间

        返回:
            StateLock 或 None
        """
        return self._lock_manager.acquire(resource, owner_id, lock_type, timeout)

    def unlock_resource(self, resource: str, owner_id: str) -> bool:
        """解锁资源"""
        return self._lock_manager.release(resource, owner_id)

    def is_resource_locked(self, resource: str) -> bool:
        """检查资源是否被锁定"""
        return self._lock_manager.is_locked(resource)

    async def process(self, message: AgentMessage) -> str:
        """处理消息"""
        if message.message_type == MessageType.TASK_ASSIGN:
            # 任务分配: 进行架构规划
            goal = message.content
            plan = await self.plan_architecture(goal)
            return f"架构规划完成: {plan.plan_id}"

        elif message.message_type == MessageType.STATUS_UPDATE:
            # 状态更新消息，处理锁请求
            content = message.content
            if content.startswith("lock:"):
                # 简单的锁请求解析
                parts = content.split(":", 2)
                resource = parts[1].strip() if len(parts) > 1 else "unknown"
                lock = self.lock_resource(resource, message.sender)
                if lock:
                    return f"锁获取成功: {lock.lock_id}"
                else:
                    return f"锁获取失败: 资源 {resource} 已被锁定"
            elif content.startswith("unlock:"):
                parts = content.split(":", 2)
                resource = parts[1].strip() if len(parts) > 1 else "unknown"
                success = self.unlock_resource(resource, message.sender)
                return f"锁释放{'成功' if success else '失败'}"

        return f"未知消息类型: {message.message_type}"

    def get_lock_stats(self) -> dict[str, Any]:
        """获取锁统计"""
        return self._lock_manager.get_stats()
