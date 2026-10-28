"""Eval 基线：保存、加载、回归比对"""

from __future__ import annotations

import json

from pathlib import Path
from typing import Any

from .models import EvalReport


def save_baseline(report: EvalReport, path: str | Path) -> Path:
    """把当前报告写为基线"""
    baseline_path = Path(path)
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return baseline_path


def load_baseline(path: str | Path) -> dict[str, Any] | None:
    """读取基线；不存在或损坏返回 None（首次运行场景）"""
    baseline_path = Path(path)
    if not baseline_path.is_file():
        return None
    try:
        return json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def compare_with_baseline(
    report: EvalReport,
    baseline: dict[str, Any] | None,
    *,
    tolerance: float = 0.0,
) -> list[str]:
    """对比基线，返回回归描述列表（空列表 = 无回归）

    判定:
        - pass_rate 下降超过 tolerance → 回归
        - 基线通过但本次失败的用例（逐条列出）
        - 新增用例不计为回归
    """
    if not baseline:
        return []

    problems: list[str] = []
    baseline_rate = float(baseline.get("pass_rate") or 0.0)
    if report.pass_rate < baseline_rate - tolerance:
        problems.append(
            f"pass_rate 回归: {report.pass_rate * 100:.1f}% < 基线 {baseline_rate * 100:.1f}%"
        )

    baseline_passed = {
        o.get("case_id")
        for o in (baseline.get("outcomes") or [])
        if o.get("passed")
    }
    for outcome in report.outcomes:
        if not outcome.passed and outcome.case_id in baseline_passed:
            problems.append(f"用例由通过转为失败: {outcome.case_id} — {outcome.detail}")

    return problems
