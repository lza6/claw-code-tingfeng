"""索引器搜索模块 - BM25 评分、搜索、上下文获取

从 text_indexer.py 拆分，负责：
- 搜索 (search)
- BM25 评分算法
- 上下文获取 (get_context)
- Cross-Encoder 重排序
"""
from __future__ import annotations

import math
from collections import OrderedDict
from typing import Any

from .models import Chunk, Document, SearchResult
from .word_index import WordIndex

# 类型别名（避免循环导入错误）
List: type[Any] = list


class BM25Scorer:
    """BM25 评分器

    BM25 (Best Matching 25) 是一种信息检索评分算法，
    考虑了词频 (TF) 和逆文档频率 (IDF)，以及文档长度归一化。
    """

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.k1 = k1
        self.b = b

    def score(
        self,
        query_terms: list[str],
        chunks: dict[str, Chunk],
        word_index: WordIndex,
    ) -> dict[str, float]:
        """BM25 评分

        参数:
            query_terms: 查询词列表
            chunks: chunk 字典
            word_index: 词索引

        返回:
            chunk_id -> score 的字典
        """
        N = len(chunks)
        if N == 0:
            return {}

        # 缓存 chunk lengths
        chunk_lengths = {
            chunk_id: len(chunk.content)
            for chunk_id, chunk in chunks.items()
        }

        avg_length = sum(chunk_lengths.values()) / N if N > 0 else 1
        scores: dict[str, float] = {}

        for term in query_terms:
            matching_paths = word_index.search_deduped(term)
            if not matching_paths:
                continue

            df = len(matching_paths)
            idf = math.log((N - df + 0.5) / (df + 0.5) + 1)

            for path in matching_paths:
                for chunk_id, chunk in chunks.items():
                    if chunk.metadata.get('source') == path:
                        tf = chunk.content.lower().count(term)
                        if tf == 0:
                            continue
                        doc_length = chunk_lengths.get(chunk_id, 1)

                        numerator = tf * (self.k1 + 1)
                        denominator = tf + self.k1 * (1 - self.b + self.b * doc_length / avg_length)
                        tf_score = numerator / denominator if denominator > 0 else 0

                        scores[chunk_id] = scores.get(chunk_id, 0) + idf * tf_score

        return scores


class SimpleScorer:
    """简单计数评分器（回退方案）"""

    def score(
        self,
        query_terms: list[str],
        chunks: dict[str, Chunk],
        word_index: WordIndex,
    ) -> dict[str, float]:
        """简单评分"""
        scores: dict[str, float] = {}
        for term in query_terms:
            matching_paths = word_index.search_deduped(term)
            for path in matching_paths:
                for chunk in chunks.values():
                    if chunk.metadata.get('source') == path:
                        scores[chunk.id] = scores.get(chunk.id, 0) + 1.0
        return scores


class IndexerSearch:
    """索引器搜索功能混合类

    提供搜索、评分、上下文获取功能。
    通过组合而非继承实现，便于单独测试。
    """

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        max_file_size: int = 1024 * 1024,
        max_documents: int = 1000,
        enable_reranker: bool = False,
        reranker_top_k: int = 10,
        reranker_model: str | None = None,
        search_cache_size: int = 256,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_file_size = max_file_size
        self.max_documents = max_documents
        self._documents: dict[str, Document] = {}
        self._chunks: dict[str, Chunk] = {}
        self._word_index = WordIndex()
        self._chunk_lengths: dict[str, int] = {}

        # 搜索缓存
        self._search_cache_size = search_cache_size
        self._search_cache: OrderedDict[str, list[SearchResult]] = OrderedDict()

        # Cross-Encoder 重排序配置
        self.enable_reranker = enable_reranker
        self.reranker_top_k = reranker_top_k
        self._reranker_model_name = reranker_model
        self._reranker: Any = None

        # 评分器
        self._bm25_scorer = BM25Scorer()
        self._simple_scorer = SimpleScorer()

    def invalidate_chunk_lengths_cache(self) -> None:
        """标记 chunk lengths 缓存无效"""
        self._chunk_lengths = {}
        self._clear_search_cache()

    def _clear_search_cache(self) -> None:
        """清除搜索缓存"""
        self._search_cache.clear()

    def search(
        self,
        query: str,
        top_k: int = 5,
        use_bm25: bool = True,
    ) -> list[SearchResult]:
        """搜索相关文档块

        参数:
            query: 搜索查询
            top_k: 返回结果数量
            use_bm25: 是否使用 BM25 评分（默认 True）

        返回:
            按相关性排序的搜索结果列表
        """
        # 检查缓存
        cache_key = f"{query}:{top_k}:{use_bm25}"
        if cache_key in self._search_cache:
            self._search_cache.move_to_end(cache_key)
            return self._search_cache[cache_key]

        from .indexer_utils import tokenize

        query_terms = tokenize(query)
        if not query_terms:
            return []

        if use_bm25:
            scores = self._bm25_scorer.score(query_terms, self._chunks, self._word_index)
        else:
            scores = self._simple_scorer.score(query_terms, self._chunks, self._word_index)

        sorted_chunks = sorted(scores.items(), key=lambda x: -x[1])
        results = []
        for chunk_id, score in sorted_chunks[:top_k]:
            chunk = self._chunks.get(chunk_id)
            if chunk:
                doc = self._documents.get(chunk.document_id)
                results.append(SearchResult(
                    chunk=chunk,
                    score=round(score, 4),
                    document=doc,
                ))

        # 缓存结果
        if len(self._search_cache) >= self._search_cache_size:
            self._search_cache.popitem(last=False)
        self._search_cache[cache_key] = results

        return results

    def get_context(
        self,
        query: str,
        top_k: int = 3,
        max_context_length: int = 4000,
    ) -> str:
        """获取增强上下文

        检索相关文档块并格式化为 LLM 可用的上下文。

        参数:
            query: 搜索查询
            top_k: 最终返回的检索结果数量
            max_context_length: 最大上下文长度（字符数）

        返回:
            格式化的上下文字符串
        """
        # 初步检索
        initial_k = self.reranker_top_k if self.enable_reranker else top_k
        results = self.search(query, top_k=initial_k)
        if not results:
            return ''

        # Cross-Encoder 重排序
        if self.enable_reranker:
            results = self._rerank_results(query, results, top_k)

        # 格式化上下���
        context_parts = []
        total_length = 0
        for result in results:
            source = getattr(result.chunk, 'source', None) or (
                result.document.source if result.document else '未知'
            )
            if self.enable_reranker:
                chunk_text = f'[来源: {source}] (相关度: {result.score:.3f})\n{result.chunk.content}'
            else:
                chunk_text = f'[来源: {source}]\n{result.chunk.content}'
            if total_length + len(chunk_text) > max_context_length:
                break
            context_parts.append(chunk_text)
            total_length += len(chunk_text)

        return '\n\n---\n\n'.join(context_parts)

    def _get_reranker(self):
        """获取 Cross-Encoder 重排序器（懒加载）"""
        if self._reranker is None and self.enable_reranker:
            try:
                from .cross_encoder_reranker import CrossEncoderReranker

                kwargs = {}
                if self._reranker_model_name:
                    kwargs['model_name'] = self._reranker_model_name
                self._reranker = CrossEncoderReranker(**kwargs)
                if not self._reranker.is_available:
                    self._reranker = None
                    self.enable_reranker = False
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(
                    f'Cross-Encoder 重排序器加载失败: {e}，已降级到关键词重排序'
                )
                self._reranker = None
                self.enable_reranker = False
        return self._reranker

    def _rerank_results(
        self,
        query: str,
        results: list[SearchResult],
        top_k: int,
    ) -> list[SearchResult]:
        """使用 Cross-Encoder 对搜索结果进行二次排序"""
        reranker = self._get_reranker()
        if reranker is None or not reranker.is_available:
            return results[:top_k]

        documents = [r.chunk.content for r in results]
        if not documents:
            return []

        rerank_results = reranker.rerank(query, documents, top_k=top_k)

        reranked = []
        for rr in rerank_results:
            if 0 <= rr.original_index < len(results):
                original = results[rr.original_index]
                reranked.append(SearchResult(
                    chunk=original.chunk,
                    score=rr.score,
                    document=original.document,
                ))

        return reranked
