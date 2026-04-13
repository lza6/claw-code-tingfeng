from __future__ import annotations

import logging
from typing import Any

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
    HAS_QDRANT = True
except ImportError:
    HAS_QDRANT = False

from .base import VectorDocument, VectorStore

logger = logging.getLogger(__name__)


class QdrantStore(VectorStore):
    """Qdrant 向量存储提供者"""

    def __init__(
        self,
        url: str = "http://localhost:6333",
        api_key: str | None = None,
        collection_name: str = "clawd_rag",
        vector_size: int = 1536,  # 默认 OpenAI Embedding 大小
    ) -> None:
        if not HAS_QDRANT:
            raise ImportError("请安装 qdrant-client: pip install qdrant-client")

        self.client = QdrantClient(url=url, api_key=api_key)
        self.collection_name = collection_name
        self.vector_size = vector_size
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """确保集合存在"""
        try:
            collections = self.client.get_collections().collections
            exists = any(c.name == self.collection_name for c in collections)
            if not exists:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=qmodels.VectorParams(
                        size=self.vector_size,
                        distance=qmodels.Distance.COSINE
                    )
                )
                logger.info(f"已创建 Qdrant 集合: {self.collection_name}")
        except Exception as e:
            logger.error(f"确保 Qdrant 集合失败: {e}")

    async def add(self, documents: list[VectorDocument]) -> bool:
        """批量添加文档"""
        try:
            points = [
                qmodels.PointStruct(
                    id=doc.id,
                    vector=doc.vector,
                    payload={"content": doc.content, **doc.metadata}
                )
                for doc in documents if doc.vector
            ]
            if not points:
                return True

            self.client.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=True
            )
            return True
        except Exception as e:
            logger.error(f"Qdrant 添加文档失败: {e}")
            return False

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorDocument]:
        """搜索相似文档"""
        try:
            # 转换过滤条件 (此处仅为示例，实际需要更复杂的转换)
            query_filter = None
            if filters:
                must = [
                    qmodels.FieldCondition(
                        key=k,
                        match=qmodels.MatchValue(value=v)
                    )
                    for k, v in filters.items()
                ]
                query_filter = qmodels.Filter(must=must)

            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=top_k,
                query_filter=query_filter,
                with_payload=True,
                with_vectors=False
            )

            return [
                VectorDocument(
                    id=str(res.id),
                    content=res.payload.get("content"),
                    metadata={k: v for k, v in res.payload.items() if k != "content"},
                    score=res.score
                )
                for res in results
            ]
        except Exception as e:
            logger.error(f"Qdrant 搜索失败: {e}")
            return []

    async def delete(self, ids: list[str]) -> bool:
        """删除文档"""
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=qmodels.PointIdsList(points=ids)
            )
            return True
        except Exception as e:
            logger.error(f"Qdrant 删除失败: {e}")
            return False

    async def clear(self) -> bool:
        """清空集合"""
        try:
            self.client.delete_collection(self.collection_name)
            self._ensure_collection()
            return True
        except Exception as e:
            logger.error(f"Qdrant 清空失败: {e}")
            return False

    def close(self) -> None:
        """释放资源"""
        self.client.close()
