"""REPL 多轮历史 + 会话续聊（此前每轮 engine 调用无状态，对话没有记忆）"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli.entrypoint import app
from src.cli.repl_session import ReplSession
from src.core.session_bridge import persist_agent_session

runner = CliRunner()


class _FakeSession:
    def __init__(self, final_result: str):
        self.final_result = final_result


@pytest.fixture
def repl(tmp_path: Path) -> ReplSession:
    return ReplSession(workdir=tmp_path, use_rich_hud=False)


class TestHistoryAccumulation:
    def test_starts_empty(self, repl):
        assert repl._history == []
        assert repl._context_messages() is None

    def test_record_turn_appends_user_and_assistant(self, repl):
        repl._record_turn("第一个问题", _FakeSession("第一个回答"))

        assert [m["role"] for m in repl._history] == ["user", "assistant"]
        assert repl._history[0]["content"] == "第一个问题"
        assert repl._history[1]["content"] == "第一个回答"

    def test_history_accumulates_across_turns(self, repl):
        repl._record_turn("Q1", _FakeSession("A1"))
        repl._record_turn("Q2", _FakeSession("A2"))

        msgs = repl._context_messages()
        assert len(msgs) == 4
        assert [m["content"] for m in msgs] == ["Q1", "A1", "Q2", "A2"]

    def test_empty_result_not_recorded_as_assistant(self, repl):
        repl._record_turn("Q1", _FakeSession(""))
        assert [m["role"] for m in repl._history] == ["user"]

    def test_none_session_is_tolerated(self, repl):
        repl._record_turn("Q1", None)
        assert len(repl._history) == 1


class TestResume:
    def test_load_history_from_saved_session(self, tmp_path: Path):
        sessions = tmp_path / ".clawd" / "sessions"
        persist_agent_session(
            "s-old", "上次的任务",
            [{"role": "assistant", "content": "上次的结论"}],
            final_result="完成", directory=sessions,
        )

        repl = ReplSession(workdir=tmp_path, use_rich_hud=False, resume_session_id="s-old")

        assert len(repl._history) >= 2
        contents = " ".join(m["content"] for m in repl._history)
        assert "上次的任务" in contents

    def test_resume_missing_session_does_not_crash(self, tmp_path: Path):
        repl = ReplSession(workdir=tmp_path, use_rich_hud=False, resume_session_id="ghost")
        assert repl._history == []


class TestContextCompaction:
    def test_long_history_is_compacted(self, repl):
        from src.agent.compaction import MIN_COMPACT_TOKENS

        repl._history = [
            {"role": "user", "content": "请实现 src/api/user.py 的登录" + "x" * (MIN_COMPACT_TOKENS * 4)},
        ]

        msgs = repl._context_messages()

        assert len(msgs) == 1 and msgs[0]["role"] == "system"
        assert "检查点摘要" in msgs[0]["content"]


class TestChatCliResumeFlag:
    def test_chat_has_resume_option(self):
        result = runner.invoke(app, ["chat", "--help"])
        assert result.exit_code == 0
        assert "--resume" in result.output
