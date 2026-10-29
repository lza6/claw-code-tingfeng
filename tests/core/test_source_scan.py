"""源码扫描排除规则测试

真实事故：打包版 Host 的 cwd 是 resources/host（含内嵌 Python 运行时），
`world_model` 直接 glob("**/*.py") 扫到 11,606 个文件（绝大多数 site-packages），
后台索引把事件循环占满，UI 的用量面板一直卡在"加载中…"。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.source_scan import DEFAULT_MAX_FILES, scan_source_files


def _mk(root: Path, rel: str, body: str = "x = 1\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class TestExclusions:
    def test_site_packages_skipped(self, tmp_path: Path):
        _mk(tmp_path, "app.py")
        _mk(tmp_path, "python/Lib/site-packages/requests/__init__.py")
        result = scan_source_files(tmp_path)
        names = {p.name for p in result.files}
        assert names == {"app.py"}

    def test_node_modules_and_dist_skipped(self, tmp_path: Path):
        _mk(tmp_path, "a.py")
        _mk(tmp_path, "node_modules/lib/index.js")
        _mk(tmp_path, "dist/bundle.py")
        _mk(tmp_path, ".clawd/cache.py")
        result = scan_source_files(tmp_path, suffixes=(".py", ".js"))
        rels = {str(p.relative_to(tmp_path)).replace("\\", "/") for p in result.files}
        assert rels == {"a.py"}

    def test_nested_project_code_kept(self, tmp_path: Path):
        _mk(tmp_path, "src/pkg/mod.py")
        _mk(tmp_path, "tests/test_mod.py")
        result = scan_source_files(tmp_path)
        assert result.count == 2

    def test_suffix_filter(self, tmp_path: Path):
        _mk(tmp_path, "a.py")
        _mk(tmp_path, "b.ts")
        assert scan_source_files(tmp_path, suffixes=(".ts",)).count == 1


class TestLimit:
    def test_truncated_flag_and_cap(self, tmp_path: Path):
        for i in range(10):
            _mk(tmp_path, f"m{i}.py")
        result = scan_source_files(tmp_path, max_files=5)
        assert result.truncated is True
        assert result.count == 5

    def test_not_truncated_under_limit(self, tmp_path: Path):
        _mk(tmp_path, "a.py")
        result = scan_source_files(tmp_path, max_files=DEFAULT_MAX_FILES)
        assert result.truncated is False and result.count == 1
