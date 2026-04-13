from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class VectorDocument:
    """向量存储文档"""
    id: str
    vector: list[float] | None = None
    content: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


@runtime_checkable
class VectorStore(Protocol):
    """向量存储提供者协议"""

    async def add(self, documents: list[VectorDocument]) -> bool:
        """添加文档"""
        ...

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorDocument]:
        """搜索文档"""
        ...

    async def delete(self, ids: list[str]) -> bool:
        """删除文档"""
        ...

    async def clear(self) -> bool:
        """清空数据"""
        ...

    def close(self) -> None:
        """释放资源"""
        ...
