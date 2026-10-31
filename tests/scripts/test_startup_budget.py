"""`scripts/startup_budget.py` 的门禁行为测试。

覆盖四件"尺子本身是否可信"的事：

1. 全部指标在预算内 → 退出码 0；
2. 任意指标超预算 → 退出码 1，且 violations 指出是哪一个；
3. 测量失败（子进程跑不起来 / 探针输出不可解析）→ 退出码 2，
   并如实把 error 写进 violations，而不是崩掉或假装通过；
4. `--json` 的字段契约与 stdout 纯净（人读文案不得混进去）。

真实子进程只跑轻量项（`-m src --version` 与 `import src.cli.entrypoint`），
`doctor --json` 单次约 4s，测试里一律 `--skip-doctor`，用 monkeypatch 覆盖。
"""

from __future__ import annotations

import importlib.util
import json
import pytest
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SCRIPT = SCRIPTS / "startup_budget.py"

# 每项测量的实值都远小于这些预算 → 任何解释器/机器上都不该误报超预算。
LOOSE_BUDGETS = [
    "--repeat",
    "1",
    "--version-budget",
    "60",
    "--import-budget",
    "60",
    "--modules-budget",
    "100000",
    "--skip-doctor",
]


def _load():
    spec = importlib.util.spec_from_file_location("startup_budget_under_test", SCRIPT)
    assert spec and spec.loader, f"无法加载 {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load()


def _run(argv: list[str], capsys) -> tuple[int, dict]:
    code = mod.main(argv)
    payload = json.loads(capsys.readouterr().out)
    return code, payload


# --------------------------------------------------------------------------
# 1. 预算内 → 0
# --------------------------------------------------------------------------


class TestWithinBudget:
    def test_all_within_budget_exits_zero(self, capsys):
        code = mod.main([*LOOSE_BUDGETS, "--json"])

        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["ok"] is True
        assert payload["code"] == 0
        assert payload["violations"] == []

    def test_real_subprocess_measurements_are_positive(self, capsys):
        """真实子进程必须给出正数，而不是 0/None 混过去。"""
        code = mod.main([*LOOSE_BUDGETS, "--json"])

        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["version_time"] > 0
        assert payload["entrypoint_import_time"] > 0
        assert payload["module_count"] > 10  # 光是解释器启动就有几十个模块

    def test_skipped_metric_is_none_and_not_a_violation(self, capsys):
        code, payload = _run([*LOOSE_BUDGETS, "--json"], capsys)

        assert code == 0
        assert payload["doctor_time"] is None
        assert all(v["metric"] != "doctor_time" for v in payload["violations"])


# --------------------------------------------------------------------------
# 2. 超预算 → 1
# --------------------------------------------------------------------------


class TestOverBudget:
    def test_version_over_budget_exits_one(self, capsys):
        code, payload = _run(
            [
                "--repeat",
                "1",
                "--version-budget",
                "0.000001",
                "--import-budget",
                "60",
                "--modules-budget",
                "100000",
                "--skip-doctor",
                "--json",
            ],
            capsys,
        )

        assert code == 1
        assert payload["ok"] is False
        assert payload["code"] == 1
        over = [v for v in payload["violations"] if v["metric"] == "version_time"]
        assert len(over) == 1
        assert over[0]["error"] is None
        assert over[0]["actual"] > over[0]["budget"]

    def test_module_count_over_budget_exits_one(self, capsys):
        """模块数超限也要单独判死（import 副作用膨胀的信号）。"""
        code, payload = _run(
            [
                "--repeat",
                "1",
                "--version-budget",
                "60",
                "--import-budget",
                "60",
                "--modules-budget",
                "5",
                "--skip-doctor",
                "--json",
            ],
            capsys,
        )

        assert code == 1
        assert [v["metric"] for v in payload["violations"]] == ["module_count"]


# --------------------------------------------------------------------------
# 3. 测量失败 → 2
# --------------------------------------------------------------------------


class TestMeasurementFailure:
    def test_unusable_interpreter_exits_two(self, capsys):
        """解释器路径不存在 → 子进程起不来 → 2，且不崩。"""
        missing = str(Path.home() / "no-such-python-xyz")
        code, payload = _run(
            ["--python", missing, "--repeat", "1", "--skip-doctor", "--json"], capsys
        )

        assert code == 2
        assert payload["ok"] is False
        metrics = {v["metric"]: v for v in payload["violations"]}
        assert metrics["version_time"]["error"]
        assert metrics["entrypoint_import_time"]["error"]
        assert metrics["module_count"]["error"]

    def test_probe_garbage_output_is_reported(self, monkeypatch, capsys):
        """探针输出不可解析时必须记 error，不能当成 0 秒通过。"""
        monkeypatch.setattr(mod, "measure_version", lambda *a, **k: (0.1, ""))
        monkeypatch.setattr(mod, "measure_entrypoint", lambda *a, **k: (None, None, "garbage"))
        monkeypatch.setattr(mod, "measure_doctor", lambda *a, **k: (0.1, ""))

        code, payload = _run(["--repeat", "1", "--json"], capsys)

        assert code == 2
        errors = {v["metric"]: v["error"] for v in payload["violations"]}
        assert errors["entrypoint_import_time"] == "garbage"
        assert errors["module_count"] == "garbage"

    def test_failure_takes_precedence_over_over_budget(self, monkeypatch, capsys):
        """一项失败 + 一项超预算 → 2（无法测量优先，因为结论不完整）。"""
        monkeypatch.setattr(mod, "measure_version", lambda *a, **k: (None, "boom"))
        monkeypatch.setattr(mod, "measure_entrypoint", lambda *a, **k: (0.1, 900, ""))
        monkeypatch.setattr(mod, "measure_doctor", lambda *a, **k: (0.1, ""))

        code, payload = _run(
            ["--repeat", "1", "--modules-budget", "5", "--json"], capsys
        )

        assert code == 2
        assert payload["code"] == 2
        assert {v["metric"] for v in payload["violations"]} == {"version_time", "module_count"}


# --------------------------------------------------------------------------
# 4. --json 契约 + stdout 纯净
# --------------------------------------------------------------------------


class TestJsonContract:
    FIELDS = {
        "ok",
        "code",
        "version_time",
        "entrypoint_import_time",
        "module_count",
        "doctor_time",
        "budgets",
        "violations",
    }

    def test_contract_fields_present(self, capsys):
        _code, payload = _run([*LOOSE_BUDGETS, "--json"], capsys)

        assert set(payload) == self.FIELDS
        assert set(payload["budgets"]) == {
            "version_time",
            "entrypoint_import_time",
            "module_count",
            "doctor_time",
        }
        assert isinstance(payload["violations"], list)
        assert isinstance(payload["module_count"], int)

    def test_stdout_is_pure_json_in_subprocess(self):
        """真实子进程跑 `--json`：stdout 必须整体可被 json.loads。"""
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), *LOOSE_BUDGETS, "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )

        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)  # 有任何人读文案混进来都会在这里炸
        assert payload["ok"] is True
        assert proc.stdout.strip().count("\n") == 0  # 单行 JSON，日志已走 stderr

    def test_update_baseline_prints_to_stderr_not_stdout(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), *LOOSE_BUDGETS, "--json", "--update-baseline"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )

        assert proc.returncode == 0, proc.stderr
        json.loads(proc.stdout)  # stdout 仍是纯 JSON
        assert "建议预算" in proc.stderr


# --------------------------------------------------------------------------
# 5. 预算常量与实测值不得分叉
# --------------------------------------------------------------------------


class TestBudgetBaseline:
    def test_suggest_budget_rounds_up_to_step(self):
        assert mod.suggest_budget(0.783) == 1.10
        assert mod.suggest_budget(0.612) == 0.85
        assert mod.suggest_budget(4.100) == 5.55

    def test_suggest_module_budget_rounds_up_to_ten(self):
        assert mod.suggest_module_budget(761) == 1030

    def test_default_budgets_match_measured_values(self):
        """DEFAULT_BUDGETS 必须等于"实测 × 1.35 向上取整"，防止注释与常量分叉。"""
        measured = mod.MEASURED_2026_10_31
        for metric in mod.TIME_METRICS:
            assert mod.DEFAULT_BUDGETS[metric] == mod.suggest_budget(measured[metric]), metric
        assert mod.DEFAULT_BUDGETS["module_count"] == mod.suggest_module_budget(
            measured["module_count"]
        )

    def test_cli_override_beats_default_budget(self):
        """--*-budget 覆盖必须真的生效（否则 CI 无法按机器调预算）。"""
        args = mod.build_parser().parse_args(
            ["--version-budget", "0.5", "--modules-budget", "999", "--doctor-budget", "9.5"]
        )
        budgets = mod.resolve_budgets(args)

        assert budgets["version_time"] == 0.5
        assert budgets["module_count"] == 999
        assert budgets["doctor_time"] == 9.5
        assert budgets["entrypoint_import_time"] == mod.DEFAULT_BUDGETS["entrypoint_import_time"]


class TestEnvFactor:
    """`CLAWD_STARTUP_BUDGET_FACTOR`：给 CI（共享 runner）用的宽松系数

    默认预算是本机 Windows 实测值。CI 用同一个绝对值会因机器更慢而假红，
    假红会让人把门禁静音 —— 这里钉住"系数只放大时间项、模块数不受影响"，
    避免有人用它把结构量（模块数）也放宽，从而弱化门禁。
    """

    def test_factor_scales_time_budgets_only(self, monkeypatch):
        monkeypatch.setenv("CLAWD_STARTUP_BUDGET_FACTOR", "2.0")
        budgets = mod.resolve_budgets(_fake_args())

        assert budgets["version_time"] == round(mod.DEFAULT_BUDGETS["version_time"] * 2.0, 2)
        assert budgets["doctor_time"] == round(mod.DEFAULT_BUDGETS["doctor_time"] * 2.0, 2)
        assert budgets["module_count"] == mod.DEFAULT_BUDGETS["module_count"], "模块数是结构量，不该被放大"

    def test_no_factor_keeps_defaults(self, monkeypatch):
        monkeypatch.delenv("CLAWD_STARTUP_BUDGET_FACTOR", raising=False)
        assert mod.resolve_budgets(_fake_args()) == {
            key: mod.DEFAULT_BUDGETS[key] for key in mod.DEFAULT_BUDGETS
        }

    def test_garbage_factor_exits_instead_of_silently_ignored(self, monkeypatch):
        monkeypatch.setenv("CLAWD_STARTUP_BUDGET_FACTOR", "loud")
        with pytest.raises(SystemExit):
            mod.resolve_budgets(_fake_args())

    def test_cli_override_wins_over_factor(self, monkeypatch):
        monkeypatch.setenv("CLAWD_STARTUP_BUDGET_FACTOR", "2.0")
        args = _fake_args(version_budget=0.5)
        assert mod.resolve_budgets(args)["version_time"] == 0.5


def _fake_args(**overrides):
    """构造 resolve_budgets 需要的命名空间（没覆盖的一律 None = 不覆盖）"""
    base = {
        "version_budget": None,
        "import_budget": None,
        "modules_budget": None,
        "doctor_budget": None,
    }
    base.update(overrides)
    return __import__('types').SimpleNamespace(**base)
