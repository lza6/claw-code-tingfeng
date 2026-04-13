import pytest
import numpy as np
import os
from src.rag.vector_store.faiss_store import FaissStore, HAS_FAISS
from src.rag.vector_store.base import VectorDocument

@pytest.mark.skipif(not HAS_FAISS, reason="faiss not installed")
@pytest.mark.asyncio
async def test_faiss_store_basic():
    dimension = 4
    store = FaissStore(dimension=dimension, metric="cosine")

    docs = [
        VectorDocument(id="doc1", vector=[1.0, 0.0, 0.0, 0.0], content="content1"),
        VectorDocument(id="doc2", vector=[0.0, 1.0, 0.0, 0.0], content="content2"),
        VectorDocument(id="doc3", vector=[0.0, 0.0, 1.0, 0.0], content="content3"),
    ]

    await store.add(docs)

    # 搜索完全匹配
    results = await store.search(query_vector=[1.0, 0.0, 0.0, 0.0], top_k=1)
    assert len(results) == 1
    assert results[0].id == "doc1"
    assert results[0].score > 0.99

    # 搜索相似
    results = await store.search(query_vector=[0.1, 0.9, 0.0, 0.0], top_k=1)
    assert len(results) == 1
    assert results[0].id == "doc2"

@pytest.mark.skipif(not HAS_FAISS, reason="faiss not installed")
@pytest.mark.asyncio
async def test_faiss_store_delete_clear():
    dimension = 4
    store = FaissStore(dimension=dimension)

    docs = [
        VectorDocument(id="doc1", vector=[1.0, 0.0, 0.0, 0.0], content="content1"),
    ]
    await store.add(docs)
    assert len(store.documents) == 1

    await store.delete(["doc1"])
    # 验证内存映射已删除
    assert "doc1" not in store.documents

    results = await store.search(query_vector=[1.0, 0.0, 0.0, 0.0], top_k=1)
    assert len(results) == 0

    await store.add(docs)
    await store.clear()
    assert len(store.documents) == 0
    assert store.index.ntotal == 0
