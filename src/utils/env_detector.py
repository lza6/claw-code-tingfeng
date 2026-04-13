from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Any


def get_platform_info() -> dict[str, str]:
    """Get basic platform information."""
    return {
        "os": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": sys.version.split()[0],
    }


def is_windows() -> bool:
    """Check if the current platform is Windows."""
    return platform.system() == "Windows"


def is_macos() -> bool:
    """Check if the current platform is macOS."""
    return platform.system() == "Darwin"


def is_linux() -> bool:
    """Check if the current platform is Linux."""
    return platform.system() == "Linux"


def get_env_var(key: str, default: Any = None) -> Any:
    """Get an environment variable with optional default."""
    return os.environ.get(key, default)


def get_boolean_env(key: str, default: bool = False) -> bool:
    """Get a boolean value from an environment variable."""
    val = os.environ.get(key)
    if val is None:
        return default
    return val.lower() in ("true", "1", "yes", "on")


def detect_workdir() -> Path:
    """Detect the working directory, favoring CLAWD_WORKDIR env var."""
    workdir_env = os.environ.get("CLAWD_WORKDIR")
    if workdir_env:
        return Path(workdir_env).resolve()
    return Path.cwd().resolve()
