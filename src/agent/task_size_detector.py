"""
Task Size Detector - 任务规模检测

从 oh-my-codex-main/src/hooks/task-size-detector.ts 转换而来。
检测用户任务的规模（small/medium/large/heavy）。
"""

import re
from dataclasses import dataclass
from enum import Enum

# ==================== 任务规模枚举 ====================

class TaskSize(str, Enum):
    """任务规模"""
    TRIVIAL = "trivial"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    HEAVY = "heavy"


# ==================== 配置类 ====================

@dataclass
class TaskSizeThresholds:
    """任务规模阈值配置"""
    small_word_limit: int = 50
    large_word_limit: int = 200


DEFAULT_THRESHOLDS = TaskSizeThresholds(
    small_word_limit=50,
    large_word_limit=200,
)


# ==================== 逃逸 Hatch 前缀 ====================

ESCAPE_HATCH_PREFIXES = [
    "quick:",
    "simple:",
    "tiny:",
    "minor:",
    "small:",
    "just:",
    "only:",
    "fast:",
    "easy:",
    "quickfix:",
]


# ==================== 小任务信号 ====================

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


# 小任务信号扩展（从 oh-my-codex-main 汲取）
SMALL_TASK_SIGNALS_EXTENDED = [*SMALL_TASK_SIGNALS, re.compile(r"\bpatch\b", re.I), re.compile(r"\bhotfix\b", re.I), re.compile(r"\btypo\s+fix\b", re.I), re.compile(r"\bupdate\s+version\s+number\b", re.I), re.compile(r"\bfix\s+small\s+issue\b", re.I)]


# ==================== 大任务信号 ====================

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


# 大任务信号扩展（从 oh-my-codex-main 汲取）
LARGE_TASK_SIGNALS_EXTENDED = [*LARGE_TASK_SIGNALS, re.compile(r"\bmodernize\b", re.I), re.compile(r"\bupdate\s+dependencies\b", re.I), re.compile(r"\bsecurity\s+patch\b", re.I), re.compile(r"\bperformance\s+optimization\b", re.I)]


# ==================== 重 Orchestration 关键词 ====================

HEAVY_MODE_KEYWORDS = {
    "ralph",
    "autopilot",
    "team",
    "ultrawork",
    "swarm",
    "ralplan",
    "ccg",
}


# ==================== 结果类 ====================

@dataclass
class TaskSizeResult:
    """任务规模检测结果"""
    size: str
    reason: str
    word_count: int
    has_escape_hatch: bool
    escape_prefix_used: str | None = None
    confidence: float = 1.0  # 置信度（0-1）
    factors: dict | None = None  # 决策因素详情


@dataclass
class TaskComplexityResult:
    """任务复杂性分析结果"""
    size: str
    confidence: float
    factors: dict[str, bool]
    recommended_agents: list[str]


# ==================== 核心函数 ====================

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
    """检查是否为重 orchestration 模式"""
    return keyword_type.lower() in HEAVY_MODE_KEYWORDS


def classify_task_size(
    text: str,
    thresholds: TaskSizeThresholds | None = None,
) -> TaskSizeResult:
    """
    分类任务规模（借鉴 oh-my-codex 的优先级策略）

    分类规则（优先级顺序）:
    1. 逃逸前缀 (quick:, simple: 等) → 总是 small
    2. 大任务信号 (architecture, refactor, entire codebase) → large
    3. 提示词 > largeWordLimit → large
    4. 小任务信号 AND 无大任务信号 → small
    5. 提示词 < smallWordLimit → small
    6. 其他 → medium

    Returns:
        TaskSizeResult: 包含 size、reason、word_count 等完整信息
    """
    thresholds = thresholds or DEFAULT_THRESHOLDS
    word_count = count_words(text)
    escape_prefix = detect_escape_hatch(text)

    # 规则 1: 显式逃逸前缀 → 总是 small
    if escape_prefix is not None:
        return TaskSizeResult(
            size=TaskSize.SMALL.value,
            reason=f'Escape hatch prefix detected: "{escape_prefix}"',
            word_count=word_count,
            has_escape_hatch=True,
            escape_prefix_used=escape_prefix,
            confidence=1.0,
            factors={"escape_hatch": True, "explicit": True},
        )

    # 使用增强的信号检测（包含 oh-my-codex-main 的扩展模式）
    has_large_enhanced = has_large_task_signals(text) or any(
        pattern.search(text) for pattern in LARGE_TASK_SIGNALS_EXTENDED
    )
    has_small_enhanced = has_small_task_signals(text) or any(
        pattern.search(text) for pattern in SMALL_TASK_SIGNALS_EXTENDED
    )

    # 规则 2: 大任务信号 → large
    if has_large_enhanced:
        return TaskSizeResult(
            size=TaskSize.LARGE.value,
            reason="Large task signals detected (architecture/refactor/cross-cutting scope)",
            word_count=word_count,
            has_escape_hatch=False,
            confidence=0.9,
            factors={"large_signals": True, "explicit": True},
        )

    # 规则 3: 长提示词 → large
    if word_count > thresholds.large_word_limit:
        return TaskSizeResult(
            size=TaskSize.LARGE.value,
            reason=f"Prompt length ({word_count} words) exceeds large task threshold ({thresholds.large_word_limit})",
            word_count=word_count,
            has_escape_hatch=False,
            confidence=0.8,
            factors={"long_prompt": True, "word_count": word_count},
        )

    # 规则 4: 小任务信号 + 无大任务信号 → small
    if has_small_enhanced and not has_large_enhanced:
        return TaskSizeResult(
            size=TaskSize.SMALL.value,
            reason="Small task signals detected (single file / minor change)",
            word_count=word_count,
            has_escape_hatch=False,
            confidence=0.85,
            factors={"small_signals": True, "explicit": True},
        )

    # 规则 5: 短提示词 → small
    if word_count <= thresholds.small_word_limit:
        return TaskSizeResult(
            size=TaskSize.SMALL.value,
            reason=f"Prompt length ({word_count} words) is within small task threshold ({thresholds.small_word_limit})",
            word_count=word_count,
            has_escape_hatch=False,
            confidence=0.7,
            factors={"short_prompt": True, "word_count": word_count},
        )

    # 规则 6: 默认 → medium
    return TaskSizeResult(
        size=TaskSize.MEDIUM.value,
        reason=f"Prompt length ({word_count} words) is in medium range",
        word_count=word_count,
        has_escape_hatch=False,
        confidence=0.6,
        factors={"medium_default": True, "word_count": word_count},
    )


def analyze_task_complexity(text: str) -> TaskComplexityResult:
    """
    深度任务复杂性分析（借鉴 oh-my-codex 的 agent recommendation 逻辑）

    分析任务规模 + 领域因素，推荐合适的 agent。

    Args:
        text: 用户输入文本

    Returns:
        TaskComplexityResult: 包含规模、置信度、因素和推荐 agent 列表
    """
    size_result = classify_task_size(text)

    # 分析领域因素
    factors = {
        "has_database": bool(re.search(r"\b(database|query|sql|migration|table|schema)\b", text, re.IGNORECASE)),
        "has_api": bool(re.search(r"\b(api|endpoint|rest|graphql|http|request|response)\b", text, re.IGNORECASE)),
        "has_auth": bool(re.search(r"\b(auth|jwt|oauth|security|password|login|permission)\b", text, re.IGNORECASE)),
        "has_ui": bool(re.search(r"\b(ui|frontend|component|react|vue|html|css|style)\b", text, re.IGNORECASE)),
        "has_test": bool(re.search(r"\b(test|spec|unit|integration|e2e|pytest|jest)\b", text, re.IGNORECASE)),
        "has_refactor": bool(re.search(r"\brefactor\b", text, re.IGNORECASE)),
        "has_performance": bool(re.search(r"\b(performance|optimize|cache|speed|latency)\b", text, re.IGNORECASE)),
        "has_debug": bool(re.search(r"\b(debug|bug|error|fix|troubleshoot)\b", text, re.IGNORECASE)),
        "has_security": bool(re.search(r"\b(security|vulnerability|exploit|injection|xss)\b", text, re.IGNORECASE)),
    }

    # 根据规模和因素推荐 agent
    recommended_agents = _get_recommended_agents(size_result.size, factors)

    # 计算综合置信度
    base_confidence = size_result.confidence
    factor_boost = sum(1 for v in factors.values() if v) * 0.05
    confidence = min(1.0, base_confidence + factor_boost)

    return TaskComplexityResult(
        size=size_result.size,
        confidence=confidence,
        factors=factors,
        recommended_agents=recommended_agents,
    )


def _get_recommended_agents(size: str, factors: dict[str, bool]) -> list[str]:
    """根据任务规模和因素推荐合适的 agent"""
    agents = []

    # 基于规模
    if size == TaskSize.LARGE:
        agents.extend(["orchestrator", "architect"])
    elif size == TaskSize.HEAVY:
        agents.extend(["orchestrator", "architect", "planner"])

    # 基于领域因素
    if factors.get("has_database"):
        agents.append("dependency-expert")
    if factors.get("has_auth"):
        agents.append("security-reviewer")
    if factors.get("has_ui"):
        agents.append("frontend-developer")
    if factors.get("has_test"):
        agents.append("test-engineer")
    if factors.get("has_refactor"):
        agents.append("code-simplifier")
    if factors.get("has_performance"):
        agents.append("performance-optimizer")
    if factors.get("has_debug"):
        agents.append("debugger")
    if factors.get("has_security"):
        agents.append("security-auditor")

    # 默认 fallback
    if not agents:
        agents.append("executor")

    return agents


# ==================== 导出 ====================

__all__ = [
    "DEFAULT_THRESHOLDS",
    "ESCAPE_HATCH_PREFIXES",
    "HEAVY_MODE_KEYWORDS",
    "LARGE_TASK_SIGNALS",
    "SMALL_TASK_SIGNALS",
    "TaskComplexityResult",
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
