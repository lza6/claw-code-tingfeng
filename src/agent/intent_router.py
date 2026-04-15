"""
Intent Router - 意图路由与关键词检测

从 oh-my-codex-main 汲取的关键词检测引擎。
提供技能激活、任务规模和意图检测能力。
"""

import re
import json
import os
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path


# ===== 关键词注册表 =====
KEYWORD_TRIGGER_DEFINITIONS = [
    {"keyword": "deepsearch", "skill": "deepsearch", "priority": 10},
    {"keyword": "deep interview", "skill": "deep-interview", "priority": 20},
    {"keyword": "analyze", "skill": "analyze", "priority": 5},
    {"keyword": "plan", "skill": "plan", "priority": 15},
    {"keyword": "build", "skill": "build-fix", "priority": 8},
    {"keyword": "fix", "skill": "build-fix", "priority": 9},
    {"keyword": "review", "skill": "code-review", "priority": 12},
    {"keyword": "security", "skill": "security-review", "priority": 14},
    {"keyword": "test", "skill": "tdd", "priority": 7},
    {"keyword": "team", "skill": "team", "priority": 25},
    {"keyword": "swarm", "skill": "swarm", "priority": 25},
    {"keyword": "ralph", "skill": "ralph", "priority": 30},
    {"keyword": "ralplan", "skill": "ralplan", "priority": 22},
    {"keyword": "doctor", "skill": "doctor", "priority": 6},
    {"keyword": "help", "skill": "help", "priority": 1},
    {"keyword": "cancel", "skill": "cancel", "priority": 50},
]


# ===== 数据类 =====
@dataclass
class KeywordMatch:
    keyword: str
    skill: str
    priority: int


@dataclass
class SkillActiveState:
    version: int = 1
    active: bool = False
    skill: str = ""
    keyword: str = ""
    phase: str = "planning"  # planning, executing, reviewing, completing
    activated_at: str = ""
    updated_at: str = ""
    source: str = "keyword-detector"
    session_id: Optional[str] = None
    thread_id: Optional[str] = None
    turn_id: Optional[str] = None


# ===== 任务规模检测 =====
class TaskSize:
    """任务规模枚举"""
    TRIVIAL = "trivial"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    HEAVY = "heavy"


@dataclass
class TaskSizeResult:
    size: str
    confidence: float
    factors: dict


# ===== 核心函数 =====
def escape_regex(text: str) -> str:
    """转义正则特殊字符"""
    return re.sub(r'[.*+?^${}()|[\]\\]', r'\\$&', text)


def is_word_char(ch: str) -> bool:
    """检查是否为单词字符"""
    return bool(ch and re.match(r'[A-Za-z0-9_]', ch))


def keyword_to_pattern(keyword: str) -> re.Pattern:
    """将关键词转换为正则模式"""
    escaped = escape_regex(keyword)
    starts_with_word = is_word_char(keyword[0]) if keyword else False
    ends_with_word = is_word_char(keyword[-1]) if keyword else False
    prefix = r'\b' if starts_with_word else ''
    suffix = r'\b' if ends_with_word else ''
    return re.compile(f'{prefix}{escaped}{suffix}', re.IGNORECASE)


# 构建关键词模式映射
KEYWORD_MAP = [
    {
        "pattern": keyword_to_pattern(entry["keyword"]),
        "skill": entry["skill"],
        "priority": entry["priority"]
    }
    for entry in KEYWORD_TRIGGER_DEFINITIONS
]

KEYWORDS_REQUIRING_INTENT = {"team", "swarm"}

TEAM_SWARM_INTENT_PATTERNS = {
    "team": [
        re.compile(r'(?:^|[^\w])\$(?:team)\b', re.IGNORECASE),
        re.compile(r'/prompts:team\b', re.IGNORECASE),
        re.compile(r'\b(?:use|run|start|enable|launch|invoke|activate|orchestrate|coordinate)\s+(?:a\s+|an\s+|the\s+)?team\b', re.IGNORECASE),
        re.compile(r'\bteam\s+(?:mode|orchestration|workflow|agents?)\b', re.IGNORECASE),
    ],
    "swarm": [
        re.compile(r'(?:^|[^\w])\$(?:swarm)\b', re.IGNORECASE),
        re.compile(r'/prompts:swarm\b', re.IGNORECASE),
        re.compile(r'\b(?:use|run|start|enable|launch|invoke|activate|orchestrate|coordinate)\s+(?:a\s+|an\s+|the\s+)?swarm\b', re.IGNORECASE),
        re.compile(r'\bswarm\s+(?:mode|orchestration|workflow|agents?)\b', re.IGNORECASE),
    ],
}


def has_explicit_prompts_invocation(text: str) -> bool:
    """检查是否有显式的 /prompts:skill 调用"""
    return bool(re.search(r'(?:^|\s)/prompts:[\w.-]+(?=[\s.,!?;:]|$)', text, re.IGNORECASE))


def extract_explicit_skill_invocations(text: str) -> list[KeywordMatch]:
    """提取显式的 $skill 调用"""
    results = []
    # 匹配 $skill 格式
    pattern = re.compile(r'(?:^|[^\w])\$([a-z][a-z0-9-]*)\b', re.IGNORECASE)

    for match in pattern.finditer(text):
        token = (match.group(1) or '').lower()
        if not token:
            continue

        # swarm -> team 映射
        normalized_skill = 'team' if token == 'swarm' else token

        # 查找对应的注册表条目
        registry_entry = next(
            (entry for entry in KEYWORD_TRIGGER_DEFINITIONS
             if entry["skill"].lower() == normalized_skill),
            None
        )
        if not registry_entry:
            continue

        if not any(item.skill == normalized_skill for item in results):
            results.append(KeywordMatch(
                keyword=f'${token}',
                skill=normalized_skill,
                priority=registry_entry["priority"]
            ))

    return results


def has_intent_context_for_keyword(text: str, keyword: str) -> bool:
    """检查关键词是否有适当的意图上下文"""
    if keyword.lower() not in KEYWORDS_REQUIRING_INTENT:
        return True
    k = keyword.lower()
    if k not in TEAM_SWARM_INTENT_PATTERNS:
        return True
    return any(p.search(text) for p in TEAM_SWARM_INTENT_PATTERNS[k])


def detect_keywords(text: str) -> list[KeywordMatch]:
    """
    检测用户输入中的关键词
    返回显式 $skill 调用优先，然后是隐式关键词按优先级排序
    """
    # 优先处理显式调用
    explicit = extract_explicit_skill_invocations(text)
    if has_explicit_prompts_invocation(text) and not explicit:
        return []

    if explicit:
        return explicit

    # 检测隐式关键词
    implicit = []
    for item in KEYWORD_MAP:
        match = item["pattern"].search(text)
        if match:
            if not has_intent_context_for_keyword(text, match.group(0)):
                continue
            implicit.append(KeywordMatch(
                keyword=match.group(0),
                skill=item["skill"],
                priority=item["priority"]
            ))

    # 合并结果
    merged = list(explicit)
    # 按优先级排序
    sorted_implicit = sorted(implicit, key=lambda x: x.priority, reverse=True)
    for item in sorted_implicit:
        if not any(existing.skill == item.skill for existing in merged):
            merged.append(item)

    return merged


def detect_primary_keyword(text: str) -> Optional[KeywordMatch]:
    """获取最高优先级的关键词匹配"""
    matches = detect_keywords(text)
    return matches[0] if matches else None


# ===== 任务规模检测 =====
def detect_task_size(text: str) -> TaskSizeResult:
    """
    检测任务规模
    基于文本长度、复杂度和关键词进行判断
    """
    text_lower = text.lower()
    word_count = len(text.split())

    # 默认因素
    factors = {
        "word_count": word_count,
        "has_code": "code" in text_lower or "function" in text_lower,
        "has_refactor": "refactor" in text_lower or "reorganize" in text_lower,
        "has_security": "security" in text_lower or "vulnerable" in text_lower,
        "has_database": "database" in text_lower or "query" in text_lower,
    }

    # 复杂度计算
    complexity_score = 0
    if word_count > 100:
        complexity_score += 3
    elif word_count > 50:
        complexity_score += 2
    elif word_count > 20:
        complexity_score += 1

    if factors["has_code"]:
        complexity_score += 2
    if factors["has_refactor"]:
        complexity_score += 2
    if factors["has_security"]:
        complexity_score += 3
    if factors["has_database"]:
        complexity_score += 2

    # 判断规模
    if complexity_score >= 8:
        size = TaskSize.HEAVY
        confidence = 0.9
    elif complexity_score >= 5:
        size = TaskSize.LARGE
        confidence = 0.8
    elif complexity_score >= 3:
        size = TaskSize.MEDIUM
        confidence = 0.7
    elif complexity_score >= 1:
        size = TaskSize.SMALL
        confidence = 0.6
    else:
        size = TaskSize.TRIVIAL
        confidence = 0.5

    return TaskSizeResult(size=size, confidence=confidence, factors=factors)


# ===== 技能激活状态管理 =====
SKILL_ACTIVE_STATE_FILE = "skill-active-state.json"


def read_skill_active_state(state_dir: str) -> Optional[SkillActiveState]:
    """读取技能激活状态"""
    state_path = Path(state_dir) / SKILL_ACTIVE_STATE_FILE
    try:
        if state_path.exists():
            with open(state_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return SkillActiveState(**data)
    except Exception:
        pass
    return None


def write_skill_active_state(state_dir: str, state: SkillActiveState) -> bool:
    """写入技能激活状态"""
    state_path = Path(state_dir) / SKILL_ACTIVE_STATE_FILE
    try:
        with open(state_path, 'w', encoding='utf-8') as f:
            json.dump(asdict(state), f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[intent_router] warning: failed to persist skill active state: {e}")
        return False


def record_skill_activation(
    text: str,
    state_dir: str,
    session_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    turn_id: Optional[str] = None,
) -> Optional[SkillActiveState]:
    """
    记录技能激活状态
    从用户输入中检测关键词并更新状态
    """
    now = datetime.now().isoformat()
    match = detect_primary_keyword(text)
    if not match:
        return None

    # 读取之前的状态
    previous = read_skill_active_state(state_dir)

    # 检测取消意图
    keywords = detect_keywords(text)
    has_cancel_intent = any(k.skill == "cancel" for k in keywords)

    # 如果有取消意图
    if has_cancel_intent and previous and previous.active:
        state = SkillActiveState(
            active=False,
            skill=previous.skill,
            keyword=previous.keyword,
            phase="completing",
            activated_at=previous.activated_at,
            updated_at=now,
            source="keyword-detector",
            session_id=session_id or previous.session_id,
            thread_id=thread_id or previous.thread_id,
            turn_id=turn_id or previous.turn_id,
        )
        write_skill_active_state(state_dir, state)
        return state

    # 确定激活时间
    same_skill = previous and previous.active and previous.skill == match.skill
    same_keyword = previous and previous.keyword.lower() == match.keyword.lower()
    activated_at = previous.activated_at if (same_skill and same_keyword) else now

    # 创建新状态
    state = SkillActiveState(
        active=True,
        skill=match.skill,
        keyword=match.keyword,
        phase="planning",
        activated_at=activated_at,
        updated_at=now,
        source="keyword-detector",
        session_id=session_id,
        thread_id=thread_id,
        turn_id=turn_id,
    )

    write_skill_active_state(state_dir, state)
    return state


# ===== 便捷函数 =====
def classify_intent(text: str) -> str:
    """
    分类意图类型
    返回: explore, implement, evolve, debate, deliver
    """
    text_lower = text.lower()

    # 辩论模式
    if any(w in text_lower for w in ["debate", "argue", "challenge", "disagree", "review"]):
        return "debate"

    # 探索模式
    if any(w in text_lower for w in ["find", "search", "explore", "analyze", "look"]):
        return "explore"

    # 演进模式
    if any(w in text_lower for w in ["improve", "evolve", "enhance", "optimize"]):
        return "evolve"

    # 实现模式
    if any(w in text_lower for w in ["implement", "add", "create", "build", "fix"]):
        return "implement"

    # 默认传递模式
    return "deliver"


# ===== 导出 =====
__all__ = [
    "KeywordMatch",
    "SkillActiveState",
    "TaskSizeResult",
    "TaskSize",
    "detect_keywords",
    "detect_primary_keyword",
    "detect_task_size",
    "classify_intent",
    "record_skill_activation",
    "read_skill_active_state",
    "write_skill_active_state",
]