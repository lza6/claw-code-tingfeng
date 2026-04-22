"""Critic Agent — 批判性审查专家

对应 oh-my-codex 的 Critic 角色：
- 对计划和设计提出挑战
- 识别潜在弱点和风险
- 提供改进建议
"""

from __future__ import annotations

import logging
from typing import Any

from ...llm import LLMConfig
from ..engine import AgentEngine
from ..factory import create_agent_engine
from .base_agent import BaseAgent
from .roles import ROLE_SYSTEM_PROMPTS, AgentRole

logger = logging.getLogger(__name__)


class CriticAgent(BaseAgent):
    """Critic Agent — 负责对计划和设计进行批判性审查"""

    def __init__(
        self,
        agent_id: str = "critic",
        message_bus: Any | None = None,
        llm_config: LLMConfig | None = None,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            role=AgentRole.CRITIC,
            message_bus=message_bus,
        )
        self._llm_config = llm_config
        self._engine: AgentEngine | None = None

    def _get_engine(self) -> AgentEngine:
        if self._engine is None:
            self._engine = create_agent_engine()
        return self._engine

    async def challenge(self, plan: dict[str, Any]) -> dict[str, Any]:
        """对计划进行批判性挑战

        Args:
            plan: 待审查的计划

        Returns:
            包含弱点、问题和改进建议的审查报告
        """
        engine = self._get_engine()
        prompt = self._build_challenge_prompt(plan)
        response = await engine.run(prompt)

        result_text = response.final_result

        return {
            "challenges": self._parse_challenges(result_text),
            "weaknesses": self._extract_section(result_text, "弱点") or [],
            "risks": self._extract_section(result_text, "风险") or [],
            "improvement_suggestions": self._extract_section(result_text, "建议") or [],
            "raw_feedback": result_text,
        }

    def _build_challenge_prompt(self, plan: dict[str, Any]) -> str:
        system_prompt = ROLE_SYSTEM_PROMPTS.get(AgentRole.CRITIC, '')
        plan_text = plan.get('plan', str(plan)) if isinstance(plan, dict) else str(plan)
        return f"""{system_prompt}

请审查以下实施计划并找出潜在问题：

计划内容：
{plan_text[:2000]}

请从以下角度进行批判性分析：
1. 技术可行性
2. 边界情况处理
3. 性能影响
4. 可维护性
5. 安全考虑

输出格式：
- 发现的问题列表
- 每个问题的严重程度（高/中/低）
- 具体的改进建议
"""

    def _parse_challenges(self, text: str) -> list[dict[str, str]]:
        """解析挑战内容"""
        challenges = []
        lines = text.split('\n')
        current = {}
        for line in lines:
            line = line.strip()
            if not line:
                if current:
                    challenges.append(current)
                    current = {}
                continue
            if line.startswith('-') or line.startswith('*'):
                if 'issue' not in current:
                    current['issue'] = line.lstrip('- *').strip()
                elif 'suggestion' not in current:
                    current['suggestion'] = line.lstrip('- *').strip()
            elif ':' in line:
                key, val = line.split(':', 1)
                current[key.strip().lower()] = val.strip()
        if current:
            challenges.append(current)
        return challenges or [{"issue": "未能解析具体问题", "suggestion": "重新审查计划"}]

    def _extract_section(self, text: str, keyword: str) -> list[str] | None:
        """提取章节内容"""
        lines = text.split('\n')
        capture = False
        section = []
        for line in lines:
            if any(k in line.lower() for k in [f'## {keyword}', f'# {keyword}', f'{keyword}', f'**{keyword}**']):
                capture = True
                continue
            if capture:
                if line.startswith('##') and keyword not in line.lower():
                    break
                if line.strip():
                    section.append(line.strip())
        return section if section else None

    async def process(self, message: Any) -> str:
        """处理消息"""
        content = getattr(message, 'content', str(message))
        # 尝试解析为 plan 对象
        import json
        try:
            plan = json.loads(content) if content.startswith('{') else {"plan": content}
        except Exception:
            plan = {"plan": content}
        result = await self.challenge(plan)
        return json.dumps(result, ensure_ascii=False, indent=2)


__all__ = ['CriticAgent']
