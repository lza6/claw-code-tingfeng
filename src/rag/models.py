"""RAG 数据模型 - Document, Chunk, SearchResult"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Document:
    """文档定义"""
    id: str
    content: str
    source: str  # 文件路径或 URL
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    """文档分块"""
    id: str
    document_id: str
    content: str
    start_pos: int  # 在原文档中的起始位置
    end_pos: int  # 在原文档中的结束位置
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResult:
    """检索结果"""
    chunk: Chunk
    score: float  # 相关性分数
    document: Document | None = None
