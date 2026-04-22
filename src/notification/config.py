"""Notification Configuration Management

Handles loading and managing notification configurations from
environment variables, config files, and profiles.

Integrates Project B (oh-my-codex) enhancements:
- Notification Profiles (multi-config support)
- Reply Listener (bidirectional communication)
- Hook Templates (extensible notification templates)
- Platform-specific mention validation
"""

import json
import os
import re
from pathlib import Path
from typing import Any

from .types import (
    DiscordBotNotificationConfig,
    DiscordNotificationConfig,
    EventNotificationConfig,
    FullNotificationConfig,
    HookEventConfig,
    HookNotificationConfig,
    NotificationEvent,
    NotificationProfile,
    NotificationProfilesConfig,
    ReplyConfig,
    SlackNotificationConfig,
    TelegramNotificationConfig,
    VerbosityLevel,
    WebhookNotificationConfig,
)

# Config file locations
CONFIG_FILENAME = ".omx-config.json"
CONFIG_PROFILE_ENV = "OMX_NOTIFICATION_PROFILE"
DEFAULT_PROFILE = "default"


def get_config_dir(cwd: str | None = None) -> Path:
    """Get the directory containing notification config."""
    cwd = cwd or os.getcwd()
    return Path(cwd)


def config_file_path(cwd: str | None = None) -> Path:
    """Get the path to the notification config file."""
    return get_config_dir(cwd) / CONFIG_FILENAME


def load_config_from_file(cwd: str | None = None) -> dict[str, Any] | None:
    """Load notification config from file if it exists."""
    path = config_file_path(cwd)
    if not path.exists():
        return None

    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def get_env_var(name: str, default: str | None = None) -> str | None:
    """Get environment variable with fallback."""
    value = os.environ.get(name, default)
    return value if value and value.strip() else default


def resolve_discord_config(raw: dict[str, Any] | None) -> DiscordNotificationConfig | None:
    """Resolve Discord webhook configuration from raw dict."""
    if not raw:
        return None

    enabled = raw.get("enabled", False)
    if not enabled:
        return None

    webhook_url = raw.get("webhookUrl") or raw.get("webhook_url")
    if not webhook_url:
        # Try environment variable
        webhook_url = get_env_var("OMX_NOTIFY_DISCORD_WEBHOOK")

    return DiscordNotificationConfig(
        enabled=enabled,
        webhook_url=webhook_url,
        username=raw.get("username"),
        mention=raw.get("mention"),
    )


def resolve_discord_bot_config(raw: dict[str, Any] | None) -> DiscordBotNotificationConfig | None:
    """Resolve Discord bot configuration from raw dict."""
    if not raw:
        return None

    enabled = raw.get("enabled", False)
    if not enabled:
        return None

    bot_token = raw.get("botToken") or raw.get("bot_token") or get_env_var("OMX_DISCORD_BOT_TOKEN")
    channel_id = raw.get("channelId") or raw.get("channel_id") or get_env_var("OMX_DISCORD_CHANNEL_ID")

    return DiscordBotNotificationConfig(
        enabled=enabled,
        bot_token=bot_token,
        channel_id=channel_id,
        mention=raw.get("mention"),
    )


def resolve_telegram_config(raw: dict[str, Any] | None) -> TelegramNotificationConfig | None:
    """Resolve Telegram configuration from raw dict."""
    if not raw:
        return None

    enabled = raw.get("enabled", False)
    if not enabled:
        return None

    bot_token = raw.get("botToken") or raw.get("bot_token") or get_env_var("OMX_TELEGRAM_BOT_TOKEN")
    chat_id = raw.get("chatId") or raw.get("chat_id") or get_env_var("OMX_TELEGRAM_CHAT_ID")

    return TelegramNotificationConfig(
        enabled=enabled,
        bot_token=bot_token,
        chat_id=chat_id,
        parse_mode=raw.get("parseMode") or raw.get("parse_mode") or "Markdown",
    )


def resolve_slack_config(raw: dict[str, Any] | None) -> SlackNotificationConfig | None:
    """Resolve Slack configuration from raw dict."""
    if not raw:
        return None

    enabled = raw.get("enabled", False)
    if not enabled:
        return None

    webhook_url = raw.get("webhookUrl") or raw.get("webhook_url") or get_env_var("OMX_SLACK_WEBHOOK")

    return SlackNotificationConfig(
        enabled=enabled,
        webhook_url=webhook_url,
        channel=raw.get("channel"),
        username=raw.get("username"),
        mention=raw.get("mention"),
    )


def resolve_webhook_config(raw: dict[str, Any] | None) -> WebhookNotificationConfig | None:
    """Resolve generic webhook configuration from raw dict."""
    if not raw:
        return None

    enabled = raw.get("enabled", False)
    if not enabled:
        return None

    url = raw.get("url") or get_env_var("OMX_WEBHOOK_URL")

    return WebhookNotificationConfig(
        enabled=enabled,
        url=url,
        headers=raw.get("headers"),
        method=raw.get("method", "POST"),
    )


def resolve_event_config(raw: dict[str, Any] | None) -> EventNotificationConfig | None:
    """Resolve per-event configuration."""
    if not raw:
        return None

    return EventNotificationConfig(
        enabled=raw.get("enabled", True),
        message_template=raw.get("messageTemplate") or raw.get("message_template"),
        discord=resolve_discord_config(raw.get("discord")),
        discord_bot=resolve_discord_bot_config(raw.get("discord-bot") or raw.get("discord_bot")),
        telegram=resolve_telegram_config(raw.get("telegram")),
        slack=resolve_slack_config(raw.get("slack")),
        webhook=resolve_webhook_config(raw.get("webhook")),
    )


def get_active_profile_name(cwd: str | None = None) -> str:
    """Get the active notification profile name."""
    profile = get_env_var(CONFIG_PROFILE_ENV, DEFAULT_PROFILE)
    return profile


# ===== Project B Enhancements: Validation Functions =====

def validate_discord_mention(raw: str | None) -> str | None:
    """Validate Discord mention format.

    Accepts: <@123456> (user), <@&789> (role)
    Returns the mention string if valid, None otherwise.
    """
    if not raw:
        return None
    mention = raw.strip()
    # User mention: <@1234567890> or <@!1234567890>
    if re.match(r'^<@!?\d{17,20}>$', mention):
        return mention
    # Role mention: <@&1234567890>
    if re.match(r'^<@&\d{17,20}>$', mention):
        return mention
    return None


def validate_slack_mention(raw: str | None) -> str | None:
    """Validate Slack mention format.

    Accepts: <@UXXXXXXXX> (user), <!channel>, <!here>, <!everyone>,
             <!subteam^SXXXXXXXXX> (user group).
    """
    if not raw:
        return None
    mention = raw.strip()
    # User mention: <@U...> or <@W...>
    if re.match(r'^<@[UW][A-Z0-9]{8,11}>$', mention):
        return mention
    # Special mentions
    if re.match(r'^<!(?:channel|here|everyone)>$', mention):
        return mention
    # User group: <!subteam^S...>
    if re.match(r'^<!subteam\^S[A-Z0-9]{8,11}>$', mention):
        return mention
    return None


def parse_mention_allowed_mentions(mention: str | None) -> dict[str, list[str]]:
    """Parse mention into allowed_mentions format for API."""
    if not mention:
        return {}
    # Discord user mention
    user_match = re.match(r'^<@!?(\d{17,20})>$', mention)
    if user_match:
        return {"users": [user_match[1]]}
    # Discord role mention
    role_match = re.match(r'^<@&(\d{17,20})>$', mention)
    if role_match:
        return {"roles": [role_match[1]]}
    return {}


# ===== Project B Enhancements: Hook Templates =====

def resolve_hook_config(raw: dict[str, Any] | None) -> HookNotificationConfig | None:
    """Resolve hook template configuration from raw dict."""
    if not raw:
        return None

    return HookNotificationConfig(
        version=raw.get("version", "1.0"),
        enabled=raw.get("enabled", True),
        session_start=HookEventConfig(
            enabled=raw.get("session_start", {}).get("enabled", True),
            message_template=raw.get("session_start", {}).get("message_template"),
        ) if raw.get("session_start") else None,
        session_stop=HookEventConfig(
            enabled=raw.get("session_stop", {}).get("enabled", True),
            message_template=raw.get("session_stop", {}).get("message_template"),
        ) if raw.get("session_stop") else None,
        session_end=HookEventConfig(
            enabled=raw.get("session_end", {}).get("enabled", True),
            message_template=raw.get("session_end", {}).get("message_template"),
        ) if raw.get("session_end") else None,
        session_idle=HookEventConfig(
            enabled=raw.get("session_idle", {}).get("enabled", True),
            message_template=raw.get("session_idle", {}).get("message_template"),
        ) if raw.get("session_idle") else None,
        ask_user_question=HookEventConfig(
            enabled=raw.get("ask_user_question", {}).get("enabled", True),
            message_template=raw.get("ask_user_question", {}).get("message_template"),
        ) if raw.get("ask_user_question") else None,
    )


# ===== Project B Enhancements: Reply Listener Config =====

def resolve_reply_config(raw: dict[str, Any] | None) -> ReplyConfig | None:
    """Resolve reply listener configuration from raw dict."""
    if not raw:
        return None

    return ReplyConfig(
        enabled=raw.get("enabled", False),
        poll_interval_ms=int(raw.get("poll_interval_ms", 3000)),
        max_message_length=int(raw.get("max_message_length", 500)),
        rate_limit_per_minute=int(raw.get("rate_limit_per_minute", 10)),
        include_prefix=raw.get("include_prefix", True),
        authorized_discord_user_ids=raw.get("authorized_discord_user_ids", []),
    )


# ===== Project B Enhancements: Notification Profiles =====

def resolve_profile(profile_raw: dict[str, Any]) -> NotificationProfile:
    """Resolve a single notification profile from raw dict."""
    return NotificationProfile(
        name=profile_raw.get("name", "default"),
        description=profile_raw.get("description"),
        enabled=profile_raw.get("enabled", True),
        discord=resolve_discord_config(profile_raw.get("discord")),
        discord_bot=resolve_discord_bot_config(profile_raw.get("discord-bot") or profile_raw.get("discord_bot")),
        telegram=resolve_telegram_config(profile_raw.get("telegram")),
        slack=resolve_slack_config(profile_raw.get("slack")),
        webhook=resolve_webhook_config(profile_raw.get("webhook")),
        events={
            k: resolve_event_config(v)
            for k, v in profile_raw.get("events", {}).items()
        },
    )


def resolve_profiles_config(raw: dict[str, Any] | None) -> NotificationProfilesConfig | None:
    """Resolve notification profiles configuration from raw dict."""
    if not raw:
        return None

    profiles_dict = raw.get("profiles", {})
    profiles = {
        name: resolve_profile(profile_data)
        for name, profile_data in profiles_dict.items()
    }

    return NotificationProfilesConfig(
        enabled=raw.get("enabled", True),
        default_profile=raw.get("default_profile", DEFAULT_PROFILE),
        profiles=profiles,
    )


def get_verbosity(config: FullNotificationConfig) -> VerbosityLevel:
    """Get the verbosity level from config."""
    verbosity_str = config.verbosity or VerbosityLevel.SESSION.value
    try:
        return VerbosityLevel(verbosity_str)
    except ValueError:
        return VerbosityLevel.SESSION


def is_event_allowed_by_verbosity(
    event: NotificationEvent,
    verbosity: VerbosityLevel,
) -> bool:
    """Check if an event is allowed based on verbosity level."""
    if verbosity == VerbosityLevel.VERBOSE:
        return True
    elif verbosity == VerbosityLevel.AGENT:
        return event in {
            NotificationEvent.ASK_USER_QUESTION,
            NotificationEvent.SESSION_START,
            NotificationEvent.SESSION_STOP,
            NotificationEvent.SESSION_END,
            NotificationEvent.SESSION_IDLE,
        }
    elif verbosity == VerbosityLevel.SESSION:
        return event in {
            NotificationEvent.SESSION_START,
            NotificationEvent.SESSION_STOP,
            NotificationEvent.SESSION_END,
            NotificationEvent.SESSION_IDLE,
        }
    elif verbosity == VerbosityLevel.MINIMAL:
        return event in {
            NotificationEvent.SESSION_START,
            NotificationEvent.SESSION_END,
        }
    return False


def should_include_tmux_tail(config: FullNotificationConfig, event: NotificationEvent) -> bool:
    """Check if tmux tail should be included based on verbosity and event."""
    verbosity = get_verbosity(config)
    if verbosity == VerbosityLevel.MINIMAL:
        return False
    if verbosity == VerbosityLevel.VERBOSE:
        return True
    # For SESSION and AGENT, include for stop/end but not start/idle
    return event in {NotificationEvent.SESSION_STOP, NotificationEvent.SESSION_END}


def is_event_enabled(config: FullNotificationConfig, event: NotificationEvent) -> bool:
    """Check if a specific event is enabled in the configuration."""
    if not config.enabled:
        return False

    # Check verbosity
    if not is_event_allowed_by_verbosity(event, get_verbosity(config)):
        return False

    # Check per-event config
    if config.events:
        event_config = config.events.get(event.value)
        if event_config:
            return event_config.enabled

    return True


def get_enabled_platforms(config: FullNotificationConfig) -> list[str]:
    """Get list of enabled platform names."""
    platforms = []

    if config.discord and config.discord.enabled:
        platforms.append("discord")
    if config.discord_bot and config.discord_bot.enabled:
        platforms.append("discord-bot")
    if config.telegram and config.telegram.enabled:
        platforms.append("telegram")
    if config.slack and config.slack.enabled:
        platforms.append("slack")
    if config.webhook and config.webhook.enabled:
        platforms.append("webhook")

    return platforms


def get_notification_config(profile_name: str | None = None, cwd: str | None = None) -> FullNotificationConfig | None:
    """Load and resolve notification configuration.

    Args:
        profile_name: Profile name to use (default: from OMX_NOTIFICATION_PROFILE env)
        cwd: Current working directory for config file lookup

    Returns:
        Resolved FullNotificationConfig or None if not configured
    """
    profile_name or get_active_profile_name(cwd)

    # Load base config from file
    raw_config = load_config_from_file(cwd)
    if not raw_config:
        return None

    # Resolve top-level platform configs
    config = FullNotificationConfig(
        enabled=raw_config.get("enabled", False),
        verbosity=raw_config.get("verbosity", VerbosityLevel.SESSION.value),
    )

    # Resolve default platforms
    config.discord = resolve_discord_config(raw_config.get("discord"))
    config.discord_bot = resolve_discord_bot_config(raw_config.get("discord-bot") or raw_config.get("discord_bot"))
    config.telegram = resolve_telegram_config(raw_config.get("telegram"))
    config.slack = resolve_slack_config(raw_config.get("slack"))
    config.webhook = resolve_webhook_config(raw_config.get("webhook"))

    # Resolve per-event configs
    events_raw = raw_config.get("events", {})
    config.events = {}
    for event_key, event_raw in events_raw.items():
        config.events[event_key] = resolve_event_config(event_raw)

    # ===== Project B Enhancements: Profiles Support =====
    profiles_raw = raw_config.get("profiles")
    if profiles_raw:
        config.profiles = NotificationProfilesConfig(
            enabled=profiles_raw.get("enabled", True),
            default_profile=profiles_raw.get("default_profile", DEFAULT_PROFILE),
            profiles={
                name: resolve_profile(profile_data)
                for name, profile_data in profiles_raw.get("profiles", {}).items()
            },
        )

    # ===== Project B Enhancements: Hook Templates =====
    hook_templates_raw = raw_config.get("hookTemplates") or raw_config.get("hook_templates")
    if hook_templates_raw:
        config.hook_templates = resolve_hook_config(hook_templates_raw)

    # ===== Project B Enhancements: Reply Listener =====
    reply_raw = raw_config.get("reply")
    if reply_raw:
        config.reply = resolve_reply_config(reply_raw)

    # Check if any platform is enabled
    if not get_enabled_platforms(config):
        return None

    return config


def resolve_profile_config(
    profile_name: str,
    cwd: str | None = None,
) -> FullNotificationConfig | None:
    """Resolve configuration for a specific profile."""
    return get_notification_config(profile_name, cwd)


def list_profiles(cwd: str | None = None) -> list[str]:
    """List available notification profiles."""
    config_path = config_file_path(cwd)
    if not config_path.exists():
        return [DEFAULT_PROFILE]

    try:
        with open(config_path, encoding="utf-8") as f:
            raw_config = json.load(f)

        profiles = raw_config.get("profiles", {})
        if profiles:
            return list(profiles.keys())
        else:
            return [DEFAULT_PROFILE]
    except (OSError, json.JSONDecodeError):
        return [DEFAULT_PROFILE]
