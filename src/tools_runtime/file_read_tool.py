"""FileReadTool - 安全文件读取工具"""
from __future__ import annotations

import signal
from pathlib import Path
from typing import NoReturn

from .base import BaseTool, ParameterSchema, ToolResult
from .path_utils import BINARY_EXTENSIONS, resolve_path

# 最大文件大小 (5MB)
MAX_FILE_SIZE = 5 * 1024 * 1024


class FileReadTool(BaseTool):
    """安全文件读取工具"""

    name = 'FileReadTool'
    description = '读取文件内容，支持文本文件和代码文件'

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name='file_path',
            param_type='str',
            required=True,
            description='要读取的文件路径',
            min_length=1,
            max_length=500,
        ),
        ParameterSchema(
            name='offset',
            param_type='int',
            required=False,
            description='起始行号（1-based）',
            default=1,
            min_value=1,
            max_value=1000000,
        ),
        ParameterSchema(
            name='limit',
            param_type='int',
            required=False,
            description='最大读取行数',
            default=1000,
            min_value=1,
            max_value=10000,
        ),
    )

    def __init__(self, base_path: Path | None = None, max_lines: int = 1000, timeout: int = 10) -> None:
        self.base_path = base_path or Path.cwd()
        self.max_lines = max_lines
        self.timeout = timeout  # 文件读取超时（秒）

    def validate(self, **kwargs) -> tuple[bool, str]:
        file_path = kwargs.get('file_path', '')
        if not file_path:
            return False, '文件路径不能为空'

        path = self._resolve_path(file_path)
        if path is None:
            return False, f'路径遍历被拒绝: {file_path}'

        if not path.exists():
            return False, f'文件不存在: {path}'

        if path.is_dir():
            return False, f'不能读取目录: {path}'

        if path.suffix.lower() in BINARY_EXTENSIONS:
            return False, f'不支持读取二进制文件: {path.suffix}'

        if path.stat().st_size > MAX_FILE_SIZE:
            return False, f'文件过大 (>5MB): {path.stat().st_size} bytes'

        return True, ''

    def execute(self, **kwargs) -> ToolResult:
        file_path = kwargs.get('file_path', '')
        offset = kwargs.get('offset', 1)  # 1-based 行号
        limit = kwargs.get('limit', self.max_lines)

        is_valid, error_msg = self.validate(file_path=file_path)
        if not is_valid:
            return ToolResult(success=False, output='', error=error_msg, exit_code=1)

        path = self._resolve_path(file_path)
        if path is None:
            return ToolResult(success=False, output='', error='路径遍历被拒绝', exit_code=1)

        try:
            content = self._read_with_timeout(path, self.timeout)
            lines = content.splitlines()

            # 计算行范围
            start = max(0, offset - 1)
            end = min(len(lines), start + limit)
            selected_lines = lines[start:end]

            # 构建带行号的输出
            output_lines = []
            total_lines = len(lines)
            output_lines.append(f'文件: {path}')
            output_lines.append(f'总行数: {total_lines}')
            if total_lines > limit:
                output_lines.append(f'显示: 第 {offset}-{end} 行 (共 {total_lines} 行)')
            output_lines.append('-' * 40)

            for i, line in enumerate(selected_lines, start=start + 1):
                output_lines.append(f'{i:4d} | {line}')

            if end < total_lines:
                output_lines.append(f'... ({total_lines - end} 行未显示)')

            return ToolResult(
                success=True,
                output='\n'.join(output_lines),
            )
        except PermissionError:
            return ToolResult(
                success=False,
                output='',
                error=f'权限不足，无法读取文件: {path}',
                exit_code=1,
            )
        except UnicodeDecodeError:
            return ToolResult(
                success=False,
                output='',
                error=f'文件编码不支持: {path}',
                exit_code=1,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output='',
                error=f'读取错误: {e!s}',
                exit_code=1,
            )

    def _resolve_path(self, file_path: str) -> Path | None:
        """解析文件路径，防止路径遍历攻击"""
        return resolve_path(file_path, self.base_path)

    def _read_with_timeout(self, path: Path, timeout: int) -> str:
        """带超时保护的文件读取

        使用信号机制实现超时控制（仅 Unix）。
        Windows 上使用简单的文件大小检查作为回退。
        """
        import sys

        if sys.platform == 'win32':
            # Windows 不支持 SIGALRM，使用直接读取
            # 文件大小检查已在 validate 中完成
            return path.read_text(encoding='utf-8', errors='replace')

        # Unix 平台：使用 SIGALRM 实现超时
        def timeout_handler(signum, frame) -> NoReturn:
            raise TimeoutError(f'文件读取超时 ({timeout}s)')

        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout)
        try:
            content = path.read_text(encoding='utf-8', errors='replace')
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        return content
