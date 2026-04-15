"""Notifications 系统类型定义

从 oh-my-codex-main/src/notifications/types.ts 汲取。

定义多平台生命周期通知系统的类型。
支持 Discord、Telegram、Slack 和通用 webhooks，
覆盖会话生命周期事件（start, stop, end, ask-user-question）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ===== 事件类型 =====
class NotificationEvent(str, Enum):
    """可以触发通知的事件"""
    SESSION_START = 'session-start'
    SESSION_STOP = 'session-stop'
    SESSION_END = 'session-end'
    SESSION_IDLE = 'session-idle'
    ASK_USER_QUESTION = 'ask-user-question'


class VerbosityLevel(str, Enum):
    """通知详细程度级别

    - verbose: 所有文本/工具调用输出
    - agent: 每个代理调用事件（包括 ask-user-question）
    - session: start/idle/stop/end + tmux 尾部片段 [默认]
    - minimal: 仅 start/stop/end，无 idle，无 tmux 尾部
    """
    VERBOSE = 'verbose'
    AGENT = 'agent'
    SESSION = 'session'
    MINIMAL = 'minimal'


class NotificationPlatform(str, Enum):
    """支持的通知平台"""
    DISCORD = 'discord'
    DISCORD_BOT = 'discord-bot'
    TELEGRAM = 'telegram'
    SLACK = 'slack'
    WEBHOOK = 'webhook'


# ===== 平台配置 =====
@dataclass
class DiscordNotificationConfig:
    """Discord webhook 配置"""
    enabled: bool = False
    webhook_url: str = ''
    username: str = ''
    mention: str = ''


@dataclass
class DiscordBotNotificationConfig:
    """Discord Bot API 配置（bot token + channel ID）"""
    enabled: bool = False
    bot_token: str = ''
    channel_id: str = ''
    mention: str = ''


@dataclass
class TelegramNotificationConfig:
    """Telegram 平台配置"""
    enabled: bool = False
    bot_token: str = ''
    chat_id: str = ''
    parse_mode: str = 'Markdown'  # 'Markdown' | 'HTML'


@dataclass
class SlackNotificationConfig:
    """Slack 平台配置"""
    enabled: bool = False
    webhook_url: str = ''
    channel: str = ''
    username: str = ''
    mention: str = ''


@dataclass
class WebhookNotificationConfig:
    """通用 webhook 配置"""
    enabled: bool = False
    url: str = ''
    headers: dict = field(default_factory=dict)
    method: str = 'POST'  # 'POST' | 'PUT'


@dataclass
class CustomWebhookCommandConfig:
    """通用自定义 webhook 命令配置"""
    enabled: bool = False
    url: str = ''
    headers: dict = field(default_factory=dict)
    method: str = 'POST'
    timeout: int = 10000


@dataclass
class CustomCliCommandConfig:
    """通用自定义 CLI 命令配置"""
    enabled: bool = False
    command: str = ''
    timeout: int = 10000


# ===== 事件配置 =====
@dataclass
class EventNotificationConfig:
    """每个事件的通知配置"""
    enabled: bool = False
    message_template: str = ''
    discord: Optional[DiscordNotificationConfig] = None
    discord_bot: Optional[DiscordBotNotificationConfig] = None
    telegram: Optional[TelegramNotificationConfig] = None
    slack: Optional[SlackNotificationConfig] = None
    webhook: Optional[WebhookNotificationConfig] = None


# ===== 顶级配置 =====
@dataclass
class FullNotificationConfig:
    """顶级通知配置（存储在 .omx-config.json）"""
    enabled: bool = False
    verbosity: VerbosityLevel = VerbosityLevel.SESSION

    # 默认平台配置
    discord: Optional[DiscordNotificationConfig] = None
    discord_bot: Optional[DiscordBotNotificationConfig] = None
    telegram: Optional[TelegramNotificationConfig] = None
    slack: Optional[SlackNotificationConfig] = None
    webhook: Optional[WebhookNotificationConfig] = None

    # OpenClaw 网关
    openclaw_enabled: bool = False

    # 自定义传输
    custom_webhook_command: Optional[CustomWebhookCommandConfig] = None
    custom_cli_command: Optional[CustomCliCommandConfig] = None

    # 每个事件的配置
    events: Optional[dict[str, EventNotificationConfig]] = None


# ===== 负载 =====
@dataclass
class FullNotificationPayload:
    """每个通知携带的负载"""
    event: NotificationEvent = NotificationEvent.SESSION_START
    session_id: str = ''
    message: str = ''
    timestamp: str = ''

    tmux_session: str = ''
    project_path: str = ''
    project_name: str = ''

    modes_used: list[str] = field(default_factory=list)
    context_summary: str = ''

    duration_ms: int = 0
    agents_spawned: int = 0
    agents_completed: int = 0

    reason: str = ''
    active_mode: str = ''

    iteration: int = 0
    max_iterations: int = 0

    question: str = ''
    incomplete_tasks: int = 0

    tmux_pane_id: str = ''
    tmux_tail: str = ''

    agent_name: str = ''
    agent_type: str = ''


# ===== 结果 =====
@dataclass
class NotificationResult:
    """通知发送尝试的结果"""
    platform: NotificationPlatform = NotificationPlatform.WEBHOOK
    success: bool = False
    error: str = ''
    message_id: str = ''


@dataclass
class DispatchResult:
    """分发通知的结果"""
    event: NotificationEvent = NotificationEvent.SESSION_START
    results: list[NotificationResult] = field(default_factory=list)
    any_success: bool = False


# ===== Reply 配置 =====
@dataclass
class ReplyConfig:
    """Reply 注入配置"""
    enabled: bool = False
    poll_interval_ms: int = 3000
    max_message_length: int = 500
    rate_limit_per_minute: int = 10
    include_prefix: bool = True
    authorized_discord_user_ids: list[str] = field(default_factory=list)


# ===== 导出 =====
__all__ = [
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
]