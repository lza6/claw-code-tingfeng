"""FileEditTool - 安全文件编辑工具"""
from __future__ import annotations

from pathlib import Path

from .base import BaseTool, ParameterSchema, ToolResult
from .path_utils import resolve_path


class FileEditTool(BaseTool):
    """安全文件编辑工具 - 支持写入和编辑文件"""

    name = 'FileEditTool'
    description = '写入或编辑文件内容'

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name='file_path',
            param_type='str',
            required=True,
            description='要写入的文件路径',
            min_length=1,
            max_length=500,
        ),
        ParameterSchema(
            name='content',
            param_type='str',
            required=True,
            description='要写入的文件内容',
            min_length=0,
            max_length=500000,  # 500KB 限制
        ),
        ParameterSchema(
            name='mode',
            param_type='str',
            required=False,
            description='写入模式: write(覆盖) 或 append(追加)',
            default='write',
            allowed_values=('write', 'append'),
        ),
        ParameterSchema(
            name='start_line',
            param_type='int',
            required=False,
            description='编辑起始行（1-indexed）。如果不提供，则执行全文件写入。',
        ),
        ParameterSchema(
            name='end_line',
            param_type='int',
            required=False,
            description='编辑结束行（含）。如果仅提供 start_line，则默认为替换单行。',
        ),
    )

    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path or Path.cwd()

    def validate(self, **kwargs) -> tuple[bool, str]:
        file_path = kwargs.get('file_path', '')
        content = kwargs.get('content')

        if not file_path:
            return False, '文件路径不能为空'

        if content is None:
            return False, '内容不能为空'

        path = self._resolve_path(file_path)
        if path is None:
            return False, f'路径遍历被拒绝: {file_path}'

        # 检查是否在 base_path 下
        if not path.is_relative_to(self.base_path.resolve()):
            return False, f'文件路径超出允许范围: {path}'

        return True, ''

    def execute(self, **kwargs) -> ToolResult:
        file_path = kwargs.get('file_path', '')
        content = kwargs.get('content', '')
        mode = kwargs.get('mode', 'write')
        start_line = kwargs.get('start_line')
        end_line = kwargs.get('end_line')

        is_valid, error_msg = self.validate(file_path=file_path, content=content)
        if not is_valid:
            return ToolResult(success=False, output='', error=error_msg, exit_code=1)

        path = self._resolve_path(file_path)
        if path is None:
            return ToolResult(success=False, output='', error='路径遍历被拒绝', exit_code=1)

        from ..utils.file_ops import apply_line_edit, atomic_write

        try:
            # 确保父目录存在
            path.parent.mkdir(parents=True, exist_ok=True)

            if start_line is not None:
                # Range edit mode (Ported from Codedb)
                end_line = end_line if end_line is not None else start_line
                apply_line_edit(path, start_line, end_line, content)
                return ToolResult(success=True, output=f'文件范围已更新 [{start_line}:{end_line}]: {path}')

            if mode == 'append':
                # Atomic append
                existing = ""
                if path.exists():
                    existing = path.read_text(encoding='utf-8', errors='replace')
                atomic_write(path, existing + content)
                return ToolResult(success=True, output=f'内容已原子追加到: {path}')
            else:
                # Atomic write
                atomic_write(path, content)
                return ToolResult(success=True, output=f'文件已原子写入: {path} ({len(content)} 字符)')
        except PermissionError:
            return ToolResult(success=False, output='', error=f'权限不足: {path}', exit_code=1)
        except Exception as e:
            return ToolResult(success=False, output='', error=f'写入错误: {e!s}', exit_code=1)

    def _resolve_path(self, file_path: str) -> Path | None:
        """解析文件路径，防止路径遍历攻击"""
        return resolve_path(file_path, self.base_path)
