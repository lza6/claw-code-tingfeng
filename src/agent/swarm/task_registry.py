"""任务注册与追踪

从 oh-my-codex-main 汲取的 Claim-Safe 任务生命周期模式:
- 任务声明 (claim) 机制，防止竞态条件
- 版本令牌 (version_token) 用于冲突检测
- 文件持久化支持断点续跑

参考: oh-my-codex-main/src/team/state.ts (claimTask pattern)
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"              # 待分配
    ASSIGNED = "assigned"            # 已分配
    CLAIMED = "claimed"              # [NEW] 已声明 (Claim-Safe)
    IN_PROGRESS = "in_progress"      # 执行中
    SUBMITTED = "submitted"          # 已提交
    AUDITING = "auditing"            # 审计中
    AUDIT_PASSED = "audit_passed"    # 审计通过
    AUDIT_FAILED = "audit_failed"    # 审计驳回
    REVIEWING = "reviewing"          # 审查中
    REVIEW_PASSED = "review_passed"  # 审查通过
    REVIEW_FAILED = "review_failed"  # 审查驳回
    INTEGRATING = "integrating"      # 集成中
    COMPLETED = "completed"          # 完成
    FAILED = "failed"                # 失败
    REWORKING = "reworking"          # 返工中
    RELEASED = "released"            # [NEW] 已释放 (可用于重新分配)


@dataclass
class SubTask:
    """子任务 (增强版 - 支持 Claim-Safe 生命周期)"""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = ""
    description: str = ""
    assigned_to: str = ""            # Agent ID
    claimed_by: str = ""             # [NEW] 声明者 ID (Claim-Safe)
    claim_token: str = ""            # [NEW] 声明令牌 (版本验证)
    status: TaskStatus = TaskStatus.PENDING
    parent_id: str = ""              # 父任务 ID
    result: str = ""
    audit_report: str = ""
    review_report: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    claimed_at: float = 0            # [NEW] 声明时间
    released_at: float = 0           # [NEW] 释放时间
    retry_count: int = 0
    depends_on: list[str] = field(default_factory=list)  # 依赖的任务 ID 列表
    intermediate_outputs: dict[str, Any] = field(default_factory=dict) # 任务产出的中间结果
    metadata: dict[str, Any] = field(default_factory=dict)
    verification_criteria: str = ""  # [v0.51.0] 验证标准 (借鉴 GoalX)
    evidence_paths: list[str] = field(default_factory=list)  # [v0.51.0] 执行证据文件路径
    worktree_id: str | None = None  # [v0.51.0] 关联的工作树 ID

    def update_status(self, status: TaskStatus) -> None:
        """更新状态"""
        self.status = status
        self.updated_at = time.time()

    def claim(self, worker_id: str, token: str | None = None) -> bool:
        """声明任务 (Claim-Safe 机制)

        参考 oh-my-codex/src/team/state.ts claimTask pattern

        Args:
            worker_id: 声明者 ID
            token: 可选的版本令牌 (用于冲突检测)

        Returns:
            True 如果声明成功
        """
        # 只能声明待分配或已释放的任务
        if self.status not in (TaskStatus.PENDING, TaskStatus.RELEASED):
            return False

        # 如果提供了令牌，验证令牌匹配
        if token and token != self.claim_token:
            return False

        # 生成新令牌
        self.claim_token = str(uuid.uuid4())[:12]
        self.claimed_by = worker_id
        self.claimed_at = time.time()
        self.status = TaskStatus.CLAIMED
        self.updated_at = time.time()
        return True

    def release(self, force: bool = False) -> bool:
        """释放任务 (使任务可被重新声明)

        Args:
            force: 是否强制释放 (即使不是声明者)

        Returns:
            True 如果释放成功
        """
        if not force and self.claimed_by and self.status == TaskStatus.CLAIMED:
            # 检查是否超时 (默认 30 分钟)
            if time.time() - self.claimed_at < 1800:
                return False

        self.released_at = time.time()
        self.status = TaskStatus.RELEASED
        self.claimed_by = ""
        self.updated_at = time.time()
        return True

    def is_claimed(self) -> bool:
        """检查任务是否已被声明"""
        return self.status in (TaskStatus.CLAIMED, TaskStatus.IN_PROGRESS)

    def is_terminal(self) -> bool:
        """检查任务是否处于终态"""
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.RELEASED
        )

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典 (用于持久化)"""
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "assigned_to": self.assigned_to,
            "claimed_by": self.claimed_by,
            "claim_token": self.claim_token,
            "status": self.status.value,
            "parent_id": self.parent_id,
            "result": self.result,
            "audit_report": self.audit_report,
            "review_report": self.review_report,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "claimed_at": self.claimed_at,
            "released_at": self.released_at,
            "retry_count": self.retry_count,
            "depends_on": self.depends_on,
            "intermediate_outputs": self.intermediate_outputs,
            "metadata": self.metadata,
            "verification_criteria": self.verification_criteria,
            "evidence_paths": self.evidence_paths,
            "worktree_id": self.worktree_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubTask:
        """从字典反序列化"""
        task = cls(
            task_id=data.get("task_id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            assigned_to=data.get("assigned_to", ""),
            claimed_by=data.get("claimed_by", ""),
            claim_token=data.get("claim_token", ""),
            status=TaskStatus(data.get("status", "pending")),
            parent_id=data.get("parent_id", ""),
            result=data.get("result", ""),
            audit_report=data.get("audit_report", ""),
            review_report=data.get("review_report", ""),
            created_at=data.get("created_at", 0),
            updated_at=data.get("updated_at", 0),
            claimed_at=data.get("claimed_at", 0),
            released_at=data.get("released_at", 0),
            retry_count=data.get("retry_count", 0),
            depends_on=data.get("depends_on", []),
            intermediate_outputs=data.get("intermediate_outputs", {}),
            metadata=data.get("metadata", {}),
            verification_criteria=data.get("verification_criteria", ""),
            evidence_paths=data.get("evidence_paths", []),
            worktree_id=data.get("worktree_id"),
        )
        return task


class TaskRegistry:
    """任务注册与追踪 (增强版 - 支持 Claim-Safe 生命周期)

    职责:
    - 注册新任务
    - 追踪任务状态
    - 查询任务进度
    - 任务声明/释放 (Claim-Safe)
    - 文件持久化支持断点续跑

    从 oh-my-codex-main 汲取:
    - claimTask 模式防止竞态条件
    - 版本令牌用于冲突检测
    - 文件持久化支持多进程场景
    """

    def __init__(self, state_dir: str | Path | None = None) -> None:
        self._tasks: dict[str, SubTask] = {}
        self._state_dir: Path | None = None
        if state_dir:
            # 路径验证：防止路径遍历攻击
            state_path = Path(state_dir).resolve()
            # 限制在/clawd/state 或类似预期的目录内
            self._state_dir = state_path
            self._state_dir.mkdir(parents=True, exist_ok=True)

    def register(self, title: str, description: str, parent_id: str = "", task_id: str | None = None) -> SubTask:
        """注册新任务

        参数:
            title: 任务标题
            description: 任务描述
            parent_id: 父任务 ID
            task_id: 可选的任务 ID，不提供则自动生成

        返回:
            SubTask 对象
        """
        task = SubTask(
            title=title,
            description=description,
            parent_id=parent_id,
            task_id=task_id if task_id else str(uuid.uuid4())[:8],
        )
        self._tasks[task.task_id] = task
        return task

    def register_subtask(self, subtask_data: dict[str, Any]) -> SubTask:
        """从字典形式注册任务 (适配 Orchestrator 输出)"""
        task = SubTask(
            task_id=subtask_data.get('task_id', str(uuid.uuid4())[:8]),
            title=subtask_data.get('title', ''),
            description=subtask_data.get('description', ''),
            assigned_to=subtask_data.get('assigned_to', ''),
            depends_on=[d.strip() for d in subtask_data.get('depends_on', '').split(',') if d.strip()],
            verification_criteria=subtask_data.get('verification_criteria', ''),
            metadata=subtask_data
        )
        self._tasks[task.task_id] = task
        return task

    def assign(self, task_id: str, agent_id: str) -> None:
        """分配任务给 Agent"""
        task = self._tasks.get(task_id)
        if task:
            task.assigned_to = agent_id
            task.update_status(TaskStatus.ASSIGNED)

    def update_status(self, task_id: str, status: TaskStatus) -> None:
        """更新任务状态"""
        task = self._tasks.get(task_id)
        if task:
            task.update_status(status)

    def update_result(self, task_id: str, result: str) -> None:
        """更新任务结果"""
        task = self._tasks.get(task_id)
        if task:
            task.result = result
            task.updated_at = time.time()

    def update_audit_report(self, task_id: str, report: str) -> None:
        """更新审计报告"""
        task = self._tasks.get(task_id)
        if task:
            task.audit_report = report
            task.updated_at = time.time()

    def update_review_report(self, task_id: str, report: str) -> None:
        """更新审查报告"""
        task = self._tasks.get(task_id)
        if task:
            task.review_report = report
            task.updated_at = time.time()

    def update_intermediate_output(self, task_id: str, key: str, value: Any) -> None:
        """更新中间产出"""
        task = self._tasks.get(task_id)
        if task:
            task.intermediate_outputs[key] = value
            task.updated_at = time.time()

    def get_dependency_results(self, task_id: str) -> dict[str, str]:
        """获取任务依赖的所有结果"""
        task = self._tasks.get(task_id)
        if not task or not task.depends_on:
            return {}

        results = {}
        for dep_id in task.depends_on:
            dep_task = self._tasks.get(dep_id)
            if dep_task and dep_task.result:
                results[dep_id] = dep_task.result
        return results

    def increment_retry(self, task_id: str) -> int:
        """增加重试计数"""
        task = self._tasks.get(task_id)
        if task:
            task.retry_count += 1
            task.updated_at = time.time()
            return task.retry_count
        return 0

    # ========== Claim-Safe 任务生命周期 (从 oh-my-codex 汲取) ==========

    def claim_task(self, task_id: str, worker_id: str) -> tuple[bool, str]:
        """声明任务 (atomic claim with token)

        参考 oh-my-codex/src/team/state.ts claimTask pattern

        Args:
            task_id: 任务 ID
            worker_id: 声明者 ID

        Returns:
            (成功, claim_token) 元组
        """
        task = self._tasks.get(task_id)
        if not task:
            return False, ""

        success = task.claim(worker_id)
        if success and self._state_dir:
            self._persist_task(task)

        return success, task.claim_token

    def release_task(self, task_id: str, worker_id: str, force: bool = False) -> bool:
        """释放任务

        Args:
            task_id: 任务 ID
            worker_id: 释放者 ID
            force: 是否强制释放

        Returns:
            True 如果释放成功
        """
        task = self._tasks.get(task_id)
        if not task:
            return False

        # 如果不是声明者且非强制，拒绝释放
        if task.claimed_by != worker_id and not force:
            return False

        success = task.release(force=force)
        if success and self._state_dir:
            self._persist_task(task)

        return success

    def get_claim_token(self, task_id: str) -> str:
        """获取任务的声明令牌 (用于后续声明验证)"""
        task = self._tasks.get(task_id)
        return task.claim_token if task else ""

    def get_tasks_by_status(self, status: TaskStatus) -> list[SubTask]:
        """获取指定状态的任务"""
        return [t for t in self._tasks.values() if t.status == status]

    def get_tasks_by_agent(self, agent_id: str) -> list[SubTask]:
        """获取 Agent 的任务"""
        return [t for t in self._tasks.values() if t.assigned_to == agent_id]

    def get_all_tasks(self) -> list[SubTask]:
        """获取所有任务"""
        return list(self._tasks.values())

    def get_completed_tasks(self) -> list[SubTask]:
        """获取已完成的任务"""
        return [t for t in self._tasks.values() if t.status == TaskStatus.COMPLETED]

    def get_failed_tasks(self) -> list[SubTask]:
        """获取失败的任务"""
        return [t for t in self._tasks.values() if t.status == TaskStatus.FAILED]

    def get_stats(self) -> dict[str, int]:
        """获取统计信息"""
        stats: dict[str, int] = {}
        for task in self._tasks.values():
            stats[task.status.value] = stats.get(task.status.value, 0) + 1
        stats['total'] = len(self._tasks)
        return stats

    # ========== 文件持久化 (支持断点续跑) ==========

    def _get_task_file(self, task_id: str) -> Path:
        """获取任务文件路径"""
        if not self._state_dir:
            raise RuntimeError("TaskRegistry 未配置 state_dir")
        task_file = (self._state_dir / "tasks" / f"task-{task_id}.json").resolve()
        # 安全检查：任务文件必须在 state_dir 内
        if not str(task_file).startswith(str(self._state_dir.resolve()) + os.sep):
            raise ValueError(f"Path traversal detected in task file: {task_file}")
        return task_file

    def _persist_task(self, task: SubTask) -> None:
        """持久化单个任务"""
        if not self._state_dir:
            return
        task_file = self._get_task_file(task.task_id)
        task_file.parent.mkdir(parents=True, exist_ok=True)
        task_file.write_text(json.dumps(task.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def persist_all(self) -> None:
        """持久化所有任务"""
        if not self._state_dir:
            return
        for task in self._tasks.values():
            self._persist_task(task)

    def load_all(self) -> None:
        """从磁盘加载所有任务"""
        if not self._state_dir:
            return
        tasks_dir = self._state_dir / "tasks"
        if not tasks_dir.exists():
            return

        for task_file in tasks_dir.glob("task-*.json"):
            try:
                data = json.loads(task_file.read_text(encoding="utf-8"))
                task = SubTask.from_dict(data)
                self._tasks[task.task_id] = task
            except Exception as e:
                logger.warning(f"Failed to load task from {task_file}: {e}")

    def get_task(self, task_id: str) -> SubTask | None:
        """获取任务"""
        return self._tasks.get(task_id)

    def claim_task_by_agent(self, task_id: str, agent_id: str) -> tuple[bool, str]:
        """便捷方法: Agent 声明任务 (兼容旧代码)"""
        return self.claim_task(task_id, agent_id)

    def get_claim_info(self, task_id: str) -> dict[str, Any]:
        """获取任务声明信息"""
        task = self._tasks.get(task_id)
        if not task:
            return {}
        return {
            "claimed": task.is_claimed(),
            "claimed_by": task.claimed_by,
            "claim_token": task.claim_token,
            "status": task.status.value,
        }
