"""Eval harness — agent 行为的可重复评测与回归（W8 能力缺口）

设计要点:
- **默认零成本**：replay 模式直接使用数据集里录制的输出，不调用任何 LLM；
  真实调用必须显式 `--live` + 环境变量 `CLAWD_EVAL_ALLOW_PAID=1` 双闸。
- **确定性断言**：exact/contains/regex/tool_sequence 四类，全部可在离线下判定。
- **基线比对**：与基线 JSON 对比，pass_rate 下降即回归。
- **轨迹回放**（X-3）：`src/eval/trajectory.py` 录制 (plan→action→observation→verify)，
  回放时固定 observation，只断言工具序列与决策分支不退化；同样零 LLM。
"""

from .baseline import compare_with_baseline, load_baseline, load_baseline_strict, save_baseline
from .metrics import evaluate_case, evaluate_case_status
from .models import EvalCase, EvalOutcome, EvalReport
from .runner import CaseNotRun, load_dataset, run_dataset
from .trajectory import (
    SCHEMA_VERSION,
    ReplayResult,
    Step,
    Trajectory,
    TrajectoryFormatError,
    load_trajectory,
    record_from_session,
    replay,
    save_trajectory,
    trajectory_from_dict,
)

__all__ = [
    "EvalCase",
    "EvalOutcome",
    "EvalReport",
    "CaseNotRun",
    "ReplayResult",
    "SCHEMA_VERSION",
    "Step",
    "Trajectory",
    "TrajectoryFormatError",
    "compare_with_baseline",
    "evaluate_case",
    "evaluate_case_status",
    "load_baseline",
    "load_baseline_strict",
    "load_dataset",
    "load_trajectory",
    "record_from_session",
    "replay",
    "run_dataset",
    "save_baseline",
    "save_trajectory",
    "trajectory_from_dict",
]
