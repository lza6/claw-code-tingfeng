from __future__ import annotations

import asyncio
import json
import logging
import math
from pathlib import Path
from typing import Any

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

from .base import VectorDocument, VectorStore

logger = logging.getLogger(__name__)


class LocalVectorStore(VectorStore):
    """轻量级本地向量存储提供者 (基于 numpy 或 pure python)"""

    def __init__(
        self,
        storage_path: Path | str,
        dimension: int = 1536,
    ) -> None:
        self.storage_path = Path(storage_path)
        self.dimension = dimension
        self.documents: dict[str, VectorDocument] = {}
        self._load()

    def _load(self) -> None:
        """从本地加载数据"""
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, encoding='utf-8') as f:
                data = json.load(f)
                for doc_id, doc_data in data.items():
                    self.documents[doc_id] = VectorDocument(
                        id=doc_id,
                        vector=doc_data.get('vector'),
                        content=doc_data.get('content'),
                        metadata=doc_data.get('metadata', {}),
                    )
            logger.info(f"已加载 {len(self.documents)} 条本地向量记录")
        except Exception as e:
            logger.error(f"加载本地向量存储失败: {e}")

    def _save(self) -> None:
        """持久化数据到本地"""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                doc_id: {
                    'vector': doc.vector,
                    'content': doc.content,
                    'metadata': doc.metadata,
                }
                for doc_id, doc in self.documents.items()
            }
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"持久化本地向量存储失败: {e}")

    async def add(self, documents: list[VectorDocument]) -> bool:
        """添加文档"""
        for doc in documents:
            if doc.vector:
                self.documents[doc.id] = doc
        await asyncio.to_thread(self._save)
        return True

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorDocument]:
        """搜索相似文档 (余弦相似度)"""
        if not self.documents:
            return []

        scored_docs = []
        for doc in self.documents.values():
            if not doc.vector:
                continue

            # 过滤
            if filters:
                match = True
                for k, v in filters.items():
                    if doc.metadata.get(k) != v:
                        match = False
                        break
                if not match:
                    continue

            score = self._cosine_similarity(query_vector, doc.vector)
            scored_docs.append((score, doc))

        # 按分数排序
        scored_docs.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, doc in scored_docs[:top_k]:
            results.append(VectorDocument(
                id=doc.id,
                content=doc.content,
                metadata=doc.metadata,
                score=score
            ))
        return results

    def _cosine_similarity(self, v1: list[float], v2: list[float]) -> float:
        """计算余弦相似度"""
        if HAS_NUMPY:
            arr1 = np.array(v1)
            arr2 = np.array(v2)
            norm1 = np.linalg.norm(arr1)
            norm2 = np.linalg.norm(arr2)
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return float(np.dot(arr1, arr2) / (norm1 * norm2))
        else:
            # 纯 Python 实现
            dot_product = sum(a * b for a, b in zip(v1, v2))
            magnitude1 = math.sqrt(sum(a * a for a in v1))
            magnitude2 = math.sqrt(sum(b * b for b in v2))
            if magnitude1 == 0 or magnitude2 == 0:
                return 0.0
            return dot_product / (magnitude1 * magnitude2)

    async def delete(self, ids: list[str]) -> bool:
        """删除文档"""
        for doc_id in ids:
            if doc_id in self.documents:
                del self.documents[doc_id]
        await asyncio.to_thread(self._save)
        return True

    async def clear(self) -> bool:
        """清空数据"""
        self.documents.clear()
        await asyncio.to_thread(self._save)
        return True

    def close(self) -> None:
        """释放资源"""
        pass
