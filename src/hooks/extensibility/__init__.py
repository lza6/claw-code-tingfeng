"""
.. note:: **参考快照，不接线（ADR 0019）**

    本模块移植自 oh-my-codex，当前**没有任何生产调用点**（`scripts/reachability.py`
    列为不可达）。仓库里与之对应的活实现见 `docs/adr/0019` 的对位表；
    真正生效的 Hook 系统是 `src/core/hook_registry/`（引擎已接线）。
    **不要在这里新增功能**，否则会造出第二套真相源。

Hook Extensibility - 钩子扩展系统

从 oh-my-codex-main/src/hooks/extensibility/ 转换而来。
提供插件化钩子系统。
"""

from .dispatcher import (
    dispatch_hook_event,
    is_hook_plugin_feature_enabled,
    should_force_enable_runtime_hook_dispatch,
)
from .loader import (
    HOOK_PLUGIN_ENABLE_ENV,
    HOOK_PLUGIN_TIMEOUT_ENV,
    discover_hook_plugins,
    ensure_hooks_dir,
    hooks_dir,
    is_hook_plugins_enabled,
    load_hook_plugin_descriptors,
    resolve_hook_plugin_timeout_ms,
    validate_hook_plugin_export,
    validate_plugin_export,
)
from .runtime import dispatch_hook_event_runtime
from .sdk import clear_hook_plugin_state, create_hook_plugin_sdk
from .types import (
    HookDispatchOptions,
    HookDispatchResult,
    HookEventEnvelope,
    HookEventName,
    HookEventSource,
    HookPluginDescriptor,
    HookPluginDispatchResult,
    HookPluginDispatchStatus,
    HookPluginLogContext,
    HookPluginOmxHudState,
    HookPluginOmxNotifyFallbackState,
    HookPluginOmxSessionState,
    HookPluginOmxUpdateCheckState,
    HookPluginTmuxSendKeysOptions,
    HookPluginTmuxSendKeysResult,
    HookRuntimeDispatchInput,
    HookRuntimeDispatchResult,
    HookSchemaVersion,
    HookValidateOptions,
)

__all__ = [
    # Loader
    "HOOK_PLUGIN_ENABLE_ENV",
    "HOOK_PLUGIN_TIMEOUT_ENV",
    "HookDispatchOptions",
    "HookDispatchResult",
    "HookEventEnvelope",
    "HookEventName",
    "HookEventSource",
    "HookPluginDescriptor",
    "HookPluginDispatchResult",
    "HookPluginDispatchStatus",
    "HookPluginLogContext",
    "HookPluginOmxHudState",
    "HookPluginOmxNotifyFallbackState",
    "HookPluginOmxSessionState",
    "HookPluginOmxUpdateCheckState",
    "HookPluginTmuxSendKeysOptions",
    "HookPluginTmuxSendKeysResult",
    "HookRuntimeDispatchInput",
    "HookRuntimeDispatchResult",
    # Types
    "HookSchemaVersion",
    "HookValidateOptions",
    "clear_hook_plugin_state",
    # SDK
    "create_hook_plugin_sdk",
    "discover_hook_plugins",
    # Dispatcher
    "dispatch_hook_event",
    # Runtime
    "dispatch_hook_event_runtime",
    "ensure_hooks_dir",
    "hooks_dir",
    "is_hook_plugin_feature_enabled",
    "is_hook_plugins_enabled",
    "load_hook_plugin_descriptors",
    "resolve_hook_plugin_timeout_ms",
    "should_force_enable_runtime_hook_dispatch",
    "validate_hook_plugin_export",
    "validate_plugin_export",
]
