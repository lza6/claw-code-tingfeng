"""角色注册完整性测试

回归背景（P0）：`CriticAgent.__init__` 用 `AgentRole.CRITIC`，但枚举里没有这个成员
→ `AttributeError: CRITIC`。而 `ralplan` 的 `enable_critic_challenge` 默认为 True，
等于 `clawd workflow ralplan` 默认参数必崩。测试零覆盖，所以一直没被发现。

这里做两件事：
1. 静态扫描：`src/` 里所有 `AgentRole.XXX` 引用必须都是真实枚举成员；
2. 动态构造：`CriticAgent()` 必须能实例化。
"""

from __future__ import annotations

import re
from pathlib import Path

from src.agent.swarm.critic_agent import CriticAgent
from src.agent.swarm.roles import ROLE_DESCRIPTIONS, ROLE_SYSTEM_PROMPTS, AgentRole

SRC = Path(__file__).resolve().parents[3] / "src"


class TestAgentRoleEnum:
    def test_critic_member_exists(self):
        assert AgentRole.CRITIC.value == "critic"

    def test_every_role_has_description_and_prompt(self):
        missing_desc = [r for r in AgentRole if r not in ROLE_DESCRIPTIONS]
        missing_prompt = [r for r in AgentRole if r not in ROLE_SYSTEM_PROMPTS]
        assert missing_desc == []
        assert missing_prompt == []

    def test_all_role_references_in_src_resolve(self):
        """任何 `AgentRole.X` 引用都必须是枚举成员（否则运行期 AttributeError）"""
        pattern = re.compile(r"AgentRole\.([A-Z_][A-Z0-9_]*)")
        known = {r.name for r in AgentRole}
        broken: list[str] = []
        for path in SRC.rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if "AgentRole." not in text:
                continue
            for name in set(pattern.findall(text)):
                if name not in known:
                    broken.append(f"{path.relative_to(SRC.parent)}: AgentRole.{name}")
        assert broken == [], f"引用了不存在的 AgentRole: {broken}"


class TestCriticAgentConstruction:
    def test_constructs_without_attribute_error(self):
        agent = CriticAgent()
        assert agent.agent_id == "critic"

    def test_role_is_critic(self):
        agent = CriticAgent()
        assert agent.role is AgentRole.CRITIC

    def test_challenge_prompt_uses_real_role_prompt(self):
        agent = CriticAgent()
        prompt = agent._build_challenge_prompt({"plan": "做点事"})
        # 角色系统提示不能为空（曾因枚举缺失而 get 到空串）
        assert "批判" in prompt
        assert "做点事" in prompt

    def test_ralplan_stage_default_enables_critic(self):
        """ralplan 默认开启挑战分支 —— 所以 CriticAgent 构造失败等于默认路径崩"""
        from src.workflow.stages.ralplan_stage import RalplanStage

        stage = RalplanStage()
        assert stage.enable_critic_challenge is True

    def test_critic_import_paths_are_same_class(self):
        """`swarm.critic` 是 `swarm.critic_agent` 的重定向，不能漂移成两份实现"""
        from src.agent.swarm import critic as critic_module

        assert critic_module.CriticAgent is CriticAgent
