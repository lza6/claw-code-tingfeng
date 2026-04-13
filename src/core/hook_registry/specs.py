"""Hook Specs — Hook 规格定义（借鉴 Onyx hooks/points）

设计目标:
    1. 每个 Hook 点有独立的 Spec 类
    2. Spec 定义输入/输出/执行器
    3. 支持测试时 monkeypatch 覆盖

参考 Onyx HookPointSpec 设计。
"""
from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.core.hook_registry.enums import HookPoint, HookResult
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class HookContext:
    """Hook 执行上下文

    传递给每个 Hook 执行器的上下文信息。
    """
    hook_point: HookPoint
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value


@dataclass
class HookExecutionResult:
    """Hook 执行结果

    包含结果状态和可能的数据修改。
    """
    result: HookResult = HookResult.CONTINUE
    message: str = ""
    modified_data: dict[str, Any] | None = None
    error: Exception | None = None


class HookPointSpec(abc.ABC):
    """Hook 点规格基类（参考 Onyx HookPointSpec）

    每个 Hook 点应继承此类并实现:
    - name: Hook 点名称
    - execute(): 执行 Hook 逻辑
    - validate(): 验证输入数据
    """

    @property
    @abc.abstractmethod
    def hook_point(self) -> HookPoint:
        """返回此 Spec 对应的 Hook 点"""
        raise NotImplementedError

    @property
    def name(self) -> str:
        """Hook 点名称（人类可读）"""
        return self.hook_point.value

    def validate(self, context: HookContext) -> bool:
        """验证输入数据

        Args:
            context: Hook 上下文

        Returns:
            True 如果数据有效
        """
        return True

    @abc.abstractmethod
    def execute(self, context: HookContext) -> HookExecutionResult:
        """执行 Hook 逻辑

        Args:
            context: Hook 上下文

        Returns:
            Hook 执行结果
        """
        raise NotImplementedError

    def on_error(self, error: Exception, context: HookContext) -> HookExecutionResult:
        """错误处理

        Args:
            error: 捕获的异常
            context: Hook 上下文

        Returns:
            默认返回 CONTINUE（不阻断主流程）
        """
        logger.warning(f"Hook {self.name} error: {error}")
        return HookExecutionResult(
            result=HookResult.WARN,
            message=f"Hook error: {error}",
            error=error,
        )


# ---------------------------------------------------------------------------
# 便捷函数式 Hook 类型
# ---------------------------------------------------------------------------

class FunctionHookSpec(HookPointSpec):
    """函数式 Hook 规格

    适用于简单的函数回调场景。
    """

    def __init__(
        self,
        hook_point: HookPoint,
        handler: Callable[[HookContext], HookExecutionResult],
        name: str | None = None,
    ):
        self._hook_point = hook_point
        self._handler = handler
        self._name = name or hook_point.value

    @property
    def hook_point(self) -> HookPoint:
        return self._hook_point

    @property
    def name(self) -> str:
        return self._name

    def execute(self, context: HookContext) -> HookExecutionResult:
        return self._handler(context)


__all__ = [
    "FunctionHookSpec",
    "HookContext",
    "HookExecutionResult",
    "HookPointSpec",
]
