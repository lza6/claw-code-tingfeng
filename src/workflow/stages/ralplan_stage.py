"""RALPLAN 共识规划阶段

集成 Planner、Architect、Critic 三方博弈，生成实施计划。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.agent.swarm.architect import ArchitectAgent
from src.agent.swarm.critic import CriticAgent
from src.agent.swarm.planner import PlannerAgent
from src.workflow.types import PipelineStage, StageContext, StageResult, StageStatus

logger = logging.getLogger(__name__)


# ============================================================================
# Descriptor Pattern (对齐 oh-my-codex pipeline descriptors)
# ============================================================================

@dataclass
class RalplanDescriptor:
    """RALPLAN 阶段的描述符 (对标 OMX 的 descriptor patterns)

    用于在前置 stages 之间传递规划意图和产出，而非直接执行硬编码逻辑。
    这种数据驱动的描述符便于：
    1. 阶段间清晰的数据结构传递
    2. 运行时监控与可视化
    3. 断点续跑时的状态重建
    4. 外部工具消费规划产出
    """
    task: str
    """原始任务描述"""

    plan: dict[str, Any]
    """实施计划文档（结构化"""

    prd: str
    """产品需求文档"""

    test_spec: str
    """测试规范"""

    architect_review: dict[str, Any] | None = None
    """Architect 审查反馈"""

    critic_review: dict[str, Any] | None = None
    """Critic 挑战意见"""

    staffing_plan: dict[str, Any] | None = None
    """人员配置计划 (借鉴 OMX)"""

    verification_plan: dict[str, Any] | None = None
    """验证与测试计划 (借鉴 OMX)"""

    risks: list[dict[str, Any]] | None = None
    """已识别的风险及缓解措施"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """扩展元数据"""

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典 (便于跨阶段传递和持久化)"""
        return {
            "task": self.task,
            "plan": self.plan,
            "prd": self.prd,
            "test_spec": self.test_spec,
            "architect_review": self.architect_review,
            "critic_review": self.critic_review,
            "staffing_plan": self.staffing_plan,
            "verification_plan": self.verification_plan,
            "risks": self.risks,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RalplanDescriptor:
        """从字典反序列化"""
        return cls(
            task=data.get("task", ""),
            plan=data.get("plan", {}),
            prd=data.get("prd", ""),
            test_spec=data.get("test_spec", ""),
            architect_review=data.get("architect_review"),
            critic_review=data.get("critic_review"),
            staffing_plan=data.get("staffing_plan"),
            verification_plan=data.get("verification_plan"),
            risks=data.get("risks", []),
            metadata=data.get("metadata", {}),
        )


class RalplanStage(PipelineStage):
    """RALPLAN 共识规划阶段
    
    执行 Planner → Architect → Critic 三方博弈流程：
    1. Planner 生成初步计划
    2. Architect 审查架构合理性
    3. Critic 挑战方案并找出弱点
    4. 整合为最终实施计划
    
    产出：
    - plan: 实施计划文档
    - prd: 产品需求文档
    - test_spec: 测试规范
    - risks: 已识别的风险及缓解措施
    """

    def __init__(
        self,
        enable_architect_review: bool = True,
        enable_critic_challenge: bool = True,
    ):
        """初始化 RALPLAN 阶段
        
        Args:
            enable_architect_review: 是否启用 Architect 审查
            enable_critic_challenge: 是否启用 Critic 挑战
        """
        self.enable_architect_review = enable_architect_review
        self.enable_critic_challenge = enable_critic_challenge

    @property
    def name(self) -> str:
        return "ralplan"

    async def run(self, ctx: StageContext) -> StageResult:
        """执行 RALPLAN 规划流程 (描述符驱动版本)

        产出:
            RalplanDescriptor 对象 (序列化为 artifacts)
        """
        import time
        logger = logging.getLogger(__name__)

        start_time = int(time.time() * 1000)
        logger.info("Starting RALPLAN consensus planning")

        task = ctx.task

        try:
            # Step 1: Planner 生成初步方案
            logger.debug("Phase 1: Planner generating initial plan")
            planner = PlannerAgent()
            initial_plan = await planner.plan(task)

            # Step 2: Architect 审查（如启用）
            architect_feedback = None
            if self.enable_architect_review:
                logger.debug("Phase 2: Architect reviewing plan")
                architect = ArchitectAgent()
                architect_feedback = await architect.review(initial_plan)

            # Step 3: Critic 挑战（如启用）
            critique = None
            if self.enable_critic_challenge:
                logger.debug("Phase 3: Critic challenging plan")
                critic = CriticAgent()
                critique = await critic.challenge(initial_plan)

            # Step 4: 构建描述符 (Descriptor)
            descriptor = self._build_descriptor(
                task=task,
                plan=initial_plan,
                architect_feedback=architect_feedback,
                critique=critique,
            )

            logger.info("RALPLAN planning completed successfully")

            return StageResult(
                status=StageStatus.SUCCESS,
                artifacts={
                    "ralplan_descriptor": descriptor.to_dict(),
                    "plan": descriptor.plan,
                    "prd": descriptor.prd,
                    "test_spec": descriptor.test_spec,
                    "architect_review": descriptor.architect_review,
                    "critic_review": descriptor.critic_review,
                    "staffing_plan": descriptor.staffing_plan,
                    "verification_plan": descriptor.verification_plan,
                    "risks": descriptor.risks,
                },
                duration_ms=int(time.time() * 1000) - start_time,
            )

        except Exception as e:
            logger.error(f"RALPLAN failed: {e}", exc_info=True)
            return StageResult(
                status=StageStatus.FAILED,
                error=str(e),
                duration_ms=int(time.time() * 1000) - start_time,
            )

    def _build_descriptor(
        self,
        task: str,
        plan: dict[str, Any],
        architect_feedback: dict[str, Any] | None = None,
        critique: dict[str, Any] | None = None,
    ) -> RalplanDescriptor:
        """构建 RALPLAN 描述符

        Args:
            task: 原始任务描述
            plan: Planner 生成的计划
            architect_feedback: Architect 审查反馈
            critique: Critic 挑战意见

        Returns:
            RalplanDescriptor 实例
        """
        # 提取各文档
        plan_doc = plan.get("plan", "Implementation plan")
        prd_doc = plan.get("prd", "Product requirements")
        test_spec = plan.get("test_spec", "Test specification")

        # 从 plan 中提取 staffing 和 verification (如果存在)
        staffing_plan = plan.get("staffing_plan")
        verification_plan = plan.get("verification_plan")
        risks = plan.get("risks", [])

        return RalplanDescriptor(
            task=task,
            plan=plan,
            prd=prd_doc,
            test_spec=test_spec,
            architect_review=architect_feedback,
            critic_review=critique,
            staffing_plan=staffing_plan,
            verification_plan=verification_plan,
            risks=risks,
            metadata={
                "enabled_architect_review": self.enable_architect_review,
                "enabled_critic_challenge": self.enable_critic_challenge,
            },
        )

    def can_skip(self, ctx: StageContext) -> bool:
        """检查是否可以跳过 RALPLAN (例如已有 plan artifacts)"""
        # 如果前一阶段已产出了 ralplan_descriptor 或 plan，可以跳过
        previous_artifacts = ctx.artifacts or {}
        return (
            "ralplan_descriptor" in previous_artifacts or
            "plan" in previous_artifacts
        )


# 便捷工厂函数
def create_ralplan_stage() -> RalplanStage:
    """创建 RALPLAN 阶段实例"""
    return RalplanStage()
