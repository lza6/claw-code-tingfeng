"""src/brain/world_model.py 的索引感知与预取逻辑测试"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.brain.world_model import RepositoryWorldModel


@pytest.mark.asyncio
async def test_world_model_initialize_parallel(tmp_path):
    """测试世界模型并行初始化流程。

    重写说明 (2026-10-17):
        原测试断言 `text_indexer.build_index_async` 被调用一次，但当前实现
        走的是**基于语义指纹的增量索引** —— 只对"指纹变化"的文件逐个调用
        `add_file_async`（见 world_model.initialize 第 3 步）。这是刻意的设计
        改进（增量而非全量），不是缺陷。原测试既断言了已废弃的 API，
        fixture 又没建任何文件，因此即使改对方法名也不会被调用。

        本测试改为验证当前真实契约，并**实际创建文件**使增量路径真的执行。
    """
    # 建两个真实文件，否则 changed_files 为空，增量索引路径根本不会跑
    (tmp_path / "f1.py").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "f2.py").write_text("b = 2\n", encoding="utf-8")

    mock_code_graph = MagicMock()
    mock_code_graph.nodes = {"f1.py": {}, "f2.py": {}}

    # 只有异步方法用 AsyncMock；get_stats 是同步方法，
    # 用 AsyncMock 会让它返回协程，导致下游 `.get(...)` 抛 AttributeError。
    mock_indexer = MagicMock()
    mock_indexer.add_file_async = AsyncMock()
    mock_indexer.get_stats.return_value = {"index_terms": 100, "total_documents": 2}

    mock_event_bus = MagicMock()

    with patch("src.rag.code_graph.CodeGraph", return_value=mock_code_graph), \
         patch("src.core.events.get_event_bus", return_value=mock_event_bus), \
         patch("src.brain.world_model.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:

        wm = RepositoryWorldModel(root_dir=tmp_path, text_indexer=mock_indexer)
        wm.dependency_graph = mock_code_graph

        await wm.initialize()

        assert wm._is_initialized is True
        # 并行构建经 to_thread 执行
        mock_to_thread.assert_called_once()
        # 增量索引：每个变更文件各调一次 add_file_async（不是全量 build_index_async）
        assert mock_indexer.add_file_async.await_count == 2, (
            f"期望 2 个文件触发增量索引，实际 {mock_indexer.add_file_async.await_count}"
        )
        assert not mock_indexer.build_index_async.called, (
            "增量路径不应退化为全量重建"
        )
        # 事件发布
        mock_event_bus.publish.assert_called_once()


@pytest.mark.asyncio
async def test_world_model_initialize_skips_unchanged(tmp_path):
    """第二次 initialize 时指纹未变，应跳过重索引（增量设计的核心收益）"""
    (tmp_path / "g.py").write_text("c = 3\n", encoding="utf-8")

    mock_code_graph = MagicMock()
    mock_code_graph.nodes = {"g.py": {}}
    mock_indexer = MagicMock()
    mock_indexer.add_file_async = AsyncMock()
    mock_indexer.get_stats.return_value = {"index_terms": 1, "total_documents": 1}

    with patch("src.rag.code_graph.CodeGraph", return_value=mock_code_graph), \
         patch("src.core.events.get_event_bus", return_value=MagicMock()), \
         patch("src.brain.world_model.asyncio.to_thread", new_callable=AsyncMock):

        wm = RepositoryWorldModel(root_dir=tmp_path, text_indexer=mock_indexer)
        wm.dependency_graph = mock_code_graph

        await wm.initialize()
        first_round = mock_indexer.add_file_async.await_count
        assert first_round == 1

        # 第二次：构造新的 world model（清空内存态），指纹文件已落盘
        wm2 = RepositoryWorldModel(root_dir=tmp_path, text_indexer=mock_indexer)
        wm2.dependency_graph = mock_code_graph
        await wm2.initialize()

        assert mock_indexer.add_file_async.await_count == first_round, (
            "指纹未变时不应重复索引"
        )


def test_predict_relevant_files_logic(tmp_path):
    """测试基于依赖和语义的相关文件预测逻辑"""
    wm = RepositoryWorldModel(root_dir=tmp_path)

    # 模拟依赖图影响分析
    mock_graph = MagicMock()
    mock_graph.impact_analysis.return_value = {
        "direct_upstream": ["upstream.py"],
        "direct_downstream": ["downstream.py"]
    }
    wm.dependency_graph = mock_graph

    # 模拟文本索引搜索
    mock_search_result = MagicMock()
    mock_search_result.document.source = "similar.py"

    mock_indexer = MagicMock()
    mock_indexer.search.return_value = [mock_search_result]
    wm.text_indexer = mock_indexer

    # 执行预测
    predictions = wm.predict_relevant_files("current.py")

    assert "upstream.py" in predictions
    assert "downstream.py" in predictions
    assert "similar.py" in predictions
    assert len(predictions) == 3


@pytest.mark.asyncio
async def test_prefetch_context_caching(tmp_path):
    """测试预取上下文的缓存机制"""
    wm = RepositoryWorldModel(root_dir=tmp_path)

    # 模拟预测结果
    wm.predict_relevant_files = MagicMock(return_value=["file1.py", "file2.py"])
    # 模拟获取上下文
    wm.get_context_for_file = MagicMock(return_value={"data": "..."})

    # 第一次预取
    results1 = await wm.prefetch_context("current.py")
    assert len(results1) == 2
    assert "file1.py" in results1
    assert "file2.py" in results1

    # 第二次预取（相同文件预测结果）
    results2 = await wm.prefetch_context("current.py")
    # 由于 file1.py 和 file2.py 已在 _prefetch_history 中，这次应该不返回新结果
    assert len(results2) == 0

    # 验证缓存生效
    # 注: 实现里的属性名是 _prefetch_history（记录已预取过的路径），
    # 早期测试写的是 _prefetch_cache —— 语义相同，名字已变更。
    assert "file1.py" in wm._prefetch_history
    assert "file2.py" in wm._prefetch_history


def test_detect_patterns_complex(tmp_path):
    """测试复杂代码结构的设计模式检测"""
    wm = RepositoryWorldModel(root_dir=tmp_path)

    # Builder 模式代码
    builder_code = """
class MyBuilder:
    def set_name(self, name):
        self.name = name
        return self

    def set_age(self, age):
        self.age = age
        return self

    def build(self):
        return object()
"""
    (tmp_path / "builder.py").write_text(builder_code)

    # Strategy 模式代码
    strategy_code = """
class SortStrategy:
    def execute(self, data): pass
    def run(self, data): pass
    def process(self, data): pass
"""
    (tmp_path / "strategy.py").write_text(strategy_code)

    patterns_builder = wm._detect_patterns("builder.py")
    assert "Builder" in patterns_builder

    patterns_strategy = wm._detect_patterns("strategy.py")
    assert "Strategy" in patterns_strategy
