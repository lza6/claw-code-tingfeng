"""Planner Agent — 战略规划专家

对应 oh-my-codex 的 Planner 角色：
- 将请求转换为可执行的实施计划
- 生成任务分解、里程碑、验收标准
- 不直接编码，只输出规划文档
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


class PlannerAgent(BaseAgent):
    """Planner Agent — 负责将需求转化为可执行的实施计划"""

    def __init__(
        self,
        agent_id: str = "planner",
        message_bus: Any | None = None,
        llm_config: LLMConfig | None = None,
    ) -> None:
        from .roles import AgentRole
        super().__init__(
            agent_id=agent_id,
            role=AgentRole.PLANNER,
            message_bus=message_bus,
        )
        self._llm_config = llm_config
        self._engine: AgentEngine | None = None

    def _get_engine(self) -> AgentEngine:
        if self._engine is None:
            if self._llm_config:
                self._engine = create_agent_engine(
                    provider_type=self._llm_config.provider.value,
                    api_key=self._llm_config.api_key,
                    model=self._llm_config.model or 'gpt-4o',
                )
            else:
                self._engine = create_agent_engine()
        return self._engine

    async def plan(self, task: str) -> dict[str, Any]:
        """生成实施计划

        Args:
            task: 任务描述

        Returns:
            包含 plan、prd、test_spec 的规划字典
        """
        engine = self._get_engine()
        prompt = self._build_planning_prompt(task)
        response = await engine.run(prompt)

        # 解析 LLM 响应为结构化规划
        result_text = response.final_result

        # 简单解析：按段落分割
        return {
            "plan": result_text,
            "prd": self._extract_section(result_text, "产品需求") or result_text[:500],
            "test_spec": self._extract_section(result_text, "测试") or "TBD",
            "staffing_plan": self._extract_section(result_text, "人员") or None,
            "verification_plan": self._extract_section(result_text, "验证") or None,
            "risks": [],
        }

    def _build_planning_prompt(self, task: str) -> str:
        system_prompt = ROLE_SYSTEM_PROMPTS.get(AgentRole.PLANNER, '')
        return f"""{system_prompt}

任务: {task}

请输出包含以下章节的规划文档：
## 实施计划
- 步骤分解
- 里程碑

## 产品需求
- 功能列表
- 验收标准

## 测试规范
- 单元测试
- 集成测试

## 人员配置（可选）

## 验证计划（可选）

## 风险识别
"""

    def _extract_section(self, text: str, keyword: str) -> str | None:
        """从文本中提取包含关键词的章节"""
        lines = text.split('\n')
        capture = False
        section_lines = []
        for line in lines:
            if any(k in line.lower() for k in [f'## {keyword}', f'{keyword}', f'**{keyword}**']):
                capture = True
                continue
            if capture:
                if line.startswith('##') and keyword not in line.lower():
                    break
                section_lines.append(line)
        return '\n'.join(section_lines).strip() if section_lines else None

    async def process(self, message: Any) -> str:
        """处理消息 (BaseAgent 接口)"""
        task = getattr(message, 'content', str(message))
        result = await self.plan(task)
        import json
        return json.dumps(result, ensure_ascii=False, indent=2)


__all__ = ['PlannerAgent']
