"""`clawd explain` 测试（回归：CLI 没有"讲人话"入口，用户只能翻 JSONL）

`explain` 不调用 LLM，只摊开会话里的事实。测试用真实 `session_bridge.save()`
造会话文件，保证格式与运行期一致。
"""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from src.cli import explain as explain_mod
from src.cli.explain import explain_session
from src.core import session_bridge
from src.core.session_bridge import SessionView


def _save(directory: Path, session_id: str, messages: list[dict], **kwargs) -> SessionView:
    view = SessionView(
        session_id=session_id,
        title=kwargs.pop("title", "测试会话"),
        messages=messages,
        status=kwargs.pop("status", "completed"),
        provider=kwargs.pop("provider", "openai"),
        model=kwargs.pop("model", "gpt-4o"),
        turn_count=kwargs.pop("turn_count", 1),
        input_tokens=kwargs.pop("input_tokens", 100),
        output_tokens=kwargs.pop("output_tokens", 50),
        total_cost=kwargs.pop("total_cost", 0.0021),
        **kwargs,
    )
    session_bridge.save(view, directory)
    return view


@pytest.fixture
def sessions_dir(tmp_path: Path) -> Path:
    return tmp_path


class TestExplainSession:
    def test_reports_tool_calls_with_outcomes(self, sessions_dir: Path):
        messages = [
            {"role": "user", "content": "读一下 a.py 然后跑测试"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "function": {"name": "FileReadTool", "arguments": '{"file_path": "a.py"}'}},
                    {"id": "c2", "function": {"name": "BashTool", "arguments": '{"command": "pytest"}'}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "x = 1"},
            {"role": "tool", "tool_call_id": "c2", "content": "Traceback ...\nAssertionError: boom"},
            {"role": "assistant", "content": "读到了 a.py，但测试失败了：AssertionError。"},
        ]
        _save(sessions_dir, "s-1", messages)

        explanation = explain_session("s-1", sessions_dir)

        assert [t.name for t in explanation.tool_calls] == ["FileReadTool", "BashTool"]
        assert explanation.tool_calls[0].ok is True
        assert explanation.tool_calls[1].ok is False
        assert explanation.ok_tools == 1
        assert explanation.failed_tools == 1
        assert "AssertionError" in explanation.final_answer

    def test_missing_tool_result_is_not_counted_as_success(self, sessions_dir: Path):
        messages = [
            {"role": "user", "content": "做事"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "function": {"name": "GrepTool", "arguments": "{}"}}],
            },
        ]
        _save(sessions_dir, "s-2", messages)

        explanation = explain_session("s-2", sessions_dir)
        assert explanation.tool_calls[0].ok is None
        assert any("没有结果记录" in note for note in explanation.notes)
        assert explanation.ok_tools == 0

    def test_no_tool_records_says_so(self, sessions_dir: Path):
        _save(sessions_dir, "s-3", [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
        ])
        text = explain_session("s-3", sessions_dir).to_text()
        assert "没有记录" in text

    def test_non_completed_status_is_noted(self, sessions_dir: Path):
        _save(sessions_dir, "s-4", [{"role": "assistant", "content": "x"}], status="failed")
        explanation = explain_session("s-4", sessions_dir)
        assert any("failed" in note for note in explanation.notes)

    def test_legacy_format_noted(self, sessions_dir: Path):
        """legacy 格式（messages 是字符串列表）也要能被解释，并提示字段可能不全"""
        legacy = sessions_dir / "s-5.json"
        legacy.write_text(
            json.dumps({
                "session_id": "s-5",
                "title": "老会话",
                "messages": ["用户说了什么", "助手回了什么"],
                "input_tokens": 10,
                "output_tokens": 5,
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        explanation = explain_session("s-5", sessions_dir)
        assert explanation.message_count == 2
        assert any("历史格式" in note for note in explanation.notes)

    def test_usage_and_cost_reported(self, sessions_dir: Path):
        _save(sessions_dir, "s-6", [{"role": "assistant", "content": "x"}],
              input_tokens=1200, output_tokens=340, total_cost=0.0123)
        explanation = explain_session("s-6", sessions_dir)
        assert explanation.input_tokens == 1200
        assert explanation.output_tokens == 340
        assert explanation.cost == pytest.approx(0.0123)

    def test_defaults_to_latest_session(self, sessions_dir: Path):
        _save(sessions_dir, "old", [{"role": "assistant", "content": "old"}])
        _save(sessions_dir, "new", [{"role": "assistant", "content": "new"}])
        assert explain_session(None, sessions_dir).session_id in {"old", "new"}

    def test_missing_session_raises(self, sessions_dir: Path):
        with pytest.raises(FileNotFoundError):
            explain_session("nope", sessions_dir)

    def test_empty_directory_raises_with_hint(self, sessions_dir: Path):
        with pytest.raises(FileNotFoundError, match="还没有任何会话"):
            explain_session(None, sessions_dir)

    def test_to_dict_is_json_safe(self, sessions_dir: Path):
        _save(sessions_dir, "s-7", [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "function": {"name": "FileReadTool", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
            {"role": "assistant", "content": "完成"},
        ])
        payload = json.loads(json.dumps(explain_session("s-7", sessions_dir).to_dict(), ensure_ascii=False))
        assert payload["tools"][0]["name"] == "FileReadTool"
        assert payload["tools"][0]["ok"] is True


class TestExplainCommand:
    def test_cli_prints_text(self, monkeypatch, sessions_dir: Path):
        from typer.testing import CliRunner

        from src.cli import entrypoint

        _save(sessions_dir, "s-cli", [{"role": "assistant", "content": "做完了"}])
        monkeypatch.setattr(
            explain_mod, "explain_session", lambda sid=None, directory=None: explain_session("s-cli", sessions_dir)
        )
        result = CliRunner().invoke(entrypoint.app, ["explain", "s-cli"])
        assert result.exit_code == 0
        assert "会话 s-cli" in result.output

    def test_cli_json_mode(self, monkeypatch, sessions_dir: Path):
        from typer.testing import CliRunner

        from src.cli import entrypoint

        _save(sessions_dir, "s-json", [{"role": "assistant", "content": "x"}])
        monkeypatch.setattr(
            explain_mod, "explain_session", lambda sid=None, directory=None: explain_session("s-json", sessions_dir)
        )
        result = CliRunner().invoke(entrypoint.app, ["explain", "s-json", "--json"])
        payload = json.loads(result.output.strip().splitlines()[-1])
        assert payload["session_id"] == "s-json"

    def test_cli_missing_session_exits_2(self, monkeypatch):
        from typer.testing import CliRunner

        from src.cli import entrypoint

        def boom(sid=None, directory=None):
            raise FileNotFoundError("没有这个会话")

        monkeypatch.setattr(explain_mod, "explain_session", boom)
        result = CliRunner().invoke(entrypoint.app, ["explain", "nope"])
        assert result.exit_code == 2


class TestResultHeuristic:
    def test_content_mentioning_error_midway_is_not_failure(self, sessions_dir: Path):
        """文件内容里出现 error 不代表读取失败（错误标志只看开头）"""
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "function": {"name": "FileReadTool", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1",
             "content": "def handle(error):\n    return 'error handled'\n" * 10},
        ]
        _save(sessions_dir, "s-heur", messages)
        explanation = explain_session("s-heur", sessions_dir)
        assert explanation.tool_calls[0].ok is True

    def test_real_failure_marker_detected(self, sessions_dir: Path):
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "function": {"name": "BashTool", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "Error: file not found"},
        ]
        _save(sessions_dir, "s-heur2", messages)
        assert explain_session("s-heur2", sessions_dir).tool_calls[0].ok is False
