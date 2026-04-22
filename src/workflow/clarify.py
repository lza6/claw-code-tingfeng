"""Clarify Gate — 意图澄清模块 (汲取自 Project B $deep-interview)

核心目标：在任务开始前，通过苏格拉底式提问明确意图、非目标和约束，防止无效交付。
"""
from __future__ import annotations

import logging
from typing import Any

from ..llm.model_manager import ModelManager

logger = logging.getLogger("workflow.clarify")

CLARIFY_PROMPT = """你是一个严谨的软件需求分析专家。你的目标是分析用户的原始需求，并识别其中的模糊点。
你需要进行“苏格拉底式提问 (Socratic Questioning)”来澄清意图。

## 分析维度:
1. 意图 (Intent): 用户真正想解决的问题是什么？
2. 范围 (Scope): 包含哪些模块？
3. 非目标 (Non-goals): 哪些是明确不需要做的？(极其重要)
4. 约束 (Constraints): 必须遵循的模式、库或性能要求。

## 原始需求:
{user_goal}

## 输出要求:
请输出一个 JSON 对象，包含：
1. "clarity_score": 0-1 之间的得分 (1 表示非常清晰，0.5 以下需要强制提问)。
2. "ambiguous_points": 模糊点列表。
3. "suggested_questions": 针对模糊点的提问。
4. "draft_contract": 如果得分较高，请提供一份初步的契约草案，包含 non_goals 和 constraints。

格式:
{{
  "clarity_score": 0.8,
  "ambiguous_points": ["...", "..."],
  "suggested_questions": ["...", "..."],
  "draft_contract": {{
    "non_goals": ["...", "..."],
    "constraints": ["...", "..."]
  }}
}}
"""

class ClarifyGate:
    """意图澄清门禁"""

    def __init__(self, model_manager: ModelManager):
        self.model_manager = model_manager

    async def analyze_intent(self, user_goal: str) -> dict[str, Any]:
        """分析用户意图清晰度"""
        logger.info("正在进行意图清晰度分析...")
        prompt = CLARIFY_PROMPT.format(user_goal=user_goal)

        try:
            response = await self.model_manager.generate_json(
                prompt=prompt,
                model_id="claude-sonnet-4-6"
            )
            return response
        except Exception as e:
            logger.error(f"意图分析失败: {e}")
            return {
                "clarity_score": 0.5,
                "ambiguous_points": ["分析过程出错"],
                "suggested_questions": ["请详细描述您的需求。"],
                "draft_contract": {"non_goals": [], "constraints": []}
            }

    def should_ask_user(self, analysis: dict[str, Any]) -> bool:
        """判断是否需要向用户提问"""
        return analysis.get("clarity_score", 1.0) < 0.7
