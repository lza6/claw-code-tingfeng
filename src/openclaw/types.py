"""OpenClaw Gateway Integration Types.

Defines types for the OpenClaw gateway waker system.
Each hook event can be mapped to a gateway with a pre-defined instruction.
"""
from dataclasses import dataclass
from typing import Any, Optional, Union

# Hook events that can trigger OpenClaw gateway calls
OpenClawHookEvent = "session_start" | "session_end" | "session_idle" | "ask_user_question" | "stop"


# HTTP gateway configuration (default when type is absent or "http")
@dataclass
class OpenClawHttpGatewayConfig:
    """HTTP gateway configuration."""
    type: str = "http"
    url: str = ""
    headers: Optional[dict[str, str]] = None
    method: str = "POST"
    timeout: int = 10000


# CLI command gateway configuration
@dataclass
class OpenClawCommandGatewayConfig:
    """CLI command gateway configuration."""
    type: str = "command"
    command: str = ""
    timeout: int = 5000


# Gateway configuration — HTTP or CLI command
OpenClawGatewayConfig = Union[OpenClawHttpGatewayConfig, OpenClawCommandGatewayConfig]


# Per-hook-event mapping to a gateway + instruction
@dataclass
class OpenClawHookMapping:
    """Per-hook-event mapping to a gateway + instruction."""
    gateway: str = ""
    instruction: str = ""
    enabled: bool = True


# Top-level config schema
@dataclass
class OpenClawConfig:
    """Top-level config schema."""
    enabled: bool = False
    gateways: dict[str, OpenClawGatewayConfig] = None
    hooks: Optional[dict[str, OpenClawHookMapping]] = None

    def __post_init__(self):
        if self.gateways is None:
            self.gateways = {}
        if self.hooks is None:
            self.hooks = {}


# Payload sent to an OpenClaw gateway
@dataclass
class OpenClawPayload:
    """Payload sent to an OpenClaw gateway."""
    event: str = ""
    instruction: str = ""
    text: str = ""
    timestamp: str = ""
    session_id: Optional[str] = None
    project_path: Optional[str] = None
    project_name: Optional[str] = None
    tmux_session: Optional[str] = None
    tmux_tail: Optional[str] = None
    channel: Optional[str] = None
    to: Optional[str] = None
    thread_id: Optional[str] = None
    context: Optional[dict[str, Any]] = None

    def __post_init__(self):
        if self.context is None:
            self.context = {}


# Context data passed from the hook
@dataclass
class OpenClawContext:
    """Context data passed from the hook."""
    session_id: Optional[str] = None
    project_path: Optional[str] = None
    tmux_session: Optional[str] = None
    prompt: Optional[str] = None
    context_summary: Optional[str] = None
    reason: Optional[str] = None
    question: Optional[str] = None
    tmux_tail: Optional[str] = None
    reply_channel: Optional[str] = None
    reply_target: Optional[str] = None
    reply_thread: Optional[str] = None


# Result of a gateway wake attempt
@dataclass
class OpenClawResult:
    """Result of a gateway wake attempt."""
    gateway: str = ""
    success: bool = False
    error: Optional[str] = None
    status_code: Optional[int] = None


# Type aliases for backward compatibility
OpenClawHookEventType = str
OpenClawConfigType = dict[str, Any]