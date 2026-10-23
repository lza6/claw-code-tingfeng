"""`scripts/check_silent_except.py` 的口径测试。

口径（AST）：一个 `except` handler 的函数体只包含 `pass` 或 `...` 才算静默吞异常。
带注释的 `pass` 仍算；有日志/重新抛出的一律不算。
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_silent_except.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_silent_under_test", _SCRIPT)
    assert spec and spec.loader, f"无法加载 {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()


def _first_handler(source: str) -> ast.ExceptHandler:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            return node.handlers[0]
    raise AssertionError("样本中没有 except")


class TestIsSilent:
    def test_bare_pass_is_silent(self):
        handler = _first_handler("try:\n    x = 1\nexcept Exception:\n    pass\n")
        assert mod._is_silent(handler) is True

    def test_pass_with_comment_is_still_silent(self):
        handler = _first_handler(
            "try:\n    x = 1\nexcept Exception:\n    pass  # noqa: BLE001\n"
        )
        assert mod._is_silent(handler) is True

    def test_ellipsis_is_silent(self):
        handler = _first_handler("try:\n    x = 1\nexcept Exception:\n    ...\n")
        assert mod._is_silent(handler) is True

    def test_logging_handler_is_not_silent(self):
        handler = _first_handler(
            "try:\n    x = 1\nexcept Exception as e:\n    print(e)\n"
        )
        assert mod._is_silent(handler) is False

    def test_reraise_is_not_silent(self):
        handler = _first_handler(
            "try:\n    x = 1\nexcept Exception:\n    raise\n"
        )
        assert mod._is_silent(handler) is False

    def test_pass_plus_statement_is_not_silent(self):
        handler = _first_handler(
            "try:\n    x = 1\nexcept Exception:\n    pass\n    x = 2\n"
        )
        assert mod._is_silent(handler) is False


def test_scan_finds_known_snippet(tmp_path, monkeypatch):
    """在临时目录里放一个已知样本，确认扫描能数到 2 处。"""
    sample = tmp_path / "src"
    sample.mkdir()
    (sample / "a.py").write_text(
        "try:\n    x = 1\nexcept Exception:\n    pass\n"
        "try:\n    y = 2\nexcept Exception as e:\n    print(e)\n"
        "try:\n    z = 3\nexcept Exception:\n    ...\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "SRC", sample)
    monkeypatch.setattr(mod, "ROOT", tmp_path)

    hits = mod.scan()

    assert len(hits) == 2
