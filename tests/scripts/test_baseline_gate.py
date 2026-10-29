"""`scripts/baseline.py` 的门禁语义测试（2026-10-23 审查补口）。

背景：审查实测到最矛盾的一条——**collect `exit_code=2` 时脚本仍 `exit=0`**，
因为旧版 `hard_fail` 只检查 ruff / version / import_sweep，且把 `None`（没测到）
当通过（`fail not in (0, None)`）。一份会说谎的"唯一取数入口"比手抄数字更危险。

本文件锁死三条语义：
1. `None`（解析失败 / 没测到）**必须**算失败；
2. `collect.exit_code != 0` 必须算失败；
3. 生产可达数低于基线、覆盖率低于阈值必须算失败。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load():
    spec = importlib.util.spec_from_file_location("baseline_gate_under_test", SCRIPTS / "baseline.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


baseline_mod = _load()


def _healthy() -> dict:
    """构造一份"全部通过"的指标快照。"""
    return {
        "version": {"cli": "0.60.7", "pyproject": "0.60.7", "dist_info": "0.60.7", "consistent": True},
        "ruff": {"hard_exit_code": 0},
        "collect": {"collected": 3261, "errors": 0, "exit_code": 0, "status": "ok"},
        "import_sweep": {
            "status": "ok",
            "fail": 0,
            "import_exit": 0,
            "dep_missing": 7,
        },
        "reachability": {"status": "ok", "prod_reachable": 443},
        # 用常量推导，避免门禁上调后"健康基线"被误判（本次 47→60 就踩到）
        "coverage": {"status": "ok", "percent_covered": baseline_mod.MIN_COVERAGE_PERCENT + 5},
    }


class TestHealthyBaseline:
    def test_all_green_has_no_reason(self):
        assert baseline_mod._hard_fail_reasons(_healthy()) == []

    def test_quick_mode_without_optional_metrics_passes(self):
        """--quick 不采集 collect/import_sweep/reachability，不应因此判失败。"""
        data = {
            "version": {"consistent": True},
            "ruff": {"hard_exit_code": 0},
            "coverage": {"status": "missing"},
        }
        assert baseline_mod._hard_fail_reasons(data) == []


class TestNoneMeansFailure:
    """核心：没测到 ≠ 通过。"""

    def test_collect_failure_is_reported(self):
        data = _healthy()
        data["collect"] = {"collected": 3259, "errors": 1, "exit_code": 2, "status": "failed"}
        reasons = baseline_mod._hard_fail_reasons(data)
        assert any("收集失败" in r for r in reasons), reasons

    def test_collect_unparsed_count_is_reported(self):
        data = _healthy()
        data["collect"] = {"collected": None, "errors": 0, "exit_code": 0, "status": "ok"}
        reasons = baseline_mod._hard_fail_reasons(data)
        assert any("收集数解析失败" in r for r in reasons), reasons

    def test_import_sweep_none_is_reported(self):
        data = _healthy()
        data["import_sweep"].update({"fail": None, "import_exit": None, "dep_missing": None})
        reasons = baseline_mod._hard_fail_reasons(data)
        assert len(reasons) >= 3, reasons
        assert all("未能解析" in r for r in reasons), reasons

    def test_import_sweep_nonzero_is_reported(self):
        data = _healthy()
        data["import_sweep"]["fail"] = 2
        reasons = baseline_mod._hard_fail_reasons(data)
        assert any("IMPORT-FAIL = 2" in r for r in reasons), reasons

    def test_import_sweep_abnormal_status_is_reported(self):
        data = _healthy()
        data["import_sweep"]["status"] = "timeout"
        reasons = baseline_mod._hard_fail_reasons(data)
        assert any("未正常结束" in r for r in reasons), reasons

    def test_reachability_none_is_reported(self):
        data = _healthy()
        data["reachability"]["prod_reachable"] = None
        reasons = baseline_mod._hard_fail_reasons(data)
        assert any("生产可达数未能解析" in r for r in reasons), reasons


class TestThresholds:
    def test_reachable_below_floor_is_reported(self):
        data = _healthy()
        data["reachability"]["prod_reachable"] = baseline_mod.MIN_REACHABLE - 1
        reasons = baseline_mod._hard_fail_reasons(data)
        assert any("生产可达" in r for r in reasons), reasons

    def test_reachable_at_floor_passes(self):
        data = _healthy()
        data["reachability"]["prod_reachable"] = baseline_mod.MIN_REACHABLE
        assert baseline_mod._hard_fail_reasons(data) == []

    def test_coverage_below_threshold_is_reported(self):
        data = _healthy()
        data["coverage"]["percent_covered"] = baseline_mod.MIN_COVERAGE_PERCENT - 0.1
        reasons = baseline_mod._hard_fail_reasons(data)
        assert any("覆盖率" in r for r in reasons), reasons

    def test_version_inconsistent_is_reported(self):
        data = _healthy()
        data["version"].update({"dist_info": "0.60.6", "consistent": False})
        reasons = baseline_mod._hard_fail_reasons(data)
        assert any("版本不一致" in r for r in reasons), reasons

    def test_ruff_hard_failure_is_reported(self):
        data = _healthy()
        data["ruff"]["hard_exit_code"] = 1
        reasons = baseline_mod._hard_fail_reasons(data)
        assert any("ruff" in r for r in reasons), reasons


def test_thresholds_are_single_source_of_truth():
    """阈值必须与 pyproject.toml 的 fail_under 一致（防止两处漂移）。"""
    import re

    text = (SCRIPTS.parent / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r"^fail_under\s*=\s*(\d+)", text, re.MULTILINE)
    assert m, "pyproject.toml 缺少 fail_under"
    assert int(m.group(1)) == baseline_mod.MIN_COVERAGE_PERCENT, (
        f"pyproject fail_under={m.group(1)} 与 baseline.MIN_COVERAGE_PERCENT="
        f"{baseline_mod.MIN_COVERAGE_PERCENT} 不一致"
    )
