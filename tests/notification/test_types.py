"""Tests for notification types."""

import pytest
from src.notification.types import (
    NotificationEvent,
    VerbosityLevel,
    NotificationPlatform,
    DiscordNotificationConfig,
    TelegramNotificationConfig,
    SlackNotificationConfig,
    FullNotificationConfig,
    FullNotificationPayload,
)


def test_notification_event_values():
    """Test NotificationEvent enum values."""
    assert NotificationEvent.SESSION_START.value == "session-start"
    assert NotificationEvent.SESSION_STOP.value == "session-stop"
    assert NotificationEvent.SESSION_END.value == "session-end"
    assert NotificationEvent.SESSION_IDLE.value == "session-idle"
    assert NotificationEvent.ASK_USER_QUESTION.value == "ask-user-question"


def test_verbosity_level_values():
    """Test VerbosityLevel enum values."""
    assert VerbosityLevel.VERBOSE.value == "verbose"
    assert VerbosityLevel.AGENT.value == "agent"
    assert VerbosityLevel.SESSION.value == "session"
    assert VerbosityLevel.MINIMAL.value == "minimal"


def test_notification_platform_values():
    """Test NotificationPlatform enum values."""
    assert NotificationPlatform.DISCORD.value == "discord"
    assert NotificationPlatform.TELEGRAM.value == "telegram"
    assert NotificationPlatform.SLACK.value == "slack"
    assert NotificationPlatform.WEBHOOK.value == "webhook"


def test_discord_config_defaults():
    """Test Discord config defaults."""
    config = DiscordNotificationConfig()
    assert config.enabled is False
    assert config.webhook_url is None
    assert config.username is None
    assert config.mention is None


def test_telegram_config_defaults():
    """Test Telegram config defaults."""
    config = TelegramNotificationConfig()
    assert config.enabled is False
    assert config.bot_token is None
    assert config.chat_id is None
    assert config.parse_mode == "Markdown"


def test_full_notification_config_defaults():
    """Test FullNotificationConfig defaults."""
    config = FullNotificationConfig()
    assert config.enabled is False
    assert config.verbosity == VerbosityLevel.SESSION
    assert config.discord is None
    assert config.telegram is None
    assert config.slack is None
    assert config.events is None


def test_full_notification_payload_required_fields():
    """Test FullNotificationPayload required fields."""
    payload = FullNotificationPayload(
        event=NotificationEvent.SESSION_START,
        session_id="test123",
        message="Test message",
        timestamp="2024-01-01T00:00:00Z",
    )
    
    assert payload.event == NotificationEvent.SESSION_START
    assert payload.session_id == "test123"
    assert payload.message == "Test message"
    assert payload.timestamp == "2024-01-01T00:00:00Z"
    assert payload.tmux_session is None
    assert payload.project_path is None
    assert payload.duration_ms is None


def test_full_notification_payload_optional_fields():
    """Test FullNotificationPayload with optional fields."""
    payload = FullNotificationPayload(
        event=NotificationEvent.SESSION_END,
        session_id="test123",
        message="Done",
        timestamp="2024-01-01T00:00:00Z",
        tmux_session="session-1",
        project_path="/path/to/project",
        project_name="my-project",
        duration_ms=5000,
        agents_spawned=3,
        agents_completed=3,
    )
    
    assert payload.tmux_session == "session-1"
    assert payload.project_path == "/path/to/project"
    assert payload.project_name == "my-project"
    assert payload.duration_ms == 5000
    assert payload.agents_spawned == 3
    assert payload.agents_completed == 3
