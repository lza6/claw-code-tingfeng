"""OpenClaw Configuration Reader.

Reads OpenClaw config from ~/.codex/.omx-config.json or notifications.openclaw key.
Supports HTTP and CLI command gateway configurations.
"""
import json
import os
from pathlib import Path
from typing import Any, Optional

from src.openclaw.types import (
    OpenClawCommandGatewayConfig,
    OpenClawConfig,
    OpenClawGatewayConfig,
    OpenClawHookEvent,
    OpenClawHookMapping,
    OpenClawHttpGatewayConfig,
)


# Cached config (None = not yet read, False = read but file missing/invalid)
_cached_config: Optional[OpenClawConfig | None] = None

VALID_HOOK_EVENTS = [
    "session_start",
    "session_end",
    "session_idle",
    "ask_user_question",
    "stop",
]

DEFAULT_ALIAS_EVENTS = ["session_end", "ask_user_question"]


def _codex_home() -> Path:
    """Get codex home directory."""
    return Path.home() / ".codex"


def _read_config_file(config_path: Path) -> dict[str, Any] | None:
    """Read config from file."""
    if not config_path.exists():
        return None
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _parse_events(value: Any) -> list[str]:
    """Parse hook events from config."""
    if not isinstance(value, list):
        return list(DEFAULT_ALIAS_EVENTS)
    events = [e for e in value if e in VALID_HOOK_EVENTS]
    return events if events else list(DEFAULT_ALIAS_EVENTS)


def _parse_gateway(gateway_name: str, config: dict[str, Any]) -> Optional[OpenClawGatewayConfig]:
    """Parse a gateway config."""
    gateway_type = config.get("type", "http")
    if gateway_type == "command":
        return OpenClawCommandGatewayConfig(
            type="command",
            command=config.get("command", ""),
            timeout=config.get("timeout", 5000),
        )
    else:
        return OpenClawHttpGatewayConfig(
            type="http",
            url=config.get("url", ""),
            headers=config.get("headers"),
            method=config.get("method", "POST"),
            timeout=config.get("timeout", 10000),
        )


def _normalize_from_aliases(notifications: dict[str, Any]) -> Optional[OpenClawConfig]:
    """Normalize from custom aliases (legacy)."""
    webhook_alias = notifications.get("custom_webhook_command")
    cli_alias = notifications.get("custom_cli_command")

    webhook_enabled = webhook_alias.get("enabled") is True and isinstance(webhook_alias.get("url"), str)
    cli_enabled = cli_alias.get("enabled") is True and isinstance(cli_alias.get("command"), str)

    if not webhook_enabled and not cli_enabled:
        return None

    gateways: dict[str, OpenClawGatewayConfig] = {}
    hooks: dict[str, OpenClawHookMapping] = {}

    if webhook_enabled and webhook_alias:
        gateways["webhook"] = OpenClawHttpGatewayConfig(
            url=webhook_alias["url"],
            headers=webhook_alias.get("headers"),
            method=webhook_alias.get("method", "POST"),
            timeout=webhook_alias.get("timeout", 10000),
        )
        events = _parse_events(webhook_alias.get("events"))
        for event in events:
            hooks[event] = OpenClawHookMapping(
                gateway="webhook",
                instruction=webhook_alias.get("instruction", "Process hook event"),
                enabled=True,
            )

    if cli_enabled and cli_alias:
        gateways["cli"] = OpenClawCommandGatewayConfig(
            command=cli_alias["command"],
            timeout=cli_alias.get("timeout", 5000),
        )
        events = _parse_events(cli_alias.get("events"))
        for event in events:
            hooks[event] = OpenClawHookMapping(
                gateway="cli",
                instruction=cli_alias.get("instruction", "Process hook event"),
                enabled=True,
            )

    return OpenClawConfig(
        enabled=True,
        gateways=gateways,
        hooks=hooks,
    )


def read_openclaw_config(config_path: Optional[Path] = None) -> Optional[OpenClawConfig]:
    """Read OpenClaw config from file."""
    global _cached_config
    if _cached_config is not None:
        return _cached_config if _cached_config is not False else None

    config_path = config_path or Path(os.environ.get(
        "OMX_OPENCLAW_CONFIG",
        str(_codex_home() / ".omx-config.json"),
    ))

    raw = _read_config_file(config_path)
    if not raw:
        _cached_config = False
        return None

    notifications = raw.get("notifications", {})
    openclaw = notifications.get("openclaw")

    if openclaw and isinstance(openclaw, dict):
        config = openclaw
    elif notifications:
        normalized = _normalize_from_aliases(notifications)
        if normalized:
            _cached_config = normalized
            return normalized
        _cached_config = False
        return None
    else:
        _cached_config = False
        return None

    enabled = config.get("enabled", False)
    gateways_raw = config.get("gateways", {})
    hooks_raw = config.get("hooks", {})

    gateways: dict[str, OpenClawGatewayConfig] = {}
    for name, gw_config in gateways_raw.items():
        if isinstance(gw_config, dict):
            gateway = _parse_gateway(name, gw_config)
            if gateway:
                gateways[name] = gateway

    hooks: dict[str, OpenClawHookMapping] = {}
    for event, hook in hooks_raw.items():
        if isinstance(hook, dict):
            hooks[event] = OpenClawHookMapping(
                gateway=hook.get("gateway", ""),
                instruction=hook.get("instruction", ""),
                enabled=hook.get("enabled", True),
            )

    result = OpenClawConfig(
        enabled=enabled,
        gateways=gateways,
        hooks=hooks,
    )
    _cached_config = result
    return result


def reset_openclaw_config_cache() -> None:
    """Reset cached config."""
    global _cached_config
    _cached_config = None