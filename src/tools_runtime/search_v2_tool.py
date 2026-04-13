"""SearchV2Tool — High-performance indexed search.

Utilizes the TrigramIndex for lightning-fast full-text searches.
Ported from Project B's codedb_search.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..core.indexing import TrigramIndex
from .base import BaseTool, ParameterSchema, ToolResult

logger = logging.getLogger(__name__)

class SearchV2Tool(BaseTool):
    """Trigram-accelerated full-text search tool."""

    name = 'SearchV2Tool'
    description = '使用三元组索引进行超快速全量代码搜索（性能优于正则扫描）'

    parameter_schemas: tuple[ParameterSchema, ...] = (
        ParameterSchema(
            name='query',
            param_type='str',
            required=True,
            description='搜索关键词',
            min_length=1,
        ),
        ParameterSchema(
            name='max_results',
            param_type='int',
            required=False,
            description='最大结果数量',
            default=50,
        ),
    )

    def __init__(self, index: TrigramIndex, base_path: Path):
        self.index = index
        self.base_path = base_path

    def execute(self, **kwargs) -> ToolResult:
        query = kwargs.get('query', '')
        max_results = kwargs.get('max_results', 50)

        if not query:
            return ToolResult(success=False, output='', error='搜索关键词不能为空')

        try:
            results = self.index.search(query)
            if not results:
                return ToolResult(success=True, output=f'未找到匹配 "{query}" 的内容')

            results = results[:max_results]
            output = [f'基于索引找到 {len(results)} 个匹配文件:', '']
            for path in results:
                output.append(f'  - {path}')

            return ToolResult(success=True, output='\n'.join(output))
        except Exception as e:
            return ToolResult(success=False, output='', error=f'搜索失败: {e}')
