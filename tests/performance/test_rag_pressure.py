import os
import time
import asyncio
import tempfile
import shutil
from pathlib import Path
import pytest
from src.rag.scanner import UnifiedScanner
from src.rag.trigram_index import TrigramIndex
from src.rag.word_index import WordIndex
from src.rag.symbol_extractor import SymbolExtractor
from src.rag.repo_map import RepoMap

def create_mock_project(root_dir: Path, num_files: int = 1000):
    """创建一个包含大量文件的模拟项目"""
    src_dir = root_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    # 创建一些子目录
    subdirs = ["core", "utils", "api", "models", "services", "ui", "auth", "db", "tests", "config"]
    for sd in subdirs:
        (src_dir / sd).mkdir(exist_ok=True)

    for i in range(num_files):
        subdir = subdirs[i % len(subdirs)]
        file_path = src_dir / subdir / f"module_{i}.py"

        # 生成一些有意义的 Python 代码内容，包含类和函数
        content = f'''"""Module {i}"""
import os
from src.utils import common
from src.core.base import BaseClass

class Class{i}(BaseClass):
    """Class {i} description"""
    def __init__(self, name: str):
        self.name = name

    def action_{i}(self, data: dict) -> bool:
        """Action {i} method"""
        return True

def function_{i}(x: int, y: int) -> int:
    return x + y
'''
        file_path.write_text(content, encoding='utf-8')

@pytest.mark.asyncio
async def test_unified_scanner_performance():
    """测试 UnifiedScanner 在大规模文件下的性能"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        num_files = 1000
        print(f"\n[Performance] Creating {num_files} mock files...")
        start_create = time.perf_counter()
        create_mock_project(root, num_files)
        print(f"[Performance] Creation took {time.perf_counter() - start_create:.2f}s")

        trigram = TrigramIndex()
        word = WordIndex()
        extractor = SymbolExtractor()
        scanner = UnifiedScanner(root, trigram, word, extractor, max_workers=16)

        # 1. 首次全量扫描
        print(f"[Performance] Starting initial full scan of {num_files} files...")
        start_scan = time.perf_counter()
        results = await scanner.scan_directory("src/**/*.py")
        scan_duration = time.perf_counter() - start_scan

        assert len(results) >= num_files
        print(f"[Performance] Initial scan took {scan_duration:.2f}s ({num_files/scan_duration:.1f} files/sec)")

        # 性能基准：1000 个小文件应该在 5 秒内完成 (在主流机器上)
        # 这里设置一个宽松的阈值供 CI 环境参考
        # assert scan_duration < 10.0

        # 2. 增量扫描 (预期极快)
        print(f"[Performance] Starting incremental scan (no changes)...")
        start_inc = time.perf_counter()
        results_inc = await scanner.scan_directory("src/**/*.py")
        inc_duration = time.perf_counter() - start_inc
        print(f"[Performance] Incremental scan took {inc_duration:.2f}s")

        assert inc_duration < scan_duration * 0.2

        # 3. RepoMap 生成性能
        repo_map = RepoMap(token_budget=4000, root_dir=root)
        other_files = [r.path for r in results]

        print(f"[Performance] Generating RepoMap for {len(other_files)} files...")
        start_map = time.perf_counter()
        map_str = repo_map.get_repo_map(chat_files=[], other_files=other_files, scanner=scanner)
        map_duration = time.perf_counter() - start_map

        assert map_str is not None
        print(f"[Performance] RepoMap generation took {map_duration:.2f}s")
        # print(f"Map Preview:\n{map_str[:200]}...")

if __name__ == "__main__":
    # 手动运行时执行
    asyncio.run(test_unified_scanner_performance())
