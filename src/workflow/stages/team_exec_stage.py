"""
Team Execution Stage - 团队执行阶段

从 oh-my-codex-main 汲取的团队执行阶段。
通过 Codex CLI workers 并行执行任务。
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.agent.swarm.worktree_manager import WorktreeManager
from src.workflow.pipeline_stage import PipelineStage, StageContext, StageResult

logger = logging.getLogger(__name__)


# ===== 配置 =====
@dataclass
class TeamExecConfig:
    """团队执行配置"""
    team_name: str = "default"
    worker_count: int = 2
    worker_role: str = "executor"
    cwd: str = "."
    task_split_mode: str = "auto"  # 'auto' | 'manual'
    timeout_seconds: int = 600


@dataclass
class TeamExecDescriptor:
    """团队执行描述符"""
    team_name: str
    worker_count: int
    worker_role: str
    tasks: list[dict[str, Any]] = field(default_factory=list)
    instructions: str = ""


# ===== 团队执行阶段 =====
class TeamExecStage(PipelineStage):
    """团队执行阶段

    通过并行 workers 执行任务。
    """

    def __init__(self, config: TeamExecConfig):
        self._config = config

    @property
    def name(self) -> str:
        return "team-exec"

    async def run(self, ctx: StageContext) -> StageResult:
        """执行团队执行阶段"""
        logger.info(f"[TeamExec] Starting team execution with {self._config.worker_count} workers")

        # 从上下文获取任务
        task = ctx.task

        # 从工件获取预分配的任务（如果有）
        preallocated_tasks = ctx.get_artifact("team_tasks")
        if preallocated_tasks:
            tasks = preallocated_tasks
        else:
            # 自动拆分任务
            tasks = self._split_tasks(task)

        # 构建团队指令
        instructions = self._build_team_instructions(ctx)

        # 执行团队
        result = await self._execute_team(tasks, instructions)

        # 返回结果
        return StageResult.completed(
            artifacts={
                "team_result": result,
                "task_count": len(tasks),
                "worker_count": self._config.worker_count,
            },
            duration_ms=result.get("duration_ms", 0) if isinstance(result, dict) else 0,
        )

    def _split_tasks(self, task: str) -> list[dict[str, Any]]:
        """自动拆分任务为子任务"""
        # 简单的基于句子的拆分
        # 实际实现应该更复杂，考虑任务复杂性
        sentences = task.split(".")
        tasks = []

        for i, sentence in enumerate(sentences):
            if sentence.strip():
                tasks.append({
                    "task_id": f"task-{i+1}",
                    "description": sentence.strip(),
                    "status": "pending",
                })

        # 至少返回一个任务
        if not tasks:
            tasks.append({
                "task_id": "task-1",
                "description": task,
                "status": "pending",
            })

        return tasks

    def _build_team_instructions(self, ctx: StageContext) -> str:
        """构建团队指令"""
        task_desc = ctx.task or self._config.team_name
        base_instruction = f"""Execute the following task:

{task_desc}

Context:
- Working directory: {ctx.cwd}
- Session ID: {ctx.session_id or 'none'}
"""

        # 从工件获取额外上下文
        if ctx.artifacts:
            plan = ctx.get_artifact("plan")
            if plan:
                base_instruction += f"\nPlan:\n{plan}\n"

        return base_instruction

    async def _execute_team(
        self,
        tasks: list[dict[str, Any]],
        instructions: str,
    ) -> dict[str, Any]:
        """执行团队任务（基于 Git Worktree 隔离）

        参考 oh-my-codex-main 的 worktree 隔离机制：
        - 为每个 worker 创建独立的 git worktree
        - 支持并行执行且互不干扰
        - 自动收集各 worktree 的执行结果
        """
        import time
        from uuid import uuid4

        start_time = time.time()

        # 初始化 worktree manager
        worktree_mgr = WorktreeManager(base_dir=Path(self._config.cwd) / ".clawd" / "worktrees")

        # 任务分配：简单轮询
        task_assignments: dict[int, list[dict[str, Any]]] = {}
        for i, task in enumerate(tasks):
            worker_idx = i % self._config.worker_count
            task_assignments.setdefault(worker_idx, []).append(task)

        worker_worktrees: dict[str, str] = {}

        try:
            # 为每个 worker 创建独立的 worktree
            for worker_idx in range(self._config.worker_count):
                worker_id = f"worker-{uuid4().hex[:8]}"
                worktree_id = f"team-{self._config.team_name}-{worker_idx}"

                worktree_mgr.create_worktree(
                    worktree_id=worktree_id,
                    base_ref="HEAD",
                    isolated=True,
                    persistent=False,
                )

                worker_worktrees[worker_id] = worktree_id

            # 并行执行各个 worker 的任务
            async def execute_worker(worker_id: str, worktree_id: str) -> dict[str, Any]:
                state = worktree_mgr.get_worktree(worktree_id)
                if not state:
                    return {"errors": [f"Worktree not found: {worktree_id}"], "tasks_completed": 0}

                assigned_tasks = task_assignments.get(worker_idx, [])
                if not assigned_tasks:
                    return {"tasks_completed": 0}

                worker_results = []
                errors = []

                for task in assigned_tasks:
                    task_desc = task.get("description", "")
                    try:
                        # 在 worktree 中执行命令
                        cmd = ["python", "-c", f"{task_desc}"]
                        result = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            timeout=self._config.timeout_seconds,
                            cwd=state.path,
                        )
                        worker_results.append({
                            "task_id": task.get("task_id"),
                            "stdout": result.stdout.strip(),
                            "stderr": result.stderr.strip(),
                            "returncode": result.returncode,
                        })
                        if result.returncode != 0:
                            errors.append(f"Task {task.get('task_id')} failed with {result.returncode}")
                    except subprocess.TimeoutExpired:
                        errors.append(f"Task {task.get('task_id')} timed out")
                    except Exception as e:
                        errors.append(f"Task {task.get('task_id')} error: {e}")

                return {
                    "worker_id": worker_id,
                    "worktree_id": worktree_id,
                    "tasks": worker_results,
                    "errors": errors,
                }

            # 为每个 worktree 直接运行其分配的任务
            async def run_worker_task(worker_id: str, worktree_id: str, tasks_for_worker: list[dict[str, Any]]) -> dict[str, Any]:
                state = worktree_mgr.get_worktree(worktree_id)
                if not state:
                    return {"errors": [f"Worktree not found: {worktree_id}"], "tasks_completed": 0}

                if not tasks_for_worker:
                    return {"worker_id": worker_id, "worktree_id": worktree_id, "tasks": [], "errors": [], "tasks_completed": 0}

                worker_results = []
                errors = []

                for task in tasks_for_worker:
                    task_desc = task.get("description", "")
                    try:
                        cmd = ["python", "-c", task_desc]
                        result = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            timeout=self._config.timeout_seconds,
                            cwd=state.path,
                        )
                        worker_results.append({
                            "task_id": task.get("task_id"),
                            "stdout": result.stdout.strip(),
                            "stderr": result.stderr.strip(),
                            "returncode": result.returncode,
                        })
                        if result.returncode != 0:
                            errors.append(f"Task {task.get('task_id')} failed with {result.returncode}")
                    except subprocess.TimeoutExpired:
                        errors.append(f"Task {task.get('task_id')} timed out")
                    except Exception as e:
                        errors.append(f"Task {task.get('task_id')} error: {e}")

                return {
                    "worker_id": worker_id,
                    "worktree_id": worktree_id,
                    "tasks": worker_results,
                    "errors": errors,
                }

            # 构建每个 worker 的任务列表
            tasks_list = []
            for idx, (worker_id, worktree_id) in enumerate(worker_worktrees.items()):
                tasks_for_this_worker = task_assignments.get(idx, [])
                tasks_list.append(run_worker_task(worker_id, worktree_id, tasks_for_this_worker))

            worker_outputs = await asyncio.gather(*tasks_list, return_exceptions=True)

            # 聚合结果
            total_completed = 0
            total_errors = []
            worker_results = []

            for wo in worker_outputs:
                if isinstance(wo, Exception):
                    total_errors.append(str(wo))
                else:
                    worker_results.append(wo)
                    total_completed += len(wo.get("tasks", []))
                    total_errors.extend(wo.get("errors", []))

            status = "completed" if not total_errors else "completed_with_errors"
            duration_ms = int((time.time() - start_time) * 1000)

            # 清理 worktrees
            for worktree_id in worker_worktrees.values():
                worktree_mgr.remove_worktree(worktree_id, force=True)

            return {
                "status": status,
                "tasks_completed": total_completed,
                "tasks_failed": len(total_errors),
                "worker_results": worker_results,
                "errors": total_errors,
                "duration_ms": duration_ms,
                "worker_count": self._config.worker_count,
            }

        except Exception as e:
            logger.exception(f"[TeamExec] Team execution failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "tasks_completed": 0,
                "duration_ms": int((time.time() - start_time) * 1000),
            }


# ===== 构建函数 =====
def create_team_exec_stage(config: TeamExecConfig = None, **options) -> PipelineStage:
    """创建团队执行阶段"""
    if config is None:
        config = TeamExecConfig(**options)
    return TeamExecStage(config)


def build_team_instruction(
    task: str,
    plan: str = "",
    context: dict[str, Any] | None = None,
) -> str:
    """构建团队指令字符串"""
    instruction = f"Task: {task}\n"

    if plan:
        instruction += f"\nPlan:\n{plan}\n"

    if context:
        instruction += "\nContext:\n"
        for key, value in context.items():
            instruction += f"- {key}: {value}\n"

    return instruction


# ===== 导出 =====
__all__ = [
    "TeamExecConfig",
    "TeamExecDescriptor",
    "TeamExecStage",
    "build_team_instruction",
    "create_team_exec_stage",
]
