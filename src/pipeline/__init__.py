"""Pipeline - 模块化工作流管道系统

借鉴 oh-my-codex 的声明式管道架构。
提供可插拔、可验证、可回滚的阶段化执行框架。
"""

from .orchestrator import PipelineOrchestrator, run_pipeline
from .stages import (
    ExecutionStage,
    PipelineStage,
    PlanningStage,
    StageContext,
    StageResult,
    VerificationStage,
)

__all__ = [
    'ExecutionStage',
    'PipelineOrchestrator',
    'PipelineStage',
    'PlanningStage',
    'StageContext',
    'StageResult',
    'VerificationStage',
    'run_pipeline',
]
