"""Hook Registry — Hook 注册表（借鉴 Onyx hooks/registry.py）

设计目标:
    1. 类型安全的 Hook 注册
    2. 启动时校验（validate_registry 检测缺失的 hook）
    3. 支持测试时 monkeypatch 覆盖
    4. 与现有 hooks.py 兼容（不替换）

参考 Onyx 的 _REGISTRY / validate_registry / get_hook_point_spec 设计。

用法:
    from src.core.hooks.registry import (
        register_hook,
        validate_registry,
        get_hook_point_spec,
    )

    # 注册自定义 Hook
    register_hook(HookPoint.PRE_LLM_CALL, MyPromptSpec())

    # 启动时校验
    validate_registry()

    # 获取并执行
    spec = get_hook_point_spec(HookPoint.PRE_LLM_CALL)
    result = spec.execute(context)
"""
from __future__ import annotations

from collections.abc import Callable

from src.core.hook_registry.enums import HookPoint, HookResult
from src.core.hook_registry.specs import HookContext, HookExecutionResult, HookPointSpec
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 内部注册表（参考 Onyx _REGISTRY）
# ---------------------------------------------------------------------------

#: 一个 Hook 点可以挂**多个**规格（此前是 1:1 字典 + 静默覆盖，
#: 配置里第二个 hook 永远不生效，日志却报 "Loaded N hooks"——2026-10-29 审计 P1-1）
_REGISTRY: dict[HookPoint, list[HookPointSpec]] = {}

# 回调列表（Hook 变更通知）
_change_callbacks: list[Callable[[HookPoint, HookPointSpec], None]] = []


# ---------------------------------------------------------------------------
# 核心 API
# ---------------------------------------------------------------------------

def register_hook(hook_point: HookPoint, spec: HookPointSpec, *, replace: bool = False) -> None:
    """注册 Hook 规格（同一 Hook 点支持多个）

    Args:
        hook_point: Hook 执行点
        spec: Hook 规格实例
        replace: True 时用该规格**替换**该点已有的全部规格；
                 False（默认）追加。同名规格会替换旧的同名项（便于热重载）。

    行为说明（与旧版差异）：旧实现是 1:1 字典，重复注册只打一条 warning 就覆盖，
    导致配置里除最后一个之外的 hook 全部失效（审计 P1-1）。现在改为追加。
    """
    specs = _REGISTRY.setdefault(hook_point, [])
    if replace:
        specs.clear()
    else:
        name = getattr(spec, "name", None)
        if name:
            specs[:] = [existing for existing in specs
                        if getattr(existing, "name", None) != name]

    specs.append(spec)

    # 通知回调
    for callback in _change_callbacks:
        try:
            callback(hook_point, spec)
        except Exception as e:
            logger.warning(f"Hook registration callback failed: {e}")

    logger.debug(f"Registered hook: {hook_point} -> {spec.__class__.__name__}")


def unregister_hook(hook_point: HookPoint) -> bool:
    """注销 Hook 点

    Args:
        hook_point: Hook 执行点

    Returns:
        True 如果成功注销
    """
    if hook_point in _REGISTRY:
        del _REGISTRY[hook_point]
        logger.debug(f"Unregistered hook: {hook_point}")
        return True
    return False


def get_hook_point_spec(hook_point: HookPoint) -> HookPointSpec | None:
    """获取 Hook 点规格

    Args:
        hook_point: Hook 执行点

    Returns:
        HookPointSpec 实例，如果未注册则返回 None

    Raises:
        ValueError: 如果 Hook 点未注册（严格模式）
    """
    specs = _REGISTRY.get(hook_point)
    if not specs:
        return None
    # 返回**最后注册**的规格：与旧版 1:1 语义一致（旧版也是最后一个胜出），
    # 保证既有单 hook 调用方行为不变。要拿全部请用 get_hook_point_specs()。
    return specs[-1]


def get_hook_point_specs(hook_point: HookPoint) -> list[HookPointSpec]:
    """获取某个 Hook 点上的**全部**规格（按注册顺序）"""
    return list(_REGISTRY.get(hook_point, []))


def execute_hook(hook_point: HookPoint, context: HookContext) -> HookExecutionResult:
    """执行 Hook

    Args:
        hook_point: Hook 执行点
        context: Hook 上下文

    Returns:
        Hook 执行结果。如果 Hook 未注册，返回 CONTINUE。
    """
    specs = get_hook_point_specs(hook_point)
    if not specs:
        # Hook 未注册，不阻断流程
        return HookExecutionResult(
            result=HookResult.CONTINUE,
            message=f"No hook registered for {hook_point}",
        )

    # 依次执行该点上的**所有**规格；DENY 立即短路（与 execute_all_hooks 语义一致）
    final = HookExecutionResult(
        result=HookResult.CONTINUE,
        message=f"No hook registered for {hook_point}",
    )
    messages: list[str] = []
    severity = {HookResult.CONTINUE: 0, HookResult.WARN: 1, HookResult.DENY: 2}
    for spec in specs:
        try:
            if not spec.validate(context):
                result = HookExecutionResult(
                    result=HookResult.WARN,
                    message=f"Invalid input for hook {hook_point}",
                )
            else:
                result = spec.execute(context)
        except Exception as error:  # noqa: BLE001 — 单个 hook 出错不阻断主流程
            result = spec.on_error(error, context)

        messages.append(str(getattr(result, "message", "") or ""))
        if severity.get(result.result, 0) >= severity.get(final.result, 0):
            final = result
        if result.result == HookResult.DENY:
            break

    if len(specs) > 1 and messages:
        final = HookExecutionResult(
            result=final.result,
            message=(str(getattr(final, "message", "") or "") + " | 全部: "
                     + " ; ".join(m for m in messages if m))[:1000],
        )
    return final


def execute_all_hooks(
    hook_points: list[HookPoint],
    context: HookContext,
) -> list[HookExecutionResult]:
    """批量执行多个 Hook

    Args:
        hook_points: Hook 点列表
        context: Hook 上下文

    Returns:
        所有 Hook 的执行结果
    """
    results = []
    for hp in hook_points:
        result = execute_hook(hp, context)
        results.append(result)

        # DENY 立即停止
        if result.result == HookResult.DENY:
            break

    return results


def get_all_specs() -> list[HookPointSpec]:
    """获取所有已注册的 Hook 规格（1:N 展开）"""
    out: list[HookPointSpec] = []
    for specs in _REGISTRY.values():
        out.extend(specs)
    return out


def get_registered_hooks() -> dict[HookPoint, HookPointSpec]:
    """获取所有已注册的 Hook（每点取最后注册的一个，兼容旧调用方）"""
    return {hp: specs[-1] for hp, specs in _REGISTRY.items() if specs}


def get_registered_hook_lists() -> dict[HookPoint, list[HookPointSpec]]:
    """获取所有已注册的 Hook（每点**全部**规格的副本）"""
    return {hp: list(specs) for hp, specs in _REGISTRY.items()}


# ---------------------------------------------------------------------------
# 启动时校验（参考 Onyx validate_registry）
# ---------------------------------------------------------------------------

def validate_registry(required_hooks: list[HookPoint] | None = None) -> None:
    """校验注册表完整性

    启动时调用此函数，确保所有必需的 Hook 点都有注册。

    Args:
        required_hooks: 必需的 Hook 点列表。如果为 None，校验所有已定义的 HookPoint。

    Raises:
        RuntimeError: 如果有 Hook 点缺失
    """
    if required_hooks is None:
        # 校验所有 HookPoint 枚举值
        required_hooks = list(HookPoint)

    missing = set(required_hooks) - set(_REGISTRY)
    if missing:
        raise RuntimeError(
            f"Hook point(s) have no registered spec: {missing}. "
            f"Register hooks using register_hook() before startup."
        )

    logger.info(f"Hook registry validated successfully ({len(_REGISTRY)} hooks registered)")


# ---------------------------------------------------------------------------
# 回调注册
# ---------------------------------------------------------------------------

def on_hook_registered(callback: Callable[[HookPoint, HookPointSpec], None]) -> None:
    """注册 Hook 变更回调

    Args:
        callback: 函数(hook_point, spec)
    """
    _change_callbacks.append(callback)


# ---------------------------------------------------------------------------
# 便捷装饰器
# ---------------------------------------------------------------------------

def hook(hook_point: HookPoint):
    """Hook 装饰器 — 将函数注册为 Hook

    用法:
        @hook(HookPoint.PRE_LLM_CALL)
        def my_pre_llm_hook(context: HookContext) -> HookExecutionResult:
            return HookExecutionResult(result=HookResult.CONTINUE)
    """
    def decorator(func: Callable[[HookContext], HookExecutionResult]) -> Callable[[HookContext], HookExecutionResult]:
        from .specs import FunctionHookSpec
        spec = FunctionHookSpec(
            hook_point=hook_point,
            handler=func,
            name=func.__name__,
        )
        register_hook(hook_point, spec)
        return func

    return decorator


__all__ = [
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
