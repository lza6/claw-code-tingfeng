"""
Hook Extensibility - 钩子扩展系统

从 oh-my-codex-main/src/hooks/extensibility/ 转换而来。
提供插件化钩子系统。
"""

from .types import (
    HookSchemaVersion,
    HookEventSource,
    HookEventName,
    HookEventEnvelope,
    HookPluginDescriptor,
    HookPluginLogContext,
    HookPluginTmuxSendKeysOptions,
    HookPluginTmuxSendKeysResult,
    HookPluginOmxSessionState,
    HookPluginOmxHudState,
    HookPluginOmxNotifyFallbackState,
    HookPluginOmxUpdateCheckState,
    HookPluginDispatchStatus,
    HookPluginDispatchResult,
    HookDispatchResult,
    HookDispatchOptions,
    HookValidateOptions,
    HookRuntimeDispatchInput,
    HookRuntimeDispatchResult,
)

from .loader import (
    HOOK_PLUGIN_ENABLE_ENV,
    HOOK_PLUGIN_TIMEOUT_ENV,
    hooks_dir,
    is_hook_plugins_enabled,
    resolve_hook_plugin_timeout_ms,
    ensure_hooks_dir,
    validate_plugin_export,
    validate_hook_plugin_export,
    HookPluginDescriptor as HookPluginDescriptor,
    discover_hook_plugins,
    load_hook_plugin_descriptors,
)

from .dispatcher import (
    dispatch_hook_event,
    is_hook_plugin_feature_enabled,
    should_force_enable_runtime_hook_dispatch,
    HookDispatchResult,
)

from .runtime import (
    dispatch_hook_event_runtime,
)

from .sdk import (
    create_hook_plugin_sdk,
    clear_hook_plugin_state,
)


__all__ = [
    # Types
    "HookSchemaVersion",
    "HookEventSource",
    "HookEventName",
    "HookEventEnvelope",
    "HookPluginDescriptor",
    "HookPluginLogContext",
    "HookPluginTmuxSendKeysOptions",
    "HookPluginTmuxSendKeysResult",
    "HookPluginOmxSessionState",
    "HookPluginOmxHudState",
    "HookPluginOmxNotifyFallbackState",
    "HookPluginOmxUpdateCheckState",
    "HookPluginDispatchStatus",
    "HookPluginDispatchResult",
    "HookDispatchResult",
    "HookDispatchOptions",
    "HookValidateOptions",
    "HookRuntimeDispatchInput",
    "HookRuntimeDispatchResult",
    # Loader
    "HOOK_PLUGIN_ENABLE_ENV",
    "HOOK_PLUGIN_TIMEOUT_ENV",
    "hooks_dir",
    "is_hook_plugins_enabled",
    "resolve_hook_plugin_timeout_ms",
    "ensure_hooks_dir",
    "validate_plugin_export",
    "validate_hook_plugin_export",
    "discover_hook_plugins",
    "load_hook_plugin_descriptors",
    # Dispatcher
    "dispatch_hook_event",
    "is_hook_plugin_feature_enabled",
    "should_force_enable_runtime_hook_dispatch",
    # Runtime
    "dispatch_hook_event_runtime",
    # SDK
    "create_hook_plugin_sdk",
    "clear_hook_plugin_state",
]
