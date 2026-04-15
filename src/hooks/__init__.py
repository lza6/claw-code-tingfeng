"""
Hooks - 钩子系统

导出钩子扩展和路由模块。
"""

from .extensibility import (
    HookEventEnvelope,
    HookDispatchResult,
    dispatch_hook_event,
    is_hook_plugins_enabled,
)

from .prompt_guidance_contract import (
    GuidanceSurfaceContract,
    ROOT_TEMPLATE_CONTRACTS,
    CORE_ROLE_CONTRACTS,
    validate_contract,
)

from .explore_routing import (
    ExploreRoute,
    parse_explore_route,
    suggest_routing_strategy,
)

from .agents_overlay import (
    OverlayLayer,
    AgentOverlay,
    OverlayState,
    AgentsOverlayManager,
    get_overlay_manager,
)

from .codebase_map import (
    FileNode,
    CodebaseMap,
    CodebaseMapper,
)

from .session import (
    SessionState,
    SessionContext,
    SessionMetadata,
    SessionManager,
    get_session_manager,
    # Mode 管理
    EXCLUSIVE_MODES,
    get_deprecation_warning,
    resolve_mode_name,
    set_state_directory,
    get_state_directory,
    get_mode_state_path,
    assert_mode_start_allowed,
)


__all__ = [
    # Extensibility
    "HookEventEnvelope",
    "HookDispatchResult",
    "dispatch_hook_event",
    "is_hook_plugins_enabled",
    # Prompt Guidance
    "GuidanceSurfaceContract",
    "ROOT_TEMPLATE_CONTRACTS",
    "CORE_ROLE_CONTRACTS",
    "validate_contract",
    # Explore Routing
    "ExploreRoute",
    "parse_explore_route",
    "suggest_routing_strategy",
    # Agents Overlay
    "OverlayLayer",
    "AgentOverlay",
    "OverlayState",
    "AgentsOverlayManager",
    "get_overlay_manager",
    # Codebase Map
    "FileNode",
    "CodebaseMap",
    "CodebaseMapper",
    # Session
    "SessionState",
    "SessionContext",
    "SessionMetadata",
    "SessionManager",
    "get_session_manager",
]
