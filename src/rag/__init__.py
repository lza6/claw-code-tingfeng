"""RAG (检索增强生成) 模块 - 轻量级文档检索与上下文增强

重构说明 (v0.14.0):
- 数据模型已移至 models.py
- TextIndexer 已移至 text_indexer.py
- LazyIndexer 已移至 lazy_indexer.py
- 此文件保留向后兼容的导出
"""
from __future__ import annotations

from .lazy_indexer import LazyIndexer
from .models import Chunk, Document, SearchResult
from .text_indexer import TextIndexer

__all__ = [
    'Chunk',
    'Document',
    'LazyIndexer',
    'SearchResult',
    'TextIndexer',
]
