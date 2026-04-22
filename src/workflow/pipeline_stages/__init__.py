"""
Pipeline stages for workflow orchestration.

This module provides stage adapters that wrap various runtime components
into PipelineStage format for the orchestrator.

整合 oh-my-codex 的 Pipeline 设计：
- 状态持久化（PipelineState）
- 条件跳过（canSkip）
- 恢复支持（PipelineState.can_resume）
"""

# 从 orchestrator 导入核心类型（避免循环导入）
from ..pipeline_orchestrator import (
    PipelineConfig,
    PipelineOrchestrator,
    PipelineResult,
    PipelineStage,
    PipelineState,
    StageAdapter,
    StageStatus,
    create_pipeline,
)
from .ralph_verify import (
    RalphVerifyDescriptor,
    RalphVerifyStageOptions,
    StageContext,
    StageResult,
    build_ralph_instruction,
    create_ralph_verify_stage,
)
from .team_exec import (
    TeamExecDescriptor,
    TeamExecStageOptions,
    build_team_instruction,
    create_team_exec_stage,
)

__all__ = [
    # Core orchestrator
    "PipelineConfig",
    "PipelineOrchestrator",
    "PipelineResult",
    "PipelineStage",
    "PipelineState",
    # Ralph verify stage
    "RalphVerifyDescriptor",
    "RalphVerifyStageOptions",
    "StageAdapter",
    # Common types
    "StageContext",
    "StageResult",
    "StageStatus",
    # Team exec stage
    "TeamExecDescriptor",
    "TeamExecStageOptions",
    "build_ralph_instruction",
    "build_team_instruction",
    "create_pipeline",
    "create_ralph_verify_stage",
    "create_team_exec_stage",
]
