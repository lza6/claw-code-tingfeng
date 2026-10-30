"""RepoMap 深度行为测试 — 真实小仓库上的建图、缓存、剪枝与降级路径

覆盖目标（src/rag/repo_map.py）：
    1. 语言检测与结构解析（含非 UTF-8、缺失文件、tree-sitter 缺失降级）
    2. 结构缓存（TTL 过期、LRU 驱逐、unknown 语言不入缓存）
    3. PageRank 权重计算（精确匹配 / 后缀匹配 / 悬挂节点 / dep_graph 优先）
    4. SQLite 标签缓存（读写、失效、失败静默）
    5. 地图格式化与 token 预算剪枝（函数数上限、截断占位符）
    6. get_repo_map 的边界（零预算、空文件表、上下文窗口补偿、RecursionError）
    7. 排名地图（ranks 缓存命中/强制刷新/过期、scanner 注入、文件数上限）
    8. get_files_by_pattern（git 列举成功 / git 失败回退 os.walk / 排除模式）

测试数据一律来自 tmp_path 下的真实文件，不使用假的文件读取。
仅当需要模拟"Linux /sys 不存在"或"git 不可用"时才替换外部协作者。
"""
from __future__ import annotations

import logging
import sqlite3
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.rag import repo_map as repo_map_module
from src.rag.repo_map import CodeStructure, RepoMap
from src.rag.repo_map import get_repo_map as get_global_repo_map

CORE_PY = '''"""core module"""
import os
from pkg.util import helper


class Widget:
    """A widget"""

    def render(self, width):
        return width

    def bare(self):
        return None


def build(name, size=3):
    return (name, size)


def decorated(x) -> int:
    return x
'''


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """构造一个真实的小仓库：多语言文件 + 非 UTF-8 + 大文件 + 空目录。"""
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "empty_dir").mkdir()
    (root / ".hidden").mkdir()
    (root / "node_modules").mkdir()

    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "core.py").write_text(CORE_PY, encoding="utf-8")
    (root / "pkg" / "util.js").write_text("function helper() { return 1; }\n", encoding="utf-8")
    # 非 UTF-8：latin-1 编码的类名，读取时以 errors='replace' 兜底
    (root / "latin.py").write_bytes(b"class Caf\xe9:\n    pass\n\ndef greet(name):\n    return name\n")
    # 大文件：60 个顶层函数，用于验证每文件函数数上限
    (root / "big.py").write_text(
        "\n".join(f"def fn_{i}(x):\n    return x" for i in range(60)) + "\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# readme\n", encoding="utf-8")
    (root / "data.bin").write_bytes(b"\x00\x01\x02")
    (root / ".hidden" / "secret.py").write_text("def hidden():\n    pass\n", encoding="utf-8")
    (root / "node_modules" / "dep.py").write_text("def dep():\n    pass\n", encoding="utf-8")
    return root


@pytest.fixture
def make_map(tmp_path: Path):
    """创建 RepoMap 并保证测试结束时关闭 SQLite 连接（避免 Windows 上删目录失败）。"""
    created: list[RepoMap] = []
    cache_root = tmp_path / "cache-root"
    cache_root.mkdir()

    def _make(**kwargs) -> RepoMap:
        kwargs.setdefault("root_dir", cache_root)
        instance = RepoMap(**kwargs)
        created.append(instance)
        return instance

    yield _make
    for instance in created:
        instance.close()


# ===== 1. 语言检测 =====


class TestDetectLanguage:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("a.py", "python"),
            ("a.pyi", "python"),
            ("A.PY", "python"),  # 后缀大小写归一
            ("a.jsx", "javascript"),
            ("a.tsx", "typescript"),
            ("a.yml", "yaml"),
            ("a.cpp", "cpp"),
            ("a.bin", None),
            ("Makefile", None),
            ("noext", None),
        ],
    )
    def test_detect_language_by_suffix(self, make_map, name, expected):
        rm = make_map()
        assert rm.detect_language(name) == expected

    def test_detect_language_ignores_directory_part(self, make_map):
        rm = make_map()
        assert rm.detect_language("some/dir.with.dots/module.py") == "python"


# ===== 2. 结构解析 =====


class TestStructureParsing:
    def test_parses_classes_functions_imports(self, make_map, repo_root):
        rm = make_map(root_dir=repo_root)
        struct = rm.get_structure(str(repo_root / "pkg" / "core.py"))

        assert struct.language == "python"
        assert struct.classes == ["Widget"]
        names = [f["name"] for f in struct.functions]
        assert "render" in names
        assert "build" in names
        assert "decorated" in names
        # from X import Y 记录的是模块名，import X 记录的是模块名
        assert "os" in struct.imports
        assert "pkg.util" in struct.imports

    def test_simple_parser_signature_matches_declaration(self, make_map, repo_root):
        """回归：简单解析器曾把签名拼成 '(('，与调用处 `def name(sig)` 的渲染约定冲突。

        缺陷位置（修复前）: src/rag/repo_map.py:427
            signature = '(' + '(' if len(match) > 1 else ''
        现象: `def render(self, width):` 解析出 signature='(('，渲染成 `def render((()`
              `def bare():` 解析出 signature='(('
              `def baz:` 解析出 name='baz:'（名字带冒号）
        期望: 与 _parse_with_tree_sitter 的正则路径一致 —— signature 是括号内的参数文本。
        """
        rm = make_map(root_dir=repo_root)
        struct = rm.get_structure(str(repo_root / "pkg" / "core.py"))
        by_name = {f["name"]: f["signature"] for f in struct.functions}

        assert by_name["render"] == "self, width"
        assert by_name["bare"] == "self"
        assert by_name["build"] == "name, size=3"
        assert by_name["decorated"] == "x"

    def test_simple_parser_strips_colon_from_bare_def(self, make_map, repo_root):
        """`def name:`（无括号）不应把冒号带进函数名。"""
        rm = make_map(root_dir=repo_root)
        target = repo_root / "bare.py"
        target.write_text("def no_parens:\n    return 1\n", encoding="utf-8")

        struct = rm.get_structure(str(target))
        assert [f["name"] for f in struct.functions] == ["no_parens"]
        assert struct.functions[0]["signature"] == ""

    def test_non_utf8_file_is_read_with_replacement(self, make_map, repo_root):
        rm = make_map(root_dir=repo_root)
        struct = rm.get_structure(str(repo_root / "latin.py"))

        assert struct.language == "python"
        # 文件名编码损坏但结构仍被解析出来
        assert len(struct.classes) == 1
        assert [f["name"] for f in struct.functions] == ["greet"]

    def test_empty_file_yields_no_symbols(self, make_map, repo_root):
        rm = make_map(root_dir=repo_root)
        struct = rm.get_structure(str(repo_root / "pkg" / "__init__.py"))
        assert struct.classes == []
        assert struct.functions == []
        assert struct.imports == []

    def test_missing_file_falls_back_to_empty_structure(self, make_map, repo_root):
        rm = make_map(root_dir=repo_root)
        struct = rm.get_structure(str(repo_root / "pkg" / "does_not_exist.py"))

        assert struct.path.endswith("does_not_exist.py")
        assert struct.language == "python"  # 语言按后缀识别
        assert struct.classes == [] and struct.functions == [] and struct.imports == []

    def test_unsupported_extension_returns_unknown_language(self, make_map, repo_root):
        rm = make_map(root_dir=repo_root)
        struct = rm.get_structure(str(repo_root / "data.bin"))

        assert struct.language == "unknown"
        assert struct.classes == [] and struct.functions == []
        # unknown 不进入结构缓存
        assert str(repo_root / "data.bin") not in rm._structure_cache

    def test_tree_sitter_missing_falls_back_to_simple_parser(self, make_map, repo_root, monkeypatch):
        """`get_structure` 的 except ImportError 分支：tree-sitter 不可用时降级。"""
        rm = make_map(root_dir=repo_root)

        def _raise_import_error(file_path, language):
            raise ImportError("tree_sitter not installed")

        monkeypatch.setattr(rm, "_parse_with_tree_sitter", _raise_import_error)
        struct = rm.get_structure(str(repo_root / "pkg" / "core.py"))

        assert struct.classes == ["Widget"]
        assert "render" in [f["name"] for f in struct.functions]

    def test_parse_with_tree_sitter_returns_structure_without_grammar(self, make_map, repo_root):
        """本机未安装 tree_sitter 时，该函数内部 except 分支仍返回可用结构（不抛异常）。"""
        rm = make_map(root_dir=repo_root)
        struct = rm._parse_with_tree_sitter(str(repo_root / "pkg" / "core.py"), "python")

        assert struct.language == "python"
        assert struct.classes == ["Widget"]

    def test_parse_with_tree_sitter_body_when_module_importable(self, make_map, repo_root, monkeypatch):
        """模拟 tree-sitter 可导入时的解析路径。

        NOTE: 该路径用 `^def` 锚定行首，只抓顶层函数（缩进的方法不匹配），
        与 _parse_simple 的 strip 后匹配不同 —— 这是两条路径的真实差异。
        """
        fake_module = types.ModuleType("tree_sitter")
        fake_module.Parser = lambda: object()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "tree_sitter", fake_module)

        rm = make_map(root_dir=repo_root)
        struct = rm._parse_with_tree_sitter(str(repo_root / "pkg" / "core.py"), "python")

        assert struct.classes == ["Widget"]
        assert [f["name"] for f in struct.functions] == ["build", "decorated"]
        assert struct.functions[0]["signature"] == "name, size=3"
        assert "os" in struct.imports

    def test_tree_sitter_path_yields_no_symbols_for_non_python(self, make_map, repo_root, monkeypatch):
        """tree-sitter 路径只对 python 抽取符号，其它语言返回空结构（记录现状）。"""
        fake_module = types.ModuleType("tree_sitter")
        fake_module.Parser = lambda: object()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "tree_sitter", fake_module)

        rm = make_map(root_dir=repo_root)
        struct = rm._parse_with_tree_sitter(str(repo_root / "pkg" / "util.js"), "javascript")

        assert struct.language == "javascript"
        assert struct.classes == []
        assert struct.functions == []
        assert struct.imports == []

    def test_parsers_ignore_malformed_lines(self, make_map, repo_root):
        """残缺行（'class' 无名字、'from' 无模块名）不应抛异常，也不产生符号。"""
        rm = make_map(root_dir=repo_root)
        target = repo_root / "weird.py"
        target.write_text("class\nfrom nowhere\nimport\n\n", encoding="utf-8")

        struct = rm.get_structure(str(target))

        assert struct.classes == []
        assert struct.functions == []
        assert struct.imports == []


# ===== 3. 结构缓存 =====


class TestStructureCache:
    def test_second_call_hits_cache(self, make_map, repo_root):
        rm = make_map(root_dir=repo_root)
        path = str(repo_root / "pkg" / "core.py")

        first = rm.get_structure(path)
        second = rm.get_structure(path)

        assert second is first
        assert len(rm._structure_cache) == 1

    def test_cache_expires_after_ttl(self, make_map, repo_root, monkeypatch):
        rm = make_map(root_dir=repo_root)
        target = repo_root / "expire.py"
        target.write_text("def first():\n    pass\n", encoding="utf-8")

        first = rm.get_structure(str(target))
        assert [f["name"] for f in first.functions] == ["first"]

        target.write_text("def second():\n    pass\n", encoding="utf-8")
        assert rm.get_structure(str(target)) is first  # TTL 内仍命中旧缓存

        expired = rm._cache_time + rm._cache_ttl + 1
        monkeypatch.setattr(repo_map_module, "time", SimpleNamespace(time=lambda: expired))

        refreshed = rm.get_structure(str(target))
        assert refreshed is not first
        assert [f["name"] for f in refreshed.functions] == ["second"]

    def test_evicts_oldest_entry_over_max_size(self, make_map, repo_root):
        rm = make_map(root_dir=repo_root)
        rm.max_cache_size = 2
        oldest = str(repo_root / "pkg" / "core.py")

        rm.get_structure(oldest)
        rm.get_structure(str(repo_root / "pkg" / "util.js"))
        rm.get_structure(str(repo_root / "big.py"))

        assert len(rm._structure_cache) == 2
        assert oldest not in rm._structure_cache


# ===== 4. PageRank =====


class _FixedDepGraph:
    """返回固定下游依赖的替身（get_downstream 优先于 struct.imports）。"""

    def __init__(self, mapping: dict[str, list[str]]):
        self._mapping = mapping
        self.updated: list[tuple[str, list[str]]] = []

    def update_file(self, path: str, imports: list[str]) -> None:
        self.updated.append((path, list(imports)))

    def get_downstream(self, path: str) -> list[str]:
        return list(self._mapping.get(path, []))


class _ExplodingDepGraph:
    def update_file(self, path, imports):
        raise RuntimeError("dependency graph unavailable")

    def get_downstream(self, path):
        return []


class _NoopDepGraph:
    def update_file(self, path, imports):
        return None

    def get_downstream(self, path):
        return []


class TestPagerank:
    def test_empty_input_returns_empty_mapping(self, make_map):
        rm = make_map()
        assert rm._calculate_pagerank([]) == {}

    def test_imported_file_scores_higher(self, make_map):
        rm = make_map()
        structures = [
            CodeStructure(path="a.py", language="python"),
            CodeStructure(path="b.py", language="python"),
            CodeStructure(path="c.py", language="python", imports=["a.py"]),
        ]

        ranks = rm._calculate_pagerank(structures)

        assert set(ranks) == {"a.py", "b.py", "c.py"}
        assert ranks["a.py"] > ranks["b.py"]

    def test_import_resolves_by_stem_and_basename(self, make_map):
        """imports 里可能只写模块名（'a'）或文件名（'a.py'），两者都要能对上。"""
        rm = make_map()
        structures = [
            CodeStructure(path="pkg/a.py", language="python"),
            CodeStructure(path="other.py", language="python", imports=["a"]),
            CodeStructure(path="third.py", language="python", imports=["a.py"]),
        ]

        ranks = rm._calculate_pagerank(structures)

        # pkg/a.py 被两个文件引用，权重必须高于未被引用的 other.py
        assert ranks["pkg/a.py"] > ranks["other.py"]
        assert ranks["pkg/a.py"] > ranks["third.py"]

    def test_unknown_import_is_ignored(self, make_map):
        """指向不存在文件的 import 不应改变其它节点的相对权重。"""
        rm = make_map()
        structures = [
            CodeStructure(path="a.py", language="python", imports=["not_present"]),
            CodeStructure(path="b.py", language="python"),
        ]

        ranks = rm._calculate_pagerank(structures)

        assert set(ranks) == {"a.py", "b.py"}
        assert all(value > 0 for value in ranks.values())
        # 无效依赖被过滤后 a.py 变成悬挂节点，与 b.py 同权
        assert ranks["a.py"] == pytest.approx(ranks["b.py"])

    def test_dangling_node_spreads_weight_evenly(self, make_map):
        rm = make_map()
        structures = [
            CodeStructure(path="a.py", language="python"),
            CodeStructure(path="b.py", language="python"),
        ]

        ranks = rm._calculate_pagerank(structures)

        assert ranks["a.py"] == pytest.approx(ranks["b.py"])

    def test_dep_graph_takes_priority_over_imports(self, make_map):
        graph = _FixedDepGraph({"c.py": ["a.py"]})
        rm = make_map(dep_graph=graph)
        structures = [
            CodeStructure(path="a.py", language="python"),
            CodeStructure(path="b.py", language="python"),
            # imports 指向 b.py，但 dep_graph 指向 a.py —— dep_graph 优先
            CodeStructure(path="c.py", language="python", imports=["b.py"]),
        ]

        ranks = rm._calculate_pagerank(structures)

        assert ranks["a.py"] > ranks["b.py"]


# ===== 5. SQLite 标签缓存 =====


class TestTagsCache:
    def test_save_then_load_roundtrip(self, make_map, repo_root):
        rm = make_map(root_dir=repo_root)
        target = repo_root / "pkg" / "core.py"
        stat = target.stat()

        rm.save_tags_cache(str(target), "python", "Widget|render", stat.st_mtime, stat.st_size)
        cached = rm.load_tags_cache(str(target))

        assert cached is not None
        assert cached["language"] == "python"
        assert cached["tags"] == "Widget|render"

    def test_load_returns_none_when_file_changed(self, make_map, repo_root):
        rm = make_map(root_dir=repo_root)
        target = repo_root / "pkg" / "util.js"
        stat = target.stat()
        rm.save_tags_cache(str(target), "javascript", "helper", stat.st_mtime, stat.st_size)

        target.write_text("function helper() { return 2; }\n", encoding="utf-8")

        assert rm.load_tags_cache(str(target)) is None

    def test_load_returns_none_for_unknown_path(self, make_map, repo_root):
        rm = make_map(root_dir=repo_root)
        assert rm.load_tags_cache(str(repo_root / "never_saved.py")) is None

    def test_load_returns_none_when_file_deleted(self, make_map, repo_root):
        rm = make_map(root_dir=repo_root)
        target = repo_root / "gone.py"
        target.write_text("def gone():\n    pass\n", encoding="utf-8")
        stat = target.stat()
        rm.save_tags_cache(str(target), "python", "gone", stat.st_mtime, stat.st_size)

        target.unlink()

        assert rm.load_tags_cache(str(target)) is None

    def test_save_failure_is_swallowed(self, make_map, caplog):
        caplog.set_level(logging.DEBUG)  # 该分支用 logger.debug 记录，默认 WARNING 级捕获不到
        rm = make_map()

        def _boom():
            raise sqlite3.OperationalError("database is locked")

        rm._get_tags_db = _boom  # type: ignore[method-assign]
        rm.save_tags_cache("a.py", "python", "tags", 1.0, 1)
        assert "Failed to save tags cache" in caplog.text

    def test_load_failure_is_swallowed(self, make_map, caplog):
        caplog.set_level(logging.DEBUG)
        rm = make_map()

        def _boom():
            raise sqlite3.OperationalError("database is locked")

        rm._get_tags_db = _boom  # type: ignore[method-assign]
        assert rm.load_tags_cache("a.py") is None
        assert "Failed to load tags cache" in caplog.text

    def test_close_releases_connection(self, make_map):
        rm = make_map()
        rm.save_tags_cache("a.py", "python", "tags", 1.0, 1)
        assert rm._db_connection is not None

        rm.close()

        assert rm._db_connection is None
        rm.close()  # 幂等：重复关闭不抛异常

    def test_close_logs_error_when_connection_close_fails(self, make_map, caplog):
        rm = make_map()
        rm.save_tags_cache("a.py", "python", "tags", 1.0, 1)

        class _BrokenConnection:
            def close(self):
                raise sqlite3.OperationalError("cannot close")

        rm._db_connection = _BrokenConnection()  # type: ignore[assignment]
        rm.close()

        assert "Error closing RepoMap database" in caplog.text

    def test_context_manager_closes_connection(self, tmp_path):
        with RepoMap(root_dir=tmp_path) as rm:
            rm.save_tags_cache("a.py", "python", "tags", 1.0, 1)
            assert rm._db_connection is not None
        assert rm._db_connection is None


# ===== 6. 地图格式化与 token 剪枝 =====


class TestFormatting:
    def test_to_map_entry_depth1_uses_docstring_when_no_symbols(self):
        struct = CodeStructure(path="a.py", language="python", docstring="module purpose")
        entry = struct.to_map_entry(depth=1)

        assert entry.splitlines()[0] == "# a.py (python)"
        assert "doc: module purpose..." in entry

    def test_to_map_entry_depth1_header_only_when_empty(self):
        struct = CodeStructure(path="a.py", language="python")
        assert struct.to_map_entry(depth=1) == "# a.py (python)"

    def test_to_map_entry_depth1_lists_symbols(self):
        struct = CodeStructure(
            path="a.py",
            language="python",
            classes=["K"],
            functions=[{"name": "f", "signature": "x"}],
            docstring="ignored when symbols exist",
        )
        entry = struct.to_map_entry(depth=1)

        assert "symbols: K, f..." in entry
        assert "ignored when symbols exist" not in entry

    def test_to_map_entry_depth3_truncates_docstring_to_first_line(self):
        struct = CodeStructure(
            path="a.py",
            language="python",
            functions=[{"name": "f", "signature": "x", "docstring": "first line\nsecond line"}],
        )
        entry = struct.to_map_entry(depth=3)

        assert "def f(x):  # first line" in entry
        assert "second line" not in entry

    def test_to_map_entry_depth2_without_docstring(self):
        struct = CodeStructure(
            path="a.py",
            language="python",
            classes=["K"],
            functions=[{"name": "f", "signature": "x", "docstring": "doc"}],
        )
        entry = struct.to_map_entry(depth=2)

        assert "  class K:" in entry
        assert "    def f(x)" in entry
        assert "# doc" not in entry

    def test_get_map_returns_empty_for_no_files(self, make_map):
        rm = make_map()
        assert rm.get_map([]) == ""

    def test_get_map_orders_by_language_weight_and_skips_unknown(self, make_map, repo_root):
        rm = make_map(root_dir=repo_root)
        output = rm.get_map(
            [
                str(repo_root / "pkg" / "util.js"),
                str(repo_root / "pkg" / "core.py"),
                str(repo_root / "data.bin"),
            ]
        )

        py_pos = output.index("core.py")
        js_pos = output.index("util.js")
        assert py_pos < js_pos  # python 权重 1.0 > javascript 0.9
        assert "data.bin" not in output  # unknown 语言被跳过
        assert "// imports: os, pkg.util" in output

    def test_format_map_limits_functions_per_file(self, make_map, repo_root):
        rm = make_map(token_budget=100_000, root_dir=repo_root)
        struct = rm.get_structure(str(repo_root / "big.py"))
        assert len(struct.functions) == 60

        output = rm._format_map([struct], show_imports=False, show_docstrings=False)

        assert output.count("  def ") == 10
        assert "def fn_9(" in output
        assert "def fn_10(" not in output

    def test_format_map_shows_docstrings_on_demand(self, make_map):
        rm = make_map(token_budget=100_000)
        struct = CodeStructure(path="a.py", language="python", docstring="explains everything")

        assert "// explains everything" in rm._format_map([struct], True, True)
        assert "explains everything" not in rm._format_map([struct], True, False)

    def test_format_map_adds_truncated_placeholder_when_budget_left(self, make_map):
        # a.py 占 3 token；第二项 14 token 超预算，但预算仍剩 >5 token → 打截断占位符
        rm = make_map(token_budget=12)
        structures = [
            CodeStructure(path="a.py", language="python"),
            CodeStructure(
                path="pkg/sub/b.py",
                language="python",
                classes=["K"],
                functions=[{"name": "f", "signature": ""}, {"name": "g", "signature": ""}],
            ),
            CodeStructure(path="pkg/sub/c.py", language="python"),
        ]

        output = rm._format_map(structures, True, False)

        assert "// a.py" in output
        assert "// pkg/sub/b.py (truncated)" in output
        assert "c.py" not in output

    def test_format_map_breaks_without_placeholder_when_budget_tight(self, make_map):
        rm = make_map(token_budget=4)
        structures = [
            CodeStructure(path="a.py", language="python"),
            CodeStructure(
                path="pkg/sub/b.py",
                language="python",
                classes=["K"],
                functions=[{"name": "f", "signature": ""}],
            ),
        ]

        output = rm._format_map(structures, True, False)

        assert "// a.py" in output
        assert "truncated" not in output


# ===== 7. get_repo_map 边界 =====


class TestGetRepoMap:
    def test_zero_budget_returns_none(self, make_map):
        rm = make_map(token_budget=0)
        assert rm.get_repo_map([], ["a.py"]) is None

    def test_no_other_files_returns_none(self, make_map):
        rm = make_map(token_budget=1024)
        assert rm.get_repo_map(["a.py"], []) is None

    def test_recursion_error_disables_map(self, make_map, caplog):
        rm = make_map(token_budget=1024)

        def _boom(*args, **kwargs):
            raise RecursionError("too deep")

        rm._get_ranked_tags_map = _boom  # type: ignore[method-assign]

        assert rm.get_repo_map([], ["a.py"]) is None
        assert rm.token_budget == 0  # 自我保护：后续调用直接返回 None
        assert "repo too large" in caplog.text

    def test_empty_listing_returns_none(self, make_map):
        rm = make_map(token_budget=1024)
        rm._get_ranked_tags_map = lambda *a, **k: ""  # type: ignore[method-assign]
        assert rm.get_repo_map([], ["a.py"]) is None

    def test_chat_files_use_other_prefix(self, make_map, repo_root):
        rm = make_map(token_budget=4096, root_dir=repo_root)
        output = rm.get_repo_map(["pkg/core.py"], ["pkg/util.js"])

        assert output is not None
        assert output.startswith("\nother ")
        assert rm.last_map is not None

    def test_no_chat_files_use_plain_prefix(self, make_map, repo_root):
        rm = make_map(token_budget=4096, root_dir=repo_root)
        output = rm.get_repo_map([], ["pkg/util.js"])

        assert output is not None
        assert output.startswith("\n")
        assert not output.startswith("\nother ")

    def test_budget_expands_when_no_chat_files(self, make_map, monkeypatch):
        rm = make_map(token_budget=1000, map_multiplier_no_files=2.0, max_context_window=100_000)
        seen: dict[str, int] = {}

        def _capture(chat_files, other_files, max_tokens, *args, **kwargs):
            seen["max_tokens"] = max_tokens
            return "// listing"

        monkeypatch.setattr(rm, "_get_ranked_tags_map", _capture)
        rm.get_repo_map([], ["a.py"])

        assert seen["max_tokens"] == 2000  # min(1000 * 2.0, 100000 - 4096)

    def test_budget_expansion_clamped_by_context_window(self, make_map, monkeypatch):
        rm = make_map(token_budget=5000, map_multiplier_no_files=2.0, max_context_window=4600)
        seen: dict[str, int] = {}

        def _capture(chat_files, other_files, max_tokens, *args, **kwargs):
            seen["max_tokens"] = max_tokens
            return "// listing"

        monkeypatch.setattr(rm, "_get_ranked_tags_map", _capture)
        rm.get_repo_map([], ["a.py"])

        assert seen["max_tokens"] == 504  # min(10000, 4600 - 4096)

    def test_budget_unchanged_when_window_too_small(self, make_map, monkeypatch):
        rm = make_map(token_budget=5000, map_multiplier_no_files=2.0, max_context_window=4000)
        seen: dict[str, int] = {}

        def _capture(chat_files, other_files, max_tokens, *args, **kwargs):
            seen["max_tokens"] = max_tokens
            return "// listing"

        monkeypatch.setattr(rm, "_get_ranked_tags_map", _capture)
        rm.get_repo_map([], ["a.py"])

        assert seen["max_tokens"] == 5000  # 4000 - 4096 <= 0 → 保持原预算

    def test_chat_files_do_not_expand_budget(self, make_map, monkeypatch):
        rm = make_map(token_budget=1000, map_multiplier_no_files=2.0, max_context_window=100_000)
        seen: dict[str, int] = {}

        def _capture(chat_files, other_files, max_tokens, *args, **kwargs):
            seen["max_tokens"] = max_tokens
            return "// listing"

        monkeypatch.setattr(rm, "_get_ranked_tags_map", _capture)
        rm.get_repo_map(["a.py"], ["b.py"])

        assert seen["max_tokens"] == 1000


# ===== 8. 排名地图（scanner / 缓存 / 上限） =====


class _ScanResult:
    def __init__(self, structure=None, success: bool = True):
        self.structure = structure
        self.success = success


class _FakeScanner:
    def __init__(self, structures, missing_ok=(), missing_fail=()):
        self._structures = list(structures)
        self._missing_ok = set(missing_ok)
        self._missing_fail = set(missing_fail)
        self.scanned: list[str] = []

    def get_repo_map_structures(self):
        return list(self._structures)

    def scan_file(self, path):
        self.scanned.append(path)
        if path in self._missing_fail:
            return _ScanResult(success=False)
        return _ScanResult(
            CodeStructure(path=path, language="python", functions=[{"name": "scanned_fn", "signature": ""}])
        )


class TestRankedTagsMap:
    def test_ranks_cache_reused_and_force_refresh(self, make_map, repo_root, monkeypatch):
        rm = make_map(token_budget=4096, root_dir=repo_root)
        calls: list[int] = []
        original = rm._calculate_pagerank

        def _counting(structures):
            calls.append(len(structures))
            return original(structures)

        monkeypatch.setattr(rm, "_calculate_pagerank", _counting)
        files = ["pkg/core.py", "pkg/util.js"]

        rm._get_ranked_tags_map([], files, 4096, set(), set(), False)
        assert len(calls) == 1

        rm._get_ranked_tags_map([], files, 4096, set(), set(), False)
        assert len(calls) == 1  # 5 分钟内命中缓存

        rm._get_ranked_tags_map([], files, 4096, set(), set(), True)
        assert len(calls) == 2  # force_refresh 强制重算

    def test_ranks_cache_expires(self, make_map, repo_root, monkeypatch):
        rm = make_map(token_budget=4096, root_dir=repo_root)
        calls: list[int] = []
        original = rm._calculate_pagerank

        def _counting(structures):
            calls.append(len(structures))
            return original(structures)

        monkeypatch.setattr(rm, "_calculate_pagerank", _counting)
        files = ["pkg/core.py"]

        rm._get_ranked_tags_map([], files, 4096, set(), set(), False)
        assert len(calls) == 1

        later = rm._ranks_cache_time + 301
        monkeypatch.setattr(repo_map_module, "time", SimpleNamespace(time=lambda: later))

        rm._get_ranked_tags_map([], files, 4096, set(), set(), False)
        assert len(calls) == 2  # 超过 5 分钟重新计算

    def test_mentioned_file_gets_double_weight(self, make_map, repo_root, monkeypatch):
        rm = make_map(token_budget=4096, root_dir=repo_root)
        monkeypatch.setattr(
            rm, "_calculate_pagerank", lambda structures: {s.path: 1.0 for s in structures}
        )

        output = rm._get_ranked_tags_map(
            [], ["pkg/core.py", "pkg/util.js"], 4096, {"util.js"}, set(), True
        )

        # util.js: 1.0 * 0.9 * 2.0 = 1.8 > core.py: 1.0 * 1.0 * 1.0
        assert output.index("// pkg/util.js") < output.index("// pkg/core.py")

    def test_dep_graph_update_failure_is_tolerated(self, make_map, repo_root, caplog):
        caplog.set_level(logging.DEBUG)
        rm = make_map(token_budget=4096, root_dir=repo_root, dep_graph=_ExplodingDepGraph())

        output = rm._get_ranked_tags_map([], ["pkg/core.py"], 4096, set(), set(), True)

        assert "// pkg/core.py" in output
        assert "Failed to update dep graph" in caplog.text

    def test_scanner_supplies_structures_and_fills_missing(self, make_map):
        rm = make_map(token_budget=4096)
        provided = CodeStructure(
            path="a.py", language="python", functions=[{"name": "from_scanner", "signature": ""}]
        )
        scanner = _FakeScanner([provided], missing_ok={"b.py"}, missing_fail={"c.py"})

        output = rm._get_ranked_tags_map(
            [], ["a.py", "b.py", "c.py"], 4096, set(), set(), True, scanner=scanner
        )

        assert "from_scanner" in output
        assert "scanned_fn" in output
        assert "// c.py" not in output  # 扫描失败的文件不进地图
        assert set(scanner.scanned) == {"b.py", "c.py"}

    def test_scanner_structures_outside_file_list_are_dropped(self, make_map):
        rm = make_map(token_budget=100_000)
        kept = CodeStructure(
            path="a.py", language="python", functions=[{"name": "kept_fn", "signature": ""}]
        )
        ghost = CodeStructure(
            path="ghost.py", language="python", functions=[{"name": "ghost_fn", "signature": ""}]
        )
        scanner = _FakeScanner([kept, ghost])

        output = rm._get_ranked_tags_map([], ["a.py"], 100_000, set(), set(), True, scanner=scanner)

        assert "kept_fn" in output
        assert "ghost_fn" not in output

    def test_pagerank_input_capped_at_max_files(self, make_map, monkeypatch):
        """超过 MAX_PAGERANK_FILES(2000) 时按文件大小预选并截断，避免超大型仓库卡死。"""
        rm = make_map(token_budget=64, dep_graph=_NoopDepGraph())
        total = 2001
        files = [f"f{i}.py" for i in range(total)]
        structures = [
            CodeStructure(
                path=name,
                language="python",
                functions=[{"name": f"fn_{i}", "signature": ""}],
                imports=[files[(i + 1) % total]],
            )
            for i, name in enumerate(files)
        ]

        captured: dict[str, list[str]] = {}

        def _stub(structs):
            captured["paths"] = [s.path for s in structs]
            return {s.path: 1.0 for s in structs}

        monkeypatch.setattr(rm, "_calculate_pagerank", _stub)
        rm._get_ranked_tags_map(
            [], files, 64, set(), set(), True, scanner=_FakeScanner(structures)
        )

        assert len(captured["paths"]) == 2000
        assert files[-1] not in captured["paths"]  # 大小相同的稳定排序，截掉最后一个

    def test_chat_files_are_not_duplicated(self, make_map, repo_root, monkeypatch):
        rm = make_map(token_budget=4096, root_dir=repo_root)
        captured: list[list[str]] = []

        def _stub(structs):
            captured.append([s.path for s in structs])
            return {s.path: 1.0 for s in structs}

        monkeypatch.setattr(rm, "_calculate_pagerank", _stub)
        rm._get_ranked_tags_map(
            ["pkg/core.py"], ["pkg/core.py", "pkg/util.js"], 4096, set(), set(), True
        )

        assert captured[0].count("pkg/core.py") == 1


# ===== 9. 文件列举 =====


class TestFilesByPattern:
    def test_walk_fallback_with_default_patterns(self, make_map, repo_root):
        rm = make_map(root_dir=repo_root)
        found = {p.replace("\\", "/") for p in rm.get_files_by_pattern()}

        assert "pkg/core.py" in found
        assert "pkg/util.js" in found
        assert "README.md" not in found
        # 隐藏目录与 node_modules 被跳过
        assert not any("node_modules" in p for p in found)
        assert not any(p.startswith(".hidden") for p in found)
        assert not any("__pycache__" in p for p in found)

    def test_root_level_files_need_explicit_pattern(self, make_map, repo_root):
        """默认模式 `**/*.py` 匹配不到仓库根目录下的文件（已记录的行为差异）。"""
        rm = make_map(root_dir=repo_root)

        default_found = {p.replace("\\", "/") for p in rm.get_files_by_pattern()}
        assert "big.py" not in default_found

        explicit_found = {p.replace("\\", "/") for p in rm.get_files_by_pattern(patterns=["*.py"])}
        assert "big.py" in explicit_found

    def test_exclude_patterns_filter_results(self, make_map, repo_root):
        rm = make_map(root_dir=repo_root)
        found = {
            p.replace("\\", "/")
            for p in rm.get_files_by_pattern(patterns=["**/*.py"], exclude_patterns=["**/core.py"])
        }

        assert "pkg/__init__.py" in found
        assert "pkg/core.py" not in found

    def test_git_listing_used_when_repository_present(self, make_map, tmp_path, monkeypatch):
        repo = tmp_path / "git-repo"
        (repo / ".git").mkdir(parents=True)
        (repo / "src").mkdir()
        (repo / "src" / "mod.py").write_text("def f():\n    pass\n", encoding="utf-8")
        (repo / "untracked.py").write_text("def g():\n    pass\n", encoding="utf-8")

        def _fake_run(cmd, **kwargs):
            assert cmd[:2] == ["git", "ls-files"]
            return SimpleNamespace(stdout="src/mod.py\nnotes.txt\n", returncode=0)

        monkeypatch.setattr("subprocess.run", _fake_run)
        rm = make_map(root_dir=repo)

        found = {p.replace("\\", "/") for p in rm.get_files_by_pattern()}

        assert found == {"src/mod.py"}  # 只按 git 列出的清单过滤，未跟踪文件不出现

    def test_git_failure_falls_back_to_walk(self, make_map, tmp_path, monkeypatch):
        repo = tmp_path / "broken-git"
        (repo / ".git").mkdir(parents=True)
        (repo / "mod.py").write_text("def f():\n    pass\n", encoding="utf-8")

        def _boom(cmd, **kwargs):
            raise FileNotFoundError("git not installed")

        monkeypatch.setattr("subprocess.run", _boom)
        rm = make_map(root_dir=repo)

        found = {p.replace("\\", "/") for p in rm.get_files_by_pattern(patterns=["*.py"])}

        assert "mod.py" in found


# ===== 10. 全局单例 =====


class TestGlobalInstance:
    def test_global_singleton_is_cached(self, tmp_path, monkeypatch):
        monkeypatch.setattr(repo_map_module, "_repo_map", None)

        first = get_global_repo_map(1234, tmp_path)
        second = get_global_repo_map(9999, tmp_path)

        assert first is second
        assert first.token_budget == 1234  # 第二次调用的参数被忽略
        first.close()
