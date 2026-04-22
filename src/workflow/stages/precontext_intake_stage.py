"""Pre-Context Intake Stage — 前置上下文摄入阶段

从 oh-my-codex-main 汲取的概念阶段：
- 在 pipeline 开始时收集上下文数据
- 扫描 codebase 提取语义信息
- 为后续阶段提供预备工件
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.workflow.pipeline_stage import PipelineStage, StageContext, StageResult

logger = logging.getLogger(__name__)


@dataclass
class PreContextIntakeConfig:
    """前置上下文摄入配置"""
    scan_depth: int = 1
    max_files: int = 100
    include_tests: bool = False


@dataclass
class PreContextDescriptor:
    """前置上下文描述符"""
    codebase_summary: str
    key_files: list[str] = field(default_factory=list)
    important_files: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class PreContextIntakeStage(PipelineStage):
    """前置上下文摄入阶段

    扫描代码库建立上下文，为 RALPLAN 阶段提供输入。
    """

    def __init__(
        self,
        config: PreContextIntakeConfig | None = None,
    ) -> None:
        self.config = config or PreContextIntakeConfig()

    @property
    def name(self) -> str:
        return "precontext-intake"

    async def run(self, ctx: StageContext) -> StageResult:
        """执行前置上下文摄入"""
        logger.info("[PreContextIntake] Scanning codebase for context")

        # 简化的实现：返回空描述符
        # 实际应该扫描文件系统、构建 codebase 摘要
        descriptor = PreContextDescriptor(
            codebase_summary="Codebase scan placeholder",
            key_files=[],
            metadata={"scan_depth": self.config.scan_depth},
        )

        return StageResult.completed(
            artifacts={"precontext": descriptor.__dict__},
            duration_ms=0,
        )

    def can_skip(self, ctx: StageContext) -> bool:
        """如果已有上下文工件则可跳过"""
        artifacts = ctx.artifacts or {}
        return "precontext" in artifacts or "codebase_summary" in artifacts


def create_precontext_intake_stage(
    scan_depth: int = 1,
    max_files: int = 100,
) -> PipelineStage:
    """创建前置上下文摄入阶段实例"""
    config = PreContextIntakeConfig(
        scan_depth=scan_depth,
        max_files=max_files,
    )
    return PreContextIntakeStage(config)


__all__ = [
    "PreContextDescriptor",
    "PreContextIntakeConfig",
    "PreContextIntakeStage",
    "create_precontext_intake_stage",
]
