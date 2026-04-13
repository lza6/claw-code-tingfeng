"""任务注册与追踪"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"              # 待分配
    ASSIGNED = "assigned"            # 已分配
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


@dataclass
class SubTask:
    """子任务"""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    title: str = ""
    description: str = ""
    assigned_to: str = ""            # Agent ID
    status: TaskStatus = TaskStatus.PENDING
    parent_id: str = ""              # 父任务 ID
    result: str = ""
    audit_report: str = ""
    review_report: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
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


class TaskRegistry:
    """任务注册与追踪

    职责:
    - 注册新任务
    - 追踪任务状态
    - 查询任务进度
    """

    def __init__(self) -> None:
        self._tasks: dict[str, SubTask] = {}

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

    def get_task(self, task_id: str) -> SubTask | None:
        """获取任务"""
        return self._tasks.get(task_id)

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
