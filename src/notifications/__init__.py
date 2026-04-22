"""Notifications 模块

多平台生命周期通知系统。
支持 Discord、Telegram、Slack 和通用 webhooks。

功能:
- 多平台通知发送 (Discord, Telegram, Slack, Webhook)
- 配置管理（从文件和环境变量加载）
- 事件驱动的通知分发

用法:
    from src.notifications import (
        FullNotificationConfig,
        FullNotificationPayload,
        NotificationEvent,
        load_notification_config,
        dispatch_notifications,
    )

    config = load_notification_config(cwd='.')
    payload = FullNotificationPayload(
        event=NotificationEvent.SESSION_START,
        session_id='session-123',
        message='Session started',
        timestamp='2026-04-14T00:00:00Z',
    )
    result = await dispatch_notifications(config, payload.event, payload)
"""

from .config import (
    is_notifications_enabled,
    load_notification_config,
    load_reply_config,
    parse_mention_allowed_mentions,
)
from .cooldown import (
    get_idle_notification_cooldown_seconds,
    is_cooldown_enabled,
    record_idle_notification_sent,
    should_send_idle_notification,
)
from .dispatcher import (
    dispatch_notifications,
    send_discord,
    send_discord_bot,
    send_slack,
    send_telegram,
    send_webhook,
    validate_discord_url,
    validate_slack_url,
    validate_telegram_token,
    validate_webhook_url,
)
from .session_registry import (
    SessionMapping,
    find_mapping_by_message_id,
    find_mapping_by_session_id,
    prune_old_entries,
    register_session,
)
from .session_registry import (
    get_stats as get_session_registry_stats,
)
from .template_engine import (
    compute_template_variables,
    interpolate_template,
    render_notification_template,
)
from .types import (
    CustomCliCommandConfig,
    CustomWebhookCommandConfig,
    DiscordBotNotificationConfig,
    # 配置
    DiscordNotificationConfig,
    DispatchResult,
    EventNotificationConfig,
    FullNotificationConfig,
    # 负载
    FullNotificationPayload,
    # 事件
    NotificationEvent,
    NotificationPlatform,
    # 结果
    NotificationResult,
    # Reply
    ReplyConfig,
    SlackNotificationConfig,
    TelegramNotificationConfig,
    VerbosityLevel,
    WebhookNotificationConfig,
)

__all__ = [
    "CustomCliCommandConfig",
    "CustomWebhookCommandConfig",
    "DiscordBotNotificationConfig",
    "DiscordNotificationConfig",
    "DispatchResult",
    "EventNotificationConfig",
    "FullNotificationConfig",
    "FullNotificationPayload",
    # 类型
    "NotificationEvent",
    "NotificationPlatform",
    "NotificationResult",
    "ReplyConfig",
    # 会话注册表
    "SessionMapping",
    "SlackNotificationConfig",
    "TelegramNotificationConfig",
    "VerbosityLevel",
    "WebhookNotificationConfig",
    "compute_template_variables",
    "dispatch_notifications",
    "find_mapping_by_message_id",
    "find_mapping_by_session_id",
    # 冷却管理
    "get_idle_notification_cooldown_seconds",
    "get_session_registry_stats",
    # 模板引擎
    "interpolate_template",
    "is_cooldown_enabled",
    "is_notifications_enabled",
    "load_notification_config",
    "load_reply_config",
    # 配置
    "parse_mention_allowed_mentions",
    "prune_old_entries",
    "record_idle_notification_sent",
    "register_session",
    "render_notification_template",
    "send_discord",
    "send_discord_bot",
    "send_slack",
    "send_telegram",
    "send_webhook",
    "should_send_idle_notification",
    # 分发
    "validate_discord_url",
    "validate_slack_url",
    "validate_telegram_token",
    "validate_webhook_url",
]
