"""
Pipeline Orchestrator - 管道编排器

从 oh-my-codex-main 汲取的管道编排器。
可配置管道序列: RALPLAN -> teams -> ralph verification。
通过 ModeState 系统持久化状态。

特点:
- 执行后端始终是 teams (Codex CLI workers)
- Ralph 迭代次数可配置
- 与现有 team mode 基础设施集成
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Callable

from .pipeline_stage import StageContext, StageResult, PipelineStage

logger = logging.getLogger(__name__)


# ===== 配置类 =====
@dataclass
class PipelineConfig:
    """管道运行配置"""
    name: str  # 人类可读的管道名称（用于状态文件和日志）
    task: str  # 驱动管道的任务描述
    stages: list[PipelineStage]  # 要执行的有序阶段列表
    cwd: str = ""  # 工作目录（默认为 process.cwd()）
    session_id: Optional[str] = None  # 可选的会话 ID，用于状态持久化
    max_ralph_iterations: int = 10  # 最大 ralph 验证迭代次数
    worker_count: int = 2  # worker 数量
    agent_type: str = "executor"  # 代理类型
    on_stage_transition: Optional[Callable[[str, str], None]] = None  # 阶段过渡回调


@dataclass
class PipelineResult:
    """管道运行结果"""
    status: str  # 'completed' | 'failed' | 'cancelled'
    stage_results: dict[str, StageResult] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    error: Optional[str] = None


# ===== 管道编排器 =====
class PipelineOrchestrator:
    """管道编排器

    顺序执行配置的阶段，在它们之间传递累积的工件。
    每个阶段过渡后通过 ModeState 系统持久化状态。
    """

    def __init__(self):
        self._mode_state: dict[str, Any] = {}

    async def run(self, config: PipelineConfig) -> PipelineResult:
        """运行配置的管道直到完成"""
        self._validate_config(config)

        cwd = config.cwd or "."
        start_time = datetime.now()

        # 初始化管道模式状态
        mode_state = self._start_mode("pipeline", config.task, len(config.stages), cwd)

        # 管道状态扩展
        pipeline_extension = {
            "pipeline_name": config.name,
            "pipeline_stages": [s.name for s in config.stages],
            "pipeline_stage_index": 0,
            "pipeline_stage_results": {},
            "pipeline_max_ralph_iterations": config.max_ralph_iterations,
            "pipeline_worker_count": config.worker_count,
            "pipeline_agent_type": config.agent_type,
        }

        await self._update_mode_state("pipeline", {
            **mode_state,
            **pipeline_extension,
            "current_phase": f"stage:{config.stages[0].name}",
        }, cwd)

        # 顺序执行阶段
        stage_results: dict[str, StageResult] = {}
        artifacts: dict[str, Any] = {}
        previous_result: Optional[StageResult] = None
        last_stage_name: Optional[str] = None

        for i, stage in enumerate(config.stages):
            # 构建阶段上下文
            ctx = StageContext(
                task=config.task,
                artifacts={**artifacts},
                previous_stage_result=previous_result,
                cwd=cwd,
                session_id=config.session_id,
            )

            # 从上一个完成/跳过的阶段到这一个的过渡回调
            if last_stage_name and config.on_stage_transition:
                try:
                    config.on_stage_transition(last_stage_name, stage.name)
                except Exception as e:
                    logger.warning(f"Stage transition callback failed: {e}")

            # 检查是否应该跳过阶段
            if stage.can_skip(ctx):
                skipped_result = StageResult(
                    status='skipped',
                    artifacts={},
                    duration_ms=0,
                )
                stage_results[stage.name] = skipped_result

                await self._update_mode_state("pipeline", {
                    "current_phase": f"stage:{stage.name}:skipped",
                    "pipeline_stage_index": i,
                    "pipeline_stage_results": {**stage_results},
                }, cwd)

                last_stage_name = stage.name
                continue

            # 执行阶段
            logger.info(f"[Pipeline] Executing stage: {stage.name}")
            stage_start = datetime.now()

            try:
                result = await stage.run(ctx)
            except Exception as e:
                logger.error(f"Stage {stage.name} failed with exception: {e}")
                result = StageResult.failed(str(e))

            stage_duration = int((datetime.now() - stage_start).total_seconds() * 1000)
            result.duration_ms = stage_duration

            stage_results[stage.name] = result

            # 更新工件
            artifacts = {**artifacts, **result.artifacts}
            previous_result = result

            # 更新模式状态
            await self._update_mode_state("pipeline", {
                "current_phase": f"stage:{stage.name}:{result.status}",
                "pipeline_stage_index": i,
                "pipeline_stage_results": {**stage_results},
                "pipeline_current_artifacts": artifacts,
            }, cwd)

            last_stage_name = stage.name

            # 如果阶段失败，停止管道
            if result.status == 'failed':
                logger.error(f"[Pipeline] Stage {stage.name} failed: {result.error}")
                break

        # 计算总时长
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        # 确定最终状态
        if any(r.status == 'failed' for r in stage_results.values()):
            final_status = 'failed'
            final_error = next((r.error for r in stage_results.values() if r.error), "Unknown failure")
        elif any(r.status == 'skipped' for r in stage_results.values()):
            final_status = 'completed_with_skips'
        else:
            final_status = 'completed'

        return PipelineResult(
            status=final_status,
            stage_results=stage_results,
            artifacts=artifacts,
            duration_ms=duration_ms,
            error=final_error if final_status == 'failed' else None,
        )

    def _validate_config(self, config: PipelineConfig) -> None:
        """验证管道配置"""
        if not config.name:
            raise ValueError("Pipeline config must have a name")
        if not config.task:
            raise ValueError("Pipeline config must have a task")
        if not config.stages:
            raise ValueError("Pipeline config must have at least one stage")

    def _start_mode(self, mode_name: str, task: str, stage_count: int, cwd: str) -> dict[str, Any]:
        """启动模式状态"""
        state = {
            "mode": mode_name,
            "task": task,
            "stage_count": stage_count,
            "started_at": datetime.now().isoformat(),
            "cwd": cwd,
        }
        self._mode_state = state
        return state

    async def _update_mode_state(self, mode: str, updates: dict[str, Any], cwd: str) -> None:
        """更新模式状态"""
        self._mode_state.update(updates)
        logger.debug(f"[Pipeline] Mode state updated: {self._mode_state.get('current_phase')}")


# ===== 管道状态恢复 =====
async def can_resume_pipeline(cwd: str = ".") -> bool:
    """检查管道是否可以恢复（从 oh-my-codex 汲取）"""
    from .mode_state import read_mode_state
    state = read_mode_state("pipeline", cwd)
    if not state:
        return False
    return state.metadata.get("active", False) and "complete" not in state.current_phase and "failed" not in state.current_phase


async def read_pipeline_state(cwd: str = ".") -> Optional[dict[str, Any]]:
    """读取当前管道状态扩展字段"""
    from .mode_state import read_mode_state
    state = read_mode_state("pipeline", cwd)
    if not state:
        return None
    if not state.metadata.get("pipeline_name"):
        return None
    return {
        "pipeline_name": state.metadata.get("pipeline_name"),
        "pipeline_stages": state.metadata.get("pipeline_stages", []),
        "pipeline_stage_index": state.metadata.get("pipeline_stage_index", 0),
        "pipeline_stage_results": state.metadata.get("pipeline_stage_results", {}),
        "pipeline_max_ralph_iterations": state.metadata.get("pipeline_max_ralph_iterations", 10),
        "pipeline_worker_count": state.metadata.get("pipeline_worker_count", 2),
    }


async def cancel_pipeline(cwd: str = ".") -> None:
    """取消正在运行的管道"""
    from .mode_state import cancel_mode
    cancel_mode("pipeline", cwd, "User cancelled")


# ===== 导出 =====
__all__ = [
    "PipelineConfig",
    "PipelineResult",
    "PipelineOrchestrator",
    "run_pipeline",
    "can_resume_pipeline",
    "read_pipeline_state",
    "cancel_pipeline",
]