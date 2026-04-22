"""
Hooks - 钩子系统

导出钩子扩展和路由模块。
"""

from .agents_overlay import (
    AgentOverlay,
    AgentsOverlayManager,
    OverlayLayer,
    OverlayState,
    get_overlay_manager,
)
from .codebase_map import (
    CodebaseMap,
    CodebaseMapper,
    FileNode,
)
from .explore_routing import (
    ExploreRoute,
    parse_explore_route,
    suggest_routing_strategy,
)
from .extensibility import (
    HookDispatchResult,
    HookEventEnvelope,
    dispatch_hook_event,
    is_hook_plugins_enabled,
)
from .prompt_guidance_contract import (
    CORE_ROLE_CONTRACTS,
    ROOT_TEMPLATE_CONTRACTS,
    GuidanceSurfaceContract,
    validate_contract,
)
from .session import (
    # Mode 管理
    EXCLUSIVE_MODES,
    SessionContext,
    SessionManager,
    SessionMetadata,
    SessionState,
    assert_mode_start_allowed,
    get_deprecation_warning,
    get_mode_state_path,
    get_session_manager,
    get_state_directory,
    resolve_mode_name,
    set_state_directory,
)

__all__ = [
    # Prompt Guidance
    "CORE_ROLE_CONTRACTS",
    "ROOT_TEMPLATE_CONTRACTS",
    # Agents Overlay
    "AgentOverlay",
    "AgentsOverlayManager",
    # Codebase Map
    "CodebaseMap",
    "CodebaseMapper",
    # Explore Routing
    "ExploreRoute",
    "FileNode",
    "GuidanceSurfaceContract",
    # Extensibility
    "HookDispatchResult",
    "HookEventEnvelope",
    "OverlayLayer",
    "OverlayState",
    # Session
    "SessionContext",
    "SessionManager",
    "SessionMetadata",
    "SessionState",
    "dispatch_hook_event",
    "get_overlay_manager",
    "get_session_manager",
    "is_hook_plugins_enabled",
    "parse_explore_route",
    "suggest_routing_strategy",
    "validate_contract",
]
