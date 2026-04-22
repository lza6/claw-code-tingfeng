"""OpenClaw Gateway Dispatcher.

Sends instruction payloads to OpenClaw gateways via HTTP or CLI command.
All calls are non-blocking with timeouts.
"""
import os
import subprocess
from datetime import datetime
from typing import Any

from src.openclaw.types import (
    OpenClawCommandGatewayConfig,
    OpenClawConfig,
    OpenClawHttpGatewayConfig,
    OpenClawPayload,
    OpenClawResult,
)

DEFAULT_HTTP_TIMEOUT_MS = 10000
DEFAULT_COMMAND_TIMEOUT_MS = 5000

MIN_COMMAND_TIMEOUT_MS = 100
MAX_COMMAND_TIMEOUT_MS = 300000

SHELL_METACHAR_RE = r"[|&;><`$()]"


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def validate_gateway_url(url: str) -> bool:
    """Validate gateway URL - HTTPS required except localhost."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme == "https":
            return True
        if parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1", "[::1]"):
            return True
        return False
    except Exception:
        return False


def clamp_timeout(timeout: int | None, default: int) -> int:
    """Clamp timeout to safe bounds."""
    if timeout is None:
        return default
    return max(MIN_COMMAND_TIMEOUT_MS, min(timeout, MAX_COMMAND_TIMEOUT_MS))


async def send_http_gateway(
    config: OpenClawHttpGatewayConfig,
    payload: OpenClawPayload,
) -> OpenClawResult:
    """Send payload via HTTP gateway."""
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=config.timeout / 1000)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            headers = config.headers or {}
            if config.method == "PUT":
                async with session.put(config.url, json=payload.__dict__, headers=headers) as resp:
                    return OpenClawResult(
                        gateway=config.url,
                        success=resp.status < 400,
                        status_code=resp.status,
                    )
            else:
                async with session.post(config.url, json=payload.__dict__, headers=headers) as resp:
                    return OpenClawResult(
                        gateway=config.url,
                        success=resp.status < 400,
                        status_code=resp.status,
                    )
    except Exception as e:
        return OpenClawResult(gateway=config.url, success=False, error=str(e))


async def send_command_gateway(
    config: OpenClawCommandGatewayConfig,
    payload: OpenClawPayload,
    instruction: str,
) -> OpenClawResult:
    """Send instruction via command gateway."""
    import shlex

    timeout_ms = clamp_timeout(config.timeout, DEFAULT_COMMAND_TIMEOUT_MS)
    timeout_sec = timeout_ms / 1000

    command = config.command.replace("{{instruction}}", instruction)

    if SHELL_METACHAR_RE.search(command):
        cmd = ["sh", "-c", command]
    else:
        cmd = shlex.split(command)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        return OpenClawResult(
            gateway=config.command,
            success=result.returncode == 0,
            error=None if result.returncode == 0 else result.stderr,
        )
    except subprocess.TimeoutExpired:
        return OpenClawResult(gateway=config.command, success=False, error="timeout")
    except Exception as e:
        return OpenClawResult(gateway=config.command, success=False, error=str(e))


async def dispatch_to_gateway(
    config: OpenClawConfig,
    gateway_name: str,
    event: str,
    instruction: str,
    context: dict[str, Any] | None = None,
) -> OpenClawResult:
    """Dispatch instruction to a gateway."""
    gateway = config.gateways.get(gateway_name)
    if not gateway:
        return OpenClawResult(gateway=gateway_name, success=False, error="gateway not found")

    payload = OpenClawPayload(
        event=event,
        instruction=instruction,
        text=instruction,
        timestamp=now_iso(),
        context=context or {},
    )

    if isinstance(gateway, OpenClawHttpGatewayConfig):
        if not validate_gateway_url(gateway.url):
            return OpenClawResult(gateway=gateway_name, success=False, error="invalid URL")
        return await send_http_gateway(gateway, payload)
    elif isinstance(gateway, OpenClawCommandGatewayConfig):
        if not os.environ.get("OMX_OPENCLAW_COMMAND"):
            return OpenClawResult(gateway=gateway_name, success=False, error="command gateway disabled")
        return await send_command_gateway(gateway, payload, instruction)

    return OpenClawResult(gateway=gateway_name, success=False, error="unknown gateway type")


async def dispatch_hook_event(
    config: OpenClawConfig,
    event: str,
    instruction: str,
    context: dict[str, Any] | None = None,
) -> list[OpenClawResult]:
    """Dispatch to all hooks for an event."""
    results = []
    hook = config.hooks.get(event)
    if hook and hook.enabled:
        result = await dispatch_to_gateway(config, hook.gateway, event, instruction, context)
        results.append(result)
    return results
