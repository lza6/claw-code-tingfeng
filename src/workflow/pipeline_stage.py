"""
Pipeline Stage 接口定义

从 oh-my-codex-main 汲取的管道阶段接口。
统一阶段接口，支持: RALPLAN -> team-exec -> ralph-verify 序列。

Stage 上下文: 每个阶段接收包含任务描述和工件累积的上下文。
Stage 结果: 每个阶段执行后返回状态和生成的工件。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StageContext:
    """阶段上下文 - 传入每个管道阶段"""
    task: str  # 用户提供的原始任务描述
    artifacts: dict[str, Any] = field(default_factory=dict)  # 之前阶段累积的工件
    previous_stage_result: StageResult | None = None  # 前一阶段的结果
    cwd: str = ""  # 管道运行的工作目录
    session_id: str | None = None  # 可选的会话 ID

    def get_artifact(self, key: str, default: Any = None) -> Any:
        """获取工件"""
        return self.artifacts.get(key, default)

    def set_artifact(self, key: str, value: Any) -> None:
        """设置工件"""
        self.artifacts[key] = value


@dataclass
class StageResult:
    """阶段结果 - 每个阶段执行后返回"""
    status: str  # 'completed' | 'failed' | 'skipped'
    artifacts: dict[str, Any] = field(default_factory=dict)  # 本阶段生成的工件
    duration_ms: int = 0  # 阶段执行的 wall-clock 时间（毫秒）
    error: str | None = None  # 失败时的人类可读错误描述

    @staticmethod
    def completed(artifacts: dict[str, Any] = None, duration_ms: int = 0) -> StageResult:
        """创建完成状态的结果"""
        return StageResult(
            status='completed',
            artifacts=artifacts or {},
            duration_ms=duration_ms,
        )

    @staticmethod
    def failed(error: str, artifacts: dict[str, Any] = None) -> StageResult:
        """创建失败状态的结果"""
        return StageResult(
            status='failed',
            artifacts=artifacts or {},
            error=error,
        )

    @staticmethod
    def skipped(artifacts: dict[str, Any] = None) -> StageResult:
        """创建跳过状态的结果"""
        return StageResult(
            status='skipped',
            artifacts=artifacts or {},
        )


class PipelineStage(ABC):
    """管道阶段抽象基类

    实现具体执行后端（ralplan, team, ralph）的统一接口。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """阶段唯一名称 (如 'ralplan', 'team-exec', 'ralph-verify')"""
        pass

    @abstractmethod
    async def run(self, ctx: StageContext) -> StageResult:
        """执行阶段，必须返回 StageResult"""
        pass

    def can_skip(self, ctx: StageContext) -> bool:
        """可选谓词 - 返回 true 跳过此阶段"""
        return False


# ===== 内置阶段实现 =====
class TimingStage(PipelineStage):
    """装饰器阶段 - 添加时间测量"""

    def __init__(self, delegate: PipelineStage):
        self._delegate = delegate

    @property
    def name(self) -> str:
        return self._delegate.name

    async def run(self, ctx: StageContext) -> StageResult:
        start = time.time()
        result = await self._delegate.run(ctx)
        result.duration_ms = int((time.time() - start) * 1000)
        return result

    def can_skip(self, ctx: StageContext) -> bool:
        return self._delegate.can_skip(ctx)


# ===== 导出 =====
__all__ = [
    "PipelineStage",
    "StageContext",
    "StageResult",
    "TimingStage",
]
