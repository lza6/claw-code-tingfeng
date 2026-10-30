"""`clawd doctor --json` 契约 + 诊断收集函数的单一来源

背景：`_handle_doctor()` 以前是"边查边打印"，机器读不到，也没法进 CI。
现在拆成 `collect_doctor_report()`（收集）+ 渲染，`--json` 与终端共用同一份数据。
另外**密钥只报"已设置"，不回显任何片段**（JSON 比人读更容易被采集/上报）。
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from src.cli.entrypoint import app
from src.cli.repl_commands import collect_doctor_report

runner = CliRunner()


class TestCollectReport:
    def test_shape(self):
        report = collect_doctor_report()

        assert set(report) >= {"ready", "checks", "count", "failed"}
        assert report["count"] == len(report["checks"]) > 0
        assert report["failed"] == sum(1 for c in report["checks"] if c["level"] == "fail")
        assert report["ready"] is (report["failed"] == 0)

    def test_every_check_has_section_level_text(self):
        for check in collect_doctor_report()["checks"]:
            assert set(check) == {"section", "level", "text"}, check
            assert check["level"] in {"pass", "warn", "fail"}
            assert check["section"] in {"env", "consistency", "capabilities"}
            assert isinstance(check["text"], str) and check["text"]


class TestDoctorJson:
    def test_json_output_is_contract(self):
        result = runner.invoke(app, ["doctor", "--json"])

        # CliRunner 默认会把 stderr 混进 output；只取 stdout（--json 必须只写 stdout）
        out = getattr(result, "stdout", None) or result.output
        payload = json.loads(out.strip().splitlines()[-1])
        assert payload["ok"] is (payload["failed"] == 0)
        assert payload["code"] == (0 if payload["ok"] else 1)
        assert payload["count"] == len(payload["checks"]) > 0
        assert result.exit_code == payload["code"], "退出码必须与 JSON 里的 code 一致"

    def test_no_secret_fragment_leaks(self, monkeypatch):
        """密钥只报"已设置"，绝不回显片段（JSON 更易被采集）"""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-verysecrettoken1234567890abcdef")
        report = collect_doctor_report()

        texts = " ".join(c["text"] for c in report["checks"])
        assert "sk-verysecret" not in texts
        assert "verysecrettoken" not in texts
        assert "OPENAI_API_KEY=已设置" in texts, texts

    def test_human_mode_still_works(self):
        """人读模式必须还能跑（不能为了 JSON 把原输出弄坏）"""
        result = runner.invoke(app, ["doctor"])

        assert "环境诊断" in result.output
        assert result.exit_code in (0, 1)
