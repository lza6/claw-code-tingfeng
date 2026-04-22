"""Notification System - Public API

Multi-platform lifecycle notifications for Clawd Code.
Sends notifications to Discord, Telegram, Slack, and generic webhooks
on session lifecycle events.

Usage:
    from src.notification import notify_lifecycle, NotificationEvent

    await notify_lifecycle("session_start", {"session_id": "abc123", "project_path": "/path/to/project"})
"""

from .config import (
    get_enabled_platforms,
    get_notification_config,
    get_verbosity,
    is_event_allowed_by_verbosity,
    is_event_enabled,
    should_include_tmux_tail,
)
from .formatter import (
    format_ask_user_question,
    format_notification,
    format_session_end,
    format_session_idle,
    format_session_start,
    format_session_stop,
)
from .notifier import load_notification_config, notify
from .types import (
    DiscordBotNotificationConfig,
    DiscordNotificationConfig,
    DispatchResult,
    EventNotificationConfig,
    FullNotificationConfig,
    FullNotificationPayload,
    NotificationEvent,
    NotificationPlatform,
    NotificationResult,
    ReplyConfig,
    ReplyListenerDaemonConfig,
    ReplyListenerState,
    SlackNotificationConfig,
    TelegramNotificationConfig,
    VerbosityLevel,
    WebhookNotificationConfig,
)

__all__ = [
    "DiscordBotNotificationConfig",
    "DiscordNotificationConfig",
    "DispatchResult",
    "EventNotificationConfig",
    "FullNotificationConfig",
    "FullNotificationPayload",
    # Types
    "NotificationEvent",
    "NotificationPlatform",
    "NotificationResult",
    "ReplyConfig",
    "ReplyListenerDaemonConfig",
    "ReplyListenerState",
    "SlackNotificationConfig",
    "TelegramNotificationConfig",
    "VerbosityLevel",
    "WebhookNotificationConfig",
    "format_ask_user_question",
    # Formatters
    "format_notification",
    "format_session_end",
    "format_session_idle",
    "format_session_start",
    "format_session_stop",
    "get_enabled_platforms",
    # Config
    "get_notification_config",
    "get_verbosity",
    "is_event_allowed_by_verbosity",
    "is_event_enabled",
    "load_notification_config",
    # Core functions
    "notify",
    "notify_lifecycle",
    "should_include_tmux_tail",
]


async def notify_lifecycle(
    event: NotificationEvent,
    data: dict,
    profile_name: str | None = None,
) -> DispatchResult | None:
    """High-level notification function for lifecycle events.

    Reads config, checks if the event is enabled, formats the message,
    and dispatches to all configured platforms.

    Args:
        event: The lifecycle event type
        data: Notification payload data
        profile_name: Optional notification profile name

    Returns:
        DispatchResult if successful, None if skipped or disabled
    """
    from .notifier import dispatch_notifications

    config = get_notification_config(profile_name)
    if not config or not is_event_enabled(config, event):
        return None

    payload = FullNotificationPayload(
        event=event,
        session_id=data.get("session_id", ""),
        message="",
        timestamp=data.get("timestamp", ""),
        tmux_session=data.get("tmux_session"),
        project_path=data.get("project_path"),
        project_name=data.get("project_name"),
        modes_used=data.get("modes_used"),
        context_summary=data.get("context_summary"),
        duration_ms=data.get("duration_ms"),
        agents_spawned=data.get("agents_spawned"),
        agents_completed=data.get("agents_completed"),
        reason=data.get("reason"),
        active_mode=data.get("active_mode"),
        iteration=data.get("iteration"),
        max_iterations=data.get("max_iterations"),
        question=data.get("question"),
        incomplete_tasks=data.get("incomplete_tasks"),
        tmux_pane=data.get("tmux_pane"),
    )

    # Format the message based on event type
    message = format_notification(event, payload)
    payload = payload._replace(message=message)

    # Dispatch to all enabled platforms
    return await dispatch_notifications(config, payload)
