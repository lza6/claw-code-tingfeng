"""
RAG Chunk Enrichment — 整合自 Onyx 的内容增强模块

提供:
1. 内容增强 - 在索引时添加上下文
2. 内容清理 - 搜索后移除增强内容
3. 语义chunk处理
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# 常量 (From Onyx)
RETURN_SEPARATOR = "\n__ret__\n"


@dataclass
class ChunkEnrichmentConfig:
    """Chunk 增强配置"""
    # 标题前缀
    include_title_prefix: bool = True
    # 文档摘要 (开头)
    include_doc_summary: bool = True
    # Chunk 上下文 (结尾)
    include_chunk_context: bool = True
    # 元数据后缀
    include_metadata_suffix: bool = True

    # Blurb 大小
    blurb_size: int = 128


@dataclass
class EnrichedChunk:
    """增强后的 Chunk"""
    content: str
    title_prefix: str = ""
    doc_summary: str = ""
    chunk_context: str = ""
    metadata_suffix_keyword: str = ""
    metadata_suffix_semantic: str = ""

    source_document: str = ""
    chunk_id: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class ChunkEnricher:
    """Chunk 增强器 (借鉴 Onyx 的 chunk_content_enrichment)"""

    def __init__(self, config: ChunkEnrichmentConfig | None = None):
        self.config = config or ChunkEnrichmentConfig()

    def enrich_for_indexing(self, chunk: EnrichedChunk) -> str:
        """为索引生成增强内容 (搜索匹配用)"""
        parts = []

        if self.config.include_title_prefix and chunk.title_prefix:
            parts.append(chunk.title_prefix)

        if self.config.include_doc_summary and chunk.doc_summary:
            parts.append(chunk.doc_summary)

        parts.append(chunk.content)

        if self.config.include_chunk_context and chunk.chunk_context:
            parts.append(chunk.chunk_context)

        if self.config.include_metadata_suffix:
            parts.append(chunk.metadata_suffix_keyword)

        return RETURN_SEPARATOR.join(parts)

    def enrich_for_embedding(self, chunk: EnrichedChunk) -> str:
        """为嵌入生成增强内容 (语义匹配用)"""
        parts = []

        if self.config.include_title_prefix and chunk.title_prefix:
            parts.append(chunk.title_prefix)

        if self.config.include_doc_summary and chunk.doc_summary:
            parts.append(chunk.doc_summary)

        parts.append(chunk.content)

        if self.config.include_chunk_context and chunk.chunk_context:
            parts.append(chunk.chunk_context)

        if self.config.include_metadata_suffix:
            parts.append(chunk.metadata_suffix_semantic)

        RETURN_SEPARATOR.join(parts)

    def cleanup_enriched_content(
        self,
        content: str,
        title: str | None = None,
        doc_summary: str | None = None,
        chunk_context: str | None = None,
        metadata_suffix: str | None = None,
    ) -> str:
        """清理增强内容 (还原原始内容)

        Args:
            content: 增强后的内容
            title: 原始标题
            doc_summary: 文档摘要
            chunk_context: Chunk 上下文
            metadata_suffix: 元数据后缀

        Returns:
            清理后的原始内容
        """
        result = content

        # 1. 移除标题
        if title:
            if result.startswith(title):
                result = result[len(title):].lstrip()
            elif result.startswith(title[:self.config.blurb_size]):
                if RETURN_SEPARATOR in result:
                    result = result.split(RETURN_SEPARATOR, 1)[-1]
                else:
                    result = result[len(title[:self.config.blurb_size]):].lstrip()

        # 2. 移除元数据后缀
        if metadata_suffix:
            result = result.removesuffix(metadata_suffix).rstrip(RETURN_SEPARATOR)

        # 3. 移除文档摘要 (开头)
        if doc_summary and result.startswith(doc_summary):
            result = result[len(doc_summary):].lstrip()

        # 4. 移除 Chunk 上下文 (结尾)
        if chunk_context and result.endswith(chunk_context):
            result = result[:len(result) - len(chunk_context)].rstrip()

        return result


class HybridSearchMixin:
    """混合搜索混入 (借鉴 Onyx 的混合搜索模式)"""

    def __init__(self):
        self.vector_weight: float = 0.5
        self.keyword_weight: float = 0.5

    def set_search_weights(self, vector: float, keyword: float) -> None:
        """设置搜索权重"""
        total = vector + keyword
        if total <= 0:
            logger.warning("权重和必须大于0，使用默认值")
            return

        self.vector_weight = vector / total
        self.keyword_weight = keyword / total

    def hybrid_score(self, vector_score: float, keyword_score: float) -> float:
        """计算混合分数"""
        return (
            self.vector_weight * vector_score +
            self.keyword_weight * keyword_score
        )


# 全局增强器
_enricher: ChunkEnricher | None = None


def get_chunk_enricher(config: ChunkEnrichmentConfig | None = None) -> ChunkEnricher:
    """获取 Chunk 增强器"""
    global _enricher
    if _enricher is None:
        _enricher = ChunkEnricher(config)
    return _enricher
