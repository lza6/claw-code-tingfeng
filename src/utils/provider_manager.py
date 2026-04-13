"""Multi-Provider Configuration Manager

Inspired by Project B (ClawGod)'s provider.json system.
Provides a simple, unified way to manage multiple API endpoints,
models, and authentication across different LLM providers.

Architecture:
    ~/.clawd/provider.json — Global provider configuration
    {
        "apiKey": "sk-...",
        "baseURL": "https://api.openai.com",
        "model": "gpt-4",
        "smallModel": "gpt-3.5-turbo",
        "timeoutMs": 3000000,
        "providers": {
            "openai": { ... },
            "anthropic": { ... },
            "custom": { ... }
        }
    }

This simplifies multi-provider switching compared to A's scattered env vars.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .logger import get_logger

logger = get_logger('provider')


@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider endpoint."""
    api_key: str = ""
    base_url: str = "https://api.anthropic.com"
    model: str = ""
    small_model: str = ""
    timeout_ms: int = 3000000  # 50 minutes (ClawGod standard)

    def to_env_injection(self) -> dict[str, str]:
        """Convert to environment variable injections (ClawGod style).

        Sets both ClawGod-compatible and Clawd-specific env vars.
        """
        env_vars = {}
        if self.api_key:
            env_vars["CLAWD_API_KEY"] = self.api_key
            env_vars["CLAWD_LLM_API_KEY"] = self.api_key
            # ClawGod 兼容: 也设置 Anthropic/OpenAI 标准变量
            if "anthropic" in self.base_url.lower():
                env_vars.setdefault("ANTHROPIC_API_KEY", self.api_key)
            elif "openai" in self.base_url.lower():
                env_vars.setdefault("OPENAI_API_KEY", self.api_key)
        if self.base_url and self.base_url != "https://api.anthropic.com":
            env_vars["CLAWD_BASE_URL"] = self.base_url
            env_vars["CLAWD_LLM_BASE_URL"] = self.base_url
            # ClawGod 兼容
            if "anthropic" in self.base_url.lower():
                env_vars.setdefault("ANTHROPIC_BASE_URL", self.base_url)
        if self.model:
            env_vars["CLAWD_MODEL"] = self.model
            env_vars["CLAWD_LLM_MODEL"] = self.model
        if self.small_model:
            env_vars["CLAWD_SMALL_MODEL"] = self.small_model
            env_vars["ANTHROPIC_SMALL_FAST_MODEL"] = self.small_model
        if self.timeout_ms:
            env_vars["CLAWD_TIMEOUT_MS"] = str(self.timeout_ms)
            env_vars["API_TIMEOUT_MS"] = str(self.timeout_ms)
        return env_vars


@dataclass
class MultiProviderConfig:
    """Multi-provider configuration container."""
    api_key: str = ""
    base_url: str = "https://api.anthropic.com"
    model: str = ""
    small_model: str = ""
    timeout_ms: int = 3000000  # 50 minutes (ClawGod standard)
    providers: dict[str, ProviderConfig] = field(default_factory=dict)

    def get_provider(self, name: str) -> ProviderConfig | None:
        """Get a specific provider configuration."""
        return self.providers.get(name)

    def add_provider(self, name: str, config: ProviderConfig):
        """Add a named provider configuration."""
        self.providers[name] = config

    def switch_to_provider(self, name: str) -> dict[str, str] | None:
        """Switch to a named provider and return env vars to inject."""
        provider = self.get_provider(name)
        if not provider:
            logger.warning(f"Provider '{name}' not found")
            return None
        return provider.to_env_injection()


class ProviderManager:
    """Manager for multi-provider configuration.

    Inspired by Project B's provider.json system.
    Provides simple, unified API endpoint management.

    Usage:
        manager = ProviderManager()
        manager.initialize()
        env_vars = manager.switch_to_provider("openai")
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._config = MultiProviderConfig()
            cls._instance._config_path: Path | None = None
            cls._instance._initialized = False
        return cls._instance

    def initialize(self, workdir: Path | None = None) -> None:
        """Initialize provider configuration from ~/.clawd/provider.json."""
        if self._initialized:
            return

        base_dir = workdir or Path.home()
        self._config_path = base_dir / ".clawd" / "provider.json"

        if self._config_path.exists():
            try:
                self._load_config()
                logger.debug(f"Loaded provider config from {self._config_path}")
            except Exception as e:
                logger.warning(f"Failed to load provider.json: {e}")
        else:
            self._create_default_config()

        # Inject environment variables (ClawGod style)
        self._inject_env_vars()

        self._initialized = True
        logger.info("Provider manager initialized")

    def _load_config(self):
        """Load configuration from provider.json."""
        with open(self._config_path, encoding='utf-8') as f:
            data = json.load(f)

        # Parse top-level fields
        self._config = MultiProviderConfig(
            api_key=data.get("apiKey", ""),
            base_url=data.get("baseURL", "https://api.anthropic.com"),
            model=data.get("model", ""),
            small_model=data.get("smallModel", ""),
            timeout_ms=data.get("timeoutMs", 3000000),
        )

        # Parse named providers
        if "providers" in data and isinstance(data["providers"], dict):
            for name, provider_data in data["providers"].items():
                provider = ProviderConfig(
                    api_key=provider_data.get("apiKey", ""),
                    base_url=provider_data.get("baseURL", "https://api.anthropic.com"),
                    model=provider_data.get("model", ""),
                    small_model=provider_data.get("smallModel", ""),
                    timeout_ms=provider_data.get("timeoutMs", 3000000),
                )
                self._config.add_provider(name, provider)

    def _create_default_config(self):
        """Create a default provider.json file."""
        if not self._config_path:
            return

        self._config_path.parent.mkdir(parents=True, exist_ok=True)

        default_data = {
            "apiKey": "",
            "baseURL": "https://api.anthropic.com",
            "model": "",
            "smallModel": "",
            "timeoutMs": 3000000,
            "providers": {
                "openai": {
                    "apiKey": "",
                    "baseURL": "https://api.openai.com",
                    "model": "gpt-4",
                    "smallModel": "gpt-3.5-turbo",
                    "timeoutMs": 3000000,
                },
                "anthropic": {
                    "apiKey": "",
                    "baseURL": "https://api.anthropic.com",
                    "model": "claude-3-5-sonnet",
                    "smallModel": "claude-3-haiku",
                    "timeoutMs": 3000000,
                },
            }
        }

        try:
            with open(self._config_path, 'w', encoding='utf-8') as f:
                json.dump(default_data, f, indent=2)
            logger.debug(f"Created default provider.json at {self._config_path}")
        except Exception as e:
            logger.warning(f"Failed to create default provider.json: {e}")

    def _inject_env_vars(self):
        """Inject configuration into environment variables (ClawGod style)."""
        # Inject top-level config as default
        if self._config.api_key:
            os.environ.setdefault("CLAWD_LLM_API_KEY", self._config.api_key)
        if self._config.base_url and self._config.base_url != "https://api.anthropic.com":
            os.environ.setdefault("CLAWD_LLM_BASE_URL", self._config.base_url)
        if self._config.model:
            os.environ.setdefault("CLAWD_LLM_MODEL", self._config.model)
        if self._config.small_model:
            os.environ.setdefault("CLAWD_SMALL_MODEL", self._config.small_model)

    def switch_provider(self, name: str) -> bool:
        """Switch to a named provider and inject env vars."""
        provider = self._config.get_provider(name)
        if not provider:
            logger.warning(f"Provider '{name}' not found")
            return False

        env_vars = provider.to_env_injection()
        for key, value in env_vars.items():
            os.environ[key] = value

        logger.info(f"Switched to provider: {name}")
        return True

    def get_config(self) -> MultiProviderConfig:
        """Get the current configuration."""
        return self._config

    def save_config(self) -> bool:
        """Save configuration to provider.json."""
        if not self._config_path:
            return False

        try:
            data = {
                "apiKey": self._config.api_key,
                "baseURL": self._config.base_url,
                "model": self._config.model,
                "smallModel": self._config.small_model,
                "timeoutMs": self._config.timeout_ms,
                "providers": {
                    name: {
                        "apiKey": p.api_key,
                        "baseURL": p.base_url,
                        "model": p.model,
                        "smallModel": p.small_model,
                        "timeoutMs": p.timeout_ms,
                    }
                    for name, p in self._config.providers.items()
                }
            }

            with open(self._config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved provider config to {self._config_path}")
            return True
        except Exception as e:
            logger.warning(f"Failed to save provider.json: {e}")
            return False


# Global singleton
provider_manager = ProviderManager()
