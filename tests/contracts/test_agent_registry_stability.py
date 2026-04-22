"""
Agent 注册表稳定性契约测试

确保核心 Agent 定义不会被意外移除或修改。
这些 Agent 是公共 API 的一部分，任何变更都需要迁移指南。

来源: oh-my-codex dist/cli/__tests__/catalog-contract.test.ts
"""

import pytest


class TestAgentRegistryStability:
    """验证 Agent 注册表的稳定性"""

    def test_core_agents_exist(self):
        """核心 Agent 应保持存在"""
        from src.agent.definitions import AGENT_DEFINITIONS

        # 这些是基础 Agent，不应被移除
        core_agents = [
            "explore",
            "planner",
            "executor",
            "verifier",
            "architect",
            "debugger",
        ]

        for agent_name in core_agents:
            assert agent_name in AGENT_DEFINITIONS, \
                f"Core agent '{agent_name}' should not be removed"

    def test_agent_definition_structure(self):
        """Agent 定义应保持稳定的结构"""
        from src.agent.definitions import AgentDefinition

        # 检查一个示例 Agent
        explore = AgentDefinition(
            name="test",
            description="Test agent",
            reasoning_effort="low",
            posture="fast-lane",
            model_class="fast",
            routing_role="specialist",
            tools="read-only",
            category="build",
        )

        # 所有必需字段应存在
        assert hasattr(explore, 'name')
        assert hasattr(explore, 'description')
        assert hasattr(explore, 'reasoning_effort')
        assert hasattr(explore, 'posture')
        assert hasattr(explore, 'model_class')
        assert hasattr(explore, 'routing_role')
        assert hasattr(explore, 'tools')
        assert hasattr(explore, 'category')

    def test_agent_posture_enum_values_stable(self):
        """AgentPosture 枚举值应保持稳定"""
        from src.agent.definitions import AgentPosture

        assert AgentPosture.FRONTIER_ORCHESTRATOR.value == "frontier-orchestrator"
        assert AgentPosture.DEEP_WORKER.value == "deep-worker"
        assert AgentPosture.FAST_LANE.value == "fast-lane"

    def test_agent_model_class_enum_values_stable(self):
        """AgentModelClass 枚举值应保持稳定"""
        from src.agent.definitions import AgentModelClass

        assert AgentModelClass.FRONTIER.value == "frontier"
        assert AgentModelClass.STANDARD.value == "standard"
        assert AgentModelClass.FAST.value == "fast"

    def test_agent_routing_role_enum_values_stable(self):
        """AgentRoutingRole 枚举值应保持稳定"""
        from src.agent.definitions import AgentRoutingRole

        assert AgentRoutingRole.LEADER.value == "leader"
        assert AgentRoutingRole.SPECIALIST.value == "specialist"
        assert AgentRoutingRole.EXECUTOR.value == "executor"

    def test_agent_category_enum_values_stable(self):
        """AgentCategory 枚举值应保持稳定"""
        from src.agent.definitions import AgentCategory

        assert AgentCategory.BUILD.value == "build"
        assert AgentCategory.REVIEW.value == "review"
        assert AgentCategory.DOMAIN.value == "domain"
        assert AgentCategory.PRODUCT.value == "product"
        assert AgentCategory.COORDINATION.value == "coordination"

    def test_agent_definitions_have_required_fields(self):
        """所有 Agent 定义应有完整的必需字段"""
        from src.agent.definitions import AGENT_DEFINITIONS

        for name, agent in AGENT_DEFINITIONS.items():
            assert agent.name, f"Agent '{name}' must have a name"
            assert agent.description, f"Agent '{name}' must have a description"
            assert agent.reasoning_effort in ["low", "medium", "high"], \
                f"Agent '{name}' has invalid reasoning_effort"
            assert agent.posture in ["frontier-orchestrator", "deep-worker", "fast-lane"], \
                f"Agent '{name}' has invalid posture"
            assert agent.model_class in ["frontier", "standard", "fast"], \
                f"Agent '{name}' has invalid model_class"
            assert agent.routing_role in ["leader", "specialist", "executor"], \
                f"Agent '{name}' has invalid routing_role"
            assert agent.tools in ["read-only", "analysis", "execution", "data"], \
                f"Agent '{name}' has invalid tools"
            assert agent.category in ["build", "review", "domain", "product", "coordination"], \
                f"Agent '{name}' has invalid category"

    def test_helper_functions_exist(self):
        """辅助函数应保持稳定"""
        from src.agent.definitions import (
            get_agent,
            get_agents_by_category,
            get_agent_names,
        )

        assert callable(get_agent)
        assert callable(get_agents_by_category)
        assert callable(get_agent_names)

    def test_get_agent_returns_correct_type(self):
        """get_agent 函数应返回正确的类型"""
        from src.agent.definitions import get_agent, AgentDefinition

        result = get_agent("explore")
        assert result is None or isinstance(result, AgentDefinition)

    def test_get_agent_names_returns_list(self):
        """get_agent_names 应返回列表"""
        from src.agent.definitions import get_agent_names

        names = get_agent_names()
        assert isinstance(names, list)
        assert len(names) > 0
        assert all(isinstance(name, str) for name in names)

    def test_explore_agent_is_read_only(self):
        """explore Agent 应为只读类型"""
        from src.agent.definitions import get_agent

        explore = get_agent("explore")
        assert explore is not None
        assert explore.tools == "read-only"

    def test_executor_agent_has_execution_tools(self):
        """executor Agent 应具有执行工具访问权限"""
        from src.agent.definitions import get_agent

        executor = get_agent("executor")
        assert executor is not None
        assert executor.tools == "execution"

    def test_architect_agent_is_frontier_model(self):
        """architect Agent 应使用前沿模型"""
        from src.agent.definitions import get_agent

        architect = get_agent("architect")
        assert architect is not None
        assert architect.model_class == "frontier"
