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

from .types import (
    # 事件
    NotificationEvent,
    VerbosityLevel,
    NotificationPlatform,

    # 配置
    DiscordNotificationConfig,
    DiscordBotNotificationConfig,
    TelegramNotificationConfig,
    SlackNotificationConfig,
    WebhookNotificationConfig,
    CustomWebhookCommandConfig,
    CustomCliCommandConfig,
    EventNotificationConfig,
    FullNotificationConfig,

    # 负载
    FullNotificationPayload,

    # 结果
    NotificationResult,
    DispatchResult,

    # Reply
    ReplyConfig,
)

from .config import (
    parse_mention_allowed_mentions,
    load_notification_config,
    load_reply_config,
    is_notifications_enabled,
)

from .dispatcher import (
    validate_discord_url,
    validate_telegram_token,
    validate_slack_url,
    validate_webhook_url,
    send_discord,
    send_discord_bot,
    send_telegram,
    send_slack,
    send_webhook,
    dispatch_notifications,
)


__all__ = [
    # 类型
    "NotificationEvent",
    "VerbosityLevel",
    "NotificationPlatform",
    "DiscordNotificationConfig",
    "DiscordBotNotificationConfig",
    "TelegramNotificationConfig",
    "SlackNotificationConfig",
    "WebhookNotificationConfig",
    "CustomWebhookCommandConfig",
    "CustomCliCommandConfig",
    "EventNotificationConfig",
    "FullNotificationConfig",
    "FullNotificationPayload",
    "NotificationResult",
    "DispatchResult",
    "ReplyConfig",

    # 配置
    "parse_mention_allowed_mentions",
    "load_notification_config",
    "load_reply_config",
    "is_notifications_enabled",

    # 分发
    "validate_discord_url",
    "validate_telegram_token",
    "validate_slack_url",
    "validate_webhook_url",
    "send_discord",
    "send_discord_bot",
    "send_telegram",
    "send_slack",
    "send_webhook",
    "dispatch_notifications",
]
