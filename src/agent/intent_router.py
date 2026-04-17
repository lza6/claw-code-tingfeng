"""
Intent Router - 意图路由

从 oh-my-codex-main 汲取的意图分类系统。
提供五种意图类型：DELIVER, EXPLORE, EVOLVE, IMPLEMENT, DEBATE。

注意: 此模块专注于意图分类，不重复实现关键词检测和任务规模检测。
请使用 keyword_registry 和 task_size_detector 模块。

参考:
- oh-my-codex-main/src/agent/router.ts
- oh-my-codex-main/src/agent/intent.rs
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional


class IntentType(str, Enum):
    """意图类型枚举（借鉴 oh-my-codex）"""
    DELIVER = "deliver"       # 交付/执行
    EXPLORE = "explore"       # 探索/分析
    EVOLVE = "evolve"         # 演进/优化
    IMPLEMENT = "implement"   # 实现/新增
    DEBATE = "debate"         # 辩论/审查


# 意图关键词映射（从 oh-my-codex 汲取）
INTENT_PATTERNS: dict[IntentType, list[re.Pattern]] = {
    IntentType.DELIVER: [
        re.compile(r'\b(deliver|complete|finish|execute|run)\b', re.I),
    ],
    IntentType.EXPLORE: [
        re.compile(r'\b(explore|search|find|analyze|investigate|discover|look)\b', re.I),
    ],
    IntentType.EVOLVE: [
        re.compile(r'\b(evolve|improve|enhance|optimize|refine|upgrade)\b', re.I),
    ],
    IntentType.IMPLEMENT: [
        re.compile(r'\b(implement|add|create|build|make|develop|write)\b', re.I),
    ],
    IntentType.DEBATE: [
        re.compile(r'\b(debate|review|critique|challenge|disagree|argue|question)\b', re.I),
    ],
}


def classify_intent(text: str) -> str:
    """
    分类用户输入意图类型（单一结果）。

    优先级顺序（按此顺序匹配，返回第一个匹配）:
    1. DEBATE - "debate", "review", "challenge" 等
    2. EXPLORE - "explore", "search", "find" 等
    3. EVOLVE - "improve", "optimize", "enhance" 等
    4. IMPLEMENT - "implement", "add", "build" 等
    5. DELIVER - 默认（execute, run 等）

    Args:
        text: 用户输入文本

    Returns:
        意图类型字符串: "deliver" | "explore" | "evolve" | "implement" | "debate"
    """
    text_lower = text.lower()

    # 按优先级顺序检查
    for intent_type, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(text_lower):
                return intent_type.value

    # 默认返回 deliver
    return IntentType.DELIVER.value


def classify_intent_ranked(text: str) -> list[tuple[str, float]]:
    """
    返回所有匹配的意图及其置信度得分（降序）。

    用于需要多意图支持或置信度区分的场景。

    Args:
        text: 用户输入文本

    Returns:
        List of (intent_type, confidence_score)，按置信度降序排列
    """
    scores: dict[str, float] = {intent.value: 0.0 for intent in IntentType}

    for intent_type, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            matches = pattern.findall(text_lower)
            if matches:
                # 匹配数越多，置信度越高
                scores[intent_type.value] += len(matches) * 0.3

    # 过滤掉零分并排序
    scored = [(intent, score) for intent, score in scores.items() if score > 0]
    scored.sort(key=lambda x: x[1], reverse=True)

    return scored if scored else [(IntentType.DELIVER.value, 1.0)]


def has_explicit_debate_intent(text: str) -> bool:
    """
    检测是否包含明确的辩论/审查意图。

    Args:
        text: 用户输入文本

    Returns:
        True 如果文本包含明确的辩论关键词
    """
    debate_keywords = [
        r'\b(debate|review|critique|challenge|disagree|argue|question)\b',
        r'\b(security|performance|quality)\s+(review|audit)\b',
        r'\bcode\s+review\b',
        r'\bimprove\s+this\b',
    ]
    text_lower = text.lower()
    return any(re.search(pattern, text_lower, re.I) for pattern in debate_keywords)


def get_primary_intent(text: str) -> str:
    """
    获取主要意图（classify_intent 的别名，保持向后兼容）。

    Args:
        text: 用户输入文本

    Returns:
        主要意图类型
    """
    return classify_intent(text)


# ===== 导出 =====

__all__ = [
    "IntentType",
    "classify_intent",
    "classify_intent_ranked",
    "has_explicit_debate_intent",
    "get_primary_intent",
]
