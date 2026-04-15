"""Notifications 配置管理

从 oh-my-codex-main/src/notifications/config.ts 汲取。

功能:
- 加载和解析通知配置
- 支持从环境变量读取敏感信息
- 配置验证
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from .types import (
    DiscordBotNotificationConfig,
    DiscordNotificationConfig,
    FullNotificationConfig,
    ReplyConfig,
    SlackNotificationConfig,
    TelegramNotificationConfig,
    VerbosityLevel,
    WebhookNotificationConfig,
)


# ===== 常量 =====
DEFAULT_CONFIG_PATHS = [
    '.omx-config.json',
    '.omx/.omx-config.json',
]


# ===== 环境变量映射 =====
ENV_VAR_MAPPINGS = {
    'OMX_DISCORD_WEBHOOK_URL': 'discord.webhook_url',
    'OMX_DISCORD_USERNAME': 'discord.username',
    'OMX_DISCORD_MENTION': 'discord.mention',
    'OMX_DISCORD_NOTIFIER_BOT_TOKEN': 'discord_bot.bot_token',
    'OMX_DISCORD_NOTIFIER_CHANNEL': 'discord_bot.channel_id',
    'OMX_TELEGRAM_BOT_TOKEN': 'telegram.bot_token',
    'OMX_TELEGRAM_CHAT_ID': 'telegram.chat_id',
    'OMX_SLACK_WEBHOOK_URL': 'slack.webhook_url',
    'OMX_SLACK_CHANNEL': 'slack.channel',
    'OMX_SLACK_USERNAME': 'slack.username',
    'OMX_SLACK_MENTION': 'slack.mention',
    'OMX_WEBHOOK_URL': 'webhook.url',
    'OMX_NOTIFICATIONS_ENABLED': 'enabled',
}


# ===== 解析函数 =====
def parse_mention_allowed_mentions(mention: str) -> dict:
    """解析 mention 字符串

    支持:
    - <@USER_ID> -> user
    - <@&ROLE_ID> -> role
    - 多个用空格分隔

    返回:
        {'parse': [], 'users': [], 'roles': []}
    """
    import re

    users: list[str] = []
    roles: list[str] = []

    if not mention:
        return {'parse': [], 'users': users, 'roles': roles}

    # 匹配用户提及 <@123456>
    user_matches = re.findall(r'<@(\d+)>', mention)
    users.extend(user_matches)

    # 匹配角色提及 <@&789>
    role_matches = re.findall(r'<@&(\d+)>', mention)
    roles.extend(role_matches)

    parse: list[str] = []
    if not users and not roles:
        parse.append('everyone')

    return {'parse': parse, 'users': users, 'roles': roles}


def _apply_env_overrides(config: FullNotificationConfig) -> None:
    """应用环境变量覆盖"""
    for env_var, path in ENV_VAR_MAPPINGS.items():
        value = os.environ.get(env_var)
        if value is None:
            continue

        parts = path.split('.')
        obj = config
        for part in parts[:-1]:
            obj = getattr(obj, part, None) or {}
            if not isinstance(obj, dict):
                obj = {}

        final_key = parts[-1]
        if isinstance(obj, dict):
            # 从 dataclass 转换
            pass
        else:
            # 设置属性
            try:
                if final_key == 'enabled':
                    value = value.lower() in ('1', 'true', 'yes')
                setattr(obj, final_key, value)
            except (AttributeError, TypeError):
                pass


def _from_dict(cls, data: dict) -> Optional[object]:
    """从字典创建 dataclass 实例"""
    if not data:
        return None
    try:
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})
    except TypeError:
        return None


def load_notification_config(
    config_path: Optional[str] = None,
    cwd: Optional[str] = None,
) -> FullNotificationConfig:
    """加载通知配置

    参数:
        config_path: 配置文件路径，如果为 None 则自动搜索
        cwd: 工作目录，用于搜索配置文件

    返回:
        FullNotificationConfig 实例
    """
    config = FullNotificationConfig()

    # 查找配置文件
    search_paths = [config_path] if config_path else []

    if cwd:
        for default_name in DEFAULT_CONFIG_PATHS:
            search_paths.append(str(Path(cwd) / default_name))

    config_data = None
    for path in search_paths:
        if path and Path(path).exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                break
            except (OSError, json.JSONDecodeError):
                continue

    # 解析配置
    if config_data and isinstance(config_data, dict):
        # 顶级配置
        if 'enabled' in config_data:
            config.enabled = bool(config_data['enabled'])

        if 'verbosity' in config_data:
            try:
                config.verbosity = VerbosityLevel(config_data['verbosity'])
            except ValueError:
                pass

        # 平台配置
        if 'discord' in config_data:
            config.discord = _from_dict(
                DiscordNotificationConfig,
                config_data['discord']
            )

        if 'discord-bot' in config_data:
            config.discord_bot = _from_dict(
                DiscordBotNotificationConfig,
                config_data['discord-bot']
            )

        if 'telegram' in config_data:
            config.telegram = _from_dict(
                TelegramNotificationConfig,
                config_data['telegram']
            )

        if 'slack' in config_data:
            config.slack = _from_dict(
                SlackNotificationConfig,
                config_data['slack']
            )

        if 'webhook' in config_data:
            config.webhook = _from_dict(
                WebhookNotificationConfig,
                config_data['webhook']
            )

        # 事件配置
        if 'events' in config_data and isinstance(config_data['events'], dict):
            config.events = config_data['events']

    # 应用环境变量覆盖
    _apply_env_overrides(config)

    return config


def load_reply_config(
    config_path: Optional[str] = None,
    cwd: Optional[str] = None,
) -> ReplyConfig:
    """加载 Reply 配置"""
    config = ReplyConfig()

    search_paths = [config_path] if config_path else []
    if cwd:
        for default_name in DEFAULT_CONFIG_PATHS:
            search_paths.append(str(Path(cwd) / default_name))

    config_data = None
    for path in search_paths:
        if path and Path(path).exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    full_data = json.load(f)
                    if isinstance(full_data, dict):
                        config_data = full_data.get('reply')
                break
            except (OSError, json.JSONDecodeError):
                continue

    if config_data and isinstance(config_data, dict):
        config.enabled = bool(config_data.get('enabled', False))
        config.poll_interval_ms = int(config_data.get('pollIntervalMs', 3000))
        config.max_message_length = int(config_data.get('maxMessageLength', 500))
        config.rate_limit_per_minute = int(config_data.get('rateLimitPerMinute', 10))
        config.include_prefix = bool(config_data.get('includePrefix', True))
        config.authorized_discord_user_ids = config_data.get(
            'authorizedDiscordUserIds', []
        )

    return config


def is_notifications_enabled(config: Optional[FullNotificationConfig] = None) -> bool:
    """检查通知是否启用

    参数:
        config: 配置，如果为 None 则尝试自动加载

    返回:
        是否启用
    """
    if config is None:
        config = load_notification_config()
    return config.enabled


# ===== 导出 =====
__all__ = [
    "parse_mention_allowed_mentions",
    "load_notification_config",
    "load_reply_config",
    "is_notifications_enabled",
]
