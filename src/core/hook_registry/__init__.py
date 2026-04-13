"""Hook Registry System — 类型安全的 Hook 注册表系统

借鉴 Onyx 的 Hook 设计:
    - 枚举定义 Hook 点
    - Spec 类定义每个 Hook 的输入/输出/执行器
    - 注册表管理 Hook 注册和校验
    - 启动时校验确保完整性

用法:
    from src.core.hook_registry import HookPoint, register_hook, execute_hook, HookContext

    # 方式 1: 装饰器
    @hook(HookPoint.PRE_LLM_CALL)
    def my_hook(context: HookContext) -> HookExecutionResult:
        return HookExecutionResult(result=HookResult.CONTINUE)

    # 方式 2: 显式注册
    register_hook(HookPoint.PRE_LLM_CALL, MySpec())

    # 执行
    result = execute_hook(HookPoint.PRE_LLM_CALL, context)
"""
from __future__ import annotations

from src.core.hook_registry.enums import HookPoint, HookResult
from src.core.hook_registry.registry import (
    execute_all_hooks,
    execute_hook,
    get_all_specs,
    get_hook_point_spec,
    get_registered_hooks,
    hook,
    on_hook_registered,
    register_hook,
    unregister_hook,
    validate_registry,
)
from src.core.hook_registry.specs import (
    FunctionHookSpec,
    HookContext,
    HookExecutionResult,
    HookPointSpec,
)

__all__ = [
    "FunctionHookSpec",
    "HookContext",
    "HookExecutionResult",
    "HookPoint",
    "HookPointSpec",
    "HookResult",
    "execute_all_hooks",
    "execute_hook",
    "get_all_specs",
    "get_hook_point_spec",
    "get_registered_hooks",
    "hook",
    "on_hook_registered",
    "register_hook",
    "unregister_hook",
    "validate_registry",
]
