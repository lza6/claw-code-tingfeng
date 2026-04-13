"""GrepTool - 文件内容搜索工具（并发优化版）"""
from __future__ import annotations

import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..rag.scope_detector import ScopeDetector
from ..rag.symbol_extractor import SymbolExtractor
from ..utils.ignore_parser import get_ignore_filter
from .base import BaseTool, ParameterSchema, ToolResult
from .path_utils import BINARY_EXTENSIONS

logger = logging.getLogger(__name__)

# 忽略的目录
IGNORE_DIRS = frozenset({
    '__pycache__', '.git', 'node_modules', '.venv', 'venv',
    '.tox', '.mypy_cache', '.pytest_cache', 'dist', 'build',
    '.idea', '.vscode', 'coverage', '.nyc_output',
})


def get_optimal_workers() -> int:
    """根据 CPU 核心数自动计算最优并发线程数

    策略: min(cpu_count, 8)，最少 2 个线程，最多 8 个线程。
    避免线程过多导致上下文切换开销，同时充分利用多核 CPU。
    """
    cpu_count = os.cpu_count() or 4
    return min(max(cpu_count, 2), 8)


class GrepTool(BaseTool):
    """文件内容正则搜索工具（并发优化版）"""

    name = 'GrepTool'
    description = '在文件内容中搜索正则表达式（支持自适应并发搜索）'

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name='pattern',
            param_type='str',
            required=True,
            description='正则表达式搜索模式',
            min_length=1,
            max_length=500,
        ),
        ParameterSchema(
            name='case_sensitive',
            param_type='bool',
            required=False,
            description='是否区分大小写',
            default=False,
        ),
        ParameterSchema(
            name='file_pattern',
            param_type='str',
            required=False,
            description='文件匹配模式（如 *.py）',
            default='*.py',
            min_length=1,
            max_length=200,
        ),
        ParameterSchema(
            name='max_results',
            param_type='int',
            required=False,
            description='最大结果数量',
            default=50,
            min_value=1,
            max_value=1000,
        ),
        ParameterSchema(
            name='scope',
            param_type='bool',
            required=False,
            description='是否显示结果所属的函数/类',
            default=False,
        ),
    )

    def __init__(
        self,
        base_path: Path | None = None,
        max_results: int = 50,
        max_file_size: int = 1024 * 1024,
        max_workers: int | None = None,
    ) -> None:
        self.base_path = base_path or Path.cwd()
        self.max_results = max_results
        self.max_file_size = max_file_size
        # 自适应并发
        self.max_workers = max_workers if max_workers is not None else get_optimal_workers()
        # 动态忽略解析器 (Ported from Project B)
        self.ignore_filter = get_ignore_filter(self.base_path)
        # 符号提取器
        self.extractor = SymbolExtractor()

    def validate(self, **kwargs) -> tuple[bool, str]:
        pattern = kwargs.get('pattern', '')
        if not pattern:
            return False, '搜索模式不能为空'
        try:
            re.compile(pattern)
        except re.error as e:
            return False, f'无效的正则表达式: {e}'
        return True, ''

    def execute(self, **kwargs) -> ToolResult:
        pattern = kwargs.get('pattern', '')
        case_sensitive = kwargs.get('case_sensitive', False)
        file_pattern = kwargs.get('file_pattern', '*.py')
        max_results = kwargs.get('max_results', self.max_results)
        scope = kwargs.get('scope', False)

        is_valid, error_msg = self.validate(pattern=pattern)
        if not is_valid:
            return ToolResult(success=False, output='', error=error_msg, exit_code=1)

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return ToolResult(success=False, output='', error=f'正则编译错误: {e}', exit_code=1)

        # 收集所有待搜索文件
        file_paths = self._collect_files(file_pattern)
        if not file_paths:
            return ToolResult(success=True, output=f'未找到匹配文件模式 "{file_pattern}" 的文件')

        # 并发搜索
        results = self._search_files_concurrent(file_paths, regex, max_results, scope)

        if not results:
            return ToolResult(success=True, output=f'未找到匹配 "{pattern}" 的内容')

        output_lines = [f'搜索 {len(file_paths)} 个文件，找到 {len(results)} 个匹配:', '']
        for file_path, line_num, line, scope_info in results:
            if scope_info:
                output_lines.append(f'{file_path}:{line_num}: {line} [in {scope_info}]')
            else:
                output_lines.append(f'{file_path}:{line_num}: {line}')

        return ToolResult(success=True, output='\n'.join(output_lines))

    def _collect_files(self, file_pattern: str) -> list[Path]:
        """收集待搜索文件列表（v0.16.0 优化：过滤二进制文件）"""
        file_paths: list[Path] = []
        try:
            for file_path in self.base_path.glob(f'**/{file_pattern}'):
                if not file_path.is_file():
                    continue
                # 动态忽略检查 (Ported from Project B)
                if self.ignore_filter.is_ignored(file_path):
                    continue
                # 跳过二进制文件（扩展名过滤）
                if file_path.suffix.lower() in BINARY_EXTENSIONS:
                    continue
                # 跳过二进制文件（内容检测：前 8KB 包含 NUL 字符）
                if self._is_binary_file(file_path):
                    continue
                # 跳过过大的文件
                try:
                    if file_path.stat().st_size > self.max_file_size:
                        continue
                except OSError:
                    continue
                file_paths.append(file_path)
        except Exception as e:
            logger.debug(f"GrepTool: 收集文件失败 ({file_pattern}): {e}")
        return file_paths

    def _is_binary_file(self, file_path: Path) -> bool:
        """检测文件是否为二进制文件（检查前 8KB 是否包含 NUL 字符）"""
        try:
            with open(file_path, 'rb') as f:
                chunk = f.read(8192)
                return b'\x00' in chunk
        except (OSError, PermissionError):
            return False

    def _search_files_concurrent(
        self,
        file_paths: list[Path],
        regex: re.Pattern[str],
        max_results: int | None = None,
        scope: bool = False,
    ) -> list[tuple[str, int, str, str | None]]:
        """并发搜索文件内容（优化版：批量加锁减少锁竞争）

        参数:
            file_paths: 待搜索的文件列表
            regex: 编译后的正则表达式
            max_results: 最大结果数量（默认使用实例的 max_results）
        """
        limit = max_results if max_results is not None else self.max_results
        results: list[tuple[str, int, str, str | None]] = []
        results_lock = threading.Lock()
        stop_event = threading.Event()

        def search_file(file_path: Path) -> list[tuple[str, int, str, str | None]]:
            """搜索单个文件（批量收集结果，减少锁竞争）"""
            if stop_event.is_set():
                return []

            file_results: list[tuple[str, int, str, str | None]] = []
            try:
                content = file_path.read_text(encoding='utf-8', errors='replace')
                rel_path = str(file_path.relative_to(self.base_path))

                # If scope is requested, prepare outline
                outline = None
                if scope:
                    outline = self.extractor.extract(str(file_path), content)

                for line_num, line in enumerate(content.splitlines(), 1):
                    if stop_event.is_set():
                        break
                    if regex.search(line):
                        scope_info = None
                        if outline:
                            enclosing = ScopeDetector.find_enclosing_symbol(outline, line_num)
                            if enclosing:
                                scope_info = f"{enclosing.kind.value} {enclosing.name}"

                        file_results.append((rel_path, line_num, line.strip(), scope_info))
            except (PermissionError, OSError, UnicodeDecodeError):
                pass
            return file_results

        # 使用线程池并发搜索
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(search_file, fp): fp for fp in file_paths}
            for future in as_completed(futures):
                if stop_event.is_set():
                    break
                try:
                    file_results = future.result()
                    if not file_results:
                        continue
                    # 批量加锁：一次性添加所有结果，减少锁竞争
                    with results_lock:
                        remaining = limit - len(results)
                        if remaining <= 0:
                            stop_event.set()
                            break
                        results.extend(file_results[:remaining])
                        if len(results) >= limit:
                            stop_event.set()
                            break
                except Exception as e:
                    fp = futures.get(future, 'unknown')
                    logger.debug(f"GrepTool: future 异常 for {fp}: {e}")

        return results[:limit]
