"""src/brain/world_model.py 的索引感知与预取逻辑测试"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.brain.world_model import RepositoryWorldModel


@pytest.mark.asyncio
async def test_world_model_initialize_parallel(tmp_path):
    """测试世界模型并行初始化流程"""
    # 模拟 CodeGraph 和 TextIndexer
    mock_code_graph = MagicMock()
    mock_code_graph.nodes = {"f1.py": {}, "f2.py": {}}

    mock_indexer = AsyncMock()
    mock_indexer.build_index_async.return_value = 2
    mock_indexer.get_stats.return_value = {"index_terms": 100, "total_documents": 2}

    # 模拟 EventBus
    mock_event_bus = MagicMock()

    with patch("src.rag.code_graph.CodeGraph", return_value=mock_code_graph), \
         patch("src.core.events.get_event_bus", return_value=mock_event_bus), \
         patch("src.brain.world_model.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:

        wm = RepositoryWorldModel(root_dir=tmp_path, text_indexer=mock_indexer)
        wm.dependency_graph = mock_code_graph

        await wm.initialize()

        assert wm._is_initialized is True
        # 验证并行构建被调用
        mock_to_thread.assert_called_once()
        # 验证索引被调用
        mock_indexer.build_index_async.assert_called_once()
        # 验证事件发布
        mock_event_bus.publish.assert_called_once()


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
    # 由于 file1.py 和 file2.py 已在 _prefetch_cache 中，这次应该不返回新结果
    assert len(results2) == 0

    # 验证缓存生效
    assert "file1.py" in wm._prefetch_cache
    assert "file2.py" in wm._prefetch_cache


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
