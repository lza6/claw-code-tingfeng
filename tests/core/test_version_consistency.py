"""版本一致性护栏。

本项目历史上出现过的坑：
- `pyproject.toml`、`README`、`CHANGELOG`、`src.__version__` 四处不一致；
- editable 安装后 `dist-info` 停留在旧版本（v0.60.2 vs 项目 v0.60.6），
  导致 `pip show` / `importlib.metadata` 与实际代码不符。

本测试把「pyproject / dist-info / src.__version__」三者锁在一起，
不一致时直接失败并给出修复命令。
"""

from __future__ import annotations

import importlib.metadata as md
from pathlib import Path

import pytest

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.10 走这里
    import tomli as tomllib  # type: ignore[no-redef]

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _project_version() -> str:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def test_src_version_matches_pyproject():
    import src

    assert src.__version__ == _project_version(), (
        "src.__version__ 与 pyproject.toml 不一致；"
        "请检查 src/__init__.py 的 _resolve_version()"
    )


def test_installed_metadata_matches_pyproject():
    try:
        installed = md.version("clawd-code")
    except md.PackageNotFoundError:  # pragma: no cover - 未安装时跳过
        pytest.skip("clawd-code 未以包形式安装")

    assert installed == _project_version(), (
        f"editable 安装元数据滞后：dist-info={installed}，"
        f"pyproject={_project_version()}。"
        "修复：python -m pip install -e . --no-deps --no-build-isolation"
    )
