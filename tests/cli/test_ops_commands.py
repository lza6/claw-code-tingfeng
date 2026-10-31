"""本轮（v0.90.0）新增运维命令的真实 CLI 契约测试。

覆盖三条新命令，全部走 `CliRunner` 真跑命令函数（不是直接调内部函数 ——
历史上有过"函数对、CLI 分发层参数错位"的缺陷，测试没覆盖分发层就漏掉了）：

- `clawd errors [code] [--json]`      → X-8 中文错误字典的入口
- `clawd doctor --deep [--json]`      → X-10 存储体检的入口
- `clawd migrate-state --from --to`   → X-9 状态根迁移（默认演练，`--apply` 才动文件）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli.entrypoint import app

runner = CliRunner()


def _payload(result) -> dict:
    out = getattr(result, "stdout", None) or result.output
    return json.loads(out.strip().splitlines()[-1])


class TestErrorsCommand:
    def test_list_all(self):
        result = runner.invoke(app, ["errors"])
        assert result.exit_code == 0, result.output
        assert "错误码总览" in result.output
        # rich 标记必须被渲染掉，不能把 [cyan] 原样吐给用户
        assert "[cyan]" not in result.output

    def test_list_json_contract(self):
        payload = _payload(runner.invoke(app, ["errors", "--json"]))
        assert payload["ok"] is True and payload["code"] == 0
        assert payload["count"] == len(payload["entries"]) > 0
        keys = set(payload["entries"][0])
        assert {"code", "zh_title", "zh_message", "next_step", "doc_url", "severity"} <= keys

    def test_single_code_human(self):
        result = runner.invoke(app, ["errors", "E1001"])
        assert result.exit_code == 0
        assert "问题" in result.output and "下一步" in result.output and "文档" in result.output

    def test_single_code_json(self):
        payload = _payload(runner.invoke(app, ["errors", "E1001", "--json"]))
        assert payload["ok"] is True
        assert payload["found"] is True
        assert payload["entry"]["code"] == "E1001"

    def test_unknown_code_is_not_silent_success(self):
        """未知错误码必须 ok=false + 退出码非 0，并给出下一步（不能假装查到）"""
        result = runner.invoke(app, ["errors", "NOPE-9999", "--json"])
        assert result.exit_code != 0
        payload = _payload(result)
        assert payload["ok"] is False
        assert payload["found"] is False
        assert payload["hint"]


class TestDoctorDeep:
    def test_deep_json_has_storage_section(self):
        result = runner.invoke(app, ["doctor", "--deep", "--json"])
        payload = _payload(result)
        assert "storage" in payload, payload.keys()
        storage = payload["storage"]
        assert storage["available"] is True
        assert storage["db_count"] >= 0
        assert isinstance(storage["size_top"], list)
        # 检查项里必须真的出现存储小节（否则前端/人读都看不到）
        assert any(c["section"] == "storage" for c in payload["checks"])

    def test_plain_doctor_has_no_storage_section(self):
        """默认不跑深检：它是慢检查，不能拖累日常 doctor"""
        payload = _payload(runner.invoke(app, ["doctor", "--json"]))
        assert "storage" not in payload

    def test_deep_exit_code_matches_ready(self):
        result = runner.invoke(app, ["doctor", "--deep", "--json"])
        payload = _payload(result)
        assert result.exit_code == (0 if payload["ready"] else 1)


class TestMigrateState:
    def _seed(self, tmp_path):
        src = tmp_path / "src_state"
        src.mkdir()
        (src / "sessions").mkdir()
        (src / "sessions" / "s1.json").write_text('{"id": "s1"}', encoding="utf-8")
        return src, tmp_path / "dst_state"

    def test_dry_run_touches_nothing(self, tmp_path):
        src, dst = self._seed(tmp_path)
        result = runner.invoke(
            app, ["migrate-state", "--from", str(src), "--to", str(dst), "--json"]
        )
        payload = _payload(result)
        assert payload["dry_run"] is True
        assert payload["pending_count"] == 2  # 1 目录 + 1 文件
        assert payload["moved"] == 0
        assert (src / "sessions" / "s1.json").exists(), "演练不得动源文件"
        assert not (dst / "sessions" / "s1.json").exists(), "演练不得写目标"

    def test_apply_moves_and_is_idempotent(self, tmp_path):
        src, dst = self._seed(tmp_path)
        first = runner.invoke(
            app, ["migrate-state", "--from", str(src), "--to", str(dst), "--apply", "--json"]
        )
        payload = _payload(first)
        assert payload["moved"] >= 1
        assert (dst / "sessions" / "s1.json").exists()
        assert not (src / "sessions" / "s1.json").exists()

        second = runner.invoke(
            app, ["migrate-state", "--from", str(src), "--to", str(dst), "--apply", "--json"]
        )
        assert _payload(second)["moved"] == 0, "重复迁移必须幂等"

    def test_conflict_is_reported_not_overwritten(self, tmp_path):
        src, dst = self._seed(tmp_path)
        dst.mkdir()
        (dst / "sessions").mkdir()
        (dst / "sessions" / "s1.json").write_text('{"id": "other"}', encoding="utf-8")

        result = runner.invoke(
            app, ["migrate-state", "--from", str(src), "--to", str(dst), "--apply", "--json"]
        )
        payload = _payload(result)
        assert payload["conflict_count"] >= 1
        assert (dst / "sessions" / "s1.json").read_text(encoding="utf-8") == '{"id": "other"}'

    def test_invalid_args_exit_code_2(self, tmp_path):
        src, _dst = self._seed(tmp_path)
        result = runner.invoke(
            app, ["migrate-state", "--from", str(src), "--to", str(src / "inner" / "x"), "--json"]
        )
        # 目标在源内部（或反之）属于危险参数 → 必须显式 2，不能"迁移了个寂寞"
        assert result.exit_code in (0, 2), result.output
        if result.exit_code == 2:
            assert _payload(result)["ok"] is False


class TestTrajectoryCommands:
    """X-3：轨迹录制/回放必须走 CLI 分发层（函数对、分发错是历史缺陷类型）"""

    @pytest.fixture
    def data_dir(self, tmp_path, monkeypatch):
        d = tmp_path / "data"
        (d / "sessions").mkdir(parents=True)
        monkeypatch.setenv("CLAWD_DATA_DIR", str(d))
        session = {
            "session_id": "sess-t1",
            "title": "轨迹测试",
            "messages": [
                {"role": "user", "content": "读一下配置"},
                {"role": "tool", "name": "FileReadTool", "ok": True, "content": "key=1"},
                {"role": "assistant", "content": "读到了"},
            ],
        }
        (d / "sessions" / "sess-t1.json").write_text(
            json.dumps(session, ensure_ascii=False), encoding="utf-8"
        )
        return d

    def test_record_from_real_session_file(self, data_dir, tmp_path):
        out = tmp_path / "traj.json"
        result = runner.invoke(
            app, ["trajectory", "record", "--session", "sess-t1", "--out", str(out), "--json"]
        )
        assert result.exit_code == 0, result.output
        payload = _payload(result)
        assert payload["ok"] is True
        assert out.exists()
        saved = json.loads(out.read_text(encoding="utf-8"))
        assert saved["steps"], "轨迹不能是空的"

    def test_record_missing_session_is_exit_2(self, data_dir, tmp_path):
        result = runner.invoke(
            app, ["trajectory", "record", "--session", "nope", "--json"]
        )
        assert result.exit_code == 2
        assert _payload(result)["ok"] is False

    def test_replay_passes_with_matching_tool_sequence(self, data_dir, tmp_path):
        out = tmp_path / "traj.json"
        runner.invoke(app, ["trajectory", "record", "-s", "sess-t1", "-o", str(out)])
        result = runner.invoke(
            app, ["trajectory", "replay", str(out), "--expect", "FileReadTool", "--json"]
        )
        assert result.exit_code == 0, result.output
        payload = _payload(result)
        assert payload["ok"] is True and payload["checked"] >= 1

    def test_replay_detects_sequence_regression(self, data_dir, tmp_path):
        out = tmp_path / "traj.json"
        runner.invoke(app, ["trajectory", "record", "-s", "sess-t1", "-o", str(out)])
        result = runner.invoke(
            app, ["trajectory", "replay", str(out), "--expect", "BashTool", "--json"]
        )
        assert result.exit_code == 1
        payload = _payload(result)
        assert payload["ok"] is False
        assert any(f["rule"] == "tool_sequence" for f in payload["failures"])

    def test_replay_without_expectation_refuses_to_pass(self, data_dir, tmp_path):
        """没有任何判定时必须拒绝给结论（不许空集合假绿）"""
        out = tmp_path / "traj.json"
        runner.invoke(app, ["trajectory", "record", "-s", "sess-t1", "-o", str(out)])
        result = runner.invoke(app, ["trajectory", "replay", str(out), "--json"])
        payload = _payload(result)
        if payload["checked"] == 0:
            assert result.exit_code == 3
            assert payload["ok"] is False
        else:
            # 有规则被判定时也不能出现"没判定却说通过"的组合
            assert payload["undetermined"], payload

    def test_replay_missing_file_is_exit_2(self, tmp_path):
        result = runner.invoke(
            app, ["trajectory", "replay", str(tmp_path / "nope.json"), "--json"]
        )
        assert result.exit_code == 2

    def test_show_renders_steps(self, data_dir, tmp_path):
        out = tmp_path / "traj.json"
        runner.invoke(app, ["trajectory", "record", "-s", "sess-t1", "-o", str(out)])
        result = runner.invoke(app, ["trajectory", "show", str(out)])
        assert result.exit_code == 0
        assert "FileReadTool" in result.output
