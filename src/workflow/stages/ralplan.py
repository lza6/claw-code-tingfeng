"""
Ralplan Stage - 规划阶段

从 oh-my-codex-main 汲取的 RALPLAN 阶段。
实现 Planner -> Architect -> Critic 循环直到达成共识。

RALPLAN-DR 模式:
- Short (默认): 有界结构
- Deliberate: 用于高风险请求，扩展测试计划
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from ..pipeline_stage import StageContext, StageResult, PipelineStage
from ..artifacts import (
    read_planning_artifacts,
    is_planning_complete,
    read_approved_execution_launch_hint,
    get_test_specs_for_prd,
)

logger = logging.getLogger(__name__)


# ===== 配置 =====
@dataclass
class RalplanConfig:
    """RALPLAN 配置"""
    mode: str = "short"  # 'short' | 'deliberate'
    max_iterations: int = 5
    interactive: bool = False
    cwd: str = "."


@dataclass
class RalplanDRSummary:
    """RALPLAN-DR 摘要"""
    principles: list[str] = field(default_factory=list)
    decision_drivers: list[str] = field(default_factory=list)
    viable_options: list[dict[str, Any]] = field(default_factory=list)
    invalidation_rationale: str = ""
    pre_mortem: list[str] = field(default_factory=list)  # 仅 deliberate 模式
    test_plan: dict[str, Any] = field(default_factory=dict)  # 仅 deliberate 模式


# ===== RALPLAN 阶段 =====
class RalplanStage(PipelineStage):
    """RALPLAN 规划阶段

    实现 Planner -> Architect -> Critic 循环直到达成共识。
    """

    def __init__(self, config: RalplanConfig):
        self._config = config

    @property
    def name(self) -> str:
        return "ralplan"

    def can_skip(self, ctx: StageContext) -> bool:
        """检查是否可以跳过 RALPLAN 阶段（如果已有已批准的计划）"""
        # 从 artifacts 检查是否已有已批准的计划
        existing_hint = read_approved_execution_launch_hint(ctx.cwd, mode="team")
        return existing_hint is not None

    async def run(self, ctx: StageContext) -> StageResult:
        """执行 RALPLAN 阶段"""
        logger.info(f"[Ralplan] Starting RALPLAN in {self._config.mode} mode")

        task = ctx.task
        cwd = self._config.cwd

        # 步骤 0: 检查是否已有已批准的计划 (从 artifacts 读取)
        existing_hint = read_approved_execution_launch_hint(cwd, mode="team")
        if existing_hint:
            logger.info(f"[Ralplan] Found existing approved plan: {existing_hint.source_path}")
            return StageResult.completed(
                artifacts={
                    "plan": {
                        "task": task,
                        "source": "existing_approved_plan",
                        "command": existing_hint.command,
                        "test_specs": existing_hint.test_spec_paths,
                    },
                    "mode": "resume",
                    "source_path": existing_hint.source_path,
                },
            )

        # 步骤 1: Planner 创建初始计划
        plan_summary = await self._planner_create_plan(task)

        # 步骤 2: Architect 审查
        architect_review = await self._architect_review(plan_summary)

        # 步骤 3: Critic 评估
        critic_verdict = await self._critic_evaluate(plan_summary, architect_review)

        # 步骤 4: 循环直到达成共识或达到最大迭代
        iteration = 1
        while iteration < self._config.max_iterations and not critic_verdict["approved"]:
            # 收集反馈并重新规划
            feedback = {
                "architect": architect_review,
                "critic": critic_verdict,
            }
            plan_summary = await self._planner_revise_plan(task, feedback)
            architect_review = await self._architect_review(plan_summary)
            critic_verdict = await self._critic_evaluate(plan_summary, architect_review)
            iteration += 1

        # 步骤 5: 应用改进
        if critic_verdict.get("improvements"):
            plan_summary = self._apply_improvements(plan_summary, critic_verdict["improvements"])

        # 构建最终计划
        final_plan = self._build_final_plan(plan_summary, architect_review, critic_verdict)

        return StageResult.completed(
            artifacts={
                "plan": final_plan,
                "ralplan_summary": plan_summary,
                "iterations": iteration,
                "approved": critic_verdict.get("approved", False),
            },
        )

    async def _planner_create_plan(self, task: str) -> RalplanDRSummary:
        """Planner 创建初始计划"""
        # TODO: 实现真正的 Planner 逻辑
        # - 分析任务
        # - 生成原则
        # - 识别决策驱动因素
        # - 提出可行选项

        logger.info("[Ralplan] Planner creating initial plan")

        return RalplanDRSummary(
            principles=[
                "保持代码简洁性",
                "遵循现有架构模式",
                "确保测试覆盖",
            ],
            decision_drivers=[
                "代码质量",
                "开发效率",
                "可维护性",
            ],
            viable_options=[
                {"name": "方案A", "pros": ["简单"], "cons": ["功能有限"]},
                {"name": "方案B", "pros": ["灵活"], "cons": ["复杂"]},
            ],
        )

    async def _architect_review(self, summary: RalplanDRSummary) -> dict[str, Any]:
        """Architect 审查"""
        # TODO: 实现真正的 Architect 审查
        # - 架构合理性
        # - 权衡分析
        # - 反论点

        logger.info("[Ralplan] Architect reviewing plan")

        return {
            "approved": True,
            "counter_arguments": [],
            "tradeoffs": [],
            "synthesis": "方案 A 更适合当前场景",
        }

    async def _critic_evaluate(
        self,
        summary: RalplanDRSummary,
        architect_review: dict[str, Any],
    ) -> dict[str, Any]:
        """Critic 评估"""
        # TODO: 实现真正的 Critic 评估
        # - 原则-选项一致性
        # - 替代方案探索
        # - 风险缓解
        # - 验收标准

        logger.info("[Ralplan] Critic evaluating plan")

        return {
            "approved": True,
            "improvements": [],
            "issues": [],
        }

    async def _planner_revise_plan(
        self,
        task: str,
        feedback: dict[str, Any],
    ) -> RalplanDRSummary:
        """Planner 修订计划"""
        logger.info("[Ralplan] Planner revising plan based on feedback")
        # TODO: 实现修订逻辑
        return await self._planner_create_plan(task)

    def _apply_improvements(
        self,
        summary: RalplanDRSummary,
        improvements: list[dict[str, Any]],
    ) -> RalplanDRSummary:
        """应用改进到计划"""
        # TODO: 实现改进应用逻辑
        return summary

    def _build_final_plan(
        self,
        summary: RalplanDRSummary,
        architect_review: dict[str, Any],
        critic_verdict: dict[str, Any],
    ) -> dict[str, Any]:
        """构建最终计划"""
        return {
            "task": "task description",
            "principles": summary.principles,
            "decision_drivers": summary.decision_drivers,
            "selected_option": summary.viable_options[0] if summary.viable_options else None,
            "implementation_steps": [],
            "verification_steps": [],
            "risks": [],
            "architect_review": architect_review,
            "critic_verdict": critic_verdict,
        }


# ===== 构建函数 =====
def create_ralplan_stage(config: RalplanConfig = None, **options) -> PipelineStage:
    """创建 RALPLAN 阶段"""
    if config is None:
        config = RalplanConfig(**options)
    return RalplanStage(config)


# ===== 导出 =====
__all__ = [
    "RalplanConfig",
    "RalplanDRSummary",
    "RalplanStage",
    "create_ralplan_stage",
]