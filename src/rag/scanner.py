"""Unified RAG Scanner — 高性能代码扫描与分析
统一 Trigram, Word, Symbol, RepoMap 的解析流程，减少磁盘 I/O。
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

from ..utils import get_logger
from .repo_map import CodeStructure
from .symbol_extractor import FileOutline, SymbolExtractor
from .trigram_index import TrigramIndex
from .word_index import WordIndex

logger = get_logger(__name__)

class ScanResult(NamedTuple):
    path: str
    mtime: float
    size: int
    content: str
    outline: FileOutline
    structure: CodeStructure
    success: bool = True
    error: str | None = None

class UnifiedScanner:
    """统一扫描器 - 一次读取，多次分析"""

    def __init__(
        self,
        root_dir: Path,
        trigram_index: TrigramIndex | None = None,
        word_index: WordIndex | None = None,
        symbol_extractor: SymbolExtractor | None = None,
        max_workers: int = 8
    ):
        self.root_dir = root_dir
        self.trigram_index = trigram_index or TrigramIndex()
        self.word_index = word_index or WordIndex()
        self.symbol_extractor = symbol_extractor or SymbolExtractor()
        self.max_workers = max_workers
        self._file_cache: dict[str, ScanResult] = {}

    def scan_file(self, rel_path: str, force: bool = False) -> ScanResult:
        """扫描单个文件 (优化版)"""
        abs_path = self.root_dir / rel_path
        try:
            st = os.stat(abs_path)
            mtime = st.st_mtime
            size = st.st_size

            # 增量检查
            if not force:
                cached = self._file_cache.get(rel_path)
                if cached and cached.mtime == mtime and cached.size == size:
                    return cached

            content = abs_path.read_text(encoding='utf-8', errors='replace')

            # 1. 符号提取
            outline = self.symbol_extractor.extract(str(abs_path), content)

            # 2. 转换为 RepoMap 结构
            structure = CodeStructure(
                path=rel_path,
                language=outline.language,
                classes=[s.name for s in outline.symbols if s.kind == "class"],
                functions=[{"name": s.name, "signature": s.detail or ""} for s in outline.symbols if s.kind == "function"],
                imports=outline.imports,
                docstring="" # 暂时留空
            )

            # 3. 更新索引 (Trigram & Word)
            self.trigram_index.index_file(str(abs_path), content)
            self.word_index.index_file(str(abs_path), content)

            result = ScanResult(
                path=rel_path,
                mtime=mtime,
                size=size,
                content=content,
                outline=outline,
                structure=structure
            )
            self._file_cache[rel_path] = result
            return result

        except Exception as e:
            logger.error(f"扫描文件失败 {rel_path}: {e}")
            return ScanResult(rel_path, 0, 0, "", None, None, success=False, error=str(e))

    async def scan_directory(self, pattern: str = "**/*.py") -> list[ScanResult]:
        """并行扫描目录 (已优化增量扫描性能)"""
        import asyncio
        # 使用快速列表，避免 resolve
        files = [str(p.relative_to(self.root_dir)).replace('\\', '/')
                for p in self.root_dir.glob(pattern) if p.is_file()]

        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            tasks = [
                loop.run_in_executor(executor, self.scan_file, f)
                for f in files
            ]
            results = await asyncio.gather(*tasks)

        return [r for r in results if r.success]

    def get_repo_map_structures(self) -> list[CodeStructure]:
        """获取所有已扫描文件的结构，用于生成 RepoMap (已优化性能)"""
        # 使用列表生成式一次性提取，避免在循环中进行多次属性访问检查
        return [
            result.structure
            for result in self._file_cache.values()
            if result.success and result.structure is not None
        ]

    def clear_cache(self):
        """清除内存缓存"""
        self._file_cache.clear()

    def get_stats(self) -> dict:
        """获取扫描统计信息"""
        total = len(self._file_cache)
        successful = sum(1 for r in self._file_cache.values() if r.success)
        return {
            "total_files": total,
            "successful": successful,
            "failed": total - successful,
            "cache_size_bytes": sum(len(r.content) for r in self._file_cache.values() if r.success)
        }
