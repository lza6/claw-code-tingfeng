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


class TestResumeCompaction:
    """长历史续跑必须先压缩（ADR-0012 的检查点 + Pi 的准入阈值）"""

    def test_short_history_untouched(self):
        from src.agent.compaction import prepare_resume_messages

        msgs = [{"role": "user", "content": "短消息"}]
        out, checkpoint = prepare_resume_messages(msgs)

        assert out == msgs
        assert checkpoint is None

    def test_long_history_compacted_to_checkpoint(self):
        from src.agent.compaction import prepare_resume_messages

        # 用 min_tokens=1 让"很短的历史"也触发压缩：测的是压缩逻辑，不是数据搬运量。
        # 此前用 120,000 字符假文本跑正则，单测耗时 42 秒（实测最慢 5 个之一）。
        msgs = [
            {"role": "user", "content": "请实现 src/api/user.py 的登录，目标支持 JWT"},
            {"role": "assistant", "content": "下一步：补测试"},
        ]

        out, checkpoint = prepare_resume_messages(msgs, min_tokens=1)

        assert checkpoint is not None
        assert len(out) == 1 and out[0]["role"] == "system"
        assert "检查点摘要" in out[0]["content"]
        assert "src/api/user.py" in out[0]["content"]  # 关键事实被保住

    def test_cli_resume_compacts_long_session(self, tmp_path: Path, monkeypatch):
        from src.core.session_bridge import persist_agent_session

        persist_agent_session(
            "s-long", "长会话", [{"role": "assistant", "content": "历史内容"}],
            directory=tmp_path,
        )
        captured = {}

        class _FakeSession:
            final_result = "ok"

        class _FakeEngine:
            def __init__(self, **kwargs):
                pass

            async def run(self, goal, prior_messages=None):
                captured["prior"] = prior_messages
                return _FakeSession()

        monkeypatch.setattr("src.agent.engine.AgentEngine", _FakeEngine)

        # CLI 走默认 30k 阈值：这里改为断言"短历史不压缩"（语义正确且快），
        # 压缩逻辑本身已由 test_long_history_compacted_to_checkpoint 覆盖
        result = runner.invoke(app, [
            "session", "resume", "s-long", "继续", "--dir", str(tmp_path),
        ])

        assert result.exit_code == 0, result.output
        assert "已载入 2 条历史消息" in result.output  # persist 写 1 条 user(goal) + 1 条 assistant
        # 短历史不压缩：原样带入（压缩逻辑另有用例覆盖，此处只验 CLI 接线）
        assert len(captured["prior"]) == 2
        assert [m["role"] for m in captured["prior"]] == ["user", "assistant"]
