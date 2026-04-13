"""
工具接口模块 - 整合自 Onyx 的工具系统

提供:
- 工具定义模型
- 工具注册表
- 工具执行器
- 工具构建器
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ToolCallStatus(str, Enum):
    """工具调用状态"""
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    is_local: bool = True
    requires_approval: bool = False
    timeout: int = 30

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "category": self.category,
            "tags": self.tags,
            "is_local": self.is_local,
            "requires_approval": self.requires_approval,
            "timeout": self.timeout,
        }


@dataclass
class ToolResult:
    """工具执行结果"""
    tool_name: str
    status: ToolCallStatus
    output: str | None = None
    error: str | None = None
    duration_ms: float = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "tool_name": self.tool_name,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }

    @property
    def is_success(self) -> bool:
        """是否成功"""
        return self.status == ToolCallStatus.SUCCESS


class BaseTool(ABC):
    """工具基类"""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._definition = ToolDefinition(
            name=name,
            description=description,
        )

    @property
    def definition(self) -> ToolDefinition:
        """获取工具定义"""
        return self._definition

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """执行工具"""
        pass

    def validate_params(self, params: dict[str, Any]) -> tuple[bool, str]:
        """验证参数"""
        return True, ""


class ToolRegistry:
    """工具注册表"""

    _instance: ToolRegistry | None = None
    _tools: dict[str, BaseTool] = {}
    _categories: dict[str, list[str]] = {}

    @classmethod
    def get_instance(cls) -> ToolRegistry:
        """获取实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, tool: BaseTool, category: str | None = None) -> None:
        """注册工具"""
        self._tools[tool.name] = tool
        cat = category or tool.definition.category

        if cat not in self._categories:
            self._categories[cat] = []
        self._categories[cat].append(tool.name)

        logger.debug(f"工具已注册: {tool.name} (category: {cat})")

    def unregister(self, name: str) -> bool:
        """注销工具"""
        tool = self._tools.pop(name, None)
        if tool:
            for cat in self._categories:
                if name in self._categories[cat]:
                    self._categories[cat].remove(name)
            return True
        return False

    def get(self, name: str) -> BaseTool | None:
        """获取工具"""
        return self._tools.get(name)

    def list_tools(self, category: str | None = None) -> list[ToolDefinition]:
        """列出工具"""
        if category:
            names = self._categories.get(category, [])
            return [self._tools[n].definition for n in names if n in self._tools]
        return [t.definition for t in self._tools.values()]

    def list_categories(self) -> list[str]:
        """列出分类"""
        return list(self._categories.keys())

    def get_by_tag(self, tag: str) -> list[ToolDefinition]:
        """按标签获取"""
        return [
            t.definition
            for t in self._tools.values()
            if tag in t.definition.tags
        ]

    def search(self, query: str) -> list[ToolDefinition]:
        """搜索工具"""
        query_lower = query.lower()
        return [
            t.definition
            for t in self._tools.values()
            if query_lower in t.name.lower() or query_lower in t.description.lower()
        ]


class ToolExecutor:
    """工具执行器"""

    def __init__(self, registry: ToolRegistry | None = None):
        self.registry = registry or ToolRegistry.get_instance()

    def execute(
        self,
        tool_name: str,
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> ToolResult:
        """同步执行工具"""
        import time

        tool = self.registry.get(tool_name)
        if not tool:
            return ToolResult(
                tool_name=tool_name,
                status=ToolCallStatus.ERROR,
                error=f"工具不存在: {tool_name}",
            )

        start_time = time.time()
        params = params or {}

        try:
            # 参数验证
            is_valid, error_msg = tool.validate_params(params)
            if not is_valid:
                return ToolResult(
                    tool_name=tool_name,
                    status=ToolCallStatus.ERROR,
                    error=f"参数验证失败: {error_msg}",
                )

            # 执行
            result = tool.execute(**params)

            # 包装结果
            if isinstance(result, str):
                return ToolResult(
                    tool_name=tool_name,
                    status=ToolCallStatus.SUCCESS,
                    output=result,
                    duration_ms=(time.time() - start_time) * 1000,
                )
            elif isinstance(result, ToolResult):
                return result
            else:
                return ToolResult(
                    tool_name=tool_name,
                    status=ToolCallStatus.SUCCESS,
                    output=str(result),
                    duration_ms=(time.time() - start_time) * 1000,
                )

        except Exception as e:
            logger.error(f"工具执行失败: {tool_name}, error: {e}")
            return ToolResult(
                tool_name=tool_name,
                status=ToolCallStatus.ERROR,
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    async def execute_async(
        self,
        tool_name: str,
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> ToolResult:
        """异步执行工具"""
        import asyncio
        import time

        tool = self.registry.get(tool_name)
        if not tool:
            return ToolResult(
                tool_name=tool_name,
                status=ToolCallStatus.ERROR,
                error=f"工具不存在: {tool_name}",
            )

        start_time = time.time()
        params = params or {}

        try:
            # 检查是否是异步方法
            result = tool.execute(**params)

            if asyncio.iscoroutine(result):
                result = await result

            if isinstance(result, str):
                return ToolResult(
                    tool_name=tool_name,
                    status=ToolCallStatus.SUCCESS,
                    output=result,
                    duration_ms=(time.time() - start_time) * 1000,
                )
            elif isinstance(result, ToolResult):
                return result
            else:
                return ToolResult(
                    tool_name=tool_name,
                    status=ToolCallStatus.SUCCESS,
                    output=str(result),
                    duration_ms=(time.time() - start_time) * 1000,
                )

        except Exception as e:
            logger.error(f"工具执行失败: {tool_name}, error: {e}")
            return ToolResult(
                tool_name=tool_name,
                status=ToolCallStatus.ERROR,
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )


# 全局实例
_registry: ToolRegistry | None = None
_executor: ToolExecutor | None = None


def get_tool_registry() -> ToolRegistry:
    """获取工具注册表"""
    global _registry
    if _registry is None:
        _registry = ToolRegistry.get_instance()
    return _registry


def get_tool_executor() -> ToolExecutor:
    """获取工具执行器"""
    global _executor
    if _executor is None:
        _executor = ToolExecutor()
    return _executor


def register_tool(tool: BaseTool, category: str | None = None) -> None:
    """注册工具"""
    get_tool_registry().register(tool, category)


def execute_tool(tool_name: str, params: dict[str, Any] | None = None) -> ToolResult:
    """执行工具"""
    return get_tool_executor().execute(tool_name, params)
