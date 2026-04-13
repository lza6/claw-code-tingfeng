from __future__ import annotations

import logging
from typing import Any

from ..llm.parsers import HeuristicToolParser
from ..tools_runtime.base import BaseTool, ToolResult
from .tool_executor import execute_tool, execute_tools_parallel, parse_tool_calls

logger = logging.getLogger('agent.tool_manager')

class ToolManager:
    """工具管理器 - 负责工具的生命周期、解析与执行"""

    def __init__(self, tools: dict[str, BaseTool]) -> None:
        self.tools = tools
        self._heuristic_parser = HeuristicToolParser()

    def add_tool(self, name: str, tool: BaseTool) -> None:
        self.tools[name] = tool

    def remove_tool(self, name: str) -> None:
        if name in self.tools:
            del self.tools[name]

    def get_available_tools(self) -> dict[str, str]:
        return {name: tool.description for name, tool in self.tools.items()}

    def parse_tool_calls(self, content: str) -> list[tuple[str, dict[str, Any]]]:
        """解析工具调用，支持标准解析与启发式解析"""
        standard_calls = parse_tool_calls(content)
        if standard_calls:
            return standard_calls

        _, heuristic_calls = self._heuristic_parser.feed(content)
        if heuristic_calls:
            return [(c['name'], c['input']) for c in heuristic_calls if c['type'] == 'tool_use']

        return []

    async def execute_tool(self, tool_name: str, tool_args: dict[str, Any]) -> ToolResult:
        return await execute_tool(self.tools, tool_name, tool_args)

    async def execute_tools_parallel(self, tool_calls: list[tuple[str, dict[str, Any]]]) -> list[Any]:
        return await execute_tools_parallel(self.tools, tool_calls)
