"""
Keyword Registry & Intent Router - 关键词注册表与意图路由

借鉴 oh-my-codex-main/src/hooks/keyword-detector.ts 和 keyword-registry.ts。
提供增强的关键词检测系统：
- 结构化关键词定义（优先级、意图验证）
- 任务规模检测（避免过度编排）
- 执行门控（ralplan-first gate）
- well-specified 信号检测
- Deep Interview 输入锁
- 技能激活状态持久化

这是 Clawd Code 的核心智能路由层。
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KeywordTrigger:
    """关键词触发器定义（不可变）"""
    keyword: str  # 触发关键词
    skill: str  # 激活的技能名称
    priority: int  # 优先级（越高越优先）
    requires_intent: bool = False  # 是否需要明确意图指示
    description: str = ""  # 触发说明


# ==================== 关键词触发器注册表 ====================

KEYWORD_TRIGGER_DEFINITIONS: list[KeywordTrigger] = [
    # Ralph 持久化循环 (高优先级)
    KeywordTrigger(
        keyword='ralph',
        skill='ralph_loop',
        priority=10,
        description="启动 RALPH 持久化循环执行",
    ),

    # Team/Swarm 团队执行 (需要明确意图)
    KeywordTrigger(
        keyword='team',
        skill='team_execution',
        priority=20,
        requires_intent=True,
        description="启动团队并行执行模式",
    ),
    KeywordTrigger(
        keyword='swarm',
        skill='team_execution',
        priority=20,
        requires_intent=True,
        description="Swarm 集群执行（映射到 team_execution）",
    ),

    # Deep Interview 深度访谈
    KeywordTrigger(
        keyword='deep-interview',
        skill='deep_interview',
        priority=15,
        description="启动深度需求澄清流程",
    ),

    # RALPLAN 计划审批
    KeywordTrigger(
        keyword='ralplan',
        skill='ralplan',
        priority=25,
        description="生成并审批执行计划",
    ),

    # Pipeline 管道执行
    KeywordTrigger(
        keyword='pipeline',
        skill='pipeline_orchestrator',
        priority=18,
        description="执行多阶段工作流管道",
    ),

    # Code Simplify 代码简化
    KeywordTrigger(
        keyword='simplify',
        skill='code_simplifier',
        priority=12,
        description="自动简化最近修改的代码",
    ),

    # Review 审查
    KeywordTrigger(
        keyword='review',
        skill='code_review',
        priority=14,
        description="执行五轴代码审查",
    ),

    # Test 测试
    KeywordTrigger(
        keyword='test',
        skill='test_engineer',
        priority=13,
        description="运行测试工程师工作流",
    ),

    # Build 构建
    KeywordTrigger(
        keyword='build',
        skill='incremental_implementation',
        priority=16,
        description="增量 TDD 实现",
    ),

    # Ship 发布
    KeywordTrigger(
        keyword='ship',
        skill='shipping_and_launch',
        priority=17,
        description="预发布清单检查和部署准备",
    ),
]

# 需要明确意图的关键词集合（防止误触发高风险操作）
KEYWORDS_REQUIRING_INTENT: set[str] = {
    trigger.keyword for trigger in KEYWORD_TRIGGER_DEFINITIONS
    if trigger.requires_intent
}

# ==================== 执行门控与任务规模检测 ====================

# 执行门控：触发重度编排的关键词（需通过 ralplan-first gate 或 bypass）
EXECUTION_GATE_KEYWORDS: set[str] = {'ralph', 'autopilot', 'team', 'ultrawork', 'swarm'}

# 绕过执行门控的前缀（force:, !）
GATE_BYPASS_PREFIXES: list[str] = ['force:', '!']

# Well-specified 信号检测（15+ 正则模式）
# 匹配这些模式之一时，自动通过执行门控
WELL_SPECIFIED_SIGNALS: list[re.Pattern] = [
    # 文件引用（明确的文件路径）
    re.compile(r'\b[\w/.-]+\.(?:ts|js|py|go|rs|java|tsx|jsx|vue|svelte|rb|c|cpp|h|css|scss|html|json|yaml|yml|toml)\b'),
    re.compile(r'(?:src|lib|test|spec|app|pages|components|hooks|utils|services|api|dist|build|scripts)/\w+'),
    # 代码结构引用
    re.compile(r'\b(?:function|class|method|interface|type|const|let|var|def|fn|struct|enum)\s+\w{2,}', re.I),
    re.compile(r'\b[a-z]+(?:[A-Z][a-z]+)+\b'),  # camelCase
    re.compile(r'\b[A-Z][a-z]+(?:[A-Z][a-z0-9]*)+\b'),  # PascalCase
    re.compile(r'\b[a-z]+(?:_[a-z]+)+\b'),  # snake_case（多段）
    # 问题追踪标识
    re.compile(r'(?:^|\s)#\d+\b'),
    re.compile(r'(?:^|\n)\s*(?:\d+[.)]\s|-\s+\S|\*\s+\S)', re.MULTILINE),
    # 验收标准与测试语言
    re.compile(r'\b(?:acceptance\s+criteria|test\s+(?:spec|plan|case)|should\s+(?:return|throw|render|display|create|delete|update))\b', re.I),
    # 错误与调试信息
    re.compile(r'\b(?:error:|bug\s*#?\d+|issue\s*#\d+|stack\s*trace|exception|TypeError|ReferenceError|SyntaxError)\b', re.I),
    # 代码块
    re.compile(r'```[\s\S]{20,}?```'),
    # VCS 引用
    re.compile(r'\b(?:PR\s*#\d+|commit\s+[0-9a-f]{7}|pull\s+request)\b', re.I),
    # 依赖与环境引用
    re.compile(r'\bin\s+[\w/.-]+\.(?:ts|js|py|go|rs|java|tsx|jsx)\b'),
    # 测试命令
    re.compile(r'\b(?:npm\s+test|npx\s+(?:vitest|jest)|pytest|cargo\s+test|go\s+test|make\s+test)\b', re.I),
]

# 技能激活状态持久化文件
SKILL_ACTIVE_STATE_FILE: Path = Path('.clawd') / 'state' / 'skill-active-state.json'

# 任务规模检测器（延迟导入以避免循环依赖）
_task_size_detector = None


def _get_task_size_detector():
    """延迟加载任务规模检测器"""
    global _task_size_detector
    if _task_size_detector is None:
        try:
            from .task_size_detector import classify_task_size
            _task_size_detector = classify_task_size
        except ImportError:
            _task_size_detector = None
    return _task_size_detector


def get_task_size_class(text: str) -> str | None:
    """
    获取任务的规模分类。

    Args:
        text: 用户输入文本

    Returns:
        任务规模：'small', 'medium', 'large', 'heavy' 或 None
    """
    detector = _get_task_size_detector()
    if detector:
        result = detector(text)
        return result.size if result else None
    return None


# 团队/集群意图模式（用于验证显式调用）
TEAM_SWARM_INTENT_PATTERNS: dict[str, list[re.Pattern]] = {
    'team': [
        re.compile(r'\$team\b', re.I),
        re.compile(r'/prompts:team\b', re.I),
        re.compile(r'team\s+mode\b', re.I),
    ],
    'swarm': [
        re.compile(r'\$swarm\b', re.I),
        re.compile(r'/prompts:swarm\b', re.I),
        re.compile(r'swarm\s+mode\b', re.I),
    ],
}


def extract_explicit_skill_invocations(text: str) -> list[KeywordTrigger]:
    """
    提取 $skill 格式的显式技能调用。

    Args:
        text: 用户输入文本

    Returns:
        按优先级排序的触发器列表（高优先级在前）
    """
    results: list[KeywordTrigger] = []
    seen_skills: set[str] = set()

    for match in re.finditer(r'\$([a-z][a-z0-9-]*)\b', text, re.I):
        token = match.group(1).lower()

        # Swarm 映射到 team
        normalized = 'team' if token == 'swarm' else token

        # 查找匹配的触发器
        for trigger in KEYWORD_TRIGGER_DEFINITIONS:
            if trigger.keyword == normalized and trigger.skill not in seen_skills:
                results.append(trigger)
                seen_skills.add(trigger.skill)
                break

    # 按优先级降序排序
    return sorted(results, key=lambda t: t.priority, reverse=True)


def has_intent_context(text: str, keyword: str) -> bool:
    """
    检查文本是否包含明确的意图指示。

    对于高风险关键词（如 team/swarm），要求有显式的调用语法
    （如 $team, /prompts:team）以避免误触发。

    Args:
        text: 用户输入文本
        keyword: 需要验证的关键词

    Returns:
        True 如果有明确意图或不需要意图验证，False 否则
    """
    if keyword.lower() not in KEYWORDS_REQUIRING_INTENT:
        return True  # 低风险关键词，始终允许

    # 特殊处理：team 关键词也接受 $swarm 作为显式调用
    if keyword.lower() == 'team' and re.search(r'\$swarm\b', text, re.I):
        return True

    # 检查是否有明确的意图指示
    patterns = TEAM_SWARM_INTENT_PATTERNS.get(keyword.lower(), [])
    return any(pattern.search(text) for pattern in patterns)


def detect_keywords(text: str) -> list[KeywordTrigger]:
    """
    检测文本中的关键词并返回匹配的触发器。

    结合显式调用检测和意图验证：
    1. 首先检查显式 $skill 调用
    2. 对于需要意图的关键词，验证是否有明确指示
    3. 返回按优先级排序的结果

    Args:
        text: 用户输入文本

    Returns:
        按优先级排序的触发器列表
    """
    # 1. 提取显式调用
    explicit_calls = extract_explicit_skill_invocations(text)

    # 2. 过滤掉没有明确意图的调用
    validated_calls = [
        trigger for trigger in explicit_calls
        if has_intent_context(text, trigger.keyword)
    ]

    return validated_calls


def get_trigger_by_keyword(keyword: str) -> KeywordTrigger | None:
    """
    根据关键词获取触发器定义。

    Args:
        keyword: 关键词

    Returns:
        触发器定义，如果不存在则返回 None
    """
    normalized = 'team' if keyword.lower() == 'swarm' else keyword.lower()
    for trigger in KEYWORD_TRIGGER_DEFINITIONS:
        if trigger.keyword == normalized:
            return trigger
    return None


def get_all_keywords() -> list[str]:
    """获取所有注册的关键词"""
    return [trigger.keyword for trigger in KEYWORD_TRIGGER_DEFINITIONS]


# 导出公共符号（按字母顺序排序，区分大小写）
__all__ = [
    'EXECUTION_GATE_KEYWORDS',
    'GATE_BYPASS_PREFIXES',
    'KEYWORDS_REQUIRING_INTENT',
    'KEYWORD_TRIGGER_DEFINITIONS',
    'SKILL_ACTIVE_STATE_FILE',
    'WELL_SPECIFIED_SIGNALS',
    'KeywordTrigger',
    'apply_ralplan_gate',
    'detect_keywords',
    'detect_primary_keyword',
    'extract_explicit_skill_invocations',
    'get_all_keywords',
    'get_deep_interview_lock_state',
    'get_skill_active_state',
    'get_task_size_class',
    'get_trigger_by_keyword',
    'has_explore_intent',
    'has_intent_context',
    'has_intent_context_for_keyword',
    'is_deep_interview_input_blocked',
    'is_read_only_intent',
    'is_underspecified_for_execution',
    'record_skill_activation',
    'release_deep_interview_on_cancel',
]


def detect_primary_keyword(text: str) -> str | None:
    """
    检测文本中的主要关键词（返回最高优先级的匹配）。

    Args:
        text: 用户输入文本

    Returns:
        主要关键词，如果不存在则返回 None
    """
    triggers = detect_keywords(text)
    if not triggers:
        return None
    # 按优先级和长度排序，返回最高优先级
    best = max(triggers, key=lambda t: (t.priority, len(t.keyword)))
    return best.keyword


def has_intent_context_for_keyword(text: str, keyword: str) -> bool:
    """
    检查文本是否包含特定关键词的明确意图指示。
    这是 has_intent_context 的公开版本。

    Args:
        text: 用户输入文本
        keyword: 需要验证的关键词

    Returns:
        True 如果有明确意图或不需要意图验证，False 否则
    """
    return has_intent_context(text, keyword)


def is_underspecified_for_execution(text: str) -> bool:
    """
    检查提示是否指定不足（缺少well-specified信号）。
    用于ralplan-first gate：如果提示太模糊，则重定向到规划阶段。

    Args:
        text: 用户输入文本

    Returns:
        True 如果提示指定不足，False 否则
    """
    # 检查是否有绕过前缀
    for prefix in GATE_BYPASS_PREFIXES:
        if text.strip().startswith(prefix):
            return False

    # 检查well-specified信号
    return not any(pattern.search(text) for pattern in WELL_SPECIFIED_SIGNALS)


def apply_ralplan_gate(keywords: list[KeywordTrigger], text: str, options: dict | None = None) -> list[KeywordTrigger]:
    """
    应用ralplan-first gate：将执行关键词重定向到ralplan，
    除非有明确意图或绕过前缀。

    Args:
        keywords: 检测到的关键词列表
        text: 原始用户输入
        options: 可选配置（保留用于兼容性）

    Returns:
        处理后的关键词列表
    """
    if not keywords:
        return keywords

    # 检查是否有绕过条件
    def has_bypass() -> bool:
        trimmed = text.strip().lower()
        # 绕过前缀
        if any(trimmed.startswith(p) for p in GATE_BYPASS_PREFIXES):
            return True
        # 已包含 ralplan
        if any(t.keyword == 'ralplan' for t in keywords):
            return True
        # 取消关键词
        return bool(re.search(r'\b(cancel|abort|stop)\b', text, re.I))

    result = []
    for trigger in keywords:
        # 检查是否是受门控限制的执行关键词
        if trigger.keyword in EXECUTION_GATE_KEYWORDS:
            # 如果已经满足绕过条件，直接添加原始触发器
            if has_bypass():
                if trigger not in result:
                    result.append(trigger)
                continue

            # 如果是模糊提示（underspecified），重定向到 ralplan
            if is_underspecified_for_execution(text):
                ralplan_trigger = get_trigger_by_keyword('ralplan')
                if ralplan_trigger and ralplan_trigger not in result:
                    result.append(ralplan_trigger)
                continue  # 跳过添加原始触发器

        # 添加原始触发器（如果还未添加）
        if trigger not in result:
            result.append(trigger)

    return result


def record_skill_activation(skill_name: str, workdir: Path | None = None) -> None:
    """
    记录技能激活状态到持久化文件。
    用于Deep Interview输入锁等功能。

    Args:
        skill_name: 已激活的技能名称
        workdir: 工作目录，默认为当前目录

    Raises:
        ValueError: 如果检测到路径遍历攻击
    """
    if workdir is None:
        workdir = Path.cwd()

    # 路径验证：确保在预期工作目录内
    workdir = workdir.resolve()
    state_file = (workdir / '.clawd' / 'state' / 'skill-active-state.json').resolve()

    # 安全检查：state_file 必须在 workdir 内（防止路径遍历）
    if not str(state_file).startswith(str(workdir) + os.sep) and str(state_file) != str(workdir):
        raise ValueError(f"Path traversal detected: {workdir} -> {state_file}")

    state_file.parent.mkdir(parents=True, exist_ok=True)

    # 读取现有状态
    state = {}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read skill state from {state_file}: {e}")
            state = {}

    # 更新激活状态
    state['active_skill'] = skill_name
    state['activated_at'] = datetime.now().isoformat()

    # 写回文件
    try:
        state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
    except OSError as e:
        logger.error(f"Failed to write skill state to {state_file}: {e}")


def get_skill_active_state(workdir: Path | None = None) -> dict:
    """
    获取当前激活的技能状态。

    Args:
        workdir: 工作目录，默认为当前目录

    Returns:
        技能激活状态字典
    """
    if workdir is None:
        workdir = Path.cwd()

    workdir = workdir.resolve()
    state_file = (workdir / '.clawd' / 'state' / 'skill-active-state.json').resolve()

    # 安全检查：state_file 必须在 workdir 内
    if not str(state_file).startswith(str(workdir) + os.sep) and str(state_file) != str(workdir):
        raise ValueError(f"Path traversal detected: {workdir} -> {state_file}")

    if not state_file.exists():
        return {}

    try:
        return json.loads(state_file.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read skill state from {state_file}: {e}")
        return {}


# ==================== Deep Interview 输入锁 (从 oh-my-codex 汲取) ====================

def get_deep_interview_lock_state(workdir: Path | None = None) -> dict | None:
    """
    获取深度面试输入锁状态（从 oh-my-codex 汲取）。

    当 deep-interview 技能激活时，此锁会阻止某些自动批准快捷方式
    （如 "yes", "proceed", "continue" 等），直到面试完成。

    Args:
        workdir: 工作目录

    Returns:
        输入锁状态字典，如果未激活则返回 None
    """
    state = get_skill_active_state(workdir)
    if state.get('active') and state.get('skill') == 'deep-interview':
        input_lock = state.get('input_lock')
        if input_lock and input_lock.get('active'):
            return input_lock
    return None


def is_deep_interview_input_blocked(user_input: str, workdir: Path | None = None) -> tuple[bool, str | None]:
    """
    检查用户输入是否被深度面试输入锁阻止。

    Args:
        user_input: 用户输入文本
        workdir: 工作目录

    Returns:
        (是否被阻止, 阻止消息)
    """
    lock_state = get_deep_interview_lock_state(workdir)
    if not lock_state:
        return False, None

    blocked_inputs = lock_state.get('blocked_inputs', [])
    normalized_input = user_input.strip().lower()
    if normalized_input in blocked_inputs:
        return True, lock_state.get('message', 'Deep interview is active; auto-approval shortcuts are blocked.')

    return False, None


def release_deep_interview_on_cancel(workdir: Path | None = None) -> bool:
    """
    在取消命令触发时释放深度面试锁。

    Args:
        workdir: 工作目录

    Returns:
        是否成功释放
    """
    if workdir is None:
        workdir = Path.cwd()

    state_file = workdir / '.clawd' / 'state' / 'skill-active-state.json'
    if not state_file.exists():
        return False

    try:
        state = json.loads(state_file.read_text(encoding='utf-8'))
        if state.get('active') and state.get('skill') == 'deep-interview' and state.get('input_lock', {}).get('active'):
            state['active'] = False
            state['current_phase'] = 'cancelled'
            if 'input_lock' in state:
                state['input_lock']['active'] = False
                state['input_lock']['exit_reason'] = 'abort'
                state['input_lock']['released_at'] = datetime.now().isoformat()
            state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
            return True
    except Exception as e:
        logger.error(f"Failed to release deep interview lock: {e}")
    return False




# ==================== EXPLORE 意图支持 (从 oh-my-codex 汲取) ====================


def has_explore_intent(text: str) -> bool:
    """
    检测用户输入是否包含 EXPLORE 意图。

    EXPLORE 意图用于只读代码探索，不产生修改。
    参考 oh-my-codex-main 的 explore 模式。

    Args:
        text: 用户输入文本

    Returns:
        True 如果包含探索意图，False 否则
    """
    explore_patterns = [
        re.compile(r'\b(explore|search|find|discover|analyze|investigate)\b', re.I),
        re.compile(r'\bhow\s+(does|do|is|are)\b', re.I),
        re.compile(r'\bwhat\s+is\b', re.I),
        re.compile(r'\blist\s+all\b', re.I),
        re.compile(r'\bshow\s+me\b', re.I),
    ]
    return any(pattern.search(text) for pattern in explore_patterns)


def is_read_only_intent(text: str) -> bool:
    """
    检查是否为只读意图（不修改代码）。

    结合 EXPLORE 意图和关键词检测。

    Args:
        text: 用户输入文本

    Returns:
        True 如果意图是只读的，False 否则
    """
    # 检查是否有明确的关键词表示探索
    triggers = detect_keywords(text)
    explore_triggers = [t for t in triggers if t.keyword in ('explore', 'analyze', 'investigate')]
    if explore_triggers:
        return True

    # 检查文本模式
    return has_explore_intent(text)
