"""度量门禁脚本的**门禁行为**测试（2026-10-23 W1'）。

覆盖三件事，都是"尺子本身是否可信"的问题：

1. `import_sweep.py --strict-exit`：`IMPORT-EXIT > 0` 时必须以非 0 退出。
   背景：2026-10-23 把 `SystemExit` 从 `IMPORT-FAIL` 重分类为 `IMPORT-EXIT` 后，
   红线变成"只要不 FAIL 就算过"，于是任何人加一个导入期 `sys.exit(1)` 的模块
   都能绕过门禁（P1-4）。`--strict-exit` 把这条路堵上。

2. `check_silent_except.py` 的阈值来源优先级：显式参数 > 基线文件 > 内置常量。
   背景：静默吞异常长期"只规定不得增加但无人看护"（172 处）。

3. `baseline.py` 的解析与统计函数：它是"单一取数入口"，错了所有文档都会错。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec and spec.loader, f"无法加载 {SCRIPTS / filename}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sweep_mod = _load("import_sweep_gate", "import_sweep.py")
silent_mod = _load("check_silent_gate", "check_silent_except.py")
baseline_mod = _load("baseline_under_test", "baseline.py")


# --------------------------------------------------------------------------
# 1. import_sweep --strict-exit
# --------------------------------------------------------------------------


def _fake_sweep(import_exit: int = 0, fail: int = 0):
    """构造 sweep() 的返回值：results 与 total。"""
    results: list[dict] = []
    for i in range(3):
        results.append({"module": f"src.ok{i}", "status": "IMPORT-OK", "error": ""})
    for i in range(import_exit):
        results.append(
            {"module": f"src.exits{i}", "status": "IMPORT-EXIT", "error": "SystemExit: 1"}
        )
    for i in range(fail):
        results.append(
            {"module": f"src.bad{i}", "status": "IMPORT-FAIL", "error": "TypeError: x"}
        )
    return results, len(results)


def _run_sweep(monkeypatch, argv: list[str], **sweep_kwargs) -> int:
    monkeypatch.setattr(sys, "argv", ["import_sweep.py", *argv])
    monkeypatch.setattr(sweep_mod, "sweep", lambda: _fake_sweep(**sweep_kwargs))
    return sweep_mod.main()


class TestImportSweepStrictExit:
    def test_import_exit_without_strict_passes(self, monkeypatch):
        """默认模式下 IMPORT-EXIT 只是提示，不失败（向后兼容）。"""
        assert _run_sweep(monkeypatch, [], import_exit=2) == 0

    def test_import_exit_with_strict_fails(self, monkeypatch):
        """--strict-exit 下 IMPORT-EXIT > 0 必须失败。"""
        assert _run_sweep(monkeypatch, ["--strict-exit"], import_exit=1) == 1

    def test_no_import_exit_with_strict_passes(self, monkeypatch):
        """--strict-exit 且无 IMPORT-EXIT 时不得误报失败。"""
        assert _run_sweep(monkeypatch, ["--strict-exit"], import_exit=0) == 0

    def test_fail_always_fails(self, monkeypatch):
        """IMPORT-FAIL > 0 无论有没有 --strict-exit 都必须失败。"""
        assert _run_sweep(monkeypatch, ["--strict-exit"], fail=1) == 1
        assert _run_sweep(monkeypatch, [], fail=1) == 1


# --------------------------------------------------------------------------
# 2. check_silent_except 阈值优先级
# --------------------------------------------------------------------------


def _run_silent(monkeypatch, argv: list[str], total: int) -> int:
    monkeypatch.setattr(sys, "argv", ["check_silent_except.py", *argv])
    monkeypatch.setattr(
        silent_mod, "scan", lambda: [{"file": "src/x.py", "line": i} for i in range(total)]
    )
    return silent_mod.main()


class TestSilentExceptThreshold:
    def test_write_baseline_persists_total(self, monkeypatch, tmp_path):
        target = tmp_path / "baseline-silent.json"

        code = _run_silent(monkeypatch, ["--write-baseline", str(target)], total=7)

        assert code == 0
        assert json.loads(target.read_text(encoding="utf-8"))["total"] == 7

    def test_baseline_file_is_used_when_no_explicit_threshold(self, monkeypatch, tmp_path):
        target = tmp_path / "baseline-silent.json"
        target.write_text(json.dumps({"total": 5}), encoding="utf-8")

        # 7 > 5 → 必须失败
        assert _run_silent(monkeypatch, ["--baseline-file", str(target)], total=7) == 1
        # 5 <= 5 → 通过
        assert _run_silent(monkeypatch, ["--baseline-file", str(target)], total=5) == 0

    def test_explicit_fail_over_beats_baseline_file(self, monkeypatch, tmp_path):
        target = tmp_path / "baseline-silent.json"
        target.write_text(json.dumps({"total": 3}), encoding="utf-8")

        # 显式 --fail-over 100 覆盖文件里的 3
        assert (
            _run_silent(
                monkeypatch, ["--baseline-file", str(target), "--fail-over", "100"], total=7
            )
            == 0
        )

    def test_no_threshold_never_fails(self, monkeypatch, tmp_path):
        """没有阈值时纯统计，退出码 0（供人工查看）。"""
        monkeypatch.setattr(silent_mod, "ROOT", tmp_path)  # 不存在的基线文件
        assert _run_silent(monkeypatch, [], total=999) == 0


# --------------------------------------------------------------------------
# 3. baseline.py
# --------------------------------------------------------------------------


class TestBaselineHelpers:
    def test_parse_kv_extracts_number(self):
        tail = ["  IMPORT-FAIL (缺陷): 0", "  IMPORT-EXIT (待复核): 2"]
        assert baseline_mod._parse_kv(tail, "IMPORT-FAIL") == 0
        assert baseline_mod._parse_kv(tail, "IMPORT-EXIT") == 2

    def test_parse_kv_returns_none_when_absent(self):
        assert baseline_mod._parse_kv(["nothing here"], "IMPORT-FAIL") is None

    def test_count_modules_counts_files_and_lines(self, monkeypatch, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
        (src / "b.py").write_text("z = 3\n", encoding="utf-8")
        monkeypatch.setattr(baseline_mod, "SRC", src)

        modules, lines = baseline_mod._count_modules()

        assert modules == 2
        assert lines == 3

    def test_silent_except_total_matches_ast_definition(self, monkeypatch, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text(
            "try:\n    a = 1\nexcept Exception:\n    pass\n"
            "try:\n    b = 2\nexcept Exception:\n    ...\n"
            "try:\n    c = 3\nexcept Exception as e:\n    print(e)\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(baseline_mod, "SRC", src)

        assert baseline_mod._silent_except_total()["total"] == 2

    def test_coverage_metrics_reports_missing_honestly(self, monkeypatch, tmp_path):
        """没有 coverage.json 时必须报 missing，不能编造百分比。"""
        monkeypatch.setattr(baseline_mod, "ROOT", tmp_path)

        result = baseline_mod._coverage_metrics()

        assert result["status"] == "missing"

    def test_coverage_metrics_reads_real_totals(self, monkeypatch, tmp_path):
        payload = {
            "totals": {"percent_covered": 46.1496, "covered_lines": 25877, "num_statements": 56072}
        }
        (tmp_path / "coverage.json").write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(baseline_mod, "ROOT", tmp_path)

        result = baseline_mod._coverage_metrics()

        assert result["status"] == "ok"
        assert result["percent_covered"] == 46.15
        assert result["covered_lines"] == 25877


@pytest.mark.parametrize("script", ["import_sweep.py", "check_silent_except.py", "baseline.py"])
def test_scripts_are_py310_parseable(script):
    """三个门禁脚本必须能被 3.10 解析（本机 venv 与 CI 都是 3.10）。"""
    import ast

    ast.parse((SCRIPTS / script).read_text(encoding="utf-8"))
