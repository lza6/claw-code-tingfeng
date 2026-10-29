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
    """读取基线；不存在或损坏返回 None

    注意：None 表示"**没有基线可比**"，绝不等于"通过"。
    调用方必须区分这两种情况（CLI 曾把 None 当成"基线比对通过（无回归）"，
    指向一个不存在的路径也能 exit 0 —— 典型的假成功）。
    想拿到明确错误请用 `load_baseline_strict`。
    """
    baseline_path = Path(path)
    if not baseline_path.is_file():
        return None
    try:
        return json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_baseline_strict(path: str | Path) -> dict[str, Any]:
    """读取基线；不存在/损坏直接抛错（给 CLI 用，不允许静默降级）"""
    baseline_path = Path(path)
    if not baseline_path.is_file():
        raise FileNotFoundError(f"基线文件不存在: {baseline_path}")
    try:
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"基线文件无法解析: {baseline_path}: {e}") from e
    if not isinstance(payload, dict):
        raise ValueError(f"基线文件格式不对（应为对象）: {baseline_path}")
    return payload


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

    baseline_unknown = int(baseline.get("unknown") or 0)
    if report.unknown > baseline_unknown:
        problems.append(
            f"未判定用例增加: {report.unknown} > 基线 {baseline_unknown}"
            "（未判定不是失败，但也不代表通过）"
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
