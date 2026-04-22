"""Pipeline 类型定义 - 可配置阶段式执行管道的核心接口"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

# ============================================================================
# 阶段状态枚举
# ============================================================================

class StageStatus(Enum):
    """阶段执行状态"""
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class StageContext:
    """阶段执行上下文
    
    传递给每个阶段的执行上下文，包含任务信息、已产生的 artifacts
    以及前一阶段的结果。
    """
    task: str
    artifacts: dict[str, Any] = field(default_factory=dict)
    previous_stage_result: StageResult | None = None
    cwd: Path = field(default_factory=Path.cwd)
    session_id: str | None = None
    pipeline_config: dict[str, Any] | None = None


# ============================================================================
# Pipeline 配置
# ============================================================================

@dataclass
class PipelineConfig:
    """Pipeline 配置
    
    用于配置和启动一个可配置阶段式执行管道。
    """
    name: str
    """Pipeline 名称（用于日志和状态文件）"""

    task: str
    """任务描述"""

    stages: list[PipelineStage]
    """有序的阶段列表"""

    cwd: str | None = None
    """工作目录（默认为当前目录）"""

    session_id: str | None = None
    """可选的会话 ID，用于状态隔离"""

    max_ralph_iterations: int | None = None
    """Ralph 验证阶段的最大迭代次数（默认 10）"""

    worker_count: int | None = None
    """Team 执行阶段的 Worker 数量（默认 2）"""

    agent_type: str | None = None
    """Team Worker 的 Agent 类型（默认 'executor'）"""

    on_stage_transition: Callable[[str, str], None] | None = None
    """阶段转换回调函数（从阶段名 -> 到阶段名），用于监控和集成"""


@dataclass
class StageResult:
    """阶段执行结果
    
    阶段执行完成后返回的结果，包含状态、产出物和执行统计。
    """
    status: StageStatus
    artifacts: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    error: str | None = None
    skipped_reason: str | None = None


# ============================================================================
# Pipeline 结果
# ============================================================================

@dataclass
class PipelineResult:
    """Pipeline 执行结果
    
    整个 pipeline 运行完成后的最终结果。
    """
    status: str
    """整体状态: 'completed' | 'failed' | 'cancelled'"""

    stage_results: Dict[str, StageResult]
    """各阶段结果映射（按阶段名索引）"""

    duration_ms: int
    """总耗时（毫秒）"""

    artifacts: Dict[str, Any]
    """所有阶段产出的合并 artifacts"""

    error: str | None = None
    """失败时的错误信息"""

    failed_stage: str | None = None
    """失败阶段的名称（如果失败）"""


# ============================================================================
# 阶段抽象基类
# ============================================================================

class PipelineStage:
    """管道阶段抽象基类
    
    所有 Pipeline 阶段必须继承此类并实现 run() 方法。
    可选择性地重写 can_skip() 以支持条件跳过优化。
    """

    @property
    def name(self) -> str:
        """阶段唯一标识符
        
        Returns:
            阶段的短名称，用于日志和状态记录
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement name property")

    async def run(self, ctx: StageContext) -> StageResult:
        """执行阶段逻辑
        
        Args:
            ctx: 执行上下文，包含任务、artifacts 和配置
            
        Returns:
            阶段执行结果
            
        Raises:
            Exception: 执行失败时应抛出异常或返回 FAILED 状态
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement run() method")

    def can_skip(self, ctx: StageContext) -> bool:
        """检查阶段是否可跳过（优化执行）
        
        如果阶段的前置条件已满足，可以跳过执行以提升效率。
        默认返回 False（不跳过）。
        
        Args:
            ctx: 执行上下文
            
        Returns:
            True 表示可以跳过，False 表示必须执行
        """
        return False

    def _skip(self, reason: str) -> StageResult:
        """生成跳过结果（内部辅助方法）
        
        Args:
            reason: 跳过原因描述
            
        Returns:
            SKIPPED 状态的 StageResult
        """
        return StageResult(
            status=StageStatus.SKIPPED,
            skipped_reason=reason,
        )


# ============================================================================
# 便捷基类
# ============================================================================

class ConditionalStage(PipelineStage):
    """条件阶段基类
    
    提供基于 artifacts 中特定键是否存在来自动判断跳过的便利类。
    子类只需设置 `skip_if_artifact_key` 即可。
    """

    skip_if_artifact_key: str | None = None

    def can_skip(self, ctx: StageContext) -> bool:
        if self.skip_if_artifact_key:
            return self.skip_if_artifact_key in ctx.artifacts
        return super().can_skip(ctx)


# ============================================================================
# 类型别名
# ============================================================================

StageHandler = Callable[[StageContext], Awaitable[StageResult]]
"""阶段处理器类型别名，用于动态注册阶段"""
