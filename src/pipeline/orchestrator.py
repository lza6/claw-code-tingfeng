"""Pipeline Orchestrator - 管道编排器

借鉴 oh-my-codex 的 Pipeline 架构。
提供声明式、阶段化的任务执行管道。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..core.events import EventBus, get_event_bus
from .stages import PipelineStage, StageContext, StageResult

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """管道配置"""
    pipeline_id: str
    goal: str
    stages: list[PipelineStage]
    max_retries: int = 3
    retry_backoff: str = "exponential"  # linear, exponential
    evidence_level: str = "minimal"  # none, minimal, full
    verification_mode: str = "auto"  # auto, strict, lenient


@dataclass
class PipelineRun:
    """管道执行运行"""
    config: PipelineConfig
    run_id: str
    started_at: str
    current_stage: int = 0
    results: dict[str, StageResult] = field(default_factory=dict)
    failed: bool = False
    error: str = ""
    completed_at: str | None = None


class PipelineOrchestrator:
    """管道编排器

    负责:
    1. 按顺序执行管道阶段
    2. 处理重试逻辑
    3. 收集证据和结果
    4. 管理回滚
    """

    def __init__(
        self,
        workdir: Path | None = None,
        event_bus: EventBus | None = None,
    ):
        self.workdir = workdir or Path.cwd()
        self._event_bus = event_bus or get_event_bus()
        self._active_runs: dict[str, PipelineRun] = {}

    def create_pipeline(
        self,
        goal: str,
        stages: list[PipelineStage],
        **kwargs,
    ) -> PipelineConfig:
        """创建管道配置"""
        import uuid
        pipeline_id = str(uuid.uuid4())[:8]

        return PipelineConfig(
            pipeline_id=pipeline_id,
            goal=goal,
            stages=stages,
            **kwargs,
        )

    async def run(self, config: PipelineConfig) -> PipelineRun:
        """执行管道"""
        run_id = str(datetime.now().timestamp())
        run = PipelineRun(
            config=config,
            run_id=run_id,
            started_at=datetime.now().isoformat(),
        )
        self._active_runs[run_id] = run

        try:
            # 依次执行每个阶段
            for stage_idx, stage in enumerate(config.stages):
                run.current_stage = stage_idx
                stage_name = stage.__class__.__name__

                logger.info(f"Executing stage {stage_idx}: {stage_name}")

                # 创建阶段上下文
                context = StageContext(
                    workdir=self.workdir,
                    pipeline_id=config.pipeline_id,
                    run_id=run_id,
                    stage_index=stage_idx,
                    previous_results=run.results,
                    config=config,
                )

                # 执行阶段 (支持重试)
                result = await self._execute_stage_with_retry(
                    stage, context, config.max_retries
                )

                run.results[stage_name] = result

                # 检查结果
                if not result.success:
                    run.failed = True
                    run.error = result.error or f"Stage {stage_name} failed"
                    logger.error(f"Stage {stage_name} failed: {result.error}")
                    break

                # 发布事件
                await self._event_bus.publish({
                    "type": "pipeline.stage.completed",
                    "pipeline_id": config.pipeline_id,
                    "stage": stage_name,
                    "result": result.to_dict(),
                })

            run.completed_at = datetime.now().isoformat()

        except Exception as e:
            run.failed = True
            run.error = str(e)
            logger.exception("Pipeline execution failed")

        finally:
            # 清理
            if run_id in self._active_runs:
                del self._active_runs[run_id]

        return run

    async def _execute_stage_with_retry(
        self,
        stage: PipelineStage,
        context: StageContext,
        max_retries: int,
    ) -> StageResult:
        """带重试的阶段执行"""
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    logger.info(f"Retry attempt {attempt} for stage {stage.__class__.__name__}")
                    # 指数退避
                    if self.config.retry_backoff == "exponential":
                        delay = min(2 ** attempt, 60)
                        await asyncio.sleep(delay)

                result = await stage.execute(context)
                return result

            except Exception as e:
                last_error = str(e)
                logger.warning(f"Stage attempt {attempt} failed: {e}")

                # 检查是否是可重试错误
                if not self._is_retryable_error(e):
                    logger.error(f"Non-retryable error: {e}")
                    break

        # 所有重试失败
        return StageResult(
            success=False,
            error=f"Stage failed after {max_retries} retries: {last_error}",
        )

    def _is_retryable_error(self, error: Exception) -> bool:
        """判断错误是否可重试"""
        # 临时性错误可以重试
        retryable_messages = [
            "timeout",
            "connection error",
            "rate limit",
            "temporary",
            "unavailable",
        ]
        error_str = str(error).lower()
        return any(msg in error_str for msg in retryable_messages)

    def get_run_status(self, run_id: str) -> PipelineRun | None:
        """获取运行状态"""
        return self._active_runs.get(run_id)


# ==================== 便捷函数 ====================

async def run_pipeline(
    goal: str,
    stages: list[PipelineStage],
    workdir: Path | None = None,
    **kwargs,
) -> PipelineRun:
    """
    便捷函数：创建并执行管道

    Args:
        goal: 任务目标
        stages: 阶段列表
        workdir: 工作目录
        **kwargs: 管道配置参数

    Returns:
        执行结果
    """
    orchestrator = PipelineOrchestrator(workdir=workdir)
    config = orchestrator.create_pipeline(goal, stages, **kwargs)
    return await orchestrator.run(config)
