"""Eval 诚实性测试（回归：假成功 + "没测"被记成"失败" + 数据集工具名不存在）

三个已修缺陷：
1. `eval --baseline /不存在的路径` 曾打印"基线比对通过（无回归）"并 EXIT=0；
2. 缺 recorded / 非法 regex / 缺工具记录一律判 FAIL → "没测"被记成"失败"，
   通过率与回归比对都被污染；
3. `smoke.json` 的 `tool_sequence` 写的是 `read_file`/`edit_file`，
   而运行期真实工具名是 `FileReadTool`/`FileEditTool` → 接真实 agent 必失败。
"""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from src.eval import (
    EvalCase,
    compare_with_baseline,
    evaluate_case_status,
    load_dataset,
    run_dataset,
)
from src.eval.baseline import load_baseline_strict
SMOKE_DATASET = Path(__file__).resolve().parents[2] / "src" / "eval" / "datasets" / "smoke.json"


class TestBaselineMustExist:
    def test_strict_loader_raises_on_missing_file(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_baseline_strict(tmp_path / "nope.json")

    def test_strict_loader_raises_on_broken_json(self, tmp_path: Path):
        bad = tmp_path / "bad.json"
        bad.write_text("{oops", encoding="utf-8")
        with pytest.raises(ValueError):
            load_baseline_strict(bad)

    def test_cli_missing_baseline_exits_2_and_never_says_passed(self, tmp_path: Path):
        from typer.testing import CliRunner

        from src.cli import entrypoint

        ds = tmp_path / "d.json"
        ds.write_text(json.dumps({"version": 1, "cases": [
            {"id": "c1", "input": "x", "expect": {"contains": ["ok"]},
             "recorded": {"output": "ok", "tools": []}},
        ]}), encoding="utf-8")

        result = CliRunner().invoke(
            entrypoint.app,
            ["eval", str(ds), "--baseline", str(tmp_path / "missing_baseline.json")],
        )
        assert result.exit_code == 2
        assert "基线不可用" in result.output
        assert "基线比对通过" not in result.output

    def test_cli_save_bootstraps_new_baseline(self, tmp_path: Path):
        from typer.testing import CliRunner

        from src.cli import entrypoint

        ds = tmp_path / "d.json"
        ds.write_text(json.dumps({"version": 1, "cases": [
            {"id": "c1", "input": "x", "expect": {"contains": ["ok"]},
             "recorded": {"output": "ok", "tools": []}},
        ]}), encoding="utf-8")
        baseline = tmp_path / "new_baseline.json"

        result = CliRunner().invoke(
            entrypoint.app, ["eval", str(ds), "--save", "--baseline", str(baseline)]
        )
        assert result.exit_code == 0
        assert baseline.is_file()
        assert "初始基线" in result.output


class TestTriState:
    def test_missing_tool_records_is_unknown(self):
        case = EvalCase(
            case_id="c", input="x",
            expect={"tool_sequence": ["FileReadTool"]},
        )
        status, detail = evaluate_case_status(case, {"output": "ok"})
        assert status == "unknown"
        assert "缺少工具调用记录" in detail

    def test_invalid_regex_is_unknown_not_fail(self):
        case = EvalCase(case_id="c", input="x", expect={"regex": "([unclosed"})
        status, detail = evaluate_case_status(case, {"output": "ok", "tools": []})
        assert status == "unknown"
        assert "非法" in detail

    def test_real_mismatch_is_fail(self):
        case = EvalCase(case_id="c", input="x", expect={"contains": ["ok"]})
        status, _ = evaluate_case_status(case, {"output": "nope", "tools": []})
        assert status == "fail"

    def test_match_is_pass(self):
        case = EvalCase(case_id="c", input="x", expect={"contains": ["ok"]})
        status, _ = evaluate_case_status(case, {"output": "ok", "tools": []})
        assert status == "pass"

    def test_unknown_count_growth_is_a_regression(self, tmp_path: Path):
        case = EvalCase(case_id="c1", input="x", expect={"contains": ["ok"]})
        report = run_dataset([case])  # 缺 recorded → unknown
        problems = compare_with_baseline(report, {"pass_rate": 1.0, "unknown": 0, "outcomes": []})
        assert any("未判定用例增加" in p for p in problems)


class TestSmokeDatasetMatchesRuntime:
    def test_dataset_tool_names_exist_as_real_tools(self):
        """数据集中声明的工具名必须是真实工具类名（否则接真实 agent 必假失败）"""
        from src.tools_runtime.file_edit_tool import FileEditTool
        from src.tools_runtime.file_read_tool import FileReadTool

        real = {FileReadTool.name, FileEditTool.name}
        assert real == {"FileReadTool", "FileEditTool"}

        smoke = Path(SMOKE_DATASET)
        cases = load_dataset(smoke)
        declared: set[str] = set()
        for case in cases:
            declared.update(case.expect.get("tool_sequence") or [])
        assert declared <= real, f"数据集中出现了不存在的工具名: {declared - real}"

    def test_smoke_dataset_still_passes(self):
        smoke = Path(SMOKE_DATASET)
        report = run_dataset(load_dataset(smoke), dataset_name="smoke")
        assert report.failed == 0
        assert report.unknown == 0
        assert report.passed == report.total


class TestHonestyDataset:
    """`src/eval/datasets/honesty.json` 专门演示三态：pass / fail / UNKNOWN"""

    def _dataset(self):
        path = Path(__file__).resolve().parents[2] / "src" / "eval" / "datasets" / "honesty.json"
        return path

    def test_three_states_all_present(self):
        report = run_dataset(load_dataset(self._dataset()), dataset_name="honesty")
        assert report.total == 4
        assert report.passed == 1
        assert report.failed == 1
        assert report.unknown == 2
        assert report.determined == 2

    def test_unknown_cases_have_reasons(self):
        report = run_dataset(load_dataset(self._dataset()), dataset_name="honesty")
        reasons = " ".join(o.detail for o in report.unknowns)
        assert "recorded" in reasons or "工具调用记录" in reasons

    def test_pass_rate_ignores_unknown(self):
        report = run_dataset(load_dataset(self._dataset()), dataset_name="honesty")
        assert report.pass_rate == 0.5, "1 通过 / 2 已判定 = 50%，未知的不进分母"

    def test_smoke_dataset_grew(self):
        """P2-5：只有 3 条用例覆盖不到 equals / 错误暴露等断言"""
        report = run_dataset(load_dataset(SMOKE_DATASET), dataset_name="smoke")
        assert report.total >= 7
        assert report.passed == report.total
