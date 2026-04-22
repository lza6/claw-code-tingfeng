"""OpenClaw - External gateway hook system.

Integration from oh-my-codex-main/src/openclaw/:
- types.py: Type definitions for gateways
- config.py: Configuration reader
- dispatcher.py: Gateway dispatch logic

Usage:
```python
from src.openclaw import read_openclaw_config, dispatch_hook_event

config = read_openclaw_config()
if config:
    await dispatch_hook_event(config, "session_end", "Session ended", {"session_id": "abc"})
```
"""
from src.openclaw.config import read_openclaw_config, reset_openclaw_config_cache
from src.openclaw.dispatcher import dispatch_hook_event, dispatch_to_gateway
from src.openclaw.types import (
    OpenClawCommandGatewayConfig,
    OpenClawConfig,
    OpenClawGatewayConfig,
    OpenClawHookEvent,
    OpenClawHookMapping,
    OpenClawHttpGatewayConfig,
    OpenClawPayload,
    OpenClawResult,
)

__all__ = [
    "OpenClawCommandGatewayConfig",
    "OpenClawConfig",
    "OpenClawGatewayConfig",
    "OpenClawHookEvent",
    "OpenClawHookMapping",
    "OpenClawHttpGatewayConfig",
    "OpenClawPayload",
    "OpenClawResult",
    "dispatch_hook_event",
    "dispatch_to_gateway",
    "read_openclaw_config",
    "reset_openclaw_config_cache",
]
