"""统一账本 + 跨会话归因测试（P3/风险表：两套账本语义重叠、explain 跨会话）"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core import session_bridge
from src.core.session_bridge import SessionView
from src.workflow.run_ledger import RunLedger, ledger_snapshot


class TestRunLedgerWriteThrough:
    def test_record_stage_writes_both_ledgers(self, tmp_path: Path):
        ledger = RunLedger(tmp_path)
        assert ledger.record_stage("ralph", "stage:plan", note="规划完成", task="做点事") is True

        snap = ledger.snapshot()
        assert [m.mode for m in snap.modes] == ["ralph"]
        assert snap.modes[0].phase == "stage:plan"
        assert len(snap.progress) == 1
        assert "规划完成" in snap.progress[0]["text"]
        assert snap.consistent is True

    def test_snapshot_reports_half_written_ledger(self, tmp_path: Path):
        from src.workflow.mode_state import ModeStateManager

        ModeStateManager(str(tmp_path)).start_mode("autopilot", "只写状态不写进度")
        snap = ledger_snapshot(tmp_path)
        assert snap.consistent is False
        assert any("ralph 进度为空" in issue for issue in snap.issues)

    def test_snapshot_reports_orphan_progress(self, tmp_path: Path):
        from src.workflow.ralph_ledger import add_progress_entry

        add_progress_entry("孤儿进度", cwd=str(tmp_path))
        snap = ledger_snapshot(tmp_path)
        assert snap.consistent is False
        assert any("孤儿进度" in issue for issue in snap.issues)

    def test_empty_workspace_is_consistent(self, tmp_path: Path):
        snap = ledger_snapshot(tmp_path)
        assert snap.consistent is True and snap.modes == [] and snap.progress == []

    def test_to_dict_is_json_safe(self, tmp_path: Path):
        import json

        RunLedger(tmp_path).record_stage("team", "stage:exec")
        payload = json.loads(json.dumps(ledger_snapshot(tmp_path).to_dict(), ensure_ascii=False, default=str))
        assert payload["modes"][0]["mode"] == "team"


class TestExplainRecent:
    def _save(self, directory: Path, sid: str, messages: list[dict], **kw) -> None:
        view = SessionView(
            session_id=sid,
            title=kw.pop("title", "t"),
            messages=messages,
            status=kw.pop("status", "completed"),
            input_tokens=kw.pop("input_tokens", 100),
            output_tokens=kw.pop("output_tokens", 20),
            total_cost=kw.pop("total_cost", 0.001),
            **kw,
        )
        session_bridge.save(view, directory)

    def test_summary_counts_and_tops(self, tmp_path: Path):
        from src.cli.explain import explain_recent

        self._save(tmp_path, "s1", [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "c1", "function": {"name": "BashTool", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "Error: boom"},
            {"role": "assistant", "content": "失败：Error: boom"},
        ])
        self._save(tmp_path, "s2", [
            {"role": "assistant", "content": "一切正常"},
        ], status="failed")

        summary = explain_recent(10, tmp_path)
        assert summary["sessions"] == 2
        assert summary["completed"] == 1
        assert summary["success_rate"] == pytest.approx(0.5)
        assert summary["tokens"] == 240
        assert summary["top_failed_tools"][0]["key"] == "BashTool"
        assert summary["top_failed_tools"][0]["count"] == 1

    def test_empty_workspace(self, tmp_path: Path):
        from src.cli.explain import explain_recent

        summary = explain_recent(5, tmp_path)
        assert summary["sessions"] == 0 and summary["success_rate"] == 0.0


class TestLedgerCli:
    def test_ledger_cli_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        import json

        from typer.testing import CliRunner

        from src.cli import entrypoint

        monkeypatch.chdir(tmp_path)
        RunLedger(tmp_path).record_stage("ralph", "stage:verify")
        result = CliRunner().invoke(entrypoint.app, ["ledger", "--json"])
        payload = json.loads(result.output.strip().splitlines()[-1])
        assert payload["modes"][0]["mode"] == "ralph"
        assert result.exit_code == 0

    def test_ledger_cli_flags_inconsistency(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from typer.testing import CliRunner

        from src.cli import entrypoint
        from src.workflow.mode_state import ModeStateManager

        monkeypatch.chdir(tmp_path)
        ModeStateManager(str(tmp_path)).start_mode("autopilot", "只写一半")
        result = CliRunner().invoke(entrypoint.app, ["ledger"])
        assert result.exit_code == 1
        assert "不一致" in result.output
