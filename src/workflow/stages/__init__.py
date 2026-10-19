"""Pipeline 阶段注册中心（平行实现，非生产默认路径）

导出所有内置阶段和工厂函数。

⚠️ 生产 pipeline 使用 `src/workflow/pipeline.py` 内嵌的阶段工厂
（`create_ralplan_stage` / `create_team_exec_stage` / ...）。
本包是历史上的平行实现，保留用于兼容与实验；**新增阶段请加到
`pipeline.py`**，避免继续扩大两套实现的差异。
"""

from .precontext_intake_stage import PreContextIntakeStage, create_precontext_intake_stage
from .ralph_verify_stage import RalphVerifyStage, create_ralph_verify_stage
from .ralplan_stage import RalplanStage, create_ralplan_stage
from .team_exec_stage import TeamExecStage, create_team_exec_stage

__all__ = [
    "PreContextIntakeStage",
    "RalphVerifyStage",
    "RalplanStage",
    "TeamExecStage",
    "create_precontext_intake_stage",
    "create_ralph_verify_stage",
    "create_ralplan_stage",
    "create_team_exec_stage",
]
