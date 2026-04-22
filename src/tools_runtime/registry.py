"""Tool Registry - 工具注册中心

从 RTK 和 claude-code-rust-master 汲取的架构优点:
- 统一的工具注册、发现、执行接口
- 工具元数据管理
- 工具执行统计 + token 用量追踪 (RTK 风格)
- token 节省报告

使用方式:
    from src.tools_runtime.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register(BashTool())
    result = await registry.execute("bash", {"command": "ls"})
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from .base import BaseTool, ToolResult

if TYPE_CHECKING:
    pass


class ToolRegistry:
    """工具注册中心

    负责管理所有工具的注册、发现、执行。

    功能:
    - 注册工具
    - 注销工具
    - 执行工具
    - 工具列表查询
    - 执行统计

    使用方式:
        registry = ToolRegistry()
        registry.register(BashTool())
        result = registry.execute("bash", {"command": "ls"})
    """
    def __init__(self):
        """Initialize ToolRegistry"""
        self._tools: dict[str, BaseTool] = {}
        self._execution_count: dict[str, int] = {}
        self._execution_times: dict[str, list[float]] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance"""
        self._tools[tool.name] = tool
        self._execution_count[tool.name] = 0
        self._execution_times[tool.name] = []

    def register_advanced_tools(self, t_index, s_index, workdir):
        """Register the new advanced tools from Project B integration."""
        from .ast_grep_tool import ASTGrepTool
        from .search_v2_tool import SearchV2Tool
        from .symbol_find_tool import SymbolFindTool

        self.register(SearchV2Tool(t_index, workdir))
        self.register(SymbolFindTool(s_index))
        self.register(ASTGrepTool(workdir))

    def unregister(self, name: str) -> BaseTool | None:
        """注销工具

        Args:
            name: 工具名称

        Returns:
            被注销的工具,如果不存在则返回 None
        """
        tool = self._tools.pop(name, None)
        self._execution_count.pop(name, None)
        self._execution_times.pop(name, None)
        return tool

    def get(self, name: str) -> BaseTool | None:
        """获取工具

        Args:
            name: 工具名称

        Returns:
            工具实例,如果不存在则返回 None
        """
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """检查工具是否存在

        Args:
            name: 工具名称

        Returns:
            是否存在
        """
        return name in self._tools

    def list_tools(self) -> list[BaseTool]:
        """列出所有工具

        Returns:
            工具列表
        """
        return list(self._tools.values())

    def get_tool_names(self) -> list[str]:
        """获取所有工具名称

        Returns:
            工具名称列表
        """
        return list(self._tools.keys())

    def execute(self, name: str, **kwargs) -> ToolResult:
        """执行工具

        Args:
            name: 工具名称
            **kwargs: 工具参数

        Returns:
            执行结果

        Raises:
            ValueError: 工具不存在
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                success=False,
                output="",
                error=f"工具不存在: {name}",
                exit_code=1,
            )

        start_time = time.time()
        try:
            result = tool.execute_safe(**kwargs)
            return result
        finally:
            elapsed = time.time() - start_time
            self._execution_count[name] = self._execution_count.get(name, 0) + 1
            times = self._execution_times.setdefault(name, [])
            times.append(elapsed)
            # 防止内存泄漏：最多保留最近 1000 次执行时间
            if len(times) > 1000:
                self._execution_times[name] = times[-1000:]

    def get_stats(self) -> dict[str, Any]:
        """获取工具执行统计

        Returns:
            统计信息字典
        """
        stats = {
            "total_tools": len(self._tools),
            "tools": {},
        }

        for name in self._tools:
            count = self._execution_count.get(name, 0)
            times = self._execution_times.get(name, [])
            avg_time = sum(times) / len(times) if times else 0.0

            stats["tools"][name] = {
                "execution_count": count,
                "avg_execution_time": avg_time,
                "total_execution_time": sum(times),
            }

        return stats

    def reset_stats(self) -> None:
        """重置统计信息"""
        self._execution_count = {name: 0 for name in self._tools}
        self._execution_times = {name: [] for name in self._tools}

    def get_tool_info(self, name: str) -> dict[str, Any] | None:
        """获取工具信息

        Args:
            name: 工具名称

        Returns:
            工具信息字典,如果不存在则返回 None
        """
        tool = self._tools.get(name)
        if tool is None:
            return None

        return {
            "name": tool.name,
            "description": getattr(tool, 'description', ''),
            "parameter_schemas": [
                {
                    "name": s.name,
                    "type": s.param_type,
                    "required": s.required,
                    "description": s.description,
                }
                for s in getattr(tool, 'parameter_schemas', ())
            ],
        }

    def list_tool_info(self) -> list[dict[str, Any]]:
        """列出所有工具信息

        Returns:
            工具信息列表
        """
        result: list[dict[str, Any]] = []
        for name in self._tools:
            info = self.get_tool_info(name)
            if info is not None:
                result.append(info)
        return result

    def get_token_report(self, days: int = 30) -> str:
        """Generate a text report of token usage (RTK style)"""
        tracker = self._get_tracker()
        if tracker is None:
            return "(token tracking not available)"
        return tracker.get_report(days=days)

    # -- Internal helpers --

    def _get_tracker(self):
        """Lazy load token tracker"""
        try:
            from ..core.token_tracker import TokenTracker
            tracker = TokenTracker()
            tracker.init()
            return tracker
        except Exception:
            return None
