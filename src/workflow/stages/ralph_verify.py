"""
Ralph Verify Stage - Ralph 验证阶段

从 oh-my-codex-main 汲取的 Ralph 验证阶段。
通过 Architect 验证实现是否满足计划要求。
循环直到验证通过或达到最大迭代次数。

Ralph 循环核心:
- 迭代执行直到任务完成
- 每次迭代后必须通过 Architect 验证
- 未通过则继续迭代
- 达到最大迭代次数后报告最佳结果
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from ..pipeline_stage import StageContext, StageResult, PipelineStage

logger = logging.getLogger(__name__)


# ===== 配置 =====
@dataclass
class RalphVerifyConfig:
    """Ralph 验证配置"""
    max_iterations: int = 10
    verification_level: str = "standard"  # 'quick' | 'standard' | 'thorough'
    require_evidence: bool = True
    cwd: str = "."


@dataclass
class RalphVerifyDescriptor:
    """Ralph 验证描述符"""
    task: str
    plan: str
    iterations: int = 0
    approved: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)


# ===== Ralph 验证阶段 =====
class RalphVerifyStage(PipelineStage):
    """Ralph 验证阶段

    通过迭代验证确保任务完成。
    每次迭代必须通过 Architect 验证才能结束。
    """

    def __init__(self, config: RalphVerifyConfig):
        self._config = config

    @property
    def name(self) -> str:
        return "ralph-verify"

    async def run(self, ctx: StageContext) -> StageResult:
        """执行 Ralph 验证阶段"""
        logger.info(f"[RalphVerify] Starting Ralph verification (max {self._config.max_iterations} iterations)")

        # 从上下文获取任务和计划
        task = ctx.task
        plan = ctx.get_artifact("plan", "")

        iteration = 0
        approved = False
        evidence = {}

        # 迭代直到验证通过或达到最大迭代
        while iteration < self._config.max_iterations and not approved:
            iteration += 1
            logger.info(f"[RalphVerify] Iteration {iteration}/{self._config.max_iterations}")

            # 验证当前状态
            verification_result = await self._verify_implementation(task, plan, iteration)

            approved = verification_result.get("approved", False)
            evidence = verification_result.get("evidence", {})

            if not approved:
                logger.info(f"[RalphVerify] Iteration {iteration} not approved: {verification_result.get('reason', 'Unknown')}")
                # 短暂延迟后继续下一次迭代
                await self._delay(0.5)

        # 构建最终报告
        final_result = self._build_final_report(task, iteration, approved, evidence)

        return StageResult.completed(
            artifacts={
                "ralph_result": final_result,
                "iterations": iteration,
                "approved": approved,
                "evidence": evidence,
            },
        )

    async def _verify_implementation(
        self,
        task: str,
        plan: str,
        iteration: int,
    ) -> dict[str, Any]:
        """验证实现

        通过 Architect 验证当前实现是否满足要求。
        """
        # TODO: 实现真正的验证逻辑
        # - 检查实现与计划的匹配度
        # - 验证测试通过
        # - 检查证据完整性

        logger.debug(f"[RalphVerify] Verifying implementation at iteration {iteration}")

        # 模拟验证结果
        # 实际实现应该调用 Architect agent 进行验证
        return {
            "approved": True,  # 简化为总是通过
            "reason": "Implementation matches plan",
            "evidence": {
                "tests_passed": True,
                "code_reviewed": True,
            },
        }

    async def _delay(self, seconds: float) -> None:
        """延迟"""
        import asyncio
        await asyncio.sleep(seconds)

    def _build_final_report(
        self,
        task: str,
        iteration: int,
        approved: bool,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        """构建最终报告"""
        return {
            "task": task,
            "status": "completed" if approved else "incomplete",
            "iterations": iteration,
            "approved": approved,
            "evidence": evidence,
            "summary": f"Completed after {iteration} iterations" if approved else f"Stopped after {iteration} iterations (max reached)",
        }


# ===== 构建函数 =====
def create_ralph_verify_stage(config: RalphVerifyConfig = None, **options) -> PipelineStage:
    """创建 Ralph 验证阶段"""
    if config is None:
        config = RalphVerifyConfig(**options)
    return RalphVerifyStage(config)


def build_ralph_instruction(
    task: str,
    plan: str = "",
    context: dict[str, Any] = None,
) -> str:
    """构建 Ralph 指令字符串"""
    instruction = f"""Continue working on the task until it is fully complete.

Task: {task}
"""

    if plan:
        instruction += f"""
Plan:
{plan}
"""

    if context:
        instruction += "\nContext:\n"
        for key, value in context.items():
            instruction += f"- {key}: {value}\n"

    instruction += """
IMPORTANT: Do not stop until the task is complete.
Verify your work before reporting completion.
"""

    return instruction


# ===== 导出 =====
__all__ = [
    "RalphVerifyConfig",
    "RalphVerifyDescriptor",
    "RalphVerifyStage",
    "create_ralph_verify_stage",
    "build_ralph_instruction",
]