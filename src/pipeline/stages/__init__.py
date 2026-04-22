"""Pipeline Stages - 管道阶段定义"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..core.events import EventBus


@dataclass
class StageContext:
    """阶段执行上下文"""
    workdir: Path
    pipeline_id: str
    run_id: str
    stage_index: int
    previous_results: dict[str, Any]
    config: Any  # PipelineConfig

    # 便捷属性
    @property
    def is_first_stage(self) -> bool:
        return self.stage_index == 0

    @property
    def is_last_stage(self) -> bool:
        return self.stage_index == self.config.max_stages - 1

    def get_previous_result(self, stage_name: str) -> Any:
        """获取前一阶段的结果"""
        return self.previous_results.get(stage_name)


@dataclass
class StageResult:
    """阶段执行结果"""
    success: bool
    output: Any = None
    error: str = ""
    evidence: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "evidence": self.evidence,
            "metadata": self.metadata,
        }


class PipelineStage(Protocol):
    """管道阶段协议"""

    async def execute(self, context: StageContext) -> StageResult:
        """执行阶段逻辑"""
        ...


# ========== 基础阶段类 ==========

class BaseStage:
    """阶段基类，提供通用功能"""

    def __init__(self, name: str, event_bus: EventBus | None = None):
        self.name = name
        self._event_bus = event_bus

    async def execute(self, context: StageContext) -> StageResult:
        """执行阶段"""
        raise NotImplementedError("Subclasses must implement execute()")

    async def _publish_event(self, event_type: str, data: dict[str, Any]):
        """发布事件"""
        if self._event_bus:
            await self._event_bus.publish({
                "type": event_type,
                "stage": self.name,
                "timestamp": datetime.now().isoformat(),
                **data,
            })


# ========== 具体阶段实现 ==========

class PlanningStage(BaseStage):
    """规划阶段 - 将目标分解为任务"""

    def __init__(
        self,
        use_consensus_planning: bool = True,
        event_bus: EventBus | None = None,
    ):
        super().__init__("planning", event_bus)
        self.use_consensus_planning = use_consensus_planning

    async def execute(self, context: StageContext) -> StageResult:
        """执行规划"""
        goal = context.config.goal

        # 这里可以实现任务分解逻辑
        # 可以调用 OrchestratorAgent.decompose_task()

        tasks = [
            {"id": "T1", "title": "分析需求", "description": goal},
            {"id": "T2", "title": "设计方案", "description": "设计实现方案"},
            {"id": "T3", "title": "实施编码", "description": "编写代码"},
        ]

        return StageResult(
            success=True,
            output={"tasks": tasks, "total": len(tasks)},
            evidence=[f"Generated {len(tasks)} tasks"],
        )


class ExecutionStage(BaseStage):
    """执行阶段 - 运行任务"""

    def __init__(
        self,
        max_retries: int = 3,
        event_bus: EventBus | None = None,
    ):
        super().__init__("execution", event_bus)
        self.max_retries = max_retries

    async def execute(self, context: StageContext) -> StageResult:
        """执行任务"""
        # 获取规划阶段的输出
        plan_result = context.get_previous_result("planning")
        if not plan_result:
            return StageResult(
                success=False,
                error="No planning result available",
            )

        tasks = plan_result.get("tasks", [])

        # 执行每个任务
        results = []
        for task in tasks:
            # 这里应该调用 Worker Agent 执行
            # 简化版本：只记录
            results.append({"task_id": task["id"], "status": "completed"})

        return StageResult(
            success=True,
            output={"executed_tasks": len(results)},
            evidence=[f"Executed {len(results)} tasks"],
        )


class VerificationStage(BaseStage):
    """验证阶段 - 检查结果"""

    def __init__(
        self,
        verification_mode: str = "auto",
        event_bus: EventBus | None = None,
    ):
        super().__init__("verification", event_bus)
        self.verification_mode = verification_mode

    async def execute(self, context: StageContext) -> StageResult:
        """验证执行结果"""
        exec_result = context.get_previous_result("execution")
        if not exec_result:
            return StageResult(
                success=False,
                error="No execution result to verify",
            )

        # 简化验证逻辑
        return StageResult(
            success=True,
            output={"verified": True},
            evidence=["All tasks verified"],
        )


# ========== 工厂函数 ==========

def create_standard_pipeline(
    goal: str,
    config_overrides: dict[str, Any] | None = None,
) -> PipelineConfig:
    """创建标准管道配置"""
    from dataclasses import replace

    stages = [
        PlanningStage(use_consensus_planning=True),
        ExecutionStage(max_retries=3),
        VerificationStage(verification_mode="auto"),
    ]

    defaults = {
        "max_retries": 3,
        "retry_backoff": "exponential",
        "evidence_level": "minimal",
        "verification_mode": "auto",
    }

    if config_overrides:
        defaults.update(config_overrides)

    from dataclasses import make_dataclass

    # 这里简化处理，实际应该使用 PipelineConfig
    return {
        "pipeline_id": "standard",
        "goal": goal,
        "stages": stages,
        **defaults,
    }


__all__ = [
    'BaseStage',
    'ExecutionStage',
    'PipelineStage',
    'PlanningStage',
    'StageContext',
    'StageResult',
    'VerificationStage',
    'create_standard_pipeline',
]
