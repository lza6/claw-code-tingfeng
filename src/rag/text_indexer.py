"""TextIndexer - 轻量级文本索引器（BM25 + TF-IDF 风格关键词匹配）

从 rag/__init__.py 导入，负责：
- 文档索引（add_document, add_file, add_directory）
- 搜索（search, get_context）
- 索引持久化（save_index, load_index）

增强功能 (v0.19.0):
- BM25 评分算法（更精确的相关性排序）
- 改进的中文分词支持（支持中文关键词提取）
- IDF 权重计算
- 更完善的停用词表

重构说明 (v0.50.0):
- 拆分为 indexer_utils.py（工具函数）、indexer_search.py（搜索）、indexer_persistence.py（持久化）
- 保持向后兼容，所有导入路径不变
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..utils import get_logger

logger = get_logger(__name__)

from .dependency_graph import DependencyGraph

# 重新导出持久化函数（向后兼容）
from .indexer_persistence import (
    load_index_legacy,
    load_index_v2,
    save_index_legacy,
    save_index_v2,
)

# 重新导出工具函数（向后兼容）
# 重新导出工具函数（向后兼容）
from .indexer_utils import (
    chunk_document as _chunk_document,
)
from .indexer_utils import (
    generate_id as _generate_id,
)
from .indexer_utils import (
    tokenize as _tokenize,
)
from .models import Chunk, Document, SearchResult
from .symbol_extractor import FileOutline, SymbolExtractor
from .trigram_index import TrigramIndex
from .word_index import WordIndex


class TextIndexer:
    """轻量级文本索引器

    使用 TF-IDF 风格的关键词匹配进行文档检索。
    不依赖外部向量数据库，适合个人开发者使用。

    增强功能 (v0.27.0):
    - Cross-Encoder 重排序（可选，对 Top-K 结果二次排序）
    - 懒加载重排序器（首次调用时才加载模型）

    内存保护:
    - max_file_size: 单文件最大大小（默认 1MB），超过则跳过索引
    - max_documents: 最大文档数量（默认 1000），防止内存溢出
    """

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        max_file_size: int = 1024 * 1024,  # 1MB
        max_documents: int = 1000,
        enable_reranker: bool = False,  # 默认禁用 Cross-Encoder（避免内存爆炸）
        reranker_top_k: int = 10,
        reranker_model: str | None = None,
        search_cache_size: int = 256,  # [性能] 搜索结果 LRU 缓存大小
        root_dir: Path | None = None,
    ) -> None:
        """初始化索引器

        参数:
            chunk_size: 分块大小（字符数）
            chunk_overlap: 分块重叠字符数
            max_file_size: 单文件最大大小（字节），超过则跳过索引
            max_documents: 最大文档数量，防止内存溢出
            enable_reranker: 是否启用 Cross-Encoder 重排序（默认 True）
            reranker_top_k: 重排序前检索的候选数量（默认 10）
            reranker_model: 重排序模型名称（None=使用默认）
            search_cache_size: 搜索结果 LRU 缓存大小（默认 256）
            root_dir: 根目录（用于 UnifiedScanner）
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_file_size = max_file_size
        self.max_documents = max_documents
        self._documents: dict[str, Document] = {}
        self._chunks: dict[str, Chunk] = {}
        self._file_metadata: dict[str, dict[str, Any]] = {}  # [NEW] 追踪文件 mtime 和 hash
        self._word_index = WordIndex()  # [NEW] Robust word index from Project B
        self._chunk_lengths: dict[str, int] = {}  # 缓存 chunk 长度
        self._skipped_files: list[str] = []  # 跳过的文件列表（最多保留 50 条）

        # [性能] 搜索结果 LRU 缓存
        self._search_cache_size = search_cache_size
        self._search_cache: dict[str, list[SearchResult]] = {}

        # Cross-Encoder 重排序配置
        self.enable_reranker = enable_reranker
        self.reranker_top_k = reranker_top_k
        self._reranker_model_name = reranker_model
        self._reranker: Any = None  # 懒加载

        # [NEW] Trigram and Symbol Indexing (Ported from Project B)
        self.trigram_index = TrigramIndex()
        self.symbol_extractor = SymbolExtractor()
        self.dependency_graph = DependencyGraph()
        self._outlines: dict[str, FileOutline] = {}

        # [NEW] Unified Scanner
        from .scanner import UnifiedScanner
        self.scanner = UnifiedScanner(
            root_dir=root_dir or Path.cwd(),
            trigram_index=self.trigram_index,
            word_index=self._word_index,
            symbol_extractor=self.symbol_extractor
        )

        # 导入搜索相关类
        from .indexer_search import BM25Scorer, SimpleScorer

        self._bm25_scorer = BM25Scorer()
        self._simple_scorer = SimpleScorer()

    def _invalidate_chunk_lengths_cache(self) -> None:
        """标记 chunk lengths 缓存无效"""
        self._chunk_lengths = {}
        self._clear_search_cache()

    def _clear_search_cache(self) -> None:
        """清除搜索缓存"""
        self._search_cache.clear()

    def add_document(self, doc: Document) -> bool:
        """添加文档到索引

        返回:
            True 表示添加成功，False 表示超过上限被跳过
        """
        if len(self._documents) >= self.max_documents:
            if len(self._skipped_files) < 50:
                self._skipped_files.append(doc.source)
            return False

        self._documents[doc.id] = doc
        chunks = self._chunk_document(doc)
        for chunk in chunks:
            self._chunks[chunk.id] = chunk

        # [NEW] Use UnifiedScanner for analysis if path is relative to root
        try:
            rel_path = str(Path(doc.source).relative_to(self.scanner.root_dir))
            scan_res = self.scanner.scan_file(rel_path)
            if scan_res.success:
                self._outlines[doc.source] = scan_res.outline
                self.dependency_graph.update_file(doc.source, scan_res.outline.imports)
        except (ValueError, Exception):
            # Fallback to legacy manual indexing
            self.trigram_index.index_file(doc.source, doc.content)
            self._word_index.index_file(doc.source, doc.content)
            outline = self.symbol_extractor.extract(doc.source, doc.content)
            self._outlines[doc.source] = outline
            self.dependency_graph.update_file(doc.source, outline.imports)

        self._invalidate_chunk_lengths_cache()
        return True

    def _chunk_document(self, doc: Document) -> list[Chunk]:
        """将文档分块"""
        return _chunk_document(
            content=doc.content,
            doc_id=doc.id,
            doc_source=doc.source,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

    def add_file(self, file_path: Path, metadata: dict[str, Any] | None = None, force: bool = False) -> Document | None:
        """从文件添加文档到索引

        返回:
            Document 对象，如果文件过大、超过文档上限或未变动则返回 None
        """
        if len(self._documents) >= self.max_documents:
            if len(self._skipped_files) < 50:
                self._skipped_files.append(str(file_path))
            return None

        try:
            stat = file_path.stat()
            file_size = stat.st_size
            mtime = stat.st_mtime

            # [增量更新] 检查文件是否已存在且未变动
            if not force and str(file_path) in self._file_metadata:
                old_meta = self._file_metadata[str(file_path)]
                if old_meta.get('mtime') == mtime and old_meta.get('size') == file_size:
                    return self._documents.get(_generate_id(str(file_path)))

            if file_size > self.max_file_size:
                if len(self._skipped_files) < 50:
                    self._skipped_files.append(str(file_path))
                return None

            content = file_path.read_text(encoding='utf-8', errors='replace')
            doc_id = _generate_id(str(file_path))
            doc = Document(
                id=doc_id,
                content=content,
                source=str(file_path),
                metadata=metadata or {},
            )

            # 更新元数据
            self._file_metadata[str(file_path)] = {
                'mtime': mtime,
                'size': file_size,
            }

            self.add_document(doc)
            return doc
        except (OSError, UnicodeDecodeError):
            return None

    async def add_file_async(self, file_path: Path, metadata: dict[str, Any] | None = None) -> Document | None:
        """异步从文件添加文档到索引（使用 asyncio.to_thread 避免阻塞事件循环）

        返回:
            Document 对象，如果��件过大或超过文档上限则返回 None
        """
        return await asyncio.to_thread(self.add_file, file_path, metadata)

    async def add_directory_async(
        self,
        dir_path: Path,
        pattern: str = '**/*.py',
        metadata: dict[str, Any] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[Document]:
        """异步从目录批量添加文档 (高性能版)

        参数:
            dir_path: 目录路径
            pattern: 文件匹配模式
            metadata: 共享元数据
            on_progress: 进度回调 (current, total)

        返回:
            成功添加的文档列表
        """
        import asyncio
        import os

        # 扫描文件列表
        files = [f for f in dir_path.glob(pattern) if f.is_file()]
        if not files:
            return []

        # 动态计算并发数 (CPU 核心数 * 2，最小 4，最大 32)
        concurrency = min(max(4, (os.cpu_count() or 4) * 2), 32)
        sem = asyncio.Semaphore(concurrency)
        total = len(files)
        current = 0

        async def _process_file(f: Path) -> Document | None:
            nonlocal current
            async with sem:
                try:
                    # [性能优化] 检查 mtime，跳过未修改文件
                    mtime = f.stat().st_mtime
                    f_id = str(f.absolute())
                    if f_id in self._file_metadata and self._file_metadata[f_id].get('mtime') == mtime:
                        return self._documents.get(f_id)

                    doc = await self.add_file_async(f, metadata)
                    if doc:
                        self._file_metadata[f_id] = {'mtime': mtime, 'size': f.stat().st_size}
                    return doc
                finally:
                    current += 1
                    if on_progress:
                        on_progress(current, total)

        tasks = [_process_file(f) for f in files]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]

    def add_directory(
        self,
        dir_path: Path,
        pattern: str = '**/*.py',
        metadata: dict[str, Any] | None = None,
    ) -> list[Document]:
        """[同步兼容层] 从目录批量添加文档"""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            # 如果已在运行，使用线程池模拟 (兼容性处理)
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor() as executor:
                docs = list(executor.map(lambda f: self.add_file(f, metadata), [f for f in dir_path.glob(pattern) if f.is_file()]))
                return [d for d in docs if d is not None]

        return loop.run_until_complete(self.add_directory_async(dir_path, pattern, metadata))

    async def build_index_async(self, root_dir: Path, pattern: str = '**/*.py') -> int:
        """异步并行为整个目录构建索引 (v0.66)"""
        import asyncio

        files = list(root_dir.glob(pattern))
        if not files:
            return 0

        # 使用信号量控制并发，防止 IO 压力过大
        sem = asyncio.Semaphore(10)

        async def _indexed_file(f: Path):
            async with sem:
                return await self.add_file_async(f)

        tasks = [_indexed_file(f) for f in files if f.is_file()]
        results = await asyncio.gather(*tasks)

        indexed_count = len([r for r in results if r is not None])
        logger.info(f"增量索引完成: {indexed_count}/{len(files)} 个文件已处理")
        return indexed_count

    def get_stats(self) -> dict[str, Any]:
        """获取索引统计信息

        返回:
            包含文档数、分块数、索引词数、跳过文件数的统计字典
        """

        # 计算索引在内存中的大致大小 (估算)
        # 每个词约 50 字节，每个分块索引项约 20 字节
        terms_count = len(self._word_index.index)
        chunks_count = len(self._chunks)
        estimated_size = (terms_count * 50) + (chunks_count * 200)

        return {
            'total_documents': len(self._documents),
            'total_chunks': chunks_count,
            'index_terms': terms_count,
            'skipped_files': len(self._skipped_files),
            'skipped_file_paths': self._skipped_files[:10],
            'estimated_size_bytes': estimated_size,
        }

    def search(self, query: str, top_k: int = 5, use_bm25: bool = True) -> list[SearchResult]:
        """搜索相关文档块

        增强功能 (v0.19.0):
        - 支持 BM25 评分算法（默认启用）
        - 更精确的相关性排序

        [性能优化 v0.37.0]:
        - 添加 LRU 缓存，相同查询直接命中，避免重复 BM25 计算

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
            return self._search_cache[cache_key]

        query_terms = _tokenize(query)
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
            # 移除最旧的条目
            oldest_key = next(iter(self._search_cache))
            del self._search_cache[oldest_key]
        self._search_cache[cache_key] = results

        return results

    def search_word(self, list: Any, word: str) -> Any:
        """[NEW] 精确单词搜索，返回 (文件, 行号) 列表 (Ported from Project B)"""
        return self._word_index.search(word)

    def get_outline(self, source_path: str) -> FileOutline | None:
        """[NEW] 获取文件的结构化大纲 (Ported from Project B)"""
        return self._outlines.get(source_path)

    def get_imported_by(self, source_path: str) -> list[str]:
        """[NEW] 获���引���该文件的文件列表 (Ported from Project B)"""
        return self.dependency_graph.get_imported_by(source_path)

    def get_context(
        self,
        query: str,
        top_k: int = 3,
        max_context_length: int = 4000,
    ) -> str:
        """获取增强上下文

        检索相关文档块并格式化为 LLM 可用的上下文。

        增强功能 (v0.27.0):
        - 引入 Cross-Encoder 重排序，先检索 Top-N 再二次排序取 Top-K

        参数:
            query: 搜索查询
            top_k: 最终返回的检索结果数量
            max_context_length: 最大上下文长度（字符数）

        返回:
            格式化的上下文字符串
        """

        # Step 1: 初步检索（如果需要重排序，取更多候选）
        initial_k = self.reranker_top_k if self.enable_reranker else top_k
        results = self.search(query, top_k=initial_k)
        if not results:
            return ''

        # Step 2: Cross-Encoder 重排序
        if self.enable_reranker:
            results = self._rerank_results(query, results, top_k)

        # Step 3: 格式化上下文
        context_parts = []
        total_length = 0
        for result in results:
            source = getattr(result.chunk, 'source', None) or (
                result.document.source if result.document else '未知'
            )
            # 仅在启用重排序时包含相关度分数
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
        """获取 Cross-Encoder 重排序���（懒加载）"""
        if self._reranker is None and self.enable_reranker:
            try:
                from .cross_encoder_reranker import CrossEncoderReranker

                kwargs = {}
                if self._reranker_model_name:
                    kwargs['model_name'] = self._reranker_model_name
                self._reranker = CrossEncoderReranker(**kwargs)
                # 验证模型是否真正可用
                if not self._reranker.is_available:
                    # 模型不可用（如 sentence-transformers 未安装或模型下载失败）
                    # 降级到关键词重排序，不抛异常
                    self._reranker = None
                    self.enable_reranker = False
            except Exception as e:
                # 加载失败，禁用重排序
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
        """使用 Cross-Encoder 对搜索结果进行二次排序

        参数:
            query: 原始查询
            results: 初步搜索结果列表
            top_k: 返回数量

        返回:
            重排序后的 SearchResult 列表
        """
        reranker = self._get_reranker()
        if reranker is None or not reranker.is_available:
            # 重排序器不可用，直接返回原始结果（截断到 top_k）
            return results[:top_k]

        # 提取文档内容
        documents = [r.chunk.content for r in results]
        if not documents:
            return []

        # 执行重排序
        rerank_results = reranker.rerank(query, documents, top_k=top_k)

        # 映射回 SearchResult
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

    def save_index(self, index_path: Path) -> None:
        """保存索引到文件（内容外部存储 + 索引引用模式）"""
        if index_path.suffix == '.json':
            return self._save_index_legacy(index_path)

        save_index_v2(
            index_path,
            self._documents,
            self._chunks,
            self._word_index.index,
        )

    def _save_index_legacy(self, index_path: Path) -> None:
        """旧格式保存（向后兼容）"""
        save_index_legacy(
            index_path,
            self._documents,
            self._chunks,
            self._word_index.index,
            self.trigram_index,
        )

    def load_index(self, index_path: Path) -> None:
        """从文件加载索引（支持新旧两种格式）"""
        if index_path.is_dir():
            return self._load_index_v2(index_path)
        return self._load_index_legacy(index_path)

    def _load_index_v2(self, index_path: Path) -> None:
        """加载新格式索引（目录结构）"""
        documents, chunks, _, chunk_lengths = load_index_v2(index_path)

        self._documents = documents
        self._chunks = chunks
        self._chunk_lengths = chunk_lengths

        # Rebuild WordIndex from documents
        for doc in self._documents.values():
            self._word_index.index_file(doc.source, doc.content)

    def _load_index_legacy(self, index_path: Path) -> None:
        """加载旧格式索引（单文件 JSON）"""
        (
            documents,
            chunks,
            _,
            chunk_lengths,
            trigram_index,
        ) = load_index_legacy(index_path)

        self._documents = documents
        self._chunks = chunks
        self._chunk_lengths = chunk_lengths

        if trigram_index:
            self.trigram_index = trigram_index
            # Re-extract outlines for loaded documents
            for doc in self._documents.values():
                self._outlines[doc.source] = self.symbol_extractor.extract(doc.source, doc.content)

    def _update_inverted_index(self, chunk: Chunk) -> None:
        """更新倒排索引 (废弃: 逻辑已移至 WordIndex)"""
        pass

    def _simple_score(
        self,
        query_terms: list[str],
    ) -> dict[str, float]:
        """简单计数评分（回退方案）"""
        return self._simple_scorer.score(query_terms, self._chunks, self._word_index)

    def _bm25_score(
        self,
        query_terms: list[str],
        top_k: int,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> dict[str, float]:
        """BM25 评分算法

        参数:
            query_terms: 查询词列表
            top_k: 返回结果数量
            k1: 词频饱和参数（默认 1.5）
            b: 文档长度归一化参数（默认 0.75）

        返回:
            chunk_id -> score 的字典
        """
        from .indexer_search import BM25Scorer

        scorer = BM25Scorer(k1=k1, b=b)
        return scorer.score(query_terms, self._chunks, self._word_index)
