"""
Pipeline Orchestrator - 工作流编排器

从 oh-my-codex-main/src/pipeline/orchestrator.ts 汲取设计：
- 状态持久化通过 ModeStateManager（对标 PipelineModeStateExtension）
- 条件跳过（canSkip）智能优化执行
- 断点续跑（canResumePipeline）支持 CI/CD 场景
- 阶段转换回调（onStageTransition）用于监控

对应项目 B 的核心组件：
- oh-my-codex-main/src/pipeline/orchestrator.ts
- oh-my-codex-main/src/pipeline/types.ts (PipelineStage, PipelineConfig, PipelineResult)

作者：Kilo Code（基于 oh-my-codex 设计理念，2026-04-17 整合增强）
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .mode_state import ModeStateManager
from .types import (
    PipelineConfig,
    PipelineResult,
    PipelineStage,
    StageContext,
    StageResult,
    StageStatus,
)

logger = logging.getLogger(__name__)

# ========== Pipeline 独占模式名 ==========

MODES_MODE_NAME = 'autopilot'

# ========== Pipeline 扩展字段名常量 ==========

PIPELINE_NAME_KEY = "pipeline_name"
PIPELINE_STAGES_KEY = "pipeline_stages"
PIPELINE_STAGE_INDEX_KEY = "pipeline_stage_index"
PIPELINE_STAGE_RESULTS_KEY = "pipeline_stage_results"
PIPELINE_MAX_ITERATIONS_KEY = "pipeline_max_ralph_iterations"
PIPELINE_WORKER_COUNT_KEY = "pipeline_worker_count"
PIPELINE_AGENT_TYPE_KEY = "pipeline_agent_type"


# ========== PipelineModeStateExtension（状态扩展）==========

@dataclass
class PipelineModeStateExtension:
    """Pipeline 扩展字段（对标 TS 的 PipelineModeStateExtension）"""
    pipeline_name: str
    pipeline_stages: list[str]
    pipeline_stage_index: int
    pipeline_stage_results: dict[str, dict[str, Any]]
    pipeline_max_ralph_iterations: int
    pipeline_worker_count: int
    pipeline_agent_type: str

    @classmethod
    def from_mode_metadata(cls, metadata: dict[str, Any]) -> PipelineModeStateExtension | None:
        """从 mode metadata 反序列化"""
        if PIPELINE_NAME_KEY not in metadata:
            return None
        return cls(
            pipeline_name=metadata[PIPELINE_NAME_KEY],
            pipeline_stages=metadata.get(PIPELINE_STAGES_KEY, []),
            pipeline_stage_index=metadata.get(PIPELINE_STAGE_INDEX_KEY, 0),
            pipeline_stage_results=metadata.get(PIPELINE_STAGE_RESULTS_KEY, {}),
            pipeline_max_ralph_iterations=metadata.get(PIPELINE_MAX_ITERATIONS_KEY, 10),
            pipeline_worker_count=metadata.get(PIPELINE_WORKER_COUNT_KEY, 2),
            pipeline_agent_type=metadata.get(PIPELINE_AGENT_TYPE_KEY, "executor"),
        )

    def to_metadata_update(self) -> dict[str, Any]:
        """构造用于更新 mode state 的增量字段"""
        return {
            PIPELINE_NAME_KEY: self.pipeline_name,
            PIPELINE_STAGES_KEY: self.pipeline_stages,
            PIPELINE_STAGE_INDEX_KEY: self.pipeline_stage_index,
            PIPELINE_STAGE_RESULTS_KEY: self.pipeline_stage_results,
            PIPELINE_MAX_ITERATIONS_KEY: self.pipeline_max_ralph_iterations,
            PIPELINE_WORKER_COUNT_KEY: self.pipeline_worker_count,
            PIPELINE_AGENT_TYPE_KEY: self.pipeline_agent_type,
        }


# ========== 辅助函数（序列化） ==========

def _serialize_result(result: StageResult) -> dict[str, Any]:
    """序列化 StageResult 为 JSON 可序列化格式"""
    # 确保 status 是字符串而非枚举
    status_value = result.status.value if hasattr(result.status, 'value') else str(result.status)
    return {
        "status": status_value,
        "artifacts": result.artifacts,
        "duration_ms": result.duration_ms,
        "error": result.error,
        "skipped_reason": result.skipped_reason,
    }


def _deserialize_result(data: dict[str, Any]) -> StageResult:
    """从 JSON 反序列化为 StageResult"""
    return StageResult(
        status=data.get("status", StageStatus.FAILED),
        artifacts=data.get("artifacts", {}),
        duration_ms=data.get("duration_ms", 0),
        error=data.get("error"),
    )


# ========== PipelineState（向后兼容适配器 - DEPRECATED） ==========

class PipelineState:
    """
    [DEPRECATED] 向后兼容的 PipelineState 适配器。

    警告: 此类已废弃，请直接使用 ModeStateManager 管理状态。
    
    旧版 API 用于与原有测试和调用代码兼容，内部通过 ModeStateManager
    实现状态持久化。文件格式符合 oh-my-codex 的 PipelineModeStateExtension。
    
    迁移指南:
        # 旧代码
        state = PipelineState(pipeline_name="my-pipeline")
        state.save()
        
        # 新代码
        from .mode_state import ModeStateManager
        manager = ModeStateManager(cwd=".")
        manager.update_metadata({"pipeline_name": "my-pipeline"})
    """

    def __init__(
        self,
        pipeline_name: str,
        current_stage_index: int = 0,
        stage_results: dict[str, StageResult] | None = None,
        artifacts: dict[str, Any] | None = None,
        cwd: str = ".",
    ):
        self.pipeline_name = pipeline_name
        self.current_stage_index = current_stage_index
        self.stage_results = stage_results or {}
        self.artifacts = artifacts or {}
        self._cwd = cwd

    def save(self, state_file: str | None = None) -> None:
        """
        保存 pipeline 状态到磁盘。

        Args:
            state_file: 兼容性参数，实际路径由 pipeline_name 和 cwd 决定
        """
        state_dir = Path(self._cwd) / ".clawd" / "pipeline"
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / f"{self.pipeline_name}.json"

        payload = {
            PIPELINE_NAME_KEY: self.pipeline_name,
            PIPELINE_STAGES_KEY: [],
            PIPELINE_STAGE_INDEX_KEY: self.current_stage_index,
            PIPELINE_STAGE_RESULTS_KEY: {
                name: _serialize_result(result)
                for name, result in self.stage_results.items()
            },
            PIPELINE_MAX_ITERATIONS_KEY: 10,
            PIPELINE_WORKER_COUNT_KEY: 2,
            PIPELINE_AGENT_TYPE_KEY: "executor",
        }
        state_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, state_file: str) -> PipelineState | None:
        """
        从文件加载 pipeline 状态。

        Args:
            state_file: 状态文件路径

        Returns:
            PipelineState 实例，加载失败返回 None
        """
        p = Path(state_file)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load pipeline state from {state_file}: {e}")
            return None

        name = data.get(PIPELINE_NAME_KEY, "")
        if not name:
            logger.warning("Pipeline state file missing pipeline_name")
            return None

        stage_results = {
            name: _deserialize_result(rd)
            for name, rd in data.get(PIPELINE_STAGE_RESULTS_KEY, {}).items()
        }

        # 推断 cwd：向上查找 .clawd 父目录
        cwd = str(p.parent.parent.parent) if p.parent.name == "pipeline" else str(p.parent)

        return cls(
            pipeline_name=name,
            current_stage_index=data.get(PIPELINE_STAGE_INDEX_KEY, 0),
            stage_results=stage_results,
            cwd=cwd,
        )

    @classmethod
    def can_resume(cls, state_file: str) -> bool:
        """
        检查是否可以从上次状态恢复。

        条件:
        1. 状态文件存在
        2. pipeline_name 存在且 current_stage_index < 总阶段数（需配合 stages 参数）
        """
        p = Path(state_file)
        if not p.exists():
            return False
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            idx = data.get(PIPELINE_STAGE_INDEX_KEY, 0)
            stages = data.get(PIPELINE_STAGES_KEY, [])
            return idx < len(stages)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to check resume state: {e}")
            return False

    @classmethod
    def get_resume_index(cls, state_file: str) -> int:
        """获取恢复时的起始阶段索引"""
        p = Path(state_file)
        if not p.exists():
            return 0
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data.get(PIPELINE_STAGE_INDEX_KEY, 0)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to get resume index: {e}")
            return 0

    def get_stage_results(self) -> dict[str, StageResult]:
        """获取已执行阶段的结果"""
        return self.stage_results.copy()

    @classmethod
    def get_stage_results_from_file(cls, state_file: str) -> dict[str, StageResult]:
        """从文件读取所有阶段结果"""
        loaded = cls.load(state_file)
        if not loaded:
            return {}
        return loaded.get_stage_results()

    def clear(self, state_file: str | None = None) -> None:
        """清理 pipeline 状态文件"""
        if state_file:
            p = Path(state_file)
            if p.exists():
                p.unlink()


# PipelineConfig 和 PipelineResult 已通过 .types 导入


# ========== Pipeline Orchestrator ==========

class PipelineOrchestrator:
    """
    Pipeline 编排器（对标 oh-my-codex 的 runPipeline）

    核心能力：
    1. 状态持久化：通过 ModeStateManager（对标 TS 的 PipelineModeStateExtension）
    2. 条件跳过：通过 canSkip 优化执行
    3. 断点续跑：从上次失败处继续
    4. 阶段回调：支持监控和日志
    5. 配置验证：确保配置正确性
    """

    def __init__(
        self,
        config: PipelineConfig,
        cwd: str = ".",
        validate: bool = True,
    ):
        self.config = config
        self._cwd = cwd
        self._mode_manager = ModeStateManager(cwd)
        self._start_time = datetime.now()
        self._cancelled = False
        self._current_index = 0
        self._last_stage_name: str | None = None

        if validate:
            self._validate_config()

    def _validate_config(self) -> None:
        """验证 pipeline 配置（对标 TS 的 validateConfig）"""
        if not self.config.name or not self.config.name.strip():
            raise ValueError("Pipeline config requires a non-empty name")
        if not self.config.task or not self.config.task.strip():
            raise ValueError("Pipeline config requires a non-empty task")
        if not self.config.stages or len(self.config.stages) == 0:
            raise ValueError("Pipeline config requires at least one stage")

        names = [s.name for s in self.config.stages]
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate stage name in pipeline: {[n for n in names if names.count(n) > 1]}")

        if self.config.max_ralph_iterations is not None:
            if not isinstance(self.config.max_ralph_iterations, int) or self.config.max_ralph_iterations <= 0:
                raise ValueError("max_ralph_iterations must be a positive integer")

        if self.config.worker_count is not None:
            if not isinstance(self.config.worker_count, int) or self.config.worker_count <= 0:
                raise ValueError("worker_count must be a positive integer")

    async def run(self) -> PipelineResult:
        """
        执行 pipeline（核心逻辑，对标 runPipeline）

        执行流程：
        1. 初始化 pipeline mode state（通过 ModeStateManager）
        2. 检查恢复状态
        3. 顺序执行阶段（支持跳过）
        4. 持久化状态（每个阶段后更新 ModeState）
        5. 完成/失败时清理
        """
        logger.info(f"启动 Pipeline: {self.config.name}，共 {len(self.config.stages)} 个阶段")

        cwd = self._cwd or os.getcwd()
        stage_names = [s.name for s in self.config.stages]

        # 1. 初始化 pipeline mode state
        self._mode_manager.start_mode(
            mode=MODES_MODE_NAME,
            task=self.config.task,
            metadata={
                PIPELINE_NAME_KEY: self.config.name,
                PIPELINE_STAGES_KEY: stage_names,
                PIPELINE_STAGE_INDEX_KEY: 0,
                PIPELINE_STAGE_RESULTS_KEY: {},
                PIPELINE_MAX_ITERATIONS_KEY: self.config.max_ralph_iterations,
                PIPELINE_WORKER_COUNT_KEY: self.config.worker_count,
                PIPELINE_AGENT_TYPE_KEY: self.config.agent_type,
                "active": True,
                "current_phase": f"stage:{stage_names[0]}" if stage_names else "initialized",
            },
        )

        # 2. 检查恢复状态
        resume_index = 0
        existing_results: dict[str, StageResult] = {}
        if self.can_resume():
            ext = self.read_pipeline_state()
            if ext:
                resume_index = ext.pipeline_stage_index
                existing_results = {
                    name: _deserialize_result(data)
                    for name, data in ext.pipeline_stage_results.items()
                }
                self._last_stage_name = stage_names[resume_index - 1] if resume_index > 0 else None
                logger.info(f"检测到可恢复的 pipeline，从阶段 {resume_index} 继续执行")

        current_results = existing_results.copy()
        self._current_index = resume_index
        stage_results_serialized: dict[str, dict[str, Any]] = {
            name: _serialize_result(r) for name, r in current_results.items()
        }

        # 3. 顺序执行阶段
        for i in range(resume_index, len(self.config.stages)):
            if self._cancelled:
                logger.warning("Pipeline 被取消")
                return self._complete_pipeline(
                    status="cancelled",
                    results=current_results,
                )

            stage = self.config.stages[i]
            ctx = self._build_context(stage, current_results)

            # 触发阶段转换回调
            if self._last_stage_name and self.config.on_stage_transition:
                self.config.on_stage_transition(self._last_stage_name, stage.name)

            # 检查跳过
            if stage.can_skip and stage.can_skip(ctx):
                skipped_result = StageResult(
                    status=StageStatus.SKIPPED,
                    artifacts={},
                    duration_ms=0,
                )
                current_results[stage.name] = skipped_result
                stage_results_serialized[stage.name] = _serialize_result(skipped_result)
                self._current_index = i + 1
                self._last_stage_name = stage.name
                self._update_mode_state(
                    current_phase=f"stage:{stage.name}:skipped",
                    pipeline_stage_index=i,
                    pipeline_stage_results=stage_results_serialized,
                )
                continue

            # 更新为运行中状态
            self._update_mode_state(
                current_phase=f"stage:{stage.name}",
                pipeline_stage_index=i,
            )

            # 执行阶段
            logger.info(f"执行阶段 [{stage.name}] ({i + 1}/{len(self.config.stages)})")
            result: StageResult
            try:
                result = await stage.run(ctx)
            except Exception as err:
                error_msg = str(err)
                result = StageResult(
                    status=StageStatus.FAILED,
                    artifacts={},
                    duration_ms=self._elapsed_ms(),
                    error=f"Stage {stage.name} threw: {error_msg}",
                )

            current_results[stage.name] = result
            stage_results_serialized[stage.name] = _serialize_result(result)
            self._current_index = i + 1
            self._last_stage_name = stage.name

            # 持久化状态
            self._update_mode_state(
                current_phase=f"stage:{stage.name}:{result.status}",
                pipeline_stage_index=i,
                pipeline_stage_results=stage_results_serialized,
            )

            # 失败处理
            if result.status == StageStatus.FAILED:
                return self._complete_pipeline(
                    status="failed",
                    failed_stage=stage.name,
                    error=result.error,
                    results=current_results,
                )

        # 4. 执行完成
        return self._complete_pipeline(status="completed", results=current_results)

    def _build_context(
        self,
        stage: PipelineStage,
        results: dict[str, StageResult],
    ) -> StageContext:
        """构建阶段执行上下文"""
        previous_result: StageResult | None = None
        if results:
            stage_names = [s.name for s in self.config.stages]
            try:
                current_idx = stage_names.index(stage.name)
                if current_idx > 0:
                    prev_name = stage_names[current_idx - 1]
                    if prev_name in results:
                        previous_result = results[prev_name]
            except ValueError:
                pass

        return StageContext(
            task=self.config.task,
            artifacts={k: r.artifacts for k, r in results.items()},
            previous_stage_result=previous_result,
            cwd=self._cwd or os.getcwd(),
            session_id=self.config.session_id,
        )

    def _update_mode_state(
        self,
        current_phase: str,
        pipeline_stage_index: int,
        pipeline_stage_results: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """通过 ModeStateManager 持久化 pipeline 状态"""
        metadata: dict[str, Any] = {
            "current_phase": current_phase,
            PIPELINE_STAGE_INDEX_KEY: pipeline_stage_index,
            PIPELINE_MAX_ITERATIONS_KEY: self.config.max_ralph_iterations,
            PIPELINE_WORKER_COUNT_KEY: self.config.worker_count,
            PIPELINE_AGENT_TYPE_KEY: self.config.agent_type,
        }
        if pipeline_stage_results is not None:
            metadata[PIPELINE_STAGE_RESULTS_KEY] = pipeline_stage_results
        self._mode_manager.update_state(MODES_MODE_NAME, metadata)

    def _complete_pipeline(
        self,
        status: str,
        results: dict[str, StageResult],
        failed_stage: str | None = None,
        error: str | None = None,
    ) -> PipelineResult:
        """完成 pipeline：更新状态并返回结果"""
        self._mode_manager.update_state(MODES_MODE_NAME, {
            "active": False,
            "current_phase": "complete" if status == "completed" else status,
            "completed_at": datetime.now().isoformat(),
            PIPELINE_STAGE_RESULTS_KEY: {
                name: _serialize_result(r) for name, r in results.items()
            },
        })

        merged_artifacts: dict[str, Any] = {}
        for r in results.values():
            merged_artifacts.update(r.artifacts)

        return PipelineResult(
            status=status,
            stage_results=results,
            duration_ms=self._elapsed_ms(),
            artifacts=merged_artifacts,
            failed_stage=failed_stage,
            error=error,
        )

    def _elapsed_ms(self) -> int:
        """计算已用时间（毫秒）"""
        return int((datetime.now() - self._start_time).total_seconds() * 1000)

    def can_resume(self) -> bool:
        """
        检查是否可以从上次状态恢复（对标 canResumePipeline）

        条件：
        1. ModeState 存在
        2. active == True
        3. current_phase 不是 complete 或 failed
        """
        state = self._mode_manager.read_state(MODES_MODE_NAME)
        if not state:
            return False
        return (
            state.metadata.get("active") is True
            and state.current_phase not in ("complete", "failed")
        )

    def read_pipeline_state(self) -> PipelineModeStateExtension | None:
        """读取 pipeline 扩展状态字段（对标 readPipelineState）"""
        state = self._mode_manager.read_state(MODES_MODE_NAME)
        if not state:
            return None
        return PipelineModeStateExtension.from_mode_metadata(state.metadata)

    def cancel(self) -> None:
        """取消 pipeline 执行"""
        self._cancelled = True
        self._mode_manager.update_state(MODES_MODE_NAME, {
            "active": False,
            "current_phase": "cancelled",
        })
        logger.info(f"Pipeline [{self.config.name}] 取消请求已发送")

    def get_current_stage(self) -> str | None:
        """获取当前正在执行的阶段名称"""
        if 0 <= self._current_index < len(self.config.stages):
            return self.config.stages[self._current_index].name
        return None


# ========== 便捷函数 ==========

def create_pipeline(
    name: str,
    task: str,
    stages: list[PipelineStage],
    **kwargs,
) -> PipelineOrchestrator:
    """
    便捷构造函数

    示例：
        pipeline = create_pipeline(
            name="my-pipeline",
            task="实现用户认证",
            stages=[
                create_plan_stage(),
                create_team_exec_stage(worker_count=2),
                create_ralph_verify_stage(max_iterations=10),
            ],
            cwd="/path/to/project",
        )
        result = await pipeline.run()
    """
    config = PipelineConfig(name=name, task=task, stages=stages, **kwargs)
    return PipelineOrchestrator(config)


def create_autopilot_pipeline_config(
    task: str,
    stages: list[PipelineStage],
    cwd: str | None = None,
    session_id: str | None = None,
    max_ralph_iterations: int = 10,
    worker_count: int = 2,
    agent_type: str = "executor",
    on_stage_transition: Callable[[str, str], None] | None = None,
) -> PipelineConfig:
    """
    创建 autopilot pipeline 配置（对标 createAutopilotPipelineConfig）

    流水线序列：RALPLAN -> team-exec -> ralph-verify
    """
    return PipelineConfig(
        name="autopilot",
        task=task,
        stages=stages,
        cwd=cwd,
        session_id=session_id,
        max_ralph_iterations=max_ralph_iterations,
        worker_count=worker_count,
        agent_type=agent_type,
        on_stage_transition=on_stage_transition,
    )


def validate_pipeline_config(config: PipelineConfig) -> None:
    """
    验证 pipeline 配置（对标 validateConfig）

    检查配置的完整性和有效性，在创建 PipelineOrchestrator 前调用。
    
    Args:
        config: 待验证的 PipelineConfig
        
    Raises:
        ValueError: 配置无效时抛出
    """
    if not config.name or not config.name.strip():
        raise ValueError("Pipeline config requires a non-empty name")
    if not config.task or not config.task.strip():
        raise ValueError("Pipeline config requires a non-empty task")
    if not config.stages or len(config.stages) == 0:
        raise ValueError("Pipeline config requires at least one stage")

    names = [s.name for s in config.stages]
    if len(names) != len(set(names)):
        raise ValueError(f"Duplicate stage name in pipeline: {[n for n in names if names.count(n) > 1]}")

    if config.max_ralph_iterations is not None:
        if not isinstance(config.max_ralph_iterations, int) or config.max_ralph_iterations <= 0:
            raise ValueError("max_ralph_iterations must be a positive integer")

    if config.worker_count is not None:
        if not isinstance(config.worker_count, int) or config.worker_count <= 0:
            raise ValueError("worker_count must be a positive integer")


def can_resume_pipeline(cwd: str = ".") -> bool:
    """检查是否可以恢复 pipeline（对标 canResumePipeline）"""
    manager = ModeStateManager(cwd)
    state = manager.read_state(MODES_MODE_NAME)
    if not state:
        return False
    return (
        state.metadata.get("active") is True
        and state.current_phase not in ("complete", "failed")
    )


def read_pipeline_state(cwd: str = ".") -> PipelineModeStateExtension | None:
    """读取 pipeline 扩展状态（对标 readPipelineState）"""
    manager = ModeStateManager(cwd)
    state = manager.read_state(MODES_MODE_NAME)
    if not state:
        return None
    return PipelineModeStateExtension.from_mode_metadata(state.metadata)


def cancel_pipeline(cwd: str = ".") -> bool:
    """取消 pipeline（对标 cancelPipeline）"""
    return ModeStateManager(cwd).cancel_mode(MODES_MODE_NAME, "user-requested")


# ========== StageAdapter（支持 PEP 544 协议） ==========

class StageAdapter:
    """
    阶段适配器基类：将现有函数式 stage 适配为 PipelineStage 接口

    使用示例：
        def my_run_func(ctx: StageContext) -> StageResult:
            return StageResult(status="completed", artifacts={}, duration_ms=100)

        stage = StageAdapter(
            name="my-stage",
            run_func=my_run_func,
            can_skip=lambda ctx: ctx.artifacts.get("skip", False),
        )
    """

    def __init__(
        self,
        name: str,
        run_func: Callable[..., Any],
        *,
        can_skip_func: Callable[[StageContext], bool] | None = None,
        can_skip: Callable[[StageContext], bool] | None = None,
    ):
        self.name = name
        self._run_func = run_func
        # 同时支持 can_skip_func 和 can_skip 两个参数名
        self._can_skip_func = can_skip_func if can_skip_func is not None else (can_skip or (lambda ctx: False))

    async def run(self, ctx: StageContext) -> StageResult:
        """执行阶段（自动处理同步/异步函数）"""
        import asyncio
        import time

        start_ms = int(time.time() * 1000)
        try:
            if asyncio.iscoroutinefunction(self._run_func):
                result = await self._run_func(ctx)
            else:
                result = self._run_func(ctx)

            if not isinstance(result, StageResult):
                raise TypeError(f"Stage run() must return StageResult, got: {type(result)}")

            return result
        except Exception as e:
            logger.exception(f"Stage [{self.name}] 执行异常")
            duration = int(time.time() * 1000) - start_ms
            return StageResult(
                status=StageStatus.FAILED,
                artifacts={},
                duration_ms=duration,
                error=str(e),
            )

    def can_skip(self, ctx: StageContext) -> bool:
        """判断是否可跳过"""
        try:
            return bool(self._can_skip_func(ctx))
        except Exception as e:
            logger.warning(f"Stage [{self.name}] can_skip 判断异常: {e}")
            return False


# ========== 导出 ==========

__all__ = [
    "PipelineConfig",
    "PipelineModeStateExtension",
    "PipelineOrchestrator",
    "PipelineResult",
    "PipelineStage",
    "PipelineState",  # 向后兼容适配器
    "StageAdapter",
    "StageStatus",
    "can_resume_pipeline",
    "cancel_pipeline",
    "create_autopilot_pipeline_config",
    "create_pipeline",
    "read_pipeline_state",
]
