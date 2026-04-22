"""Synthesized Agent — 动态合成专家代理 (汲取自 Project B)

核心功能：
1. 动态身份识别：根据任务描述自动匹配最合适的技能。
2. 技能热加载：从 skills/ 目录加载技能定义并注入 System Prompt。
3. 角色代入：完全代入特定技能所要求的专家身份、约束和执行流。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from .base_agent import BaseAgent
from .message_bus import AgentMessage, MessageBus
from .roles import ROLE_SYSTEM_PROMPTS, AgentRole

logger = logging.getLogger("agent.synthesized")

class SynthesizedAgent(BaseAgent):
    def __init__(
        self,
        agent_id: str,
        message_bus: MessageBus,
        dynamic_instruction: str = "",
        skill_name: str | None = None
    ) -> None:
        super().__init__(agent_id, AgentRole.SYNTHESIZED, message_bus)
        self.dynamic_instruction = dynamic_instruction
        self.skill_name = skill_name
        self.skills_dir = Path("skills")
        self._refresh_system_prompt()

    def _refresh_system_prompt(self) -> None:
        """根据动态指令或技能名称刷新 System Prompt"""
        base_prompt = ROLE_SYSTEM_PROMPTS.get(AgentRole.SYNTHESIZED, "")

        skill_context = ""
        if self.skill_name:
            skill_path = self.skills_dir / self.skill_name / "SKILL.md"
            if not skill_path.exists():
                skill_path = self.skills_dir / self.skill_name / "README.md"

            if skill_path.exists():
                try:
                    skill_content = skill_path.read_text(encoding='utf-8')
                    # 提取核心内容 (去除元数据)
                    content = re.sub(r'^---.*?---', '', skill_content, flags=re.DOTALL)
                    skill_context = f"\n[已加载技能: {self.skill_name}]:\n{content.strip()}"
                    logger.info(f"SynthesizedAgent {self.agent_id} 成功加载技能: {self.skill_name}")
                except Exception as e:
                    logger.error(f"加载技能 {self.skill_name} 失败: {e}")

        self.system_prompt = base_prompt.format(
            dynamic_instruction=f"{self.dynamic_instruction}\n{skill_context}"
        )

    async def process(self, message: AgentMessage) -> str:
        """执行动态代理逻辑"""
        # 汲取 GoalX/Project B: 如果消息元数据中指定了新技能，则动态切换
        new_skill = message.metadata.get("skill_name")
        if new_skill and new_skill != self.skill_name:
            logger.info(f"SynthesizedAgent {self.agent_id} 正在动态切换到新技能: {new_skill}")
            self.skill_name = new_skill
            self._refresh_system_prompt()

        from ..factory import create_agent_engine
        engine = create_agent_engine()

        full_prompt = f"{self.system_prompt}\n\n[当前任务消息]:\n{message.content}"

        try:
            session = await engine.run(full_prompt)
            return session.final_result
        except Exception as e:
            logger.error(f"SynthesizedAgent 执行失败: {e}")
            return f"Error: {e}"
