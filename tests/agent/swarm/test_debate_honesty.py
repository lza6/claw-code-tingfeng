"""DebateEngine 诚实性测试（回归：缺 orchestrator 时返回 "[模拟 CRITIC 响应] ..."）

旧实现把占位符字符串当成"辩论总结"返回，调用方（workflow planner）直接
`logger.info(f"辩论共识总结: {summary}")` 打印出去 —— 用户以为看到了评审意见。
现在没有 orchestrator / 调用失败都抛 `DebateUnavailable`，由调用方按失败处理。
"""

from __future__ import annotations

import asyncio

import pytest

from src.agent.swarm.debate import DebateEngine, DebateRole, DebateUnavailable


class TestDebateWithoutOrchestrator:
    def test_construct_without_orchestrator(self):
        assert DebateEngine().orchestrator is None

    def test_conduct_debate_raises_instead_of_faking(self):
        engine = DebateEngine()
        with pytest.raises(DebateUnavailable):
            asyncio.run(engine.conduct_debate(context="c", proposal="p"))

    def test_get_agent_response_raises_with_role_in_message(self):
        engine = DebateEngine()
        with pytest.raises(DebateUnavailable) as exc:
            asyncio.run(engine._get_agent_response(DebateRole.CRITIC, "审查这个计划"))
        assert "critic" in str(exc.value)

    def test_no_mock_string_is_returned(self):
        """确认返回体里不再出现"[模拟 ...]"占位符"""
        engine = DebateEngine()
        try:
            text = asyncio.run(engine._get_agent_response(DebateRole.ADVOCATE, "p"))
        except DebateUnavailable:
            return  # 期望路径
        pytest.fail(f"未抛错，返回了可疑内容: {text!r}")


class _FailingOrchestrator:
    async def execute_task_simple(self, task_prompt: str, role_hint: str) -> str:
        raise RuntimeError("LLM 不可达")


class _EchoOrchestrator:
    async def execute_task_simple(self, task_prompt: str, role_hint: str) -> str:
        return f"[{role_hint}] 真实响应"


class TestDebateWithOrchestrator:
    def test_orchestrator_failure_is_not_swallowed(self):
        engine = DebateEngine(orchestrator=_FailingOrchestrator())
        with pytest.raises(DebateUnavailable) as exc:
            asyncio.run(engine._get_agent_response(DebateRole.CRITIC, "p"))
        assert "RuntimeError" in str(exc.value)

    def test_real_orchestrator_response_passes_through(self):
        engine = DebateEngine(orchestrator=_EchoOrchestrator())
        text = asyncio.run(engine._get_agent_response(DebateRole.ADVOCATE, "p"))
        assert text == "[advocate] 真实响应"
