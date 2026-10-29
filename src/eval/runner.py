"""Eval 运行器 — replay（零成本）/ live（需显式双闸）两种模式"""

from __future__ import annotations

import json
import os
import time

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .metrics import evaluate_case_status
from .models import EvalCase, EvalOutcome, EvalReport

PAID_ENV_GATE = "CLAWD_EVAL_ALLOW_PAID"

AgentFn = Callable[[EvalCase], dict[str, Any]]


class EvalConfigError(RuntimeError):
    """数据集非法或模式不被允许"""


class CaseNotRun(RuntimeError):
    """用例无法执行（不是失败，是"没测"）→ 记 unknown，不污染通过率"""


def load_dataset(path: str | Path) -> list[EvalCase]:
    """加载数据集 JSON

    格式:
        {"version": 1, "cases": [{"id": ..., "input": ..., "expect": {...}, "recorded": {...}}]}
    """
    dataset_path = Path(path)
    if not dataset_path.is_file():
        raise EvalConfigError(f"数据集不存在: {dataset_path}")

    try:
        payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise EvalConfigError(f"数据集读取失败: {e}") from e

    raw_cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(raw_cases, list) or not raw_cases:
        raise EvalConfigError("数据集必须包含非空 cases 数组")

    cases: list[EvalCase] = []
    errors: list[str] = []
    for idx, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            errors.append(f"cases[{idx}] 必须是对象")
            continue
        case = EvalCase(
            case_id=str(raw.get("id") or f"case-{idx}"),
            input=str(raw.get("input") or ""),
            expect=raw.get("expect") or {},
            recorded=raw.get("recorded"),
            tags=[str(t) for t in (raw.get("tags") or [])],
        )
        errors.extend(case.validate())
        cases.append(case)

    if errors:
        raise EvalConfigError("数据集校验失败:\n" + "\n".join(f"  - {e}" for e in errors))
    return cases


def _replay_agent(case: EvalCase) -> dict[str, Any]:
    if not case.recorded:
        raise CaseNotRun(
            f"用例 {case.case_id} 缺少 recorded 字段，replay 模式无法执行"
            "（如需真实调用请用 live 模式并显式授权）"
        )
    return case.recorded


def _live_allowed() -> bool:
    return os.environ.get(PAID_ENV_GATE, "").lower() in ("1", "true", "yes")


def run_dataset(
    cases: list[EvalCase],
    agent_fn: AgentFn | None = None,
    *,
    live: bool = False,
    dataset_name: str = "",
) -> EvalReport:
    """执行数据集

    Args:
        cases: 用例列表
        agent_fn: 执行函数（live 模式必须提供；replay 模式默认为录制回放）
        live: 是否真实调用 agent。需同时设置 CLAWD_EVAL_ALLOW_PAID=1
        dataset_name: 数据集标识（写入报告）

    Raises:
        EvalConfigError: live 模式未授权 / 缺少 agent_fn
    """
    if live:
        if not _live_allowed():
            raise EvalConfigError(
                f"live 模式会发起真实 LLM 调用（可能产生费用）。"
                f"请显式设置 {PAID_ENV_GATE}=1 后再试。"
            )
        if agent_fn is None:
            raise EvalConfigError("live 模式必须提供 agent_fn")
        runner: AgentFn = agent_fn
        mode = "live"
    else:
        runner = agent_fn or _replay_agent
        mode = "replay"

    report = EvalReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        mode=mode,
        dataset=dataset_name,
    )

    for case in cases:
        started = time.perf_counter()
        unknown = False
        try:
            result = runner(case)
            status, detail = evaluate_case_status(case, result)
            passed = status == "pass"
            unknown = status == "unknown"
            if unknown:
                detail = f"未判定: {detail}"
        except CaseNotRun as e:
            passed, detail, unknown = False, f"未执行: {e}", True
        except Exception as e:  # 执行异常是真实失败，不中断整轮
            passed, detail, unknown = False, f"执行异常: {type(e).__name__}: {e}", False
        elapsed_ms = (time.perf_counter() - started) * 1000
        report.outcomes.append(
            EvalOutcome(
                case_id=case.case_id,
                passed=passed,
                detail=detail,
                elapsed_ms=elapsed_ms,
                tags=case.tags,
                unknown=unknown,
            )
        )

    return report
