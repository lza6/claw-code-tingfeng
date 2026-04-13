"""任务规划器 - 负责生成 TODO 列表，动态拆分任务

从 workflow/engine.py 拆分出来 (Phase 2: PLAN)
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import replace

from .code_scanner import CodeIssue
from .models import (
    Dimension,
    DimensionSource,
    WorkflowIntent,
    WorkflowPhase,
    WorkflowStatus,
    WorkflowTask,
)

logger = logging.getLogger('workflow.task_planner')


class TaskPlanner:
    """任务规划器 - 根据发现的问题生成 TODO 列表"""

    BUILTIN_DIMENSIONS = {
        "depth": "Depth: Pick the single most impactful area and go as deep as possible. Trace code paths end-to-end.",
        "breadth": "Breadth: Scan all dimensions to build a complete map. Cover every major component.",
        "adversarial": "Adversarial: Your job is to find problems. Look for bugs, design flaws, edge cases.",
        "audit": "Audit: Conduct a systematic review of correctness, regressions, safety, and documentation.",
        "evidence": "Evidence: Quantify everything. Run benchmarks, measure build times, check test coverage.",
        "perfectionist": "Perfectionist: Demand ironclad evidence for every claim. Cite exact code references.",
    }

    @staticmethod
    def plan_tasks(issues: list[CodeIssue], intent: WorkflowIntent = WorkflowIntent.DELIVER) -> list[WorkflowTask]:
        """根据发现的问题生成 TODO 列表，动态拆分"""
        tasks: list[WorkflowTask] = []

        # Priority scoring: severity -> weight
        severity_weight = {'critical': 10, 'high': 7, 'medium': 4, 'low': 1}

        # 汲取 GoalX: 根据意图注入全局维度
        global_dimensions = []
        if intent == WorkflowIntent.EXPLORE:
            global_dimensions.append(Dimension(name="depth", guidance=TaskPlanner.BUILTIN_DIMENSIONS["depth"]))
        elif intent == WorkflowIntent.EVOLVE:
            global_dimensions.append(Dimension(name="perfectionist", guidance=TaskPlanner.BUILTIN_DIMENSIONS["perfectionist"]))

        for i, issue in enumerate(issues, 1):
            weight = severity_weight.get(issue.severity, 1)

            # 为高风险任务分配特定的维度
            dimensions = list(global_dimensions)
            if issue.severity in ("critical", "high"):
                dimensions.append(Dimension(
                    name="perfectionist",
                    guidance=TaskPlanner.BUILTIN_DIMENSIONS["perfectionist"],
                    source=DimensionSource.BUILTIN
                ))
                dimensions.append(Dimension(
                    name="audit",
                    guidance=TaskPlanner.BUILTIN_DIMENSIONS["audit"],
                    source=DimensionSource.BUILTIN
                ))

            task = WorkflowTask(
                task_id=f'fix-{i:03d}',
                phase=WorkflowPhase.EXECUTE,
                title=f'{issue.category}.{issue.severity}: {issue.description}',
                description=(
                    f'文件: {issue.file}:{issue.line}\n'
                    f'问题: {issue.description}\n'
                    f'建议: {issue.suggestion}'
                ),
                status=WorkflowStatus.PENDING,
                result=f'{weight}',  # temporarily store weight for sorting
                dimensions=dimensions
            )
            tasks.append(task)

        # Sort by weight descending (critical first)
        tasks.sort(key=lambda t: int(t.result or '0'), reverse=True)

        # Re-assign result to empty (weight was temporary)
        tasks = [replace(t, result=None) for t in tasks]

        # Dynamic split: if too many similar issues, group them
        if len(tasks) > 20:
            tasks = TaskPlanner._consolidate_similar_tasks(tasks)
        elif 0 < len(tasks) < 3:
            tasks = TaskPlanner._split_tasks(tasks)

        # 依赖校验 (DAG 检测)
        return TaskPlanner.validate_and_sort_dependencies(tasks)

    @staticmethod
    def validate_and_sort_dependencies(tasks: list[WorkflowTask]) -> list[WorkflowTask]:
        """校验任务依赖关系并进行拓扑排序。

        如果检测到循环依赖，将抛出 ValueError。
        """
        if not tasks:
            return []

        task_map = {t.task_id: t for t in tasks}
        adj = {t.task_id: [] for t in tasks}
        in_degree = {t.task_id: 0 for t in tasks}

        for t in tasks:
            for dep_id in t.depends_on:
                if dep_id in task_map:
                    adj[dep_id].append(t.task_id)
                    in_degree[t.task_id] += 1
                else:
                    logger.warning(f"任务 {t.task_id} 依赖不存在的任务 {dep_id}，已忽略")

        # Kahn's algorithm
        queue = deque([t_id for t_id, deg in in_degree.items() if deg == 0])
        sorted_ids = []

        while queue:
            u = queue.popleft()
            sorted_ids.append(u)
            for v in adj[u]:
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    queue.append(v)

        if len(sorted_ids) != len(tasks):
            # 找到不在 sorted_ids 中的任务，它们构成了循环依赖
            cycle_tasks = [t_id for t_id in task_map if t_id not in sorted_ids]
            raise ValueError(f"检测到循环依赖或不可达任务: {cycle_tasks}")

        return [task_map[t_id] for t_id in sorted_ids]

    @staticmethod
    def _consolidate_similar_tasks(tasks: list[WorkflowTask]) -> list[WorkflowTask]:
        """合并同类型问题为分组任务（防止任务过多）"""
        grouped: dict[str, list[WorkflowTask]] = {}
        for task in tasks:
            category = task.title.split(':')[0].strip()
            grouped.setdefault(category, []).append(task)

        result: list[WorkflowTask] = []
        for category, group in grouped.items():
            if len(group) <= 3:
                result.extend(group)
            else:
                # Consolidate similar issues into one task
                result.append(WorkflowTask(
                    task_id=f'group-{tasks.index(group[0]):03d}',
                    phase=WorkflowPhase.EXECUTE,
                    title=f'{category} ({len(group)} 个同类问题)',
                    description='\n'.join(f'- {t.description}' for t in group),
                    status=WorkflowStatus.PENDING,
                    result=None,
                ))

        return result

    @staticmethod
    def _split_tasks(tasks: list[WorkflowTask]) -> list[WorkflowTask]:
        """将少量任务拆分成更细粒度的子任务"""
        split: list[WorkflowTask] = []
        for task in tasks:
            parts = task.task_id.split('-')
            idx = parts[-1] if parts else '001'
            split.extend([
                WorkflowTask(
                    task_id=f'fix-{idx}a', phase=WorkflowPhase.EXECUTE,
                    title=f'{task.title} — 分析',
                    description=f'分析根因: {task.description}',
                    status=WorkflowStatus.PENDING,
                ),
                WorkflowTask(
                    task_id=f'fix-{idx}b', phase=WorkflowPhase.EXECUTE,
                    title=f'{task.title} — 实现',
                    description=f'实施修复: {task.description}',
                    status=WorkflowStatus.PENDING,
                ),
                WorkflowTask(
                    task_id=f'fix-{idx}c', phase=WorkflowPhase.EXECUTE,
                    title=f'{task.title} — 验证',
                    description=f'验证修复效果: {task.description}',
                    status=WorkflowStatus.PENDING,
                ),
            ])
        return split
