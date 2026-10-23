"""`scripts/import_sweep.py` 的归因逻辑测试。

背景（2026-10-23 复核）：`classify()` 曾把 `SystemExit` 兜底判为 `IMPORT-FAIL`，
导致 `src.cli.surface_viewer` 因 venv 缺 `jsonschema` 在导入期 `sys.exit(1)` 时，
被上报成"项目代码缺陷"，让 `IMPORT-FAIL = 0` 这条硬指标永久失真。

本测试锁定三种归因，防止回归。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "import_sweep.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("import_sweep_under_test", _SCRIPT)
    assert spec and spec.loader, f"无法加载 {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sweep_mod = _load_module()


def _mnf(name: str) -> ModuleNotFoundError:
    return ModuleNotFoundError(f"No module named '{name}'", name=name)


class TestClassify:
    def test_third_party_missing_is_dep_missing(self):
        # Arrange / Act
        status = sweep_mod.classify(_mnf("loguru"))

        # Assert
        assert status == "DEP-MISSING"

    def test_src_missing_is_import_fail(self):
        status = sweep_mod.classify(_mnf("src.not_exist"))

        assert status == "IMPORT-FAIL"

    def test_import_error_is_import_fail(self):
        status = sweep_mod.classify(ImportError("cannot import name 'X'"))

        assert status == "IMPORT-FAIL"

    def test_type_error_is_import_fail(self):
        status = sweep_mod.classify(TypeError("unsupported operand"))

        assert status == "IMPORT-FAIL"

    def test_system_exit_is_import_exit_not_fail(self):
        """导入期 sys.exit 不得被算作代码缺陷。"""
        status = sweep_mod.classify(SystemExit(1))

        assert status == "IMPORT-EXIT"

    def test_keyboard_interrupt_is_import_exit(self):
        status = sweep_mod.classify(KeyboardInterrupt())

        assert status == "IMPORT-EXIT"

    def test_system_exit_with_zero_code_is_still_import_exit(self):
        """exit(0) 同样是导入期主动退出，一样要单列复核。"""
        status = sweep_mod.classify(SystemExit(0))

        assert status == "IMPORT-EXIT"


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (_mnf("requests"), "DEP-MISSING"),
        (_mnf("src.cli.nope"), "IMPORT-FAIL"),
        (SystemExit(1), "IMPORT-EXIT"),
    ],
)
def test_classify_matrix(exc, expected):
    assert sweep_mod.classify(exc) == expected
