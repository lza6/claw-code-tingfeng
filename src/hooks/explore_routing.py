"""
Explore Routing - 探索路由

从 oh-my-codex-main/src/hooks/explore-routing.ts 转换而来。
提供代码探索路由功能。

整合增强（2026-04-17）:
- 添加 oh-my-codex-main 的 WELL_SPECIFIED_SIGNALS 模式
- 添加任务规模检测（classifyTaskSize）集成
- 添加执行门控（applyRalplanGate）逻辑
"""

import os
import re
from dataclasses import dataclass

# 环境变量名称
OMX_EXPLORE_CMD_ENV = "USE_OMX_EXPLORE_CMD"

# 禁用值集合
DISABLED_VALUES = {"0", "false", "no", "off"}


# ---------------------------------------------------------------------------
# 任务规模检测（从 oh-my-codex 汲取）
# ---------------------------------------------------------------------------

@dataclass
class TaskSizeResult:
    """任务规模检测结果"""
    size: str  # 'small' | 'medium' | 'large' | 'heavy'
    word_count: int
    thresholds: dict


# 执行门控关键词（从 oh-my-codex/keyword-detector.ts）
EXECUTION_GATE_KEYWORDS = {"ralph", "autopilot", "team", "ultrawork"}

# 绕过前缀
GATE_BYPASS_PREFIXES = ["force:", "!"]

# 详细说明信号（从 oh-my-codex 汲取）
WELL_SPECIFIED_SIGNALS = [
    # 文件扩展名
    r"\b[\w/.-]+\.(?:ts|js|py|go|rs|java|tsx|jsx|vue|svelte|rb|c|cpp|h|css|scss|html|json|yaml|yml|toml)\b",
    # 目录路径
    r"(?:src|lib|test|spec|app|pages|components|hooks|utils|services|api|dist|build|scripts)/\w+",
    # 函数/类/方法关键字
    r"\b(?:function|class|method|interface|type|const|let|var|def|fn|struct|enum)\s+\w{2,}",
    # CamelCase 标识符
    r"\b[a-z]+(?:[A-Z][a-z]+)+\b",
    # PascalCase 标识符
    r"\b[A-Z][a-z]+(?:[A-Z][a-z0-9]*)+\b",
    # snake_case 标识符
    r"\b[a-z]+(?:_[a-z]+)+\b",
    # Issue/PR 编号
    r"(?:^|\s)#\d+\b",
    # 编号步骤或列表
    r"(?:^|\n)\s*(?:\d+[.)]\s|-\s+|\*\s+)",
    # 验收标准关键词
    r"\b(?:acceptance\s+criteria|test\s+(?:spec|plan|case)|should\s+(?:return|throw|render|display|create|delete|update))\b",
    # 错误/问题引用
    r"\b(?:error:|bug\s*#?\d+|issue\s*#\d+|stack\s*trace|exception|TypeError|ReferenceError|SyntaxError)\b",
    # 代码块
    r"```[\s\S]{20,}?```",
    # PR/提交引用
    r"\b(?:PR\s*#\d+|commit\s+[0-9a-f]{7}|pull\s+request)\b",
    # "in <path>" 模式
    r"\bin\s+[\w/.-]+\.(?:ts|js|py|go|rs|java|tsx|jsx)\b",
    # 测试运行命令
    r"\b(?:npm\s+test|npx\s+(?:vitest|jest)|pytest|cargo\s+test|go\s+test|make\s+test)\b",
]

# 编译正则表达式
_WELL_SPECIFIED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in WELL_SPECIFIED_SIGNALS]

# 简单探索模式正则
SIMPLE_EXPLORATION_PATTERNS = [
    r"\b(where|find|locate|search|grep|ripgrep)\b",
    r"\b(file|files|path|paths|symbol|symbols|usage|usages|reference|references)\b",
    r"\b(pattern|patterns|match|matches|matching)\b",
    r"\bhow does\b",
    r"\bwhich\b.*\b(contain|contains|define|defines|use|uses)\b",
    r"\b(read[- ]only|explor(e|ation)|inspect|lookup|look up|map)\b",
]

# 非探索模式正则
NON_EXPLORATION_PATTERNS = [
    r"\b(implement|write|edit|modify|change|refactor|fix|patch|add|remove|delete)\b",
    r"\b(build|create)\b.*\b(feature|system|workflow|integration|module)\b",
    r"\b(migrate|rewrite|overhaul|redesign)\b",
    r"\b(test|lint|typecheck|compile|deploy)\b",
]

# 编译非探索模式
_NON_EXPLORATION_COMPILED = [re.compile(p, re.IGNORECASE) for p in NON_EXPLORATION_PATTERNS]


@dataclass
class ExploreRoute:
    """探索路由"""
    target: str
    route_type: str  # 'file' | 'symbol' | 'pattern' | 'directory'
    confidence: float


# 路由模式
ROUTE_PATTERNS = {
    "file": [
        r"find\s+(?:the\s+)?file\s+(\S+)",
        r"where\s+is\s+(\S+)",
        r"locate\s+(\S+)",
        r"which\s+file\s+contains\s+(\S+)",
    ],
    "symbol": [
        r"(?:find|search|lookup)\s+(?:the\s+)?symbol\s+(\S+)",
        r"where\s+(?:is|defined)\s+(\S+)",
        r"definition\s+of\s+(\S+)",
    ],
    "pattern": [
        r"search\s+(?:for\s+)?(?:the\s+)?pattern\s+(\S+)",
        r"find\s+(?:all\s+)?(?:occurrences?\s+of\s+)?(\S+)",
    ],
    "directory": [
        r"explore\s+(?:the\s+)?directory\s+(\S+)",
        r"list\s+(?:the\s+)?(\S+)\s+directory",
    ],
}


def is_explore_command_routing_enabled(env: dict | None = None) -> bool:
    """检查探索命令路由是否启用"""
    env = env or os.environ
    raw = env.get(OMX_EXPLORE_CMD_ENV)
    if not isinstance(raw, str):
        return True
    return raw.strip().lower() not in DISABLED_VALUES


def classify_task_size(text: str, thresholds: dict | None = None) -> TaskSizeResult:
    """
    任务规模检测（从 oh-my-codex 汲取）。

    Args:
        text: 任务文本
        thresholds: 阈值配置 {smallWordLimit, largeWordLimit}

    Returns:
        TaskSizeResult 结果
    """
    default_thresholds = {"smallWordLimit": 50, "largeWordLimit": 200}
    if thresholds:
        default_thresholds.update(thresholds)

    words = text.split()
    word_count = len(words)

    if word_count <= default_thresholds["smallWordLimit"]:
        size = "small"
    elif word_count >= default_thresholds["largeWordLimit"]:
        size = "large"
    else:
        size = "medium"

    return TaskSizeResult(
        size=size,
        word_count=word_count,
        thresholds=default_thresholds
    )


def is_heavy_mode(keyword: str) -> bool:
    """
    判断是否为重型模式（从 oh-my-codex 汲取）。

    重型模式应仅在明确指定时启用，避免对小任务过度编排。
    """
    return keyword in EXECUTION_GATE_KEYWORDS


def is_underspecified_for_execution(text: str) -> bool:
    """
    检查提示是否规格不足，不适合直接执行（从 oh-my-codex 汲取）。
    返回 True 表示应转到 ralplan 进行规划。
    """
    trimmed = text.strip()
    if not trimmed:
        return True

    # 绕过前缀 force: 或 !
    for prefix in GATE_BYPASS_PREFIXES:
        if trimmed.startswith(prefix):
            return False

    # 详细说明信号检测
    for pattern in _WELL_SPECIFIED_PATTERNS:
        if pattern.search(trimmed):
            return False

    # 移出模式关键词计算有效词数
    stripped = re.sub(
        r"\b(?:ralph|autopilot|team|ultrawork|ulw|swarm)\b",
        "",
        trimmed,
        flags=re.IGNORECASE
    ).strip()
    effective_words = len([w for w in stripped.split() if w])
    return effective_words <= 15


def apply_ralplan_gate(keywords: list, text: str,
                      cwd: str | None = None,
                      prior_skill: str | None = None) -> tuple[list, bool, list]:
    """
    应用 ralplan-first 门控（从 oh-my-codex/keyword-detector.ts 汲取）。

    如果执行关键词存在但提示规格不足，将执行关键词替换为 ralplan。

    Returns:
        (过滤后的关键词列表, 是否应用门控, 被门控的关键词)
    """
    if not keywords:
        return keywords, False, []

    # 取消总是胜出
    if "cancel" in keywords:
        return keywords, False, []

    # 已有 ralplan 不门控
    if "ralplan" in keywords:
        return keywords, False, []

    # 检查是否有执行关键词
    execution_keywords = [k for k in keywords if k in EXECUTION_GATE_KEYWORDS]
    if not execution_keywords:
        return keywords, False, []

    # 检查规格
    if not is_underspecified_for_execution(text):
        return keywords, False, []

    # 通过计划完成检查 + 短跟随 bypass
    plan_complete = _is_planning_complete(cwd or os.getcwd())
    short_followup_bypass = [
        k for k in execution_keywords
        if k in ("team", "ralph") and _is_approved_execution_followup_shortcut(k, text, {
            "planningComplete": plan_complete,
            "priorSkill": prior_skill,
        })
    ]
    if short_followup_bypass:
        return keywords, False, []

    # 门控：替换执行关键词为 ralplan
    filtered = [k for k in keywords if k not in EXECUTION_GATE_KEYWORDS]
    if "ralplan" not in filtered:
        filtered.append("ralplan")

    return filtered, True, execution_keywords


def _is_planning_complete(cwd: str) -> bool:
    """检查规划是否完成（从 oh-my-codex 汲取）"""
    planning_artifacts_path = os.path.join(cwd, ".omx", "artifacts")
    return os.path.exists(planning_artifacts_path)


def _is_approved_execution_followup_shortcut(
    keyword: str,
    text: str,
    context: dict
) -> bool:
    """
    检查是否为已批准的执行跟随快捷键（从 oh-my-codex 汲取）。

    例如，在批准计划后的小调整可以直接执行，无需重新规划。
    """
    planning_complete = context.get("planningComplete", False)
    if not planning_complete:
        return False

    # 检查是否包含明确的批准信号
    approval_signals = [
        r"\bapproved\b",
        r"\ballowed\b",
        r"\bgo\s+proceed\b",
        r"\byes\b",
    ]
    text_lower = text.lower()
    for signal in approval_signals:
        if re.search(signal, text_lower):
            return True

    return False


def is_simple_exploration_prompt(text: str) -> bool:
    """检查是否为简单探索提示（增强版）"""
    trimmed = text.strip()
    if not trimmed:
        return False

    # 先检查非探索模式
    for pattern in _NON_EXPLORATION_COMPILED:
        if pattern.search(trimmed):
            return False

    # 检查简单探索模式
    for pattern in SIMPLE_EXPLORATION_PATTERNS:
        if re.search(pattern, trimmed, re.IGNORECASE):
            return True

    return False


def build_explore_routing_guidance(env: dict | None = None) -> str:
    """构建探索路由指南"""
    if not is_explore_command_routing_enabled(env):
        return ""

    lines = [
        f"**Explore Command Preference:** enabled via `{OMX_EXPLORE_CMD_ENV}` (default-on; opt out with `0`, `false`, `no`, or `off`)",
        "- Advisory steering only: agents SHOULD use explore as the default first stop for direct inspection.",
        "- For simple file/symbol lookups, use explore FIRST before attempting full code analysis.",
        "- When the user asks for a simple read-only exploration task (file/symbol/pattern/relationship lookup), strongly prefer explore as the default surface.",
        "- Explore examples: `explore --prompt 'which files define TeamPolicy'`, `explore --prompt 'find usages of buildExploreRoutingGuidance'`.",
        "- Keep implementation, refactor, test, or ambiguous broad requests on the normal path.",
    ]

    return "\n".join(lines)


def parse_explore_route(query: str) -> ExploreRoute | None:
    """解析探索路由查询"""
    import re

    query_lower = query.lower()

    # 文件路由
    for pattern in ROUTE_PATTERNS["file"]:
        match = re.search(pattern, query_lower)
        if match:
            return ExploreRoute(
                target=match.group(1),
                route_type="file",
                confidence=0.9,
            )

    # 符号路由
    for pattern in ROUTE_PATTERNS["symbol"]:
        match = re.search(pattern, query_lower)
        if match:
            return ExploreRoute(
                target=match.group(1),
                route_type="symbol",
                confidence=0.85,
            )

    # 模式路由
    for pattern in ROUTE_PATTERNS["pattern"]:
        match = re.search(pattern, query_lower)
        if match:
            return ExploreRoute(
                target=match.group(1),
                route_type="pattern",
                confidence=0.8,
            )

    # 目录路由
    for pattern in ROUTE_PATTERNS["directory"]:
        match = re.search(pattern, query_lower)
        if match:
            return ExploreRoute(
                target=match.group(1),
                route_type="directory",
                confidence=0.75,
            )

    return None


def suggest_routing_strategy(query: str) -> str:
    """建议路由策略"""
    if not is_simple_exploration_prompt(query):
        return "default"

    route = parse_explore_route(query)
    if not route:
        return "default"

    route_strategies = {
        "file": "file_search",
        "symbol": "symbol_search",
        "pattern": "grep_search",
        "directory": "directory_explore",
    }
    return route_strategies.get(route.route_type, "default")


# ===== 导出 =====
__all__ = [
    "EXECUTION_GATE_KEYWORDS",
    "GATE_BYPASS_PREFIXES",
    "OMX_EXPLORE_CMD_ENV",
    "WELL_SPECIFIED_SIGNALS",
    "ExploreRoute",
    "TaskSizeResult",
    "apply_ralplan_gate",
    "build_explore_routing_guidance",
    "classify_task_size",
    "is_explore_command_routing_enabled",
    "is_heavy_mode",
    "is_simple_exploration_prompt",
    "is_underspecified_for_execution",
    "parse_explore_route",
    "suggest_routing_strategy",
]
