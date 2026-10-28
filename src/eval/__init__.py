"""Eval harness — agent 行为的可重复评测与回归（W8 能力缺口）

设计要点:
- **默认零成本**：replay 模式直接使用数据集里录制的输出，不调用任何 LLM；
  真实调用必须显式 `--live` + 环境变量 `CLAWD_EVAL_ALLOW_PAID=1` 双闸。
- **确定性断言**：exact/contains/regex/tool_sequence 四类，全部可在离线下判定。
- **基线比对**：与基线 JSON 对比，pass_rate 下降即回归。
"""

from .baseline import compare_with_baseline, load_baseline, save_baseline
from .metrics import evaluate_case
from .models import EvalCase, EvalOutcome, EvalReport
from .runner import load_dataset, run_dataset

__all__ = [
    "EvalCase",
    "EvalOutcome",
    "EvalReport",
    "compare_with_baseline",
    "evaluate_case",
    "load_baseline",
    "load_dataset",
    "run_dataset",
    "save_baseline",
]
