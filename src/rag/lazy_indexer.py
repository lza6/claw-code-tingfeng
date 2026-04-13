"""LazyIndexer - 惰性索引器（流式加载和内存优化）

从 rag/__init__.py 拆分，负责：
- 惰性文件索引（只存储路径，搜索时才读取内容）
- LRU 内容缓存
- 倒排索引构建
- 索引持久化（save_index / load_index）
"""
from __future__ import annotations

import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any


class LazyIndexer:
    """惰性索引器 - 流式加载和内存优化

    与 TextIndexer 不同，LazyIndexer 不会将所有文档内容加载到内存中。
    它只存储文件路径和元数据，在搜索时才读取文件内容。
    适合大规模文档索引场景。

    增强功能:
    - index_content: 可选内容索引模式，启用后构建倒排索引时读取文件内容
    - 搜索时能匹配文件内容关键词，而不仅仅是文件名
    """

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50, index_content: bool = False, max_cache_size: int = 100) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.index_content = index_content  # 是否索引文件内容
        self._file_index: dict[str, dict[str, Any]] = {}  # file_path -> metadata
        self._inverted_index: dict[str, set[str]] = {}  # term -> file_paths
        self._content_cache: OrderedDict[str, str] = OrderedDict()  # file_path -> content (真正的 LRU)
        self._max_cache_size = max_cache_size  # 最大缓存文件数（可配置，默认 100）
        self._index_built = False  # 索引是否已构建标志，避免重复检查和构建

    def add_file(self, file_path: Path, metadata: dict[str, Any] | None = None) -> None:
        """添加文件到索引（不读取内容）"""
        path_str = str(file_path)
        self._file_index[path_str] = {
            'path': path_str,
            'metadata': metadata or {},
            'indexed': False,
        }

    def add_directory(self, dir_path: Path, pattern: str = '**/*.py') -> int:
        """批量添加目录下的文件到索引

        返回:
            添加的文件数量
        """
        count = 0
        for file_path in dir_path.glob(pattern):
            if file_path.is_file():
                self.add_file(file_path)
                count += 1
        return count

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """搜索相关文件（带权重的倒排索引）

        返回:
            相关文件列表，包含文件路径、匹配分数和摘要
        """
        if not self._index_built and self._file_index:
            self.build_index()

        query_terms = self._tokenize(query)
        if not query_terms:
            return []

        # 计算文件相关性分数 (基于位置和结构权重的启发式算法)
        scores: dict[str, float] = {}
        for term in query_terms:
            matching_files = self._inverted_index.get(term, set())
            for file_path in matching_files:
                # 基础分
                weight = 1.0

                # 路径和文件名权重加成
                name_part = Path(file_path).name.lower()
                if term in name_part:
                    weight += 5.0  # 文件名匹配权重最高
                if term in file_path.lower():
                    weight += 2.0  # 路径匹配权重

                scores[file_path] = scores.get(file_path, 0) + weight

        # 排序并返回 top_k
        sorted_files = sorted(scores.items(), key=lambda x: -x[1])
        results: list[dict[str, Any]] = []
        for file_path, score in sorted_files[:top_k]:
            content = self._read_file_cached(file_path)
            results.append({
                'file_path': file_path,
                'score': score,
                'content_preview': content[:300] if content else '',
                'metadata': self._file_index[file_path].get('metadata', {}),
            })
        return results

    def get_context(self, query: str, top_k: int = 3, max_context_length: int = 4000) -> str:
        """获取增强上下文（惰性加载）"""
        results = self.search(query, top_k=top_k)
        if not results:
            return ''

        context_parts: list[str] = []
        total_length = 0
        for result in results:
            content = self._read_file_cached(result['file_path'])
            if not content:
                continue
            chunk_text = f'[来源: {result["file_path"]}]\n{content[:1000]}'
            if total_length + len(chunk_text) > max_context_length:
                break
            context_parts.append(chunk_text)
            total_length += len(chunk_text)

        return '\n\n---\n\n'.join(context_parts)

    def _read_file_cached(self, file_path: str) -> str | None:
        """带缓存的文件读取（真正的 LRU 淘汰）"""
        if file_path in self._content_cache:
            # 访问时移动到末尾（最近使用）
            self._content_cache.move_to_end(file_path)
            return self._content_cache[file_path]

        try:
            content = Path(file_path).read_text(encoding='utf-8', errors='replace')
            # LRU 缓存淘汰：移除最久未使用的
            if len(self._content_cache) >= self._max_cache_size:
                self._content_cache.popitem(last=False)
            self._content_cache[file_path] = content
            return content
        except (OSError, PermissionError):
            return None

    def _tokenize(self, text: str) -> list[str]:
        """高级分词 (支持 CamelCase, snake_case 和中英文混合)"""
        # 1. 基础分词
        raw_tokens = re.findall(r'[a-zA-Z\u4e00-\u9fff0-9_]{2,}', text)

        processed_tokens: set[str] = set()
        for token in raw_tokens:
            low_token = token.lower()
            processed_tokens.add(low_token)

            # 2. 拆分 snake_case
            if '_' in token:
                parts = token.split('_')
                for p in parts:
                    if len(p) >= 2:
                        processed_tokens.add(p.lower())

            # 3. 拆分 CamelCase / PascalCase
            camel_parts = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)', token)
            if len(camel_parts) > 1:
                for p in camel_parts:
                    if len(p) >= 2:
                        processed_tokens.add(p.lower())

        stop_words = {
            'the', 'is', 'are', 'was', 'were', 'and', 'or', 'not', 'this', 'that',
            'def', 'class', 'return', 'import', 'from', 'self', 'args', 'kwargs'
        }
        return [t for t in processed_tokens if t not in stop_words]

    def build_index(self) -> int:
        """构建带权重的倒排索引"""
        newly_indexed = 0
        for file_path, meta in self._file_index.items():
            if meta['indexed']:
                continue

            # 始终索引文件名和路径 (高权重项)
            file_name = Path(file_path).name
            terms = self._tokenize(file_name + ' ' + file_path)

            if self.index_content:
                content = self._read_file_cached(file_path)
                if content:
                    # 识别代码结构 (启发式)
                    # 提取类名和函数名
                    struct_terms = re.findall(r'(?:class|def|function)\s+([a-zA-Z_]\w*)', content)
                    content_terms = self._tokenize(content)

                    # 结构化词条权重提升
                    for term in struct_terms:
                        t_parts = self._tokenize(term)
                        for tp in t_parts:
                            terms.append(tp)
                            terms.append(tp) # 额外增加权重

                    terms.extend(content_terms)

            for term in terms:
                if term not in self._inverted_index:
                    self._inverted_index[term] = set()
                self._inverted_index[term].add(file_path)
            meta['indexed'] = True
            newly_indexed += 1
        self._index_built = True
        return newly_indexed

    def clear_cache(self) -> None:
        """清空内容缓存"""
        self._content_cache.clear()

    def get_cache_info(self) -> dict[str, Any]:
        """获取缓存信息"""
        return {
            'current_size': len(self._content_cache),
            'max_size': self._max_cache_size,
            'usage_percent': round(len(self._content_cache) / max(self._max_cache_size, 1) * 100, 1),
        }

    def get_stats(self) -> dict[str, Any]:
        """获取索引统计信息"""
        return {
            'total_files': len(self._file_index),
            'indexed_files': sum(1 for m in self._file_index.values() if m['indexed']),
            'cache_size': len(self._content_cache),
            'index_terms': len(self._inverted_index),
        }

    # ==================== 索引持久化 ====================

    def save_index(self, index_path: Path) -> None:
        """保存索引到文件

        保存内容：
        - 文件索引（路径和元数据）
        - 倒排索引（词 -> 文件路径映射）
        - 索引状态（哪些文件已索引）

        注意：不保存内容缓存（搜索时可重新加载）。

        参数:
            index_path: 索引文件路径（JSON 格式）
        """
        index_data = {
            'version': '1',
            'file_index': self._file_index,
            'inverted_index': {
                term: list(file_paths)
                for term, file_paths in self._inverted_index.items()
            },
            'index_built': self._index_built,
        }

        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps(index_data, ensure_ascii=False, indent=2))

    def load_index(self, index_path: Path) -> bool:
        """从文件加载索引

        参数:
            index_path: 索引文件路径

        返回:
            True 表示加载成功，False 表示文件不存在或格式错误
        """
        if not index_path.exists():
            return False

        try:
            index_data = json.loads(index_path.read_text())

            self._file_index = index_data.get('file_index', {})
            self._inverted_index = {
                term: set(file_paths)
                for term, file_paths in index_data.get('inverted_index', {}).items()
            }
            self._index_built = index_data.get('index_built', False)

            return True
        except (json.JSONDecodeError, KeyError, TypeError):
            return False

    def clear(self) -> None:
        """清空所有索引数据"""
        self._file_index.clear()
        self._inverted_index.clear()
        self._content_cache.clear()
        self._index_built = False
