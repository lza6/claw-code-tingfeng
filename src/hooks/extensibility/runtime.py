"""
.. note:: **参考快照，不接线（ADR 0019）**

    本模块移植自 oh-my-codex，当前**没有任何生产调用点**（`scripts/reachability.py`
    列为不可达）。仓库里与之对应的活实现见 `docs/adr/0019` 的对位表；
    真正生效的 Hook 系统是 `src/core/hook_registry/`（引擎已接线）。
    **不要在这里新增功能**，否则会造出第二套真相源。

Hook Runtime - 钩子运行时调度

从 oh-my-codex-main/src/hooks/extensibility/runtime.ts 转换而来。
提供运行时钩子事件调度功能。
"""

import os

from .dispatcher import dispatch_hook_event
from .loader import is_hook_plugins_enabled
from .types import HookDispatchResult, HookRuntimeDispatchInput, HookRuntimeDispatchResult


async def dispatch_hook_event_runtime(
    input_data: HookRuntimeDispatchInput,
) -> HookRuntimeDispatchResult:
    """运行时调度钩子事件"""
    enabled = (
        input_data.event.source in ("native", "derived")
        or is_hook_plugins_enabled(os.environ)
    )

    if not enabled:
        return HookRuntimeDispatchResult(
            dispatched=False,
            reason="plugins_disabled",
            result=HookDispatchResult(
                enabled=False,
                reason="disabled",
                event=input_data.event.event,
                source=input_data.event.source,
                plugin_count=0,
                results=[],
            ),
        )

    result = await dispatch_hook_event(
        input_data.event,
        cwd=input_data.cwd,
        allow_team_worker_side_effects=input_data.allow_team_worker_side_effects,
        enabled=enabled,
    )

    return HookRuntimeDispatchResult(
        dispatched=True,
        reason="ok",
        result=result,
    )


# ===== 导出 =====
__all__ = [
    "dispatch_hook_event_runtime",
]
