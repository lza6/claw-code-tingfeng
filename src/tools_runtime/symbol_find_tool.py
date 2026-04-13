"""SymbolFindTool — Global definition lookup.

Utilizes the SymbolIndex for instant definition discovery across the codebase.
Ported from Project B's codedb_find.
"""
from __future__ import annotations

import logging

from ..core.symbol_index import SymbolIndex
from .base import BaseTool, ParameterSchema, ToolResult

logger = logging.getLogger(__name__)

class SymbolFindTool(BaseTool):
    """Global symbol discovery tool."""

    name = 'SymbolFindTool'
    description = '在全量代码库中查找函数、类或定义的具体位置（O(1) 性能）'

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name='name',
            param_type='str',
            required=True,
            description='符号名称（如函数名或类名）',
            min_length=1,
        ),
    )

    def __init__(self, index: SymbolIndex):
        self.index = index

    def execute(self, **kwargs) -> ToolResult:
        name = kwargs.get('name', '')
        if not name:
            return ToolResult(success=False, output='', error='符号名称不能为空')

        try:
            locations = self.index.find_symbol(name)
            if not locations:
                return ToolResult(success=True, output=f'未找到符号 "{name}" 的定义')

            output = [f'找到符号 "{name}" 的 {len(locations)} 个定义:', '']
            for loc in locations:
                detail = f" ({loc.detail})" if loc.detail else ""
                output.append(f'  - {loc.path}:{loc.line_start}-{loc.line_end} [{loc.kind}]{detail}')

            return ToolResult(success=True, output='\n'.join(output))
        except Exception as e:
            return ToolResult(success=False, output='', error=f'查找失败: {e}')
