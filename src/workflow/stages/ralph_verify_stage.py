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
from pathlib import Path
from typing import Any

from ..pipeline_stage import PipelineStage, StageContext, StageResult

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
            verification_result = await self._verify_implementation(
                task, plan, iteration, cwd=Path(ctx.cwd)
            )

            approved = verification_result.get("approved", False)
            evidence = verification_result.get("evidence", {})

            if not approved:
                logger.info(f"[RalphVerify] Iteration {iteration} not approved: {verification_result.get('reason', 'Unknown')}")
                if evidence.get("status") == "not_configured":
                    # 没有可执行的验证命令：重试也不会改变结果，提前结束
                    # （而不是空转 max_iterations 次并最终谎称完成）。
                    logger.warning(
                        "[RalphVerify] 未配置验证命令，停止迭代；"
                        "结果标记为 skipped（未验证），不代表通过"
                    )
                    break
                # 验证失败后**不重试**：本阶段没有"重新实现"步骤，
                # 原样重跑同一条命令只会得到同样结果（白跑最多 10 次全量测试）。
                logger.info(
                    "[RalphVerify] 验证未通过；本阶段无重新实现步骤，停止迭代"
                )
                break

        # 构建最终报告
        final_result = self._build_final_report(task, iteration, approved, evidence)

        artifacts = {
            "ralph_result": final_result,
            "iterations": iteration,
            "approved": approved,
            "evidence": evidence,
        }

        # 阶段状态必须与验证结论一致：
        # 未通过却返回 completed，等于让管道把失败当成成功继续往下走。
        if approved:
            return StageResult.completed(artifacts=artifacts)
        if evidence.get("status") == "not_configured":
            return StageResult.skipped(artifacts=artifacts)
        return StageResult.failed(
            error=evidence.get("reason") or "验证未通过",
            artifacts=artifacts,
        )

    async def _verify_implementation(
        self,
        task: str,
        plan: str,
        iteration: int,
        cwd: Path | None = None,
    ) -> dict[str, Any]:
        """真实验证：运行验证命令并以退出码判定。

        历史：这里曾 `return {"approved": True}`（"简化为总是通过"）——
        循环结构看起来完整，循环体却永远批准。

        现在接入 `verification_runner`：
        - 有 tests/ 或设置了 CLAWD_VERIFY_COMMAND → 真跑，退出码 0 才算通过
        - 两者都没有 → `not_configured`，**不冒充通过**，调用方会提前结束循环
        """
        from ..verification_runner import run_verification

        # 必须用**管道上下文的工作目录**，而不是配置默认值 "."：
        # 否则会把进程当前目录当成目标项目去跑测试，可能对另一个项目报通过
        # —— 正是本项目刚修复过的那类"假验证"。
        target = Path(cwd) if cwd is not None else Path(self._config.cwd)

        logger.debug(
            f"[RalphVerify] Verifying implementation at iteration {iteration} "
            f"(cwd={target})"
        )
        vr = run_verification(target)

        return {
            "approved": vr.verified,
            "reason": vr.reason or vr.status,
            "evidence": {
                "tests_passed": vr.verified,
                "status": vr.status,
                "command": vr.command,
                "exit_code": vr.exit_code,
                "duration_ms": vr.duration_ms,
                "output_tail": vr.output_tail,
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
    "build_ralph_instruction",
    "create_ralph_verify_stage",
]
