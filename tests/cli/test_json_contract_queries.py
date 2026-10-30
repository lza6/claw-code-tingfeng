"""X-7 收尾：查询类命令的 `--json` 契约（第二批，12 个命令）

背景（为什么需要这一批）
    此前只有 `doctor/session/catalog/usage/ledger/...` 少数命令能出 `--json`，
    脚本想拿"当前有哪些 agent / 权限怎么判 / 质量门过没过"只能 grep 屏幕文字。
    本批把剩下真正需要机器读的命令统一到 `CommandResult` 契约：
    `{ok, code, ...}`，**退出码与 JSON 里的 code 必须一致**（否则 CI 判断失真）。

    这些测试全部**零成本**：不触真实 LLM、不跑真质量门（会执行 ruff/mypy），
    用假对象替换执行体，只验证"数据形状 + 契约 + 人读模式没被弄坏"。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from src.cli.entrypoint import app

runner = CliRunner()


def _payload(result) -> dict:
    """取 stdout 最后一行当 JSON（CliRunner 会把 stderr/日志混进 output）"""
    out = getattr(result, "stdout", None) or result.output
    return json.loads(out.strip().splitlines()[-1])


def _invoke(*args: str):
    return runner.invoke(app, list(args))


# ---------------------------------------------------------------------------
# agent list / show / keywords / intent
# ---------------------------------------------------------------------------
class TestAgentJson:
    def test_list_json_is_contract(self):
        result = _invoke("agent", "list", "--json")

        payload = _payload(result)
        assert payload["ok"] is True and payload["code"] == 0
        assert payload["count"] == len(payload["agents"]) > 0
        assert result.exit_code == 0
        # camelCase 键是有意保留的既有下游兼容面（见模块注释）
        assert {"name", "category", "modelClass"} <= set(payload["agents"][0])

    def test_list_format_json_same_contract(self):
        """`--format json` 与 `--json` 是**同一**契约，不维护两套形态"""
        a = _payload(_invoke("agent", "list", "--format", "json"))
        b = _payload(_invoke("agent", "list", "--json"))
        assert a["count"] == b["count"]
        assert [x["name"] for x in a["agents"]] == [x["name"] for x in b["agents"]]

    def test_list_bad_category_exit_1(self):
        result = _invoke("agent", "list", "--category", "no-such-category")
        assert result.exit_code == 1

    def test_show_json(self):
        names = [a["name"] for a in _payload(_invoke("agent", "list", "--json"))["agents"]]
        payload = _payload(_invoke("agent", "show", names[0], "--json"))
        assert payload["ok"] is True
        assert payload["name"] == names[0]
        assert payload["description"]

    def test_show_missing_is_json_and_exit_1(self):
        result = _invoke("agent", "show", "definitely-not-an-agent", "--json")
        payload = _payload(result)
        assert payload["ok"] is False and payload["code"] == 1
        assert result.exit_code == 1

    def test_keywords_json(self):
        payload = _payload(_invoke("agent", "keywords", "--json"))
        assert payload["count"] == len(payload["keywords"]) > 0
        assert {"keyword", "skill", "priority", "requires_intent"} <= set(payload["keywords"][0])

    def test_intent_json(self):
        payload = _payload(_invoke("agent", "intent", "帮我修一下这个 bug", "--json"))
        assert payload["primary"]
        assert isinstance(payload["ranked"], list)


# ---------------------------------------------------------------------------
# permissions / config / autonomy
# ---------------------------------------------------------------------------
class TestPermissionsJson:
    def test_core_sections_present(self):
        payload = _payload(_invoke("permissions", "--json"))

        assert payload["ok"] is True
        assert len(payload["autonomy_levels"]) >= 2
        assert {e["value"] for e in payload["effects"]} >= {"allow", "deny"}
        assert {d["value"] for d in payload["exec_decisions"]} >= {"allow", "forbidden"}
        assert any(p["sample"] == ".git/config" for p in payload["protected_paths"])
        assert "rules" not in payload, "不加 --rules 时不该把规则表吐出来"

    def test_rules_flag_adds_rules(self):
        payload = _payload(_invoke("permissions", "--rules", "--json"))
        rules = payload["rules"]
        assert any(
            r["prefix"] == "git push --force" and r["decision"] == "forbidden" for r in rules
        )

    def test_human_mode_still_works(self):
        result = _invoke("permissions")
        assert result.exit_code == 0
        assert "审批模式" in result.output


class TestConfigJson:
    def test_report_json(self):
        payload = _payload(_invoke("config", "--json"))
        assert payload["ok"] is True
        assert payload["lines"], "配置优先级报告不能是空的"

    def test_web_json_is_refused_honestly(self):
        """`--json` 与 `--web` 组合没有"结果"可输出 → 明确拒绝，不假装成功"""
        result = _invoke("config", "--web", "--json")
        payload = _payload(result)
        assert payload["ok"] is False and payload["code"] == 2
        assert result.exit_code == 2


class TestAutonomyJson:
    def test_list_empty(self, tmp_path: Path):
        payload = _payload(_invoke("autonomy", "list", "--json", "--dir", str(tmp_path)))
        assert payload["ok"] is True and payload["commands"] == [] and payload["count"] == 0

    def test_list_after_allow(self, tmp_path: Path):
        _invoke("autonomy", "allow", "pytest", "--dir", str(tmp_path))
        payload = _payload(_invoke("autonomy", "list", "--json", "--dir", str(tmp_path)))
        assert payload["commands"] == ["pytest"] and payload["count"] == 1

    def test_list_corrupted_file_is_json_error(self, tmp_path: Path):
        d = tmp_path / ".clawd" / "autonomy"
        d.mkdir(parents=True)
        (d / "allow.json").write_text("{not json", encoding="utf-8")
        result = _invoke("autonomy", "list", "--json", "--dir", str(tmp_path))
        payload = _payload(result)
        # 错误也必须是合法 JSON（否则 `--json | jq` 直接崩）
        assert payload["ok"] is False and payload["code"] == 1
        assert result.exit_code == 1

    def test_log_qwith_broken_line_reports_skipped(self, tmp_path: Path):
        d = tmp_path / ".clawd" / "autonomy"
        d.mkdir(parents=True)
        (d / "decisions.jsonl").write_text(
            '{"时间": "t1", "决策": "allow", "工具": "Bash", "理由": "已预授权"}\n'
            "{broken\n"
            '{"时间": "t2", "决策": "deny", "工具": "Bash", "理由": "越界"}\n',
            encoding="utf-8",
        )
        payload = _payload(_invoke("autonomy", "log", "--json", "--dir", str(tmp_path)))
        assert payload["count"] == 2
        assert payload["total_lines"] == 3
        assert payload["skipped_lines"] == 1, "坏行必须计数上报，不能静默丢"
        assert payload["entries"][0]["决策"] == "allow"


# ---------------------------------------------------------------------------
# quality-gate / ralplan / pipeline / explore（执行体全部用假对象，零成本）
# ---------------------------------------------------------------------------
class TestQualityGateJson:
    def test_json_contract(self, monkeypatch: pytest.MonkeyPatch):
        from src.core.quality_gate import (
            GateCheck,
            GateCheckResult,
            GateLevel,
            GateReport,
            GateResult,
        )

        def fake_run(self, path_hint=None):
            check = GateCheck(name="lint", command=["ruff", "check"], level=GateLevel.COMMIT)
            return GateReport(
                level=GateLevel.COMMIT,
                checks=[
                    GateCheckResult(check=check, result=GateResult.PASS, output="", duration_ms=1.5),
                    GateCheckResult(
                        check=GateCheck(name="tests", command="pytest", level=GateLevel.COMMIT),
                        result=GateResult.FAIL,
                        output="\n".join(f"line{i}" for i in range(40)),
                        duration_ms=2.5,
                    ),
                ],
                overall=GateResult.FAIL,
                summary="1 项失败",
            )

        monkeypatch.setattr("src.core.quality_gate.QualityGate.run", fake_run)
        result = _invoke("quality-gate", "--level", "commit", "--json")

        payload = _payload(result)
        assert payload["ok"] is False and payload["code"] == 1
        assert result.exit_code == 1, "退出码必须与 JSON 的 code 一致"
        assert payload["failed"] == 1
        assert payload["overall"] == "fail"
        # 失败检查只给尾部 20 行，避免 JSON 被整段日志淹没
        failed = [c for c in payload["checks"] if c["result"] == "fail"][0]
        assert failed["output_tail"] == [f"line{i}" for i in range(20, 40)]
        passed = [c for c in payload["checks"] if c["result"] == "pass"][0]
        assert passed["output_tail"] == []


class TestRalplanJson:
    def test_json_contract(self, monkeypatch: pytest.MonkeyPatch):
        from src.workflow.ralplan import ConsensusPlan, PlanOption

        async def fake_run(self, goal):
            return ConsensusPlan(
                goal=goal,
                objective="把 X 做掉",
                tasks=[{"id": "t1", "title": "干一件小事"}],
                risks=["风险一"],
                mitigations=["缓解一"],
                confidence=0.91,
                validator="critic",
                chosen_option=PlanOption(
                    name="方案A", description="先做再说", pros=["快"], cons=["糙"],
                    cost_estimate="4h",
                ),
            )

        monkeypatch.setattr("src.workflow.ralplan.RalplanEngine.run", fake_run)
        result = _invoke("ralplan", "把 X 做掉", "--json")

        payload = _payload(result)
        assert result.exit_code == 0
        assert payload["ok"] is True
        assert payload["confidence"] == pytest.approx(0.91)
        assert payload["confidence_met"] is True
        assert payload["chosen_option"]["name"] == "方案A"
        assert payload["tasks"][0]["id"] == "t1"
        assert payload["plan_path"].endswith("consensus.json")


class TestPipelineJson:
    def test_json_contract(self, monkeypatch: pytest.MonkeyPatch):
        from src.workflow.pipeline_orchestrator import StageStatus

        async def fake_run(self):
            return SimpleNamespace(
                status="completed",
                duration_ms=1234.0,
                failed_stage=None,
                error=None,
                stage_results={
                    "ralplan": SimpleNamespace(status=StageStatus.SUCCESS),
                    "team": SimpleNamespace(status=StageStatus.SKIPPED),
                },
            )

        monkeypatch.setattr(
            "src.workflow.pipeline_orchestrator.PipelineOrchestrator.run", fake_run
        )
        result = _invoke("pipeline", "做一件大事", "--no-team", "--budget", "1h", "--json")

        payload = _payload(result)
        assert result.exit_code == 0
        assert payload["status"] == "completed"
        assert payload["stages"]["ralplan"] == "success"
        # --budget 当前对编排器无效，机器读也必须知道（不能只在人读里提示）
        assert payload["budget_ignored"] is True


class TestExploreJson:
    def test_json_contract(self, monkeypatch: pytest.MonkeyPatch):
        async def fake_run(self):
            return SimpleNamespace(findings="## 结论\n模块 A 是入口")

        monkeypatch.setattr("src.cli.commands.explore.ExploreMode.run", fake_run)
        result = _invoke("explore", "看看入口", "--json")

        payload = _payload(result)
        assert result.exit_code == 0
        assert payload["goal"] == "看看入口"
        assert "模块 A 是入口" in payload["findings"]


# ---------------------------------------------------------------------------
# role show / eval（查角色用的命令 + CI 门禁用命令）
# ---------------------------------------------------------------------------
class TestRoleShowJson:
    def test_json_contains_system_prompt(self):
        names = [p["name"] for p in _payload(_invoke("role", "list", "--json"))["personas"]]
        payload = _payload(_invoke("role", "show", names[0], "--json"))
        assert payload["ok"] is True
        assert payload["name"] == names[0]
        # 提示词必须原文可审计（不是摘要）
        assert isinstance(payload["system_prompt"], str) and payload["system_prompt"]

    def test_missing_role_is_json_error(self):
        result = _invoke("role", "show", "no-such-role-xyz", "--json")
        payload = _payload(result)
        assert payload["ok"] is False and payload["code"] == 1
        assert result.exit_code == 1


class TestEvalJson:
    def test_replay_dataset_json(self):
        dataset = Path(__file__).resolve().parents[2] / "src" / "eval" / "datasets" / "smoke.json"
        result = _invoke("eval", str(dataset), "--json")

        payload = _payload(result)
        assert payload["mode"] == "replay"
        assert payload["total"] == payload["passed"] + payload["failed"] + payload["unknown"] > 0
        assert payload["determined"] == payload["passed"] + payload["failed"]
        assert payload["ok"] is (payload["failed"] == 0)
        assert result.exit_code == payload["code"], "退出码必须与 JSON 的 code 一致"

    def test_missing_dataset_json_error_exit_1(self):
        result = _invoke("eval", "does-not-exist.json", "--json")
        payload = _payload(result)
        assert payload["ok"] is False and payload["code"] == 1
        assert result.exit_code == 1

    def test_human_mode_still_works(self):
        dataset = Path(__file__).resolve().parents[2] / "src" / "eval" / "datasets" / "smoke.json"
        result = _invoke("eval", str(dataset))
        assert "passed" in result.output


class TestJsonStdoutPurity:
    """`--json` 时 stdout 必须只有 JSON —— 日志不能混进来

    真实缺陷（v0.89.0 自测发现）：`setup_logging()` 把控制台日志接到 **stdout**，
    于是 `clawd config --generate --json` 会先打几行 "Discovered 63 skills"，
    `| jq` 直接解析失败。修法：`--json` 在 argv 里时日志整体改道 stderr。
    """

    def test_logger_routes_to_stderr_in_machine_mode(self):
        import logging
        import sys

        from src.utils import logger as logger_mod

        assert logger_mod._wants_machine_output(["--json"]) is True
        assert logger_mod._wants_machine_output(["config", "--generate"]) is False

        old_argv = sys.argv
        try:
            sys.argv = ["clawd", "config", "--json"]
            logger_mod.setup_logging(level=logging.INFO)
            handlers = [h for h in logging.getLogger().handlers
                        if isinstance(h, logging.StreamHandler)]
            assert handlers, "至少要有一个控制台 handler"
            assert handlers[-1].stream is sys.stderr, "机器模式日志必须走 stderr"
        finally:
            sys.argv = old_argv
            logger_mod.setup_logging(level=logging.WARNING)

    def test_generate_json_is_parseable_stdout(self, tmp_path: Path, monkeypatch):
        # 生成过程会在 cwd 下写 .clawd/AGENTS.md —— 切到临时目录，别污染仓库
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "cfg" / "config.toml"
        result = _invoke("config", "--generate", "--json", "--path", str(target))

        payload = _payload(result)
        assert result.exit_code == 0
        assert payload["action"] == "generate"
        assert payload["target"].endswith("config.toml")
        assert payload["tool_signatures_file"] == "tool_signatures.json"
        assert target.exists(), "非 dry-run 必须真的写出配置"
        assert (target.parent / "tool_signatures.json").exists(), "工具签名必须落盘（否则该能力无调用方）"
