"""
Task Analyzer - 任务规模分析

从 oh-my-codex-main 汲取的任务规模检测引擎。
用于判断任务规模（small/medium/large/heavy）并决定相应的执行策略。
"""

import re
from dataclasses import dataclass


# ===== 任务规模 =====
class TaskSize:
    TRIVIAL = "trivial"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    HEAVY = "heavy"


# ===== 配置 =====
@dataclass
class TaskSizeThresholds:
    small_word_limit: int = 50
    large_word_limit: int = 200


DEFAULT_THRESHOLDS = TaskSizeThresholds(
    small_word_limit=50,
    large_word_limit=200,
)


# ===== 逃逸 hatch 前缀 =====
ESCAPE_HATCH_PREFIXES = [
    "quick:",
    "simple:",
    "tiny:",
    "minor:",
    "small:",
    "just:",
    "only:",
]


# ===== 小任务信号 =====
SMALL_TASK_SIGNALS = [
    re.compile(r"\btypo\b", re.IGNORECASE),
    re.compile(r"\bspelling\b", re.IGNORECASE),
    re.compile(r"\brename\s+\w+\s+to\b", re.IGNORECASE),
    re.compile(r"\bone[\s-]liner?\b", re.IGNORECASE),
    re.compile(r"\bone[\s-]line\s+fix\b", re.IGNORECASE),
    re.compile(r"\bsingle\s+file\b", re.IGNORECASE),
    re.compile(r"\bin\s+this\s+file\b", re.IGNORECASE),
    re.compile(r"\bthis\s+function\b", re.IGNORECASE),
    re.compile(r"\bthis\s+line\b", re.IGNORECASE),
    re.compile(r"\bminor\s+(fix|change|update|tweak)\b", re.IGNORECASE),
    re.compile(r"\bfix\s+(a\s+)?typo\b", re.IGNORECASE),
    re.compile(r"\badd\s+a?\s*comment\b", re.IGNORECASE),
    re.compile(r"\bwhitespace\b", re.IGNORECASE),
    re.compile(r"\bindentation\b", re.IGNORECASE),
    re.compile(r"\bformat(ting)?\s+(this|the)\b", re.IGNORECASE),
    re.compile(r"\bquick\s+fix\b", re.IGNORECASE),
    re.compile(r"\bsmall\s+(fix|change|tweak|update)\b", re.IGNORECASE),
    re.compile(r"\bupdate\s+(the\s+)?version\b", re.IGNORECASE),
    re.compile(r"\bbump\s+version\b", re.IGNORECASE),
]


# ===== 大任务信号 =====
LARGE_TASK_SIGNALS = [
    re.compile(r"\barchitect(ure|ural)?\b", re.IGNORECASE),
    re.compile(r"\brefactor\b", re.IGNORECASE),
    re.compile(r"\bredesign\b", re.IGNORECASE),
    re.compile(r"\bfrom\s+scratch\b", re.IGNORECASE),
    re.compile(r"\bcross[\s-]cutting\b", re.IGNORECASE),
    re.compile(r"\bentire\s+(codebase|project|application|app|system)\b", re.IGNORECASE),
    re.compile(r"\ball\s+(files|modules|components)\b", re.IGNORECASE),
    re.compile(r"\bmultiple\s+files\b", re.IGNORECASE),
    re.compile(r"\bacross\s+(the\s+)?(codebase|project|files|modules)\b", re.IGNORECASE),
    re.compile(r"\bsystem[\s-]wide\b", re.IGNORECASE),
    re.compile(r"\bmigrat(e|ion)\b", re.IGNORECASE),
    re.compile(r"\bfull[\s-]stack\b", re.IGNORECASE),
    re.compile(r"\bend[\s-]to[\s-]end\b", re.IGNORECASE),
    re.compile(r"\boverhaul\b", re.IGNORECASE),
    re.compile(r"\bcomprehensive\b", re.IGNORECASE),
    re.compile(r"\bextensive\b", re.IGNORECASE),
    re.compile(r"\bimplement\s+(a\s+)?(new\s+)?system\b", re.IGNORECASE),
    re.compile(r"\bbuild\s+(a\s+)?(complete|full|new)\b", re.IGNORECASE),
]


# ===== 重Orchestration关键词 =====
HEAVY_MODE_KEYWORDS = {
    "ralph",
    "autopilot",
    "team",
    "ultrawork",
    "swarm",
    "ralplan",
    "ccg",
}


# ===== 结果类 =====
@dataclass
class TaskSizeResult:
    size: str
    reason: str
    word_count: int
    has_escape_hatch: bool
    escape_prefix_used: str | None = None


# ===== 核心函数 =====
def count_words(text: str) -> int:
    """统计单词数"""
    return len(text.strip().split())


def detect_escape_hatch(text: str) -> str | None:
    """检测逃逸 hatch 前缀"""
    trimmed = text.strip().lower()
    for prefix in ESCAPE_HATCH_PREFIXES:
        if trimmed.startswith(prefix):
            return prefix
    return None


def has_small_task_signals(text: str) -> bool:
    """检查小任务信号"""
    return any(pattern.search(text) for pattern in SMALL_TASK_SIGNALS)


def has_large_task_signals(text: str) -> bool:
    """检查大任务信号"""
    return any(pattern.search(text) for pattern in LARGE_TASK_SIGNALS)


def is_heavy_mode(keyword_type: str) -> bool:
    """检查是否为重Orchestration模式"""
    return keyword_type.lower() in HEAVY_MODE_KEYWORDS


def classify_task_size(
    text: str,
    thresholds: TaskSizeThresholds = DEFAULT_THRESHOLDS,
) -> TaskSizeResult:
    """
    分类任务规模

    分类规则（优先级顺序）：
    1. 逃逸 hatch 前缀（quick:, simple: 等）→ 总是 small
    2. 大任务信号（architecture, refactor, entire codebase）→ large
    3. Prompt > largeWordLimit 词 → large
    4. 小任务信号 + 在限制内 → small
    5. Prompt <= smallWordLimit 词 → small
    6. 其他 → medium
    """
    word_count = count_words(text)
    escape_prefix = detect_escape_hatch(text)

    # 规则 1: 显式逃逸 → small
    if escape_prefix is not None:
        return TaskSizeResult(
            size=TaskSize.SMALL,
            reason=f'Escape hatch prefix detected: "{escape_prefix}"',
            word_count=word_count,
            has_escape_hatch=True,
            escape_prefix_used=escape_prefix,
        )

    has_large = has_large_task_signals(text)
    has_small = has_small_task_signals(text)

    # 规则 2: 大任务信号 → large
    if has_large:
        return TaskSizeResult(
            size=TaskSize.LARGE,
            reason="Large task signals detected (architecture/refactor/cross-cutting scope)",
            word_count=word_count,
            has_escape_hatch=False,
        )

    # 规则 3: 长 prompt → large
    if word_count > thresholds.large_word_limit:
        return TaskSizeResult(
            size=TaskSize.LARGE,
            reason=f"Prompt length ({word_count} words) exceeds large task threshold ({thresholds.large_word_limit})",
            word_count=word_count,
            has_escape_hatch=False,
        )

    # 规则 4: 小信号 + 在限制内 → small
    if has_small and not has_large:
        return TaskSizeResult(
            size=TaskSize.SMALL,
            reason="Small task signals detected (single file / minor change)",
            word_count=word_count,
            has_escape_hatch=False,
        )

    # 规则 5: 短 prompt → small
    if word_count <= thresholds.small_word_limit:
        return TaskSizeResult(
            size=TaskSize.SMALL,
            reason=f"Prompt length ({word_count} words) is within small task threshold ({thresholds.small_word_limit})",
            word_count=word_count,
            has_escape_hatch=False,
        )

    # 规则 6: 默认 → medium
    return TaskSizeResult(
        size=TaskSize.MEDIUM,
        reason=f"Prompt length ({word_count} words) is in medium range",
        word_count=word_count,
        has_escape_hatch=False,
    )


# ===== 高级分类 =====
def analyze_task_complexity(text: str) -> dict:
    """
    分析任务复杂性，返回详细报告
    """
    result = classify_task_size(text)

    # 额外的复杂性因素
    complexity_factors = {
        "has_database": bool(re.search(r"\b(database|query|sql|migration)\b", text, re.IGNORECASE)),
        "has_api": bool(re.search(r"\b(api|endpoint|rest|graphql)\b", text, re.IGNORECASE)),
        "has_auth": bool(re.search(r"\b(auth|jwt|oauth|security|password)\b", text, re.IGNORECASE)),
        "has_ui": bool(re.search(r"\b(ui|frontend|component|react|vue|html|css)\b", text, re.IGNORECASE)),
        "has_test": bool(re.search(r"\b(test|spec|unit|integration|e2e)\b", text, re.IGNORECASE)),
        "has_refactor": bool(re.search(r"\brefactor\b", text, re.IGNORECASE)),
        "has_performance": bool(re.search(r"\b(performance|optimize|cache|speed)\b", text, re.IGNORECASE)),
    }

    # 计算复杂性得分
    complexity_score = sum(complexity_factors.values())

    return {
        "size": result.size,
        "reason": result.reason,
        "word_count": result.word_count,
        "factors": complexity_factors,
        "complexity_score": complexity_score,
        "recommended_agents": _get_recommended_agents(result.size, complexity_factors),
    }


def _get_recommended_agents(size: str, factors: dict) -> list[str]:
    """根据任务规模和因素推荐代理"""
    agents = []

    if size == TaskSize.LARGE:
        agents.extend(["orchestrator", "architect"])

    if factors.get("has_database"):
        agents.append("dba")
    if factors.get("has_auth"):
        agents.append("security-auditor")
    if factors.get("has_ui"):
        agents.append("frontend-engineer")
    if factors.get("has_test"):
        agents.append("test-engineer")
    if factors.get("has_refactor"):
        agents.append("refactor-specialist")
    if factors.get("has_performance"):
        agents.append("performance-optimizr")

    if not agents:
        agents.append("coder")

    return agents


# ===== 导出 =====
__all__ = [
    "TaskSize",
    "TaskSizeResult",
    "TaskSizeThresholds",
    "analyze_task_complexity",
    "classify_task_size",
    "count_words",
    "detect_escape_hatch",
    "has_large_task_signals",
    "has_small_task_signals",
    "is_heavy_mode",
]
