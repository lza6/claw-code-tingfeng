"""Notification System Types

Defines types for the multi-platform lifecycle notification system.
Supports Discord, Telegram, Slack, and generic webhooks across
35+ lifecycle events aligned with oh-my-codex HookEventName.

Integrates Project B (oh-my-codex) enhancements:
- Notification Profiles (multi-config support)
- Reply Listener (bidirectional communication)
- Hook Templates (extensible notification templates)
- Platform-specific mention validation
- Expanded event types (38 events)
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NotificationEvent(str, Enum):
    """Events that can trigger notifications (aligned with oh-my-codex HookEventName).

    参考: oh-my-codex-main/src/hooks/extensibility/types.ts
    分类:
        - 会话生命周期 (Session lifecycle)
        - Agent 生命周期 (Agent lifecycle)
        - 任务/工作流 (Task/Workflow)
        - Pipeline 阶段 (Pipeline stages)
        - 团队协作 (Team collaboration)
        - 审核/审查 (Audit/Review)
        - 自我修复 (Self-healing)
        - 资源/性能 (Resource/Performance)
        - 通知系统自身 (Notification system)
        - 阻塞/用户交互 (Blocking/User interaction)
    """

    # ========== 会话生命周期 ==========
    SESSION_START = 'session-start'
    SESSION_STOP = 'session-stop'
    SESSION_END = 'session-end'
    SESSION_IDLE = 'session-idle'

    # ========== 用户交互 ==========
    ASK_USER_QUESTION = 'ask-user-question'
    USER_RESPONDED = 'user-responded'

    # ========== Agent 生命周期 ==========
    AGENT_START = 'agent-start'
    AGENT_END = 'agent-end'

    # ========== 任务/工作流 ==========
    TASK_CREATED = 'task-created'
    TASK_ASSIGNED = 'task-assigned'
    TASK_STARTED = 'task-started'
    TASK_COMPLETE = 'task-complete'
    TASK_FAILED = 'task-failed'
    TASK_RETRY = 'task-retry'

    # ========== Pipeline 阶段 ==========
    PIPELINE_START = 'pipeline-start'
    PIPELINE_STAGE_START = 'pipeline-stage-start'
    PIPELINE_STAGE_COMPLETE = 'pipeline-stage-complete'
    PIPELINE_STAGE_FAILED = 'pipeline-stage-failed'
    PIPELINE_COMPLETE = 'pipeline-complete'
    PIPELINE_RESUMED = 'pipeline-resumed'

    # ========== 团队协作 ==========
    WORKER_JOINED = 'worker-joined'
    WORKER_LEFT = 'worker-left'
    TEAM_DISPATCH = 'team-dispatch'
    TEAM_RESULT = 'team-result'

    # ========== 审核/审查 ==========
    AUDIT_REQUEST = 'audit-request'
    AUDIT_RESULT = 'audit-result'
    REVIEW_REQUEST = 'review-request'
    REVIEW_RESULT = 'review-result'

    # ========== 自我修复 ==========
    ERROR_DETECTED = 'error-detected'
    ERROR_DIAGNOSED = 'error-diagnosed'
    FIX_APPLIED = 'fix-applied'
    HEAL_COMPLETE = 'heal-complete'
    HEAL_FAILED = 'heal-failed'

    # ========== 资源/性能 ==========
    BUDGET_EXCEEDED = 'budget-exceeded'
    RESOURCE_WARNING = 'resource-warning'

    # ========== 通知系统自身 ==========
    NOTIFICATION_SENT = 'notification-sent'
    NOTIFICATION_FAILED = 'notification-failed'

    # ========== 阻塞 ==========
    BLOCKED = 'blocked'


class VerbosityLevel(str, Enum):
    """Verbosity levels for notification filtering.

    - verbose: all text/tool call output
    - agent:   per-agent-call events (includes ask-user-question)
    - session: start/idle/stop/end + tmux tail snippet [DEFAULT]
    - minimal: start/stop/end only, no idle, no tmux tail
    """
    VERBOSE = "verbose"
    AGENT = "agent"
    SESSION = "session"
    MINIMAL = "minimal"


class NotificationPlatform(str, Enum):
    """Supported notification platforms."""
    DISCORD = "discord"
    DISCORD_BOT = "discord-bot"
    TELEGRAM = "telegram"
    SLACK = "slack"
    WEBHOOK = "webhook"




@dataclass
class DiscordNotificationConfig:
    """Discord webhook configuration."""
    enabled: bool = False
    webhook_url: str | None = None
    username: str | None = None
    mention: str | None = None


@dataclass
class DiscordBotNotificationConfig:
    """Discord Bot API configuration (bot token + channel ID)."""
    enabled: bool = False
    bot_token: str | None = None
    channel_id: str | None = None
    mention: str | None = None


@dataclass
class TelegramNotificationConfig:
    """Telegram platform configuration."""
    enabled: bool = False
    bot_token: str | None = None
    chat_id: str | None = None
    parse_mode: str | None = "Markdown"  # "Markdown" or "HTML"


@dataclass
class SlackNotificationConfig:
    """Slack platform configuration."""
    enabled: bool = False
    webhook_url: str | None = None
    channel: str | None = None
    username: str | None = None
    mention: str | None = None


@dataclass
class WebhookNotificationConfig:
    """Generic webhook configuration."""
    enabled: bool = False
    url: str | None = None
    headers: dict[str, str] | None = None
    method: str = "POST"  # "POST" or "PUT"


@dataclass
class CustomWebhookCommandConfig:
    """Generic custom webhook command config (normalized to OpenClaw gateway at runtime)."""
    enabled: bool | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    method: str | None = None
    timeout: int | None = None


@dataclass
class CustomCliCommandConfig:
    """Generic custom CLI command config (normalized to OpenClaw gateway at runtime)."""
    enabled: bool | None = None
    command: str | None = None
    timeout: int | None = None


# ===== Project B Enhancements: Hook Templates =====

@dataclass
class HookEventConfig:
    """Per-event hook configuration."""
    enabled: bool = True
    message_template: str | None = None


@dataclass
class HookNotificationConfig:
    """Top-level schema for the hookTemplates key in .omx-config.json."""
    version: str = "1.0"
    enabled: bool = True

    # Per-event hook configuration
    session_start: HookEventConfig | None = None
    session_stop: HookEventConfig | None = None
    session_end: HookEventConfig | None = None
    session_idle: HookEventConfig | None = None
    ask_user_question: HookEventConfig | None = None


@dataclass
class EventNotificationConfig:
    """Per-event notification configuration."""
    enabled: bool = True
    message_template: str | None = None
    discord: DiscordNotificationConfig | None = None
    discord_bot: DiscordBotNotificationConfig | None = None
    telegram: TelegramNotificationConfig | None = None
    slack: SlackNotificationConfig | None = None
    webhook: WebhookNotificationConfig | None = None


# ===== Project B Enhancements: Notification Profiles =====

@dataclass
class NotificationProfile:
    """Named notification profile configuration."""
    name: str
    description: str | None = None
    enabled: bool = True

    # Platform configs (same as FullNotificationConfig but for profiles)
    discord: DiscordNotificationConfig | None = None
    discord_bot: DiscordBotNotificationConfig | None = None
    telegram: TelegramNotificationConfig | None = None
    slack: SlackNotificationConfig | None = None
    webhook: WebhookNotificationConfig | None = None

    # Per-event configuration
    events: dict[str, EventNotificationConfig] | None = None


@dataclass
class NotificationProfilesConfig:
    """Top-level notifications block (supports both flat and profiled config)."""
    enabled: bool = True
    default_profile: str = "default"
    profiles: dict[str, NotificationProfile] = field(default_factory=dict)


@dataclass
class FullNotificationConfig:
    """Top-level notification configuration (stored in .omx-config.json)."""
    enabled: bool = False
    verbosity: VerbosityLevel = VerbosityLevel.SESSION

    # Default platform configs
    discord: DiscordNotificationConfig | None = None
    discord_bot: DiscordBotNotificationConfig | None = None
    telegram: TelegramNotificationConfig | None = None
    slack: SlackNotificationConfig | None = None
    webhook: WebhookNotificationConfig | None = None

    # OpenClaw gateway
    openclaw: dict[str, Any] | None = None
    custom_webhook_command: CustomWebhookCommandConfig | None = None
    custom_cli_command: CustomCliCommandConfig | None = None

    # Per-event configuration
    events: dict[str, EventNotificationConfig] | None = None

    # ===== Project B Enhancements =====
    # Notification Profiles
    profiles: NotificationProfilesConfig | None = None

    # Hook Templates
    hook_templates: HookNotificationConfig | None = None


# ===== Project B Enhancements: Reply Listener =====

@dataclass
class ReplyConfig:
    """Reply injection configuration."""
    enabled: bool = False
    poll_interval_ms: int = 3000
    max_message_length: int = 500
    rate_limit_per_minute: int = 10
    include_prefix: bool = True
    authorized_discord_user_ids: list[str] = field(default_factory=list)


@dataclass
class ReplyListenerState:
    """State of the reply listener daemon."""
    is_running: bool = False
    pid: int | None = None
    started_at: str | None = None
    last_poll_at: str | None = None
    telegram_last_update_id: int | None = None
    discord_last_message_id: str | None = None
    messages_injected: int = 0
    errors: int = 0
    last_error: str | None = None


@dataclass
class ReplyListenerDaemonConfig(ReplyConfig):
    """Configuration for the reply listener daemon."""
    discord_enabled: bool = False
    telegram_enabled: bool = False
    discordBotToken: str | None = None
    telegramBotToken: str | None = None
    authorized_users: list[str] = field(default_factory=list)
    rate_limit_per_second: float = 1.0
    rate_limit_burst: int = 5
    poll_interval_seconds: float = 5.0
    state_dir: str | None = None


@dataclass
class TeamMailboxMessage:
    """Message in team mailbox (for inter-worker communication)."""
    message_id: str
    from_worker: str
    to_worker: str
    body: str
    created_at: str
    notified_at: str | None = None
    delivered_at: str | None = None


@dataclass
class TeamMailbox:
    """Worker mailbox container."""
    worker: str
    messages: list[TeamMailboxMessage]


# ===== Project B Enhancements: Validation Utilities =====

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


@dataclass
class FullNotificationPayload:
    """Payload sent with each notification."""
    event: NotificationEvent
    session_id: str
    message: str
    timestamp: str

    # Optional fields
    tmux_session: str | None = None
    project_path: str | None = None
    project_name: str | None = None
    modes_used: list[str] | None = None
    context_summary: str | None = None
    duration_ms: int | None = None
    agents_spawned: int | None = None
    agents_completed: int | None = None
    reason: str | None = None
    active_mode: str | None = None
    iteration: int | None = None
    max_iterations: int | None = None
    question: str | None = None
    incomplete_tasks: int | None = None
    tmux_pane: str | None = None


@dataclass
class NotificationResult:
    """Result of a single notification dispatch."""
    platform: NotificationPlatform
    success: bool
    error: str | None = None
    response: dict[str, Any] | None = None


@dataclass
class DispatchResult:
    """Aggregate result of dispatching to all platforms."""
    results: list[NotificationResult] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        """Check if all notifications succeeded."""
        return all(r.success for r in self.results)

    @property
    def any_succeeded(self) -> bool:
        """Check if any notification succeeded."""
        return any(r.success for r in self.results)


# Type aliases for backward compatibility
NotificationConfig = FullNotificationConfig
NotificationPayload = FullNotificationPayload
