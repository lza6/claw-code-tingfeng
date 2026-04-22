"""Notification System - Core Notifier

Legacy notifier module for backward compatibility.
New code should use notify_lifecycle from index.py.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_notification_config, is_event_enabled
from .dispatcher import dispatch_notifications
from .formatter import format_notification
from .types import FullNotificationConfig, FullNotificationPayload, NotificationEvent

logger = logging.getLogger(__name__)


class NotificationError(Exception):
    """Base exception for notification errors."""
    pass


async def notify(
    config: FullNotificationConfig,
    payload: FullNotificationPayload,
) -> dict[str, Any] | None:
    """Send a notification using the given config and payload.

    This is a legacy function. Use notify_lifecycle() for new code.

    Args:
        config: Notification configuration
        payload: Notification payload

    Returns:
        Dispatch result dict if successful, None if skipped
    """
    if not config or not config.enabled:
        return None

    # Check if event is enabled
    if not is_event_enabled(config, payload.event):
        return None

    # Format message
    message = format_notification(payload.event, payload)
    # Create new payload with formatted message (dataclasses don't have _replace)
    updated_payload = FullNotificationPayload(
        event=payload.event,
        session_id=payload.session_id,
        message=message,
        timestamp=payload.timestamp,
        tmux_session=payload.tmux_session,
        project_path=payload.project_path,
        project_name=payload.project_name,
        modes_used=payload.modes_used,
        context_summary=payload.context_summary,
        duration_ms=payload.duration_ms,
        agents_spawned=payload.agents_spawned,
        agents_completed=payload.agents_completed,
        reason=payload.reason,
        active_mode=payload.active_mode,
        iteration=payload.iteration,
        max_iterations=payload.max_iterations,
        question=payload.question,
        incomplete_tasks=payload.incomplete_tasks,
        tmux_pane=payload.tmux_pane,
    )

    # Dispatch
    result = await dispatch_notifications(config, updated_payload)

    if result and result.any_succeeded:
        logger.info(f"Notification dispatched successfully: {payload.event}")
    else:
        logger.warning(f"Notification failed or no platforms succeeded: {payload.event}")

    return {
        "event": payload.event.value,
        "success": result.any_succeeded if result else False,
        "platform_results": [
            {
                "platform": r.platform.value,
                "success": r.success,
                "error": r.error,
            }
            for r in result.results
        ] if result else [],
    }


def load_notification_config(
    config_path: Path | None = None,
    profile: str | None = None,
) -> FullNotificationConfig | None:
    """Load notification configuration from file.

    Args:
        config_path: Path to config file (default: .omx-config.json in cwd)
        profile: Profile name to use

    Returns:
        FullNotificationConfig if found, None otherwise
    """
    from .config import get_notification_config

    cwd = str(config_path.parent) if config_path else None
    return get_notification_config(profile, cwd)


async def send_session_start_notification(
    session_id: str,
    project_path: str | None = None,
    tmux_session: str | None = None,
    modes_used: list[str] | None = None,
) -> bool:
    """Convenience function for session start notifications."""

    payload = FullNotificationPayload(
        event=NotificationEvent.SESSION_START,
        session_id=session_id,
        message="",
        timestamp=datetime.now(timezone.utc).isoformat(),
        project_path=project_path,
        tmux_session=tmux_session,
        modes_used=modes_used,
    )

    config = get_notification_config()
    if not config:
        return False

    result = await notify(config, payload)
    return result is not None and result.get("success", False)


async def send_session_end_notification(
    session_id: str,
    duration_ms: int,
    agents_spawned: int | None = None,
    agents_completed: int | None = None,
    reason: str | None = None,
) -> bool:
    """Convenience function for session end notifications."""

    payload = FullNotificationPayload(
        event=NotificationEvent.SESSION_END,
        session_id=session_id,
        message="",
        timestamp=datetime.now(timezone.utc).isoformat(),
        duration_ms=duration_ms,
        agents_spawned=agents_spawned,
        agents_completed=agents_completed,
        reason=reason,
    )

    config = get_notification_config()
    if not config:
        return False

    result = await notify(config, payload)
    return result is not None and result.get("success", False)
