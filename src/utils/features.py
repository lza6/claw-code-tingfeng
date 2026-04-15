"""Feature Flag Manager — Clawd Code

Refactored to delegate metadata and defaults to src.core.config.feature_flags
and environment detection to src.utils.env_detector.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..core.config.feature_flags import DEFAULT_FEATURES, DEFAULT_METADATA, FeatureMetadata
from .env_detector import detect_workdir
from .logger import get_logger

logger = get_logger('features')


class FeatureFlagManager:
    """Enhanced Feature Flag Manager with runtime override support."""
    _instance = None

    def __init__(self, workdir: Path | None = None):
        self.workdir = workdir or detect_workdir()
        self._features: dict[str, Any] = DEFAULT_FEATURES.copy()
        self._runtime_overrides: dict[str, Any] = {}
        self._override_sources: dict[str, str] = {}
        self._metadata: dict[str, FeatureMetadata] = DEFAULT_METADATA.copy()
        self._initialized = False
        self._change_callbacks: list[Callable[[str, Any], None]] = []

    @classmethod
    def get_instance(cls, workdir: Path | None = None) -> FeatureFlagManager:
        if cls._instance is None:
            cls._instance = cls(workdir)
        return cls._instance

    def initialize(self, workdir: Path | None = None) -> None:
        if self._initialized:
            return

        if workdir:
            self.workdir = workdir

        config_path = self.workdir / ".clawd" / "features.json"
        if config_path.exists():
            try:
                with open(config_path, encoding='utf-8') as f:
                    file_features = json.load(f)
                    self._features.update(file_features)
                    for key in file_features:
                        self._override_sources[key] = "features.json"
                logger.debug(f"Loaded feature flags from {config_path}")
            except Exception as e:
                logger.warning(f"Failed to load features.json: {e}")
        else:
            self._ensure_config_dir()
            try:
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(DEFAULT_FEATURES, f, indent=2)
                logger.debug(f"Created default features.json at {config_path}")
            except Exception as e:
                logger.warning(f"Failed to create default features.json: {e}")

        self._sync_to_env()
        self._apply_internal_overrides()
        self._initialized = True
        logger.info(f"Feature manager initialized ({len(self._features)} flags)")

    def _ensure_config_dir(self):
        config_dir = self.workdir / ".clawd"
        config_dir.mkdir(parents=True, exist_ok=True)

    def _sync_to_env(self):
        for key, value in self._features.items():
            env_key = f"CLAWD_FEATURE_{key.upper()}"
            if env_key not in os.environ:
                os.environ[env_key] = str(value).lower()

    def _apply_internal_overrides(self):
        overrides_json = os.environ.get("CLAUDE_INTERNAL_FC_OVERRIDES")
        if not overrides_json:
            return

        try:
            overrides = json.loads(overrides_json)
            if isinstance(overrides, dict):
                for key, value in overrides.items():
                    self._features[key] = value
                    self._override_sources[key] = "CLAUDE_INTERNAL_FC_OVERRIDES"
                logger.debug(f"Applied {len(overrides)} internal feature overrides")
        except Exception as e:
            logger.warning(f"Failed to apply internal overrides: {e}")

    def is_enabled(self, feature_name: str) -> bool:
        if feature_name in self._runtime_overrides:
            val = self._runtime_overrides[feature_name]
            return val.get("enabled", True) if isinstance(val, dict) else bool(val)

        overrides_json = os.environ.get("CLAUDE_INTERNAL_FC_OVERRIDES")
        if overrides_json:
            try:
                overrides = json.loads(overrides_json)
                if feature_name in overrides:
                    val = overrides[feature_name]
                    return val.get("enabled", True) if isinstance(val, dict) else bool(val)
            except Exception:
                pass

        env_val = os.environ.get(f"CLAWD_FEATURE_{feature_name.upper()}")
        if env_val is not None:
            return env_val.lower() in ('true', '1', 'yes', 'on')

        val = self._features.get(feature_name, False)
        return val.get("enabled", True) if isinstance(val, dict) else bool(val)

    def get_feature(self, feature_name: str) -> Any:
        if feature_name in self._runtime_overrides:
            return self._runtime_overrides[feature_name]
        return self._features.get(feature_name, False)

    def get_all(self) -> dict[str, Any]:
        result = self._features.copy()
        result.update(self._runtime_overrides)
        return result

    def set_feature(self, name: str, value: Any, persistent: bool = False):
        if persistent:
            self._features[name] = value
            self._override_sources[name] = "features.json"
            self._save_to_file()
        else:
            self._runtime_overrides[name] = value
            self._override_sources[name] = "runtime_set_feature"

        os.environ[f"CLAWD_FEATURE_{name.upper()}"] = str(value).lower()
        for callback in self._change_callbacks:
            try:
                callback(name, value)
            except:
                pass

    def clear_runtime_override(self, name: str) -> None:
        """Clear a runtime feature override."""
        self._runtime_overrides.pop(name, None)
        self._override_sources.pop(name, None)
        env_key = f"CLAWD_FEATURE_{name.upper()}"
        if env_key in os.environ:
            del os.environ[env_key]

    def get_override_report(self) -> dict[str, str]:
        """Get a report of active feature overrides."""
        return self._override_sources.copy()

    def get_features_by_category(self, category: str) -> dict[str, Any]:
        """Get all feature flags in a specific category."""
        all_features = self.get_all()
        return {
            name: val for name, val in all_features.items()
            if self._metadata.get(name) and self._metadata[name].category == category
        }

    def reset_to_defaults(self) -> None:
        """Reset all features to their default values."""
        self._features = DEFAULT_FEATURES.copy()
        self._runtime_overrides.clear()
        self._override_sources.clear()
        # Clean env
        for key in list(os.environ.keys()):
            if key.startswith("CLAWD_FEATURE_"):
                del os.environ[key]
        self._sync_to_env()

    def _save_to_file(self):
        config_path = self.workdir / ".clawd" / "features.json"
        try:
            self._ensure_config_dir()
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(self._features, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save features.json: {e}")

    def get_metadata(self, feature_name: str) -> FeatureMetadata | None:
        return self._metadata.get(feature_name)

    def register_change_callback(self, callback: Callable[[str, Any], None]):
        self._change_callbacks.append(callback)


features = FeatureFlagManager.get_instance()


class FeatureRegistry:
    def __init__(self):
        self._registry: dict[str, dict[str, Any]] = {}

    def register(self, name: str, description: str, category: str = "general",
                 default_value: Any = False, requires_restart: bool = False) -> None:
        self._registry[name] = {
            "description": description, "category": category,
            "default_value": default_value, "requires_restart": requires_restart,
        }

    def is_enabled(self, name: str) -> bool:
        return features.is_enabled(name)

    def register_defaults_from_manager(self, manager: FeatureFlagManager | None = None) -> None:
        if manager is None:
            manager = FeatureFlagManager.get_instance()
        for name, metadata in manager._metadata.items():
            self.register(name, metadata.description, metadata.category,
                          metadata.default_value, metadata.requires_restart)

registry = FeatureRegistry()

__all__ = ["DEFAULT_FEATURES", "FeatureFlagManager", "FeatureMetadata", "FeatureRegistry", "features", "registry"]
