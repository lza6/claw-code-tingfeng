"""AgentSession 测试 - Agent 会话管理"""
from __future__ import annotations

import pytest

from src.agent.engine_session_data import AgentSession, AgentStep


class TestAgentStepCreation:
    """AgentStep 创建测试"""

    def test_create_step_minimal(self):
        """测试创建最小 AgentStep"""
        step = AgentStep(step_type="plan", action="test", result="ok", success=True)
        assert step.step_type == "plan"
        assert step.action == "test"
        assert step.result == "ok"
        assert step.success is True

    def test_create_step_full(self):
        """测试创建完整 AgentStep"""
        step = AgentStep(
            step_type="execute",
            action="run_test",
            result="测试通过",
            success=True,
        )
        assert step.step_type == "execute"
        assert step.action == "run_test"
        assert step.result == "测试通过"
        assert step.success is True

    def test_step_equality(self):
        """测试 Step 相等性（frozen dataclass）"""
        step1 = AgentStep(step_type="plan", action="a", result="r", success=True)
        step2 = AgentStep(step_type="plan", action="a", result="r", success=True)
        step3 = AgentStep(step_type="execute", action="b", result="r", success=True)

        assert step1 == step2
        assert step1 != step3


class TestAgentSessionCreation:
    """AgentSession 创建测试"""

    def test_create_empty_session(self):
        """测试创建空会话"""
        session = AgentSession(goal="测试任务")
        assert session.steps == []
        assert session.total_tokens == 0
        assert session.goal == "测试任务"
        assert session.is_complete is False
        assert session.final_result == ''

    def test_create_session_with_steps(self):
        """测试创建带步骤的会话"""
        steps = [
            AgentStep(step_type="plan", action="a", result="r", success=True),
            AgentStep(step_type="execute", action="b", result="r", success=True),
        ]
        session = AgentSession(goal="任务", steps=steps)
        assert len(session.steps) == 2
        assert session.step_count == 2

    def test_create_session_with_metadata(self):
        """测试创建带元数据的会话"""
        session = AgentSession(
            goal="复杂任务",
            context={"project": "test", "version": "1.0"},
            total_tokens=500,
        )
        assert session.goal == "复杂任务"
        assert session.context["project"] == "test"
        assert session.total_tokens == 500


class TestAgentSessionAddStep:
    """AgentSession 添加步骤测试"""

    def test_add_step(self):
        """测试添加步骤"""
        session = AgentSession(goal="测试")
        step = AgentStep(step_type="plan", action="a", result="r", success=True)
        session.add_step(step)

        assert len(session.steps) == 1
        assert session.steps[0] == step
        assert session.step_count == 1

    def test_add_multiple_steps(self):
        """测试添加多个步骤"""
        session = AgentSession(goal="测试")
        session.add_step(AgentStep(step_type="plan", action="a", result="r", success=True))
        session.add_step(AgentStep(step_type="execute", action="b", result="r", success=True))
        session.add_step(AgentStep(step_type="verify", action="c", result="r", success=True))

        assert len(session.steps) == 3
        assert session.step_count == 3

    def test_last_step(self):
        """测试获取最后一步"""
        session = AgentSession(goal="测试")
        step1 = AgentStep(step_type="plan", action="a", result="r", success=True)
        step2 = AgentStep(step_type="execute", action="b", result="r", success=True)
        session.add_step(step1)
        session.add_step(step2)

        assert session.last_step == step2

    def test_last_step_empty(self):
        """测试空会话的最后一步"""
        session = AgentSession(goal="测试")
        assert session.last_step is None


class TestAgentSessionTokenTracking:
    """AgentSession Token 追踪测试"""

    def test_session_tokens(self):
        """测试设置 Token"""
        session = AgentSession(goal="测试", total_tokens=100)
        assert session.total_tokens == 100

    def test_update_tokens(self):
        """测试更新 Token"""
        session = AgentSession(goal="测试")
        session.total_tokens = 100
        assert session.total_tokens == 100

        session.total_tokens += 200
        assert session.total_tokens == 300


class TestAgentSessionCompletion:
    """AgentSession 完成状态测试"""

    def test_mark_complete(self):
        """测试标记完成"""
        session = AgentSession(goal="测试")
        session.mark_complete("任务完成", success=True)

        assert session.is_complete is True
        assert session.final_result == "任务完成"

    def test_mark_failure(self):
        """测试标记失败"""
        session = AgentSession(goal="测试")
        session.mark_complete("错误信息", success=False)

        assert session.is_complete is True
        assert session.final_result == "错误信息"
        assert session.context.get('error') == "错误信息"


class TestAgentSessionSerialization:
    """AgentSession 序列化测试"""

    def test_to_dict(self):
        """测试转换为字典"""
        session = AgentSession(
            goal="目标",
            total_tokens=500,
        )
        session.add_step(AgentStep(step_type="plan", action="a", result="r", success=True))

        data = session.to_dict()
        assert 'goal' in data
        assert 'total_tokens' in data
        assert data['goal'] == "目标"
        assert data['total_tokens'] == 500
        assert data['step_count'] == 1
        assert data['is_complete'] is False

    def test_to_dict_empty_session(self):
        """测试空会话序列化"""
        session = AgentSession(goal="空任务")
        data = session.to_dict()
        assert data is not None
        assert data['goal'] == "空任务"
        assert data['step_count'] == 0

    def test_to_dict_truncates_result(self):
        """测试长结果截断"""
        session = AgentSession(goal="测试")
        long_result = "x" * 1000
        session.mark_complete(long_result)

        data = session.to_dict()
        assert len(data['final_result']) <= 500


class TestAgentSessionEdgeCases:
    """AgentSession 边界条件测试"""

    def test_large_token_count(self):
        """测试大 Token 数"""
        session = AgentSession(goal="测试", total_tokens=1000000000)
        assert session.total_tokens == 1000000000

    def test_many_steps(self):
        """测试大量步骤"""
        session = AgentSession(goal="测试")
        for i in range(100):
            session.add_step(AgentStep(
                step_type="plan",
                action=f"step_{i}",
                result="r",
                success=True,
            ))

        assert session.step_count == 100

    def test_context_dict_operations(self):
        """测试上下文字典操作"""
        session = AgentSession(goal="测试")
        session.context["key1"] = "value1"
        session.context["key2"] = 42

        assert session.context["key1"] == "value1"
        assert session.context["key2"] == 42
