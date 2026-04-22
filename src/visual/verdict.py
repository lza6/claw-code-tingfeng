"""
Visual Verdict - 可视化判决

从 oh-my-codex-main/src/visual/verdict.ts 转换而来。
提供视觉验证和判决功能。
"""

from dataclasses import dataclass
from enum import Enum


class VisualVerdictStatus(str, Enum):
    """视觉判决状态"""
    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    SKIP = "skip"


VISUAL_NEXT_ACTIONS_LIMIT = 5
VISUAL_VERDICT_STATUSES = ["pass", "fail", "partial", "skip"]


@dataclass
class VisualVerdict:
    """视觉判决"""
    score: float
    verdict: VisualVerdictStatus
    category_match: bool
    differences: list[str]
    suggestions: list[str]
    reasoning: str


@dataclass
class VisualLoopFeedback:
    """视觉循环反馈"""
    score: float
    verdict: VisualVerdictStatus
    category_match: bool
    differences: list[str]
    suggestions: list[str]
    reasoning: str
    threshold: float
    passes_threshold: bool
    next_actions: list[str]


def parse_visual_verdict_status(value: str) -> VisualVerdictStatus:
    """解析视觉判决状态"""
    normalized = value.strip().lower()
    for status in VisualVerdictStatus:
        if status.value == normalized:
            return status
    raise ValueError(f"visual_verdict.verdict must be one of: {VISUAL_VERDICT_STATUSES}")


def validate_verdict_data(data: dict) -> VisualVerdict:
    """验证判决数据"""
    score = data.get("score")
    if not isinstance(score, (int, float)):
        raise ValueError("visual_verdict.score must be a number")

    verdict = parse_visual_verdict_status(data.get("verdict", ""))

    category_match = data.get("category_match", False)
    if not isinstance(category_match, bool):
        raise ValueError("visual_verdict.category_match must be a boolean")

    differences = _as_trimmed_string_array(data.get("differences", []), "differences")
    suggestions = _as_trimmed_string_array(data.get("suggestions", []), "suggestions")

    reasoning = data.get("reasoning", "")
    if not isinstance(reasoning, str):
        raise ValueError("visual_verdict.reasoning must be a string")

    return VisualVerdict(
        score=score,
        verdict=verdict,
        category_match=category_match,
        differences=differences,
        suggestions=suggestions,
        reasoning=reasoning,
    )


def _as_trimmed_string_array(value: any, field: str) -> list[str]:
    """转换为修剪的字符串数组"""
    if not isinstance(value, list):
        raise ValueError(f"visual_verdict.{field} must be an array")

    result = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"visual_verdict.{field} must contain strings")
        trimmed = item.strip()
        if trimmed:
            result.append(trimmed)

    return result


def create_visual_loop_feedback(
    verdict: VisualVerdict,
    threshold: float,
) -> VisualLoopFeedback:
    """创建视觉循环反馈"""
    passes_threshold = verdict.score >= threshold

    next_actions = []
    if not passes_threshold and verdict.suggestions:
        next_actions = verdict.suggestions[:VISUAL_NEXT_ACTIONS_LIMIT]

    return VisualLoopFeedback(
        score=verdict.score,
        verdict=verdict.verdict,
        category_match=verdict.category_match,
        differences=verdict.differences,
        suggestions=verdict.suggestions,
        reasoning=verdict.reasoning,
        threshold=threshold,
        passes_threshold=passes_threshold,
        next_actions=next_actions,
    )


# ===== 导出 =====
__all__ = [
    "VISUAL_NEXT_ACTIONS_LIMIT",
    "VISUAL_VERDICT_STATUSES",
    "VisualLoopFeedback",
    "VisualVerdict",
    "VisualVerdictStatus",
    "create_visual_loop_feedback",
    "parse_visual_verdict_status",
    "validate_verdict_data",
]
