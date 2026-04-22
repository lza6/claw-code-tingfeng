"""Path utilities for project-level directories

汲取 oh-my-codex-main/src/utils/paths.ts

Provides utilities for resolving application directories:
- State directories
- Config files
- Log directories
- Cache directories
"""

from __future__ import annotations

import os
from pathlib import Path


def get_app_home() -> Path:
    """Get the application home directory

    Priority:
    1. CLAWD_HOME environment variable
    2. ~/.clawd (default)

    Returns:
        Path to the application home directory
    """
    home = os.getenv("CLAWD_HOME")
    if home:
        return Path(home).expanduser().resolve()
    return Path.home() / ".clawd"


def get_state_dir() -> Path:
    """Get the state directory for runtime state"""
    return get_app_home() / "state"


def get_config_path() -> Path:
    """Get the main configuration file path"""
    return get_app_home() / "config.toml"


def get_logs_dir() -> Path:
    """Get the logs directory"""
    return get_app_home() / "logs"


def get_cache_dir() -> Path:
    """Get the cache directory"""
    return get_app_home() / "cache"


def get_skills_dir() -> Path:
    """Get the user skills directory"""
    return get_app_home() / "skills"


def get_prompts_dir() -> Path:
    """Get the user prompts directory"""
    return get_app_home() / "prompts"


def get_agents_dir() -> Path:
    """Get the user agents directory"""
    return get_app_home() / "agents"


def get_project_skills_dir(project_root: Path | None = None) -> Path:
    """Get the project-level skills directory

    Args:
        project_root: Project root directory (defaults to cwd)

    Returns:
        Path to .clawd/skills/ in the project
    """
    root = project_root or Path.cwd()
    return root / ".clawd" / "skills"


def get_project_agents_dir(project_root: Path | None = None) -> Path:
    """Get the project-level agents directory

    Args:
        project_root: Project root directory (defaults to cwd)

    Returns:
        Path to .clawd/agents/ in the project
    """
    root = project_root or Path.cwd()
    return root / ".clawd" / "agents"


def ensure_dir(path: Path) -> None:
    """Ensure a directory exists (create if needed)"""
    path.mkdir(parents=True, exist_ok=True)


def resolve_safe_path(base: Path, *parts: str) -> Path:
    """Safely resolve a path within a base directory

    Prevents path traversal attacks by ensuring the resolved path
    stays within the base directory.

    Args:
        base: Base directory
        parts: Path parts to join

    Returns:
        Resolved Path

    Raises:
        ValueError: If the resolved path escapes the base directory
    """
    target = base.joinpath(*parts).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        raise ValueError(f"Path escapes base directory: {target} -> {base}")
    return target


def get_relative_path(file_path: Path, base: Path) -> Path:
    """Get relative path from base

    Args:
        file_path: Absolute file path
        base: Base directory

    Returns:
        Relative path from base
    """
    return file_path.resolve().relative_to(base.resolve())


def is_path_under(base: Path, target: Path) -> bool:
    """Check if target path is under base directory

    Args:
        base: Base directory
        target: Target path to check

    Returns:
        True if target is under base (or equal)
    """
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False
