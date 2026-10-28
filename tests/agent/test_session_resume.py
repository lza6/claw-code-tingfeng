"""会话续跑：prior_messages 注入 + session resume CLI"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.agent.engine import _normalize_prior_messages
from src.agent.engine_loop import AgentLoopConfig, build_initial_messages
from src.cli.entrypoint import app
from src.core.session_bridge import persist_agent_session

runner = CliRunner()


def _config(**kwargs) -> AgentLoopConfig:
    base = dict(
        goal="当前任务", llm_provider=None, messages=[], max_iterations=1,
        system_prompt="SYSTEM", tools={},
    )
    base.update(kwargs)
    return AgentLoopConfig(**base)


class TestBuildInitialMessages:
    def test_without_prior_is_system_then_user(self):
        msgs = build_initial_messages(_config(), "本次目标")

        assert [m.role for m in msgs] == ["system", "user"]
        assert msgs[0].content == "SYSTEM"
        assert "本次目标" in msgs[1].content

    def test_prior_inserted_between_system_and_new_goal(self):
        from src.llm.config import LLMMessage

        prior = [
            LLMMessage(role="user", content="上次：实现登录"),
            LLMMessage(role="assistant", content="上次：已写完 API"),
        ]
        msgs = build_initial_messages(_config(prior_messages=prior), "现在补测试")

        assert [m.role for m in msgs] == ["system", "user", "assistant", "user"]
        assert msgs[-1].content == "现在补测试" or "现在补测试" in msgs[-1].content

    def test_empty_prior_entries_skipped(self):
        from src.llm.config import LLMMessage

        prior = [LLMMessage(role="user", content=""), LLMMessage(role="user", content="有效")]
        msgs = build_initial_messages(_config(prior_messages=prior), "新目标")

        assert len(msgs) == 3  # system + 1 有效 prior + user


class TestNormalizePrior:
    def test_dicts_converted(self):
        out = _normalize_prior_messages([
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
        ])

        assert [m.role for m in out] == ["user", "assistant"]
        assert out[1].content == "b"

    def test_unknown_role_becomes_user(self):
        out = _normalize_prior_messages([{"role": "unknown", "content": "x"}])
        assert out[0].role == "user"

    def test_empty_content_dropped(self):
        assert _normalize_prior_messages([{"role": "user", "content": ""}]) is None

    def test_none_returns_none(self):
        assert _normalize_prior_messages(None) is None
        assert _normalize_prior_messages([]) is None

    def test_objects_passed_through(self):
        from src.llm.config import LLMMessage

        msg = LLMMessage(role="user", content="x")
        assert _normalize_prior_messages([msg]) == [msg]


class TestResumeCli:
    def test_resume_injects_history_into_engine(self, tmp_path: Path, monkeypatch):
        """CLI resume 必须把历史消息传给 engine.run(prior_messages=...)"""
        persist_agent_session(
            "s-resume", "上次的任务", [{"role": "assistant", "content": "上次的结论"}],
            final_result="完成", directory=tmp_path,
        )
        captured = {}

        class _FakeSession:
            final_result = "续跑完成"

        class _FakeEngine:
            def __init__(self, **kwargs):
                pass

            async def run(self, goal, prior_messages=None):
                captured["goal"] = goal
                captured["prior"] = prior_messages
                return _FakeSession()

        monkeypatch.setattr("src.agent.engine.AgentEngine", _FakeEngine)

        result = runner.invoke(app, [
            "session", "resume", "s-resume", "继续补测试", "--dir", str(tmp_path),
        ])

        assert result.exit_code == 0, result.output
        assert captured["goal"] == "继续补测试"
        assert captured["prior"], "历史消息必须被注入"
        roles = [m.get("role") for m in captured["prior"]]
        assert "user" in roles and "assistant" in roles
        assert "续跑完成" in result.output

    def test_resume_missing_session_exits_one(self, tmp_path: Path):
        result = runner.invoke(app, [
            "session", "resume", "ghost", "x", "--dir", str(tmp_path),
        ])
        assert result.exit_code == 1
        assert "读取失败" in result.output
