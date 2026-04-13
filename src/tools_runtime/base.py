"""工具基类定义 - 含参数 Schema 校验

借鉴 Onyx 的工具设计:
    - Tool 元数据（分类、版本、作者）
    - ToolCategory 枚举
    - is_enabled 运行时开关
    - get_usage() 使用统计
"""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..core.exceptions import (
    ToolExecutionError,
    ToolInvalidArgsError,
)


class ToolCategory(str, Enum):
    """工具分类枚举（借鉴 Onyx 工具分类）"""
    SEARCH = "search"
    FILE_READER = "file_reader"
    CODE_EDIT = "code_edit"
    SHELL = "shell"
    WEB = "web"
    MEMORY = "memory"
    IMAGE = "image"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    MCP = "mcp"
    CUSTOM = "custom"
    UTILITY = "utility"


@dataclass(frozen=True)
class ToolResult:
    """工具执行结果"""
    success: bool
    output: str
    error: str = ''
    exit_code: int = 0
    execution_time_ms: int = 0  # 执行时间（毫秒）
    metadata: dict[str, Any] = field(default_factory=dict)  # 额外元数据


@dataclass(frozen=True)
class ParameterSchema:
    """工具参数 Schema 定义

    属性:
        name: 参数名称
        param_type: 参数类型 (str, int, float, bool, dict, list)
        required: 是否必填
        description: 参数描述
        default: 默认值
        min_value: 最小值（数值类型）
        max_value: 最大值（数值类型）
        min_length: 最小长度（字符串类型）
        max_length: 最大长度（字符串类型）
        allowed_values: 允许的值列表（枚举类型）
    """
    name: str
    param_type: str  # 'str', 'int', 'float', 'bool', 'dict', 'list'
    required: bool = True
    description: str = ''
    default: Any = None
    min_value: float | None = None
    max_value: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    allowed_values: tuple[Any, ...] | None = None


class BaseTool(ABC):
    """工具基类

    集成结构化异常体系：
    - 参数验证失败 → ToolInvalidArgsError
    - 工具执行失败 → ToolExecutionError
    - 工具超时 → ToolTimeoutError

    借鉴 Onyx 设计:
    - category: 工具分类
    - version: 工具版本
    - is_enabled: 运行时开关
    - _usage_count: 使用统计
    """

    name: str = 'base'
    description: str = 'Base tool'
    category: ToolCategory = ToolCategory.UTILITY
    version: str = "1.0.0"

    # 子类应覆盖此属性定义参数 schema
    parameter_schemas: tuple[ParameterSchema, ...] = ()

    def __init__(self):
        self._is_enabled: bool = True
        self._usage_count: int = 0
        self._last_used: float | None = None

    @property
    def is_enabled(self) -> bool:
        """检查工具是否启用（运行时开关）"""
        return self._is_enabled

    @is_enabled.setter
    def is_enabled(self, value: bool) -> None:
        self._is_enabled = value

    @property
    def usage_count(self) -> int:
        """获取使用次数"""
        return self._usage_count

    @property
    def last_used(self) -> float | None:
        """获取最后使用时间（Unix 时间戳）"""
        return self._last_used

    def get_usage_stats(self) -> dict[str, Any]:
        """获取使用统计信息"""
        return {
            "name": self.name,
            "category": self.category.value,
            "version": self.version,
            "enabled": self._is_enabled,
            "usage_count": self._usage_count,
            "last_used": self._last_used,
        }

    def _increment_usage(self) -> None:
        """增加使用计数"""
        self._usage_count += 1
        self._last_used = time.time()

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """执行工具（同步）

        子类实现时应捕获业务异常并转换为 ToolResult，
        或抛出 ToolExecutionError 子类异常。
        """
        ...

    async def async_execute(self, **kwargs) -> ToolResult:
        """执行工具（异步）

        子类可覆盖此方法提供原生异步实现。
        默认使用 asyncio.to_thread 包装同步 execute。
        """
        return await asyncio.to_thread(self.execute, **kwargs)

    def validate(self, **kwargs) -> tuple[bool, str]:
        """验证参数，返回 (是否有效, 错误信息)

        默认实现会基于 parameter_schemas 进行自动校验。
        子类可覆盖此方法添加额外的业务校验逻辑。
        """
        return self._validate_with_schema(kwargs)

    def _validate_with_schema(self, kwargs: dict[str, Any]) -> tuple[bool, str]:
        """基于 parameter_schemas 自动校验参数

        返回:
            (是否有效, 错误信息)
        """
        if not self.parameter_schemas:
            return True, ''

        for schema in self.parameter_schemas:
            value = kwargs.get(schema.name)

            # 检查必填参数
            if schema.required and (value is None or value == ''):
                if schema.default is not None:
                    kwargs[schema.name] = value = schema.default
                else:
                    return False, f'缺少必填参数: {schema.name}'

            # 如果参数为空，跳过校验
            if value is None:
                continue

            # 类型检查
            if not self._check_type(value, schema.param_type):
                return False, f'参数 {schema.name} 类型错误，期望 {schema.param_type}，实际 {type(value).__name__}'

            # 数值范围检查
            if schema.param_type in ('int', 'float') and isinstance(value, (int, float)) and not isinstance(value, bool):
                if schema.min_value is not None and value < schema.min_value:
                    return False, f'参数 {schema.name} 值过小，最小值: {schema.min_value}'
                if schema.max_value is not None and value > schema.max_value:
                    return False, f'参数 {schema.name} 值过大，最大值: {schema.max_value}'

            # 字符串长度检查
            if schema.param_type == 'str' and isinstance(value, str):
                if schema.min_length is not None and len(value) < schema.min_length:
                    return False, f'参数 {schema.name} 长度过短，最小长度: {schema.min_length}'
                if schema.max_length is not None and len(value) > schema.max_length:
                    return False, f'参数 {schema.name} 长度过长，最大长度: {schema.max_length}'

            # 枚举值检查
            if schema.allowed_values is not None and value not in schema.allowed_values:
                return False, f'参数 {schema.name} 值不在允许范围内: {schema.allowed_values}'

        return True, ''

    @staticmethod
    def _check_type(value: Any, expected_type: str) -> bool:
        """检查值类型是否匹配"""
        type_map = {
            'str': str,
            'int': int,
            'float': (int, float),  # int 可以作为 float 使用
            'bool': bool,
            'dict': dict,
            'list': (list, tuple),
        }
        expected = type_map.get(expected_type)
        if expected is None:
            return True  # 未知类型，跳过检查
        return isinstance(value, expected)

    def execute_safe(self, **kwargs) -> ToolResult:
        """安全执行工具（同步），自动捕获异常并转换为 ToolResult"""
        if not self._is_enabled:
            return ToolResult(
                success=False,
                output='',
                error=f'工具 {self.name} 已禁用',
                exit_code=1,
            )

        start_time = time.time()
        try:
            is_valid, error_msg = self.validate(**kwargs)
            if not is_valid:
                raise ToolInvalidArgsError(tool_name=self.name, reason=error_msg)
            result = self.execute(**kwargs)
            self._increment_usage()
            # 附加执行时间
            elapsed_ms = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=result.success,
                output=result.output,
                error=result.error,
                exit_code=result.exit_code,
                execution_time_ms=elapsed_ms,
            )
        except ToolInvalidArgsError as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return ToolResult(success=False, output='', error=str(e), exit_code=1, execution_time_ms=elapsed_ms)
        except ToolExecutionError as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return ToolResult(success=False, output='', error=str(e), exit_code=1, execution_time_ms=elapsed_ms)
        except TimeoutError:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return ToolResult(success=False, output='', error=f'工具 {self.name} 执行超时', exit_code=124, execution_time_ms=elapsed_ms)
        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=False,
                output='',
                error=f'工具 {self.name} 执行异常: {e}',
                exit_code=1,
                execution_time_ms=elapsed_ms,
            )

    async def async_execute_safe(self, **kwargs) -> ToolResult:
        """安全执行工具（异步），自动捕获异常并转换为 ToolResult"""
        try:
            is_valid, error_msg = self.validate(**kwargs)
            if not is_valid:
                raise ToolInvalidArgsError(tool_name=self.name, reason=error_msg)
            return await self.async_execute(**kwargs)
        except ToolInvalidArgsError as e:
            return ToolResult(success=False, output='', error=str(e), exit_code=1)
        except ToolExecutionError as e:
            return ToolResult(success=False, output='', error=str(e), exit_code=1)
        except TimeoutError:
            return ToolResult(success=False, output='', error=f'工具 {self.name} 执行超时', exit_code=124)
        except asyncio.CancelledError:
            # 任务被取消，返回错误结果后重新抛出以正确传播取消信号
            ToolResult(success=False, output='', error='任务被取消', exit_code=130)
            raise
        except Exception as e:
            return ToolResult(
                success=False,
                output='',
                error=f'工具 {self.name} 执行异常: {e}',
                exit_code=1,
            )
