"""
Team Execution Stage - 团队执行阶段

从 oh-my-codex-main 汲取的团队执行阶段。
通过 Codex CLI workers 并行执行任务。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from .pipeline_stage import StageContext, StageResult, PipelineStage

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
        base_instruction = f"""Execute the following task:

{task}

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
        """执行团队任务

        实际实现应该调用 omx team 或通过 MCP 与团队系统交互。
        这里是一个模拟实现。
        """
        # TODO: 实现真正的团队执行
        # - 调用 omx team API
        # - 管理 workers 生命周期
        # - 收集结果

        logger.info(f"[TeamExec] Would execute {len(tasks)} tasks with {self._config.worker_count} workers")

        return {
            "status": "completed",
            "tasks_completed": len(tasks),
            "tasks_failed": 0,
            "duration_ms": 0,
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
    context: dict[str, Any] = None,
) -> str:
    """构建团队指令字符串"""
    instruction = f"Task: {task}\n"

    if plan:
        instruction += f"\nPlan:\n{plan}\n"

    if context:
        instruction += f"\nContext:\n"
        for key, value in context.items():
            instruction += f"- {key}: {value}\n"

    return instruction


# ===== 导出 =====
__all__ = [
    "TeamExecConfig",
    "TeamExecDescriptor",
    "TeamExecStage",
    "create_team_exec_stage",
    "build_team_instruction",
]