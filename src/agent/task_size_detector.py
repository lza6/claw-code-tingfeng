"""
Task Size Detector - 任务规模检测

从 oh-my-codex-main/src/hooks/task-size-detector.ts 转换而来。
检测用户任务的规模（small/medium/large）。
"""

import enum
import enum
import re
from dataclasses import dataclass
from typing import Optional


class TaskSize(str, enum.Enum):
    """任务规模"""
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


@dataclass
class TaskSizeResult:
    """任务规模检测结果"""
    size: str
    reason: str
    word_count: int
    has_escape_hatch: bool
    escape_prefix_used: Optional[str] = None


@dataclass
class TaskSizeThresholds:
    """任务规模阈值"""
    small_word_limit: int = 50
    large_word_limit: int = 200


# 逃逸前缀
ESCAPE_HATCH_PREFIXES = [
    "quick:",
    "simple:",
    "tiny:",
    "minor:",
    "small:",
    "just:",
    "only:",
]

# 小任务信号
SMALL_TASK_SIGNALS = [
    re.compile(r"\btypo\b", re.I),
    re.compile(r"\bspelling\b", re.I),
    re.compile(r"\brename\s+\w+\s+to\b", re.I),
    re.compile(r"\bone[\s-]liner?\b", re.I),
    re.compile(r"\bone[\s-]line\s+fix\b", re.I),
    re.compile(r"\bsingle\s+file\b", re.I),
    re.compile(r"\bin\s+this\s+file\b", re.I),
    re.compile(r"\bthis\s+function\b", re.I),
    re.compile(r"\bthis\s+line\b", re.I),
    re.compile(r"\bminor\s+(fix|change|update|tweak)\b", re.I),
    re.compile(r"\bfix\s+(a\s+)?typo\b", re.I),
    re.compile(r"\badd\s+a?\s*comment\b", re.I),
    re.compile(r"\bwhitespace\b", re.I),
    re.compile(r"\bindentation\b", re.I),
    re.compile(r"\bformat(ting)?\s+(this|the)\b", re.I),
    re.compile(r"\bquick\s+fix\b", re.I),
    re.compile(r"\bsmall\s+(fix|change|tweak|update)\b", re.I),
    re.compile(r"\bupdate\s+(the\s+)?version\b", re.I),
    re.compile(r"\bbump\s+version\b", re.I),
]

# 大任务信号
LARGE_TASK_SIGNALS = [
    re.compile(r"\barchitect(ure|ural)?\b", re.I),
    re.compile(r"\brefactor\b", re.I),
    re.compile(r"\bredesign\b", re.I),
    re.compile(r"\bfrom\s+scratch\b", re.I),
    re.compile(r"\bcross[\s-]cutting\b", re.I),
    re.compile(r"\bentire\s+(codebase|project|application|app|system)\b", re.I),
    re.compile(r"\ball\s+(files|modules|components)\b", re.I),
    re.compile(r"\bmultiple\s+files\b", re.I),
    re.compile(r"\bacross\s+(the\s+)?(codebase|project|files|modules)\b", re.I),
    re.compile(r"\bsystem[\s-]wide\b", re.I),
    re.compile(r"\bmigrat(e|ion)\b", re.I),
    re.compile(r"\bfull[\s-]stack\b", re.I),
    re.compile(r"\bend[\s-]to[\s-]end\b", re.I),
    re.compile(r"\boverhaul\b", re.I),
    re.compile(r"\bcomprehensive\b", re.I),
    re.compile(r"\bextensive\b", re.I),
    re.compile(r"\bimplement\s+(a\s+)?(new\s+)?system\b", re.I),
    re.compile(r"\bbuild\s+(a\s+)?(complete|full|new)\b", re.I),
]


def count_words(text: str) -> int:
    """统计文本字数"""
    return len(text.strip().split())


def detect_escape_hatch(text: str) -> Optional[str]:
    """检测逃逸前缀"""
    trimmed = text.strip().lower()
    for prefix in ESCAPE_HATCH_PREFIXES:
        if trimmed.startswith(prefix):
            return prefix
    return None


def has_small_task_signals(text: str) -> bool:
    """检查是否有小任务信号"""
    return any(pattern.search(text) for pattern in SMALL_TASK_SIGNALS)


def has_large_task_signals(text: str) -> bool:
    """检查是否有大任务信号"""
    return any(pattern.search(text) for pattern in LARGE_TASK_SIGNALS)


def classify_task_size(
    text: str,
    thresholds: Optional[TaskSizeThresholds] = None,
) -> TaskSizeResult:
    """分类任务规模

    分类规则（优先级顺序）:
    1. 逃逸前缀 (quick:, simple: 等) → 总是 small
    2. 大任务信号 (architecture, refactor, entire codebase) → large
    3. 提示词 > largeWordLimit → large
    4. 小任务信号 AND 提示词 < largeWordLimit → small
    5. 提示词 < smallWordLimit → small
    6. 其他 → medium
    """
    thresholds = thresholds or TaskSizeThresholds()
    word_count = count_words(text)
    escape_prefix = detect_escape_hatch(text)

    # 规则1: 显式逃逸前缀 → 总是 small
    if escape_prefix:
        return TaskSizeResult(
            size=TaskSize.SMALL.value,
            reason=f'Escape hatch prefix detected: "{escape_prefix}"',
            word_count=word_count,
            has_escape_hatch=True,
            escape_prefix_used=escape_prefix,
        )

    has_large = has_large_task_signals(text)
    has_small = has_small_task_signals(text)

    # 规则2: 大任务信号 → 总是 large
    if has_large:
        return TaskSizeResult(
            size=TaskSize.LARGE.value,
            reason="Large task signals detected (architecture/refactor/cross-cutting scope)",
            word_count=word_count,
            has_escape_hatch=False,
        )

    # 规则3: 长提示词 → large
    if word_count > thresholds.large_word_limit:
        return TaskSizeResult(
            size=TaskSize.LARGE.value,
            reason=f"Prompt length ({word_count} words) exceeds large task threshold ({thresholds.large_word_limit})",
            word_count=word_count,
            has_escape_hatch=False,
        )

    # 规则4: 小任务信号 + 在限制内 → small
    if has_small and not has_large:
        return TaskSizeResult(
            size=TaskSize.SMALL.value,
            reason="Small task signals detected (single file / minor change)",
            word_count=word_count,
            has_escape_hatch=False,
        )

    # 规则5: 短提示词 → small
    if word_count <= thresholds.small_word_limit:
        return TaskSizeResult(
            size=TaskSize.SMALL.value,
            reason=f"Prompt length ({word_count} words) is within small task threshold ({thresholds.small_word_limit})",
            word_count=word_count,
            has_escape_hatch=False,
        )

    # 规则6: 默认 → medium
    return TaskSizeResult(
        size=TaskSize.MEDIUM.value,
        reason=f"Prompt length ({word_count} words) is in medium range",
        word_count=word_count,
        has_escape_hatch=False,
    )


# 重载模式关键词
HEAVY_MODE_KEYWORDS = {
    "ralph",
    "autopilot",
    "team",
    "ultrawork",
    "swarm",
    "ralplan",
    "ccg",
}


def is_heavy_mode(keyword_type: str) -> bool:
    """检查是否是重载模式"""
    return keyword_type in HEAVY_MODE_KEYWORDS


# ===== 导出 =====
__all__ = [
    "TaskSize",
    "TaskSizeResult",
    "TaskSizeThresholds",
    "count_words",
    "detect_escape_hatch",
    "has_small_task_signals",
    "has_large_task_signals",
    "classify_task_size",
    "HEAVY_MODE_KEYWORDS",
    "is_heavy_mode",
]
