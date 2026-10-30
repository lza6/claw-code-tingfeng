"""Eval harness 行为测试（W8 能力缺口闭环）

覆盖：数据集加载与校验、五类确定性断言、replay/live 双闸、基线保存与回归比对、CLI 端到端。
全部离线执行，不发起任何真实 LLM 调用。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.eval import (
    EvalCase,
    compare_with_baseline,
    evaluate_case,
    load_baseline,
    load_dataset,
    run_dataset,
    save_baseline,
)
from src.eval.runner import EvalConfigError

# ==========================================================================
# 数据集加载与校验
# ==========================================================================


def _write_dataset(path: Path, cases: list[dict]) -> Path:
    path.write_text(
        json.dumps({"version": 1, "cases": cases}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


class TestLoadDataset:
    def test_loads_valid_dataset(self, tmp_path: Path):
        ds = _write_dataset(
            tmp_path / "d.json",
            [
                {
                    "id": "c1",
                    "input": "读文件",
                    "expect": {"contains": ["ok"]},
                    "recorded": {"output": "ok done", "tools": ["read_file"]},
                }
            ],
        )

        cases = load_dataset(ds)

        assert len(cases) == 1
        assert cases[0].case_id == "c1"
        assert cases[0].expect == {"contains": ["ok"]}

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(EvalConfigError, match="数据集不存在"):
            load_dataset(tmp_path / "nope.json")

    def test_malformed_json_raises(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")

        with pytest.raises(EvalConfigError, match="读取失败"):
            load_dataset(bad)

    def test_empty_cases_raises(self, tmp_path: Path):
        ds = _write_dataset(tmp_path / "d.json", [])
        with pytest.raises(EvalConfigError, match="非空 cases"):
            load_dataset(ds)

    def test_rejects_empty_expect(self, tmp_path: Path):
        ds = _write_dataset(tmp_path / "d.json", [{"id": "c1", "input": "x", "expect": {}}])
        with pytest.raises(EvalConfigError, match="expect 不能为空"):
            load_dataset(ds)

    def test_rejects_unknown_assertion(self, tmp_path: Path):
        ds = _write_dataset(
            tmp_path / "d.json", [{"id": "c1", "input": "x", "expect": {"bogus": 1}}]
        )
        with pytest.raises(EvalConfigError, match="未知断言类型"):
            load_dataset(ds)

    def test_rejects_non_list_contains(self, tmp_path: Path):
        ds = _write_dataset(
            tmp_path / "d.json", [{"id": "c1", "input": "x", "expect": {"contains": "ok"}}]
        )
        with pytest.raises(EvalConfigError, match="必须是列表"):
            load_dataset(ds)


# ==========================================================================
# 断言引擎
# ==========================================================================


class TestEvaluateCase:
    def test_equals_pass_and_fail(self):
        case = EvalCase(case_id="c", input="", expect={"equals": "hello"})
        assert evaluate_case(case, {"output": "hello"})[0] is True
        ok, detail = evaluate_case(case, {"output": "hello!"})
        assert ok is False
        assert "equals 不匹配" in detail

    def test_equals_ignores_surrounding_whitespace(self):
        case = EvalCase(case_id="c", input="", expect={"equals": "done"})
        assert evaluate_case(case, {"output": "  done\n"})[0] is True

    def test_contains_reports_all_missing(self):
        case = EvalCase(case_id="c", input="", expect={"contains": ["a", "b", "c"]})
        ok, detail = evaluate_case(case, {"output": "a only"})
        assert ok is False
        assert "'b'" in detail and "'c'" in detail

    def test_not_contains_blocks_forbidden(self):
        case = EvalCase(case_id="c", input="", expect={"not_contains": ["Traceback"]})
        assert evaluate_case(case, {"output": "all good"})[0] is True
        assert evaluate_case(case, {"output": "Traceback ..."})[0] is False

    def test_regex_match_and_invalid_pattern(self):
        case = EvalCase(case_id="c", input="", expect={"regex": r"\d{3}-\d{4}"})
        assert evaluate_case(case, {"output": "call 555-1234"})[0] is True
        assert evaluate_case(case, {"output": "no digits"})[0] is False

        bad = EvalCase(case_id="c", input="", expect={"regex": "([unclosed"})
        ok, detail = evaluate_case(bad, {"output": "x"})
        assert ok is False
        assert "regex 非法" in detail

    def test_tool_sequence_order_matters(self):
        case = EvalCase(case_id="c", input="", expect={"tool_sequence": ["read_file", "write_file"]})
        assert evaluate_case(case, {"output": "", "tools": ["read_file", "write_file"]})[0] is True
        ok, detail = evaluate_case(case, {"output": "", "tools": ["write_file", "read_file"]})
        assert ok is False
        assert "tool_sequence 不一致" in detail

    def test_multiple_assertions_must_all_pass(self):
        case = EvalCase(
            case_id="c", input="", expect={"contains": ["a"], "not_contains": ["b"]}
        )
        assert evaluate_case(case, {"output": "a ok"})[0] is True
        assert evaluate_case(case, {"output": "a but b"})[0] is False

    def test_missing_output_treated_as_empty(self):
        case = EvalCase(case_id="c", input="", expect={"contains": ["x"]})
        assert evaluate_case(case, {})[0] is False


# ==========================================================================
# 运行器：replay / live 双闸
# ==========================================================================


class TestRunDataset:
    def test_replay_uses_recorded_output(self):
        cases = [
            EvalCase(
                case_id="c1",
                input="x",
                expect={"contains": ["ok"]},
                recorded={"output": "ok", "tools": []},
            )
        ]

        report = run_dataset(cases)

        assert report.mode == "replay"
        assert report.passed == 1
        assert report.pass_rate == 1.0

    def test_replay_without_recorded_marks_unknown_not_failed(self):
        """缺 recorded = **没测**（unknown），不是失败；也不得计入通过率分母"""
        cases = [
            EvalCase(case_id="c1", input="x", expect={"contains": ["ok"]}),
            EvalCase(
                case_id="c2",
                input="y",
                expect={"contains": ["ok"]},
                recorded={"output": "ok", "tools": []},
            ),
        ]

        report = run_dataset(cases)

        assert report.total == 2
        assert report.unknown == 1
        assert report.unknowns[0].case_id == "c1"
        assert "recorded" in report.unknowns[0].detail
        assert report.failed == 0, "没测不该被记成失败"
        assert report.passed == 1
        assert report.determined == 1
        assert report.pass_rate == 1.0, "通过率只在已判定用例里算"
        assert "未判定" in report.summary_line()

    def test_live_requires_env_gate(self, monkeypatch):
        monkeypatch.delenv("CLAWD_EVAL_ALLOW_PAID", raising=False)

        with pytest.raises(EvalConfigError, match="CLAWD_EVAL_ALLOW_PAID"):
            run_dataset([EvalCase(case_id="c", input="", expect={"contains": ["x"]})], live=True)

    def test_live_requires_agent_fn(self, monkeypatch):
        monkeypatch.setenv("CLAWD_EVAL_ALLOW_PAID", "1")

        with pytest.raises(EvalConfigError, match="必须提供 agent_fn"):
            run_dataset([EvalCase(case_id="c", input="", expect={"contains": ["x"]})], live=True)

    def test_live_runs_agent_fn_when_authorized(self, monkeypatch):
        monkeypatch.setenv("CLAWD_EVAL_ALLOW_PAID", "1")
        calls: list[str] = []

        def fake_agent(case: EvalCase) -> dict:
            calls.append(case.case_id)
            return {"output": "answer", "tools": ["search"]}

        report = run_dataset(
            [
                EvalCase(
                    case_id="c1",
                    input="q",
                    expect={"contains": ["answer"], "tool_sequence": ["search"]},
                )
            ],
            agent_fn=fake_agent,
            live=True,
        )

        assert calls == ["c1"]
        assert report.mode == "live"
        assert report.passed == 1

    def test_agent_exception_recorded_as_failure(self):
        def boom(case: EvalCase) -> dict:
            raise RuntimeError("agent crashed")

        report = run_dataset(
            [EvalCase(case_id="c1", input="x", expect={"contains": ["ok"]})],
            agent_fn=boom,
        )

        assert report.failed == 1
        assert "执行异常" in report.failures[0].detail
        assert "RuntimeError" in report.failures[0].detail


# ==========================================================================
# 基线
# ==========================================================================


class TestBaseline:
    def _report(self, outcomes: list[tuple[str, bool]]):
        cases = [
            EvalCase(
                case_id=cid,
                input="",
                expect={"contains": ["ok"]},
                recorded={"output": "ok" if ok else "nope", "tools": []},
            )
            for cid, ok in outcomes
        ]
        return run_dataset(cases)

    def test_save_and_load_roundtrip(self, tmp_path: Path):
        report = self._report([("c1", True), ("c2", False)])
        path = tmp_path / "nested" / "baseline.json"

        written = save_baseline(report, path)

        assert written.is_file()
        loaded = load_baseline(written)
        assert loaded is not None
        assert loaded["total"] == 2
        assert loaded["passed"] == 1

    def test_load_missing_returns_none(self, tmp_path: Path):
        assert load_baseline(tmp_path / "absent.json") is None

    def test_load_corrupt_returns_none(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        assert load_baseline(bad) is None

    def test_compare_detects_pass_rate_regression(self, tmp_path: Path):
        baseline = save_baseline(self._report([("c1", True), ("c2", True)]), tmp_path / "b.json")
        worse = self._report([("c1", True), ("c2", False)])

        problems = compare_with_baseline(worse, load_baseline(baseline))

        assert any("pass_rate 回归" in p for p in problems)
        assert any("c2" in p for p in problems)

    def test_compare_passes_when_improved(self, tmp_path: Path):
        baseline = save_baseline(self._report([("c1", True), ("c2", False)]), tmp_path / "b.json")
        better = self._report([("c1", True), ("c2", True)])

        assert compare_with_baseline(better, load_baseline(baseline)) == []

    def test_compare_without_baseline_is_clean(self):
        assert compare_with_baseline(self._report([("c1", True)]), None) == []

    def test_tolerance_suppresses_small_drop(self, tmp_path: Path):
        baseline = save_baseline(
            self._report([("c1", True), ("c2", True), ("c3", True), ("c4", True)]),
            tmp_path / "b.json",
        )
        slightly_worse = self._report(
            [("c1", True), ("c2", True), ("c3", True), ("c4", False)]
        )

        problems = compare_with_baseline(
            slightly_worse, load_baseline(baseline), tolerance=0.3
        )

        # pass_rate 7.5%→ 75% 下降 25% 在 30% 容忍内，但逐用例回归仍要报出
        assert not any("pass_rate 回归" in p for p in problems)
        assert any("c4" in p for p in problems)


# ==========================================================================
# CLI 端到端
# ==========================================================================


class TestEvalCommand:
    def test_cli_runs_dataset_and_exits_zero(self, tmp_path: Path):
        from typer.testing import CliRunner

        from src.cli import entrypoint

        ds = _write_dataset(
            tmp_path / "d.json",
            [
                {
                    "id": "c1",
                    "input": "x",
                    "expect": {"contains": ["ok"]},
                    "recorded": {"output": "ok", "tools": []},
                }
            ],
        )

        result = CliRunner().invoke(entrypoint.app, ["eval", str(ds)])

        assert result.exit_code == 0, result.output
        assert "1/1 passed" in result.output

    def test_cli_failing_case_exits_one(self, tmp_path: Path):
        from typer.testing import CliRunner

        from src.cli import entrypoint

        ds = _write_dataset(
            tmp_path / "d.json",
            [
                {
                    "id": "c1",
                    "input": "x",
                    "expect": {"contains": ["missing"]},
                    "recorded": {"output": "ok", "tools": []},
                }
            ],
        )

        result = CliRunner().invoke(entrypoint.app, ["eval", str(ds)])

        assert result.exit_code == 1
        assert "FAIL" in result.output

    def test_cli_rejects_invalid_dataset_with_exit_one(self, tmp_path: Path):
        from typer.testing import CliRunner

        from src.cli import entrypoint

        bad = tmp_path / "bad.json"
        bad.write_text("{}", encoding="utf-8")

        result = CliRunner().invoke(entrypoint.app, ["eval", str(bad)])

        assert result.exit_code == 1
        assert "数据集非法" in result.output

    def test_cli_live_without_gate_exits_two(self, tmp_path: Path, monkeypatch):
        from typer.testing import CliRunner

        from src.cli import entrypoint

        monkeypatch.delenv("CLAWD_EVAL_ALLOW_PAID", raising=False)
        ds = _write_dataset(
            tmp_path / "d.json",
            [
                {
                    "id": "c1",
                    "input": "x",
                    "expect": {"contains": ["ok"]},
                    "recorded": {"output": "ok", "tools": []},
                }
            ],
        )

        result = CliRunner().invoke(entrypoint.app, ["eval", str(ds), "--live"])

        assert result.exit_code == 2
        assert "CLAWD_EVAL_ALLOW_PAID" in result.output

    def test_cli_save_baseline_then_compare(self, tmp_path: Path):
        from typer.testing import CliRunner

        from src.cli import entrypoint

        ds = _write_dataset(
            tmp_path / "d.json",
            [
                {
                    "id": "c1",
                    "input": "x",
                    "expect": {"contains": ["ok"]},
                    "recorded": {"output": "ok", "tools": []},
                }
            ],
        )
        baseline = tmp_path / "baseline.json"
        runner = CliRunner()

        first = runner.invoke(
            entrypoint.app, ["eval", str(ds), "--save", "--baseline", str(baseline)]
        )
        assert first.exit_code == 0
        assert baseline.is_file()

        second = runner.invoke(entrypoint.app, ["eval", str(ds), "--baseline", str(baseline)])
        assert second.exit_code == 0
        assert "基线比对通过" in second.output
