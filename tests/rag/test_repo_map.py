"""RepoMap 单元测试 — 验证代码地图生成与层次化渲染"""
import pytest
from pathlib import Path
from src.rag.repo_map import RepoMap, CodeStructure

def test_code_structure_to_map_entry_depth_1():
    """测试深度 1 的极简渲染 (仅符号名)"""
    cs = CodeStructure(
        path="src/test.py",
        language="python",
        classes=["MyClass"],
        functions=[{"name": "my_func", "signature": "x, y"}],
        docstring="Test module"
    )

    entry = cs.to_map_entry(depth=1)
    assert "# src/test.py (python)" in entry
    assert "symbols: MyClass, my_func" in entry

def test_code_structure_to_map_entry_depth_2():
    """测试深度 2 的标准渲染 (类/方法定义)"""
    cs = CodeStructure(
        path="src/test.py",
        language="python",
        classes=["MyClass"],
        functions=[{"name": "my_func", "signature": "x, y"}],
        docstring="Test module"
    )

    entry = cs.to_map_entry(depth=2)
    assert "class MyClass:" in entry
    assert "def my_func(x, y)" in entry

def test_code_structure_to_map_entry_depth_3():
    """测试深度 3 的完整渲染 (带 Docstring)"""
    cs = CodeStructure(
        path="src/test.py",
        language="python",
        classes=["MyClass"],
        functions=[{"name": "my_func", "signature": "x, y", "docstring": "Do something"}],
    )

    entry = cs.to_map_entry(depth=3)
    assert "def my_func(x, y):  # Do something" in entry

def test_repomap_initialization():
    """测试 RepoMap 初始化与配置"""
    rm = RepoMap(token_budget=1024)
    assert rm.token_budget == 1024

def test_repomap_pagerank_sorting(tmp_path):
    """验证 PageRank 权重排序是否正确"""
    # 模拟两个文件结构
    # a.py 被多次引用 (重要)
    # b.py 孤立 (不重要)
    rm = RepoMap(root_dir=tmp_path)

    structures = [
        CodeStructure(path="a.py", language="python", functions=[{"name": "core_api"}]),
        CodeStructure(path="b.py", language="python", functions=[{"name": "unused_api"}]),
        CodeStructure(path="c.py", language="python", imports=["a.py"], functions=[{"name": "caller"}]),
    ]

    ranks = rm._calculate_pagerank(structures)

    # a.py 应该比 b.py 权重更高，因为它被 c.py 引用了
    assert ranks["a.py"] > ranks["b.py"]
