import pytest
import asyncio
import os
from pathlib import Path
from src.memory.enterprise_ltm import EnterpriseLTM, ImplementationPattern, PatternType
from src.rag.vector_store.local import LocalVectorStore
from src.core.project_context import ProjectContext

@pytest.fixture
def temp_project(tmp_path):
    ctx = ProjectContext(workdir=tmp_path)
    ctx.ensure_dirs()
    return ctx

@pytest.mark.asyncio
async def test_local_vector_store_basic(tmp_path):
    storage_path = tmp_path / "test_vectors.json"
    store = LocalVectorStore(storage_path=storage_path)

    from src.rag.vector_store.base import VectorDocument

    docs = [
        VectorDocument(id="1", vector=[0.1, 0.2, 0.3], content="test1"),
        VectorDocument(id="2", vector=[0.9, 0.8, 0.7], content="test2"),
    ]

    await store.add(docs)

    # 搜索相似
    results = await store.search(query_vector=[0.1, 0.2, 0.31], top_k=1)
    assert len(results) == 1
    assert results[0].id == "1"

    results = await store.search(query_vector=[0.89, 0.81, 0.72], top_k=1)
    assert len(results) == 1
    assert results[0].id == "2"

@pytest.mark.asyncio
async def test_enterprise_ltm_vector_search(temp_project, monkeypatch):
    # Mock litellm embedding to avoid API calls
    class MockEmbeddingResponse:
        def __init__(self, vector):
            self.data = [{'embedding': vector}]

    def mock_embedding(model, input, **kwargs):
        # 根据输入内容返回伪造的向量
        if "python" in input.lower():
            return MockEmbeddingResponse([1.0, 0.0, 0.0])
        elif "rust" in input.lower():
            return MockEmbeddingResponse([0.0, 1.0, 0.0])
        else:
            return MockEmbeddingResponse([0.0, 0.0, 1.0])

    from src.llm.litellm_singleton import LiteLLMSingleton
    monkeypatch.setattr(LiteLLMSingleton, "embedding", mock_embedding)

    ltm = EnterpriseLTM(project_ctx=temp_project)

    # 存入模式
    pattern1 = ImplementationPattern(
        pattern_id="p1",
        task_type="python",
        description="Python implementation of a decorator",
        solution_code="def dec(f): ...",
        success_metrics={}
    )
    pattern2 = ImplementationPattern(
        pattern_id="p2",
        task_type="rust",
        description="Rust implementation of a trait",
        solution_code="trait MyTrait { ... }",
        success_metrics={}
    )

    await ltm.store_pattern(pattern1)
    await ltm.store_pattern(pattern2)

    # 搜索
    results = await ltm.find_similar_patterns("How to write a Python decorator")
    assert len(results) > 0
    assert results[0].pattern_id == "p1"

    results = await ltm.find_similar_patterns("Rust trait example")
    assert len(results) > 0
    assert results[0].pattern_id == "p2"

@pytest.mark.asyncio
async def test_enterprise_ltm_fallback(temp_project, monkeypatch):
    # 测试向量搜索失败时的回退
    def mock_embedding_error(model, input, **kwargs):
        raise Exception("Embedding API failed")

    from src.llm.litellm_singleton import LiteLLMSingleton
    monkeypatch.setattr(LiteLLMSingleton, "embedding", mock_embedding_error)

    ltm = EnterpriseLTM(project_ctx=temp_project)

    # 存入模式 (手动存入 SQLite 以模拟已有数据或存储失败但 SQLite 成功的情况)
    pattern = ImplementationPattern(
        pattern_id="fallback-test",
        task_type="test",
        description="Search me via keywords",
        solution_code="print('fallback')",
        success_metrics={}
    )
    # 由于 store_pattern 也会调用 embedding，我们需要在 store_pattern 时 mock
    # 或者直接调用 _store_pattern_sync
    ltm._store_pattern_sync(pattern)

    # 检索 (应该由于 embedding 报错而回退到关键词搜索)
    results = await ltm.find_similar_patterns("keywords")
    assert len(results) > 0
    assert results[0].pattern_id == "fallback-test"
