from __future__ import annotations

import logging
from typing import Any

try:
    import faiss
    import numpy as np
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False

from .base import VectorDocument, VectorStore

logger = logging.getLogger(__name__)


class FaissStore(VectorStore):
    """FAISS 向量存储提供者 (高性能本地索引)"""

    def __init__(
        self,
        dimension: int = 1536,
        index_type: str = "Flat",
        metric: str = "cosine",
    ) -> None:
        if not HAS_FAISS:
            raise ImportError("请安装 faiss-cpu 或 faiss-gpu: pip install faiss-cpu")

        self.dimension = dimension
        self.metric = metric

        # 初始化索引
        if metric == "cosine":
            # FAISS 使用内积 (Inner Product) 来模拟余弦相似度 (需向量归一化)
            self.index = faiss.IndexFlatIP(dimension)
        else:
            self.index = faiss.IndexFlatL2(dimension)

        self.doc_map: dict[int, str] = {}  # 映射 faiss_id -> doc_id
        self.documents: dict[str, VectorDocument] = {}  # 存储完整文档信息
        self._next_id = 0

    async def add(self, documents: list[VectorDocument]) -> bool:
        """批量添加文档"""
        if not documents:
            return True

        vectors = []
        valid_docs = []
        for doc in documents:
            if doc.vector:
                if len(doc.vector) != self.dimension:
                    logger.warning(f"向量维度不匹配: 期望 {self.dimension}, 实际 {len(doc.vector)}")
                    continue
                vectors.append(doc.vector)
                valid_docs.append(doc)

        if not vectors:
            return True

        np_vectors = np.array(vectors).astype('float32')
        if self.metric == "cosine":
            # 归一化以支持余弦相似度
            faiss.normalize_L2(np_vectors)

        self.index.add(np_vectors)

        for i, doc in enumerate(valid_docs):
            faiss_id = self._next_id + i
            self.doc_map[faiss_id] = doc.id
            self.documents[doc.id] = doc

        self._next_id += len(valid_docs)
        return True

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorDocument]:
        """搜索相似文档"""
        if self.index.ntotal == 0:
            return []

        np_query = np.array([query_vector]).astype('float32')
        if self.metric == "cosine":
            faiss.normalize_L2(np_query)

        distances, indices = self.index.search(np_query, top_k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1 or idx not in self.doc_map:
                continue

            doc_id = self.doc_map[idx]
            original_doc = self.documents.get(doc_id)
            if not original_doc:
                continue

            # 简单的内存过滤 (FAISS 原生过滤较复杂)
            if filters:
                match = True
                for k, v in filters.items():
                    if original_doc.metadata.get(k) != v:
                        match = False
                        break
                if not match:
                    continue

            results.append(VectorDocument(
                id=doc_id,
                content=original_doc.content,
                metadata=original_doc.metadata,
                score=float(dist)
            ))

        return results

    async def delete(self, ids: list[str]) -> bool:
        """删除文档 (FAISS 默认索引不支持高效删除，此处仅标记失效)"""
        # 注意：IndexFlat 不支持直接 remove
        # 简单实现：从元数据映射中移除
        for doc_id in ids:
            if doc_id in self.documents:
                del self.documents[doc_id]
            # 移除所有映射到此 doc_id 的 faiss_id
            keys_to_del = [k for k, v in self.doc_map.items() if v == doc_id]
            for k in keys_to_del:
                del self.doc_map[k]
        return True

    async def clear(self) -> bool:
        """清空索引"""
        if self.metric == "cosine":
            self.index = faiss.IndexFlatIP(self.dimension)
        else:
            self.index = faiss.IndexFlatL2(self.dimension)
        self.doc_map.clear()
        self.documents.clear()
        self._next_id = 0
        return True

    def close(self) -> None:
        """释放资源"""
        pass
