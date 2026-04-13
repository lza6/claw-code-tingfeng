"""GlobTool - 文件模式匹配搜索工具"""
from __future__ import annotations

from pathlib import Path

from ..utils.ignore_parser import get_ignore_filter
from .base import BaseTool, ParameterSchema, ToolResult


class GlobTool(BaseTool):
    """文件模式匹配搜索工具（带超时和深度保护）"""

    name = 'GlobTool'
    description = '使用 glob 模式搜索文件（带深度限制）'

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name='pattern',
            param_type='str',
            required=True,
            description='文件匹配模式（如 *.py）',
            min_length=1,
            max_length=200,
        ),
    )

    # 默认最大目录深度（防止无限递归）
    DEFAULT_MAX_DEPTH = 20
    # 默认最大扫描文件数（防止过大目录）
    DEFAULT_MAX_FILES = 10000

    def __init__(
        self,
        base_path: Path | None = None,
        max_results: int = 100,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> None:
        self.base_path = base_path or Path.cwd()
        self.max_results = max_results
        self.max_depth = max_depth
        self.max_files = max_files
        # 动态忽略解析器 (Ported from Project B)
        self.ignore_filter = get_ignore_filter(self.base_path)

    def validate(self, **kwargs) -> tuple[bool, str]:
        pattern = kwargs.get('pattern', '')
        if not pattern:
            return False, '搜索模式不能为空'
        return True, ''

    def execute(self, **kwargs) -> ToolResult:
        pattern = kwargs.get('pattern', '')

        is_valid, error_msg = self.validate(pattern=pattern)
        if not is_valid:
            return ToolResult(success=False, output='', error=error_msg, exit_code=1)

        try:
            # 使用 pathlib 的 glob 功能
            matches = self._glob_with_limits(f'**/{pattern}')

            # 过滤只返回文件
            file_matches = [m for m in matches if m.is_file()]

            # 限制结果数量
            limited = file_matches[:self.max_results]

            if not limited:
                return ToolResult(success=True, output=f'未找到匹配 "{pattern}" 的文件')

            output_lines = [f'找到 {len(file_matches)} 个匹配文件 (显示 {len(limited)} 个):', '']
            for match in limited:
                rel_path = match.relative_to(self.base_path)
                size = match.stat().st_size
                output_lines.append(f'  {rel_path} ({size:,} bytes)')

            if len(file_matches) > self.max_results:
                output_lines.append(f'\n... 还有 {len(file_matches) - self.max_results} 个文件未显示')

            return ToolResult(success=True, output='\n'.join(output_lines))
        except Exception as e:
            return ToolResult(success=False, output='', error=f'Glob 错误: {e!s}', exit_code=1)

    def _glob_with_limits(self, pattern: str) -> list[Path]:
        """带深度和文件数限制的 glob 搜索"""
        matches: list[Path] = []
        base_resolved = self.base_path.resolve()
        files_scanned = 0

        for path in self.base_path.glob(pattern):
            if files_scanned >= self.max_files:
                break
            files_scanned += 1

            # 检查深度（先 resolve 再计算相对路径）
            try:
                resolved = path.resolve()
                rel = resolved.relative_to(base_resolved)
                if len(rel.parts) > self.max_depth:
                    continue
            except ValueError:
                continue

            # 动态忽略检查 (Ported from Project B)
            if self.ignore_filter.is_ignored(path):
                continue

            if path.is_file():
                matches.append(path)

        return matches
