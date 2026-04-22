"""工作流集成层 - 统一Pipeline、Ralplan、Team入口

整合所有工作流模块为统一CLI入口。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.utils.logger import get_logger
from src.workflow.engine import WorkflowEngine
from src.workflow.pipeline_orchestrator import PipelineConfig, PipelineOrchestrator
from src.workflow.ralplan import RalplanEngine

logger = get_logger(__name__)


async def run_pipeline(
    goal: str,
    workdir: Path | None = None,
    intent: str = "implement",
    use_team: bool = True,
    use_ralph: bool = True,
    budget: str | None = None,
) -> dict[str, Any]:
    """统一流水线执行入口"""
    workdir = workdir or Path.cwd()
    config = PipelineConfig(
        use_team=use_team,
        use_ralph=use_ralph,
        budget=budget,
    )
    orchestrator = PipelineOrchestrator(workdir, config)
    result = await orchestrator.execute(goal)
    return {
        "goal": result.goal,
        "status": result.final_status,
        "confidence": result.consensus_plan.confidence if result.consensus_plan else 0.0,
        "team_status": result.team_result.get("status") if result.team_result else None,
        "ralph_iterations": result.ralph_result.get("iterations") if result.ralph_result else None,
        "artifacts": {k: str(v) for k, v in result.artifacts.items()},
    }


async def run_ralplan_only(
    goal: str,
    workdir: Path | None = None,
) -> dict[str, Any]:
    """仅运行共识规划 (不执行)"""
    workdir = workdir or Path.cwd()
    engine = RalplanEngine(workdir)
    plan = await engine.run(goal)
    return {
        "goal": plan.goal,
        "objective": plan.objective,
        "confidence": plan.confidence,
        "tasks_count": len(plan.tasks),
        "risks_count": len(plan.risks),
        "validator": plan.validator,
    }


async def run_workflow_only(
    goal: str,
    workdir: Path | None = None,
    intent: str = "implement",
    iterations: int = 3,
) -> dict[str, Any]:
    """仅运行标准Workflow (不使用Pipeline)"""
    workdir = workdir or Path.cwd()
    engine = WorkflowEngine(workdir, max_iterations=iterations)
    import os
    os.environ["CLAWD_WORKFLOW_INTENT"] = intent
    result = await engine.run(goal)
    return {
        "goal": result.goal,
        "status": result.status,
        "iterations": result.iterations,
        "final_result": result.final_result[:200] if result.final_result else None,
    }


__all__ = [
    "run_pipeline",
    "run_ralplan_only",
    "run_workflow_only",
]
