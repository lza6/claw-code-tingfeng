"""Backward compatibility wrapper for src.core.config_injector."""
from pathlib import Path

from .config.injector import (
    ConfigChangeEvent,
    ConfigInjector,
    ConfigValue,
    config_injector,
    get_config,
    get_config_injector,
    get_full_config,
    reset_config_injector,
    set_config,
)

__all__ = [
    "ConfigChangeEvent",
    "ConfigInjector",
    "ConfigValue",
    "Path",
    "config_injector",
    "get_config",
    "get_config_injector",
    "get_full_config",
    "reset_config_injector",
    "set_config",
]
