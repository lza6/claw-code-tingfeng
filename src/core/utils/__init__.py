"""Core Utilities Package

Provides common utility functions for path handling, platform commands,
JSON parsing, and other cross-cutting concerns.
"""

from .paths import (
    codex_agents_dir,
    codex_config_path,
    codex_home,
    codex_prompts_dir,
    ensure_dir,
    ensure_omx_dirs,
    find_project_root,
    omx_logs_dir,
    omx_notepad_path,
    omx_plans_dir,
    omx_project_memory_path,
    omx_state_dir,
    package_root,
    project_codex_agents_dir,
    project_skills_dir,
    user_skills_dir,
)
from .platform_command import (
    PlatformCommandSpec,
    ProbedPlatformCommand,
    SpawnErrorKind,
    build_platform_command_spec,
    classify_spawn_error,
    is_command_available,
    probe_platform_command,
    resolve_command_path_for_platform,
    run_command,
    run_command_check,
    spawn_platform_command_async,
    spawn_platform_command_sync,
    which,
)
from .safe_json import (
    SafeJSONEncoder,
    safe_json_dump,
    safe_json_loads,
    safe_json_parse,
    safe_json_parse_with_type,
)
from .sleep import Sleeper, sleep, sleep_sync, sleep_until, sleep_with_progress

__all__ = [
    # Agents MD
    "AgentDefinition",
    # Agents Model Table
    "PlatformCommandSpec",
    "ProbedPlatformCommand",
    "SafeJSONEncoder",
    "Sleeper",
    # Platform command
    "SpawnErrorKind",
    "add_generated_agents_marker",
    "build_platform_command_spec",
    "classify_spawn_error",
    "codex_agents_dir",
    "codex_config_path",
    # Paths
    "codex_home",
    "codex_prompts_dir",
    "ensure_dir",
    "ensure_omx_dirs",
    "find_project_root",
    "format_agent_md",
    "get_agent_model_table",
    "get_default_agents",
    "is_command_available",
    "omx_logs_dir",
    "omx_notepad_path",
    "omx_plans_dir",
    "omx_project_memory_path",
    "omx_state_dir",
    "package_root",
    "probe_platform_command",
    "project_codex_agents_dir",
    "project_skills_dir",
    "resolve_command_path_for_platform",
    "run_command",
    "run_command_check",
    "safe_json_dump",
    "safe_json_loads",
    # Safe JSON
    "safe_json_parse",
    "safe_json_parse_with_type",
    # Sleep
    "sleep",
    "sleep_sync",
    "sleep_until",
    "sleep_with_progress",
    "spawn_platform_command_async",
    "spawn_platform_command_sync",
    "user_skills_dir",
    "which",
]
