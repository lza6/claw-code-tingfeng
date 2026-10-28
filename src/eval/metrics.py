"""确定性评测断言（离线可判定，不依赖 LLM 判分）"""

from __future__ import annotations

import re

from typing import Any

from .models import EvalCase


def _check_equals(expected: str, output: str) -> tuple[bool, str]:
    if output.strip() == str(expected).strip():
        return True, "equals 匹配"
    return False, f"equals 不匹配: 期望 {str(expected)[:80]!r} 实际 {output[:80]!r}"


def _check_contains(needles: Any, output: str) -> tuple[bool, str]:
    if not isinstance(needles, list):
        return False, "contains 必须是列表"
    missing = [n for n in needles if str(n) not in output]
    if not missing:
        return True, f"contains 命中 {len(needles)} 项"
    return False, f"contains 缺失 {missing}"


def _check_not_contains(needles: Any, output: str) -> tuple[bool, str]:
    if not isinstance(needles, list):
        return False, "not_contains 必须是列表"
    present = [n for n in needles if str(n) in output]
    if not present:
        return True, "not_contains 通过"
    return False, f"not_contains 命中禁止项 {present}"


def _check_regex(pattern: str, output: str) -> tuple[bool, str]:
    try:
        matched = re.search(str(pattern), output) is not None
    except re.error as e:
        return False, f"regex 非法: {e}"
    return (True, "regex 匹配") if matched else (False, f"regex 不匹配: {pattern!r}")


def _check_tool_sequence(expected: Any, tools: list[str]) -> tuple[bool, str]:
    if not isinstance(expected, list):
        return False, "tool_sequence 必须是列表"
    if [str(t) for t in expected] == [str(t) for t in tools]:
        return True, f"tool_sequence 一致（{len(tools)} 次调用）"
    return False, f"tool_sequence 不一致: 期望 {expected} 实际 {tools}"


def evaluate_case(case: EvalCase, result: dict[str, Any]) -> tuple[bool, str]:
    """按 case.expect 判定一次执行结果

    Args:
        case: 评测用例
        result: {"output": str, "tools": list[str]}

    Returns:
        (是否通过, 说明)
    """
    output = str(result.get("output") or "")
    tools = [str(t) for t in (result.get("tools") or [])]

    checks = {
        "equals": lambda v: _check_equals(v, output),
        "contains": lambda v: _check_contains(v, output),
        "not_contains": lambda v: _check_not_contains(v, output),
        "regex": lambda v: _check_regex(v, output),
        "tool_sequence": lambda v: _check_tool_sequence(v, tools),
    }

    details: list[str] = []
    all_passed = True
    for key, expected in case.expect.items():
        check = checks.get(key)
        if check is None:
            details.append(f"未知断言 {key}")
            all_passed = False
            continue
        ok, detail = check(expected)
        details.append(detail)
        if not ok:
            all_passed = False

    return all_passed, "; ".join(details)
