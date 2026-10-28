"""Tests for src.notification.config — 配置加载/解析/校验真实行为。

覆盖：
1. 配置文件的定位与容错加载（缺失 / 非法 JSON / 可读路径）
2. 各平台 raw dict → dataclass 的字段映射（camelCase/snake_case/环境变量回退/开关语义）
3. verbosity 过滤矩阵与 per-event 开关
4. mention 格式校验
5. 顶层 get_notification_config 的组装与 None 判定
"""

from __future__ import annotations

import json

import pytest

from src.notification import config as cfg
from src.notification.types import (
    DiscordNotificationConfig,
    EventNotificationConfig,
    FullNotificationConfig,
    NotificationEvent,
    NotificationProfile,
    NotificationProfilesConfig,
    ReplyConfig,
    SlackNotificationConfig,
    TelegramNotificationConfig,
    VerbosityLevel,
    WebhookNotificationConfig,
)

_ENV_NAMES = [
    "OMX_NOTIFY_DISCORD_WEBHOOK",
    "OMX_DISCORD_BOT_TOKEN",
    "OMX_DISCORD_CHANNEL_ID",
    "OMX_TELEGRAM_BOT_TOKEN",
    "OMX_TELEGRAM_CHAT_ID",
    "OMX_SLACK_WEBHOOK",
    "OMX_WEBHOOK_URL",
    "OMX_NOTIFICATION_PROFILE",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """隔离宿主环境变量，避免测试随机器环境变化。"""
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def write_config(directory, data) -> None:
    (directory / cfg.CONFIG_FILENAME).write_text(
        json.dumps(data), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 路径 / 文件加载
# ---------------------------------------------------------------------------


class TestConfigFilePath:
    def test_config_dir_defaults_to_cwd(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        assert cfg.get_config_dir() == tmp_path

    def test_config_dir_uses_explicit_cwd(self, tmp_path):
        assert cfg.get_config_dir(str(tmp_path / "sub")) == tmp_path / "sub"

    def test_config_file_path_appends_filename(self, tmp_path):
        assert cfg.config_file_path(str(tmp_path)) == tmp_path / cfg.CONFIG_FILENAME


class TestLoadConfigFromFile:
    def test_missing_file_returns_none(self, tmp_path):
        assert cfg.load_config_from_file(str(tmp_path)) is None

    def test_valid_json_is_parsed(self, tmp_path):
        write_config(tmp_path, {"enabled": True, "verbosity": "verbose"})
        assert cfg.load_config_from_file(str(tmp_path)) == {
            "enabled": True,
            "verbosity": "verbose",
        }

    def test_malformed_json_returns_none(self, tmp_path):
        (tmp_path / cfg.CONFIG_FILENAME).write_text("{not json", encoding="utf-8")
        assert cfg.load_config_from_file(str(tmp_path)) is None

    def test_unreadable_path_returns_none(self, tmp_path):
        # 目录不能当文件读 → OSError 分支
        (tmp_path / cfg.CONFIG_FILENAME).mkdir()
        assert cfg.load_config_from_file(str(tmp_path)) is None


# ---------------------------------------------------------------------------
# 环境变量助手
# ---------------------------------------------------------------------------


class TestGetEnvVar:
    def test_returns_value_when_present(self, monkeypatch):
        monkeypatch.setenv("OMX_WEBHOOK_URL", "https://hook.example/x")
        assert cfg.get_env_var("OMX_WEBHOOK_URL") == "https://hook.example/x"

    def test_missing_returns_default(self):
        assert cfg.get_env_var("OMX_WEBHOOK_URL", "fallback") == "fallback"
        assert cfg.get_env_var("OMX_WEBHOOK_URL") is None

    def test_blank_value_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("OMX_WEBHOOK_URL", "   ")
        assert cfg.get_env_var("OMX_WEBHOOK_URL", "fallback") == "fallback"


# ---------------------------------------------------------------------------
# 平台配置解析
# ---------------------------------------------------------------------------


class TestResolveDiscordConfig:
    def test_none_raw(self):
        assert cfg.resolve_discord_config(None) is None
        assert cfg.resolve_discord_config({}) is None

    def test_disabled_returns_none_even_with_url(self):
        assert cfg.resolve_discord_config(
            {"enabled": False, "webhookUrl": "https://d/x"}
        ) is None

    def test_camel_case_keys(self):
        resolved = cfg.resolve_discord_config({
            "enabled": True,
            "webhookUrl": "https://discord/webhook",
            "username": "clawd",
            "mention": "<@123456789012345678>",
        })
        assert isinstance(resolved, DiscordNotificationConfig)
        assert resolved.enabled is True
        assert resolved.webhook_url == "https://discord/webhook"
        assert resolved.username == "clawd"
        assert resolved.mention == "<@123456789012345678>"

    def test_snake_case_keys(self):
        resolved = cfg.resolve_discord_config(
            {"enabled": True, "webhook_url": "https://discord/snake"}
        )
        assert resolved.webhook_url == "https://discord/snake"

    def test_env_fallback_when_url_absent(self, monkeypatch):
        monkeypatch.setenv("OMX_NOTIFY_DISCORD_WEBHOOK", "https://env/webhook")
        assert cfg.resolve_discord_config({"enabled": True}).webhook_url == (
            "https://env/webhook"
        )

    def test_url_none_when_no_source(self):
        assert cfg.resolve_discord_config({"enabled": True}).webhook_url is None


class TestResolveDiscordBotConfig:
    def test_disabled_or_empty(self):
        assert cfg.resolve_discord_bot_config(None) is None
        assert cfg.resolve_discord_bot_config({"enabled": False}) is None

    def test_explicit_tokens(self):
        resolved = cfg.resolve_discord_bot_config({
            "enabled": True,
            "botToken": "tok",
            "channelId": "123",
            "mention": "<@&123456789012345678>",
        })
        assert resolved.bot_token == "tok"
        assert resolved.channel_id == "123"
        assert resolved.mention == "<@&123456789012345678>"

    def test_snake_case_tokens(self):
        resolved = cfg.resolve_discord_bot_config({
            "enabled": True,
            "bot_token": "snake-tok",
            "channel_id": "456",
        })
        assert (resolved.bot_token, resolved.channel_id) == ("snake-tok", "456")

    def test_env_fallback_for_both_fields(self, monkeypatch):
        monkeypatch.setenv("OMX_DISCORD_BOT_TOKEN", "env-tok")
        monkeypatch.setenv("OMX_DISCORD_CHANNEL_ID", "789")
        resolved = cfg.resolve_discord_bot_config({"enabled": True})
        assert (resolved.bot_token, resolved.channel_id) == ("env-tok", "789")


class TestResolveTelegramConfig:
    def test_disabled_or_empty(self):
        assert cfg.resolve_telegram_config(None) is None
        assert cfg.resolve_telegram_config({"enabled": False}) is None

    def test_camel_case_with_parse_mode(self):
        resolved = cfg.resolve_telegram_config({
            "enabled": True,
            "botToken": "t",
            "chatId": "42",
            "parseMode": "HTML",
        })
        assert isinstance(resolved, TelegramNotificationConfig)
        assert (resolved.bot_token, resolved.chat_id, resolved.parse_mode) == (
            "t", "42", "HTML",
        )

    def test_parse_mode_defaults_to_markdown(self):
        assert cfg.resolve_telegram_config(
            {"enabled": True, "bot_token": "x", "chat_id": "1"}
        ).parse_mode == "Markdown"

    def test_env_fallback(self, monkeypatch):
        monkeypatch.setenv("OMX_TELEGRAM_BOT_TOKEN", "env-t")
        monkeypatch.setenv("OMX_TELEGRAM_CHAT_ID", "99")
        resolved = cfg.resolve_telegram_config({"enabled": True})
        assert (resolved.bot_token, resolved.chat_id) == ("env-t", "99")


class TestResolveSlackConfig:
    def test_disabled_or_empty(self):
        assert cfg.resolve_slack_config(None) is None
        assert cfg.resolve_slack_config({"enabled": False}) is None

    def test_full_mapping(self):
        resolved = cfg.resolve_slack_config({
            "enabled": True,
            "webhookUrl": "https://slack/hook",
            "channel": "#dev",
            "username": "clawd",
            "mention": "<!here>",
        })
        assert isinstance(resolved, SlackNotificationConfig)
        assert resolved.webhook_url == "https://slack/hook"
        assert resolved.channel == "#dev"
        assert resolved.username == "clawd"
        assert resolved.mention == "<!here>"

    def test_env_fallback_for_webhook(self, monkeypatch):
        monkeypatch.setenv("OMX_SLACK_WEBHOOK", "https://env-slack/hook")
        assert cfg.resolve_slack_config({"enabled": True}).webhook_url == (
            "https://env-slack/hook"
        )


class TestResolveWebhookConfig:
    def test_disabled_or_empty(self):
        assert cfg.resolve_webhook_config(None) is None
        assert cfg.resolve_webhook_config({"enabled": False}) is None

    def test_defaults_method_to_post(self):
        resolved = cfg.resolve_webhook_config(
            {"enabled": True, "url": "https://hook/x"}
        )
        assert isinstance(resolved, WebhookNotificationConfig)
        assert resolved.url == "https://hook/x"
        assert resolved.method == "POST"
        assert resolved.headers is None

    def test_explicit_method_and_headers(self):
        resolved = cfg.resolve_webhook_config({
            "enabled": True,
            "url": "https://hook/y",
            "method": "PUT",
            "headers": {"X-Token": "abc"},
        })
        assert (resolved.method, resolved.headers) == ("PUT", {"X-Token": "abc"})

    def test_env_fallback_for_url(self, monkeypatch):
        monkeypatch.setenv("OMX_WEBHOOK_URL", "https://env/hook")
        assert cfg.resolve_webhook_config({"enabled": True}).url == "https://env/hook"


class TestResolveEventConfig:
    def test_none_and_empty(self):
        assert cfg.resolve_event_config(None) is None
        assert cfg.resolve_event_config({}) is None

    def test_defaults(self):
        resolved = cfg.resolve_event_config({"message_template": "hi {session}"})
        assert isinstance(resolved, EventNotificationConfig)
        assert resolved.enabled is True
        assert resolved.message_template == "hi {session}"
        assert resolved.discord is None

    def test_camel_case_template_and_platforms(self):
        resolved = cfg.resolve_event_config({
            "enabled": False,
            "messageTemplate": "tmpl",
            "discord": {"enabled": True, "webhookUrl": "https://d"},
            "discord-bot": {"enabled": True, "botToken": "b", "channelId": "c"},
            "telegram": {"enabled": True, "botToken": "t", "chatId": "1"},
            "slack": {"enabled": True, "webhookUrl": "https://s"},
            "webhook": {"enabled": True, "url": "https://w"},
        })
        assert resolved.enabled is False
        assert resolved.message_template == "tmpl"
        assert resolved.discord.webhook_url == "https://d"
        assert resolved.discord_bot.channel_id == "c"
        assert resolved.telegram.chat_id == "1"
        assert resolved.slack.webhook_url == "https://s"
        assert resolved.webhook.url == "https://w"

    def test_discord_bot_snake_case_key(self):
        resolved = cfg.resolve_event_config({
            "discord_bot": {"enabled": True, "bot_token": "b", "channel_id": "c"},
        })
        assert resolved.discord_bot.bot_token == "b"


# ---------------------------------------------------------------------------
# mention 校验
# ---------------------------------------------------------------------------


class TestMentionValidation:
    @pytest.mark.parametrize(("raw", "expected"), [
        ("<@123456789012345678>", "<@123456789012345678>"),
        ("<@!123456789012345678>", "<@!123456789012345678>"),
        ("  <@123456789012345678>  ", "<@123456789012345678>"),
    ])
    def test_discord_user_mention_valid(self, raw, expected):
        assert cfg.validate_discord_mention(raw) == expected

    def test_discord_role_mention_valid(self):
        assert cfg.validate_discord_mention("<@&123456789012345678>") == (
            "<@&123456789012345678>"
        )

    @pytest.mark.parametrize("raw", [
        None,
        "",
        "<@123>",                      # 位数不足
        "123456789012345678",          # 缺尖括号
        "<@everyone>",
        "<@&123>",
    ])
    def test_discord_mention_invalid(self, raw):
        assert cfg.validate_discord_mention(raw) is None

    @pytest.mark.parametrize("raw", [
        "<@U0123456789>",
        "<@W0123456789>",
        "<!channel>",
        "<!here>",
        "<!everyone>",
        "<!subteam^S0123456789>",
    ])
    def test_slack_mention_valid(self, raw):
        assert cfg.validate_slack_mention(raw) == raw

    @pytest.mark.parametrize("raw", [
        None,
        "",
        "<@U012>",
        "<@X0123456789>",
        "<!here!>",
        "@here",
    ])
    def test_slack_mention_invalid(self, raw):
        assert cfg.validate_slack_mention(raw) is None

    def test_allowed_mentions_for_user(self):
        assert cfg.parse_mention_allowed_mentions("<@!123456789012345678>") == {
            "users": ["123456789012345678"]
        }

    def test_allowed_mentions_for_role(self):
        assert cfg.parse_mention_allowed_mentions("<@&123456789012345678>") == {
            "roles": ["123456789012345678"]
        }

    @pytest.mark.parametrize("raw", [None, "", "<!here>", "plain"])
    def test_allowed_mentions_empty_for_non_discord(self, raw):
        assert cfg.parse_mention_allowed_mentions(raw) == {}


# ---------------------------------------------------------------------------
# hook 模板 / reply / profile
# ---------------------------------------------------------------------------


class TestResolveHookConfig:
    def test_none_and_empty(self):
        assert cfg.resolve_hook_config(None) is None
        assert cfg.resolve_hook_config({}) is None

    def test_defaults(self):
        resolved = cfg.resolve_hook_config({"version": "2.0"})
        assert resolved.version == "2.0"
        assert resolved.enabled is True
        assert resolved.session_start is None

    def test_version_and_enabled_defaults(self):
        resolved = cfg.resolve_hook_config({"session_end": {"enabled": False}})
        assert resolved.version == "1.0"
        assert resolved.enabled is True
        assert resolved.session_end.enabled is False
        assert resolved.session_end.message_template is None

    def test_per_event_templates(self):
        resolved = cfg.resolve_hook_config({
            "enabled": False,
            "session_start": {"message_template": "start {project}"},
            "session_stop": {"enabled": False, "message_template": "stop"},
            "session_idle": {"message_template": "idle"},
            "ask_user_question": {"message_template": "ask"},
        })
        assert resolved.enabled is False
        assert resolved.session_start.message_template == "start {project}"
        assert resolved.session_start.enabled is True
        assert resolved.session_stop.enabled is False
        assert resolved.session_idle.message_template == "idle"
        assert resolved.ask_user_question.message_template == "ask"
        assert resolved.session_end is None


class TestResolveReplyConfig:
    def test_none_and_empty(self):
        assert cfg.resolve_reply_config(None) is None
        assert cfg.resolve_reply_config({}) is None

    def test_defaults(self):
        resolved = cfg.resolve_reply_config({"enabled": True})
        assert isinstance(resolved, ReplyConfig)
        assert resolved.enabled is True
        assert resolved.poll_interval_ms == 3000
        assert resolved.max_message_length == 500
        assert resolved.rate_limit_per_minute == 10
        assert resolved.include_prefix is True
        assert resolved.authorized_discord_user_ids == []

    def test_string_numbers_are_coerced(self):
        resolved = cfg.resolve_reply_config({
            "poll_interval_ms": "500",
            "max_message_length": "100",
            "rate_limit_per_minute": "3",
            "include_prefix": False,
            "authorized_discord_user_ids": ["u1"],
        })
        assert resolved.poll_interval_ms == 500
        assert resolved.max_message_length == 100
        assert resolved.rate_limit_per_minute == 3
        assert resolved.include_prefix is False
        assert resolved.authorized_discord_user_ids == ["u1"]

    def test_non_numeric_value_raises(self):
        with pytest.raises(ValueError):
            cfg.resolve_reply_config({"poll_interval_ms": "soon"})


class TestResolveProfiles:
    def test_resolve_profile_defaults(self):
        profile = cfg.resolve_profile({})
        assert isinstance(profile, NotificationProfile)
        assert profile.name == "default"
        assert profile.enabled is True
        assert profile.events == {}
        assert profile.discord is None

    def test_resolve_profile_full(self):
        profile = cfg.resolve_profile({
            "name": "ops",
            "description": "oncall",
            "enabled": False,
            "discord": {"enabled": True, "webhookUrl": "https://d"},
            "telegram": {"enabled": True, "botToken": "t", "chatId": "1"},
            "events": {"session-start": {"enabled": True, "messageTemplate": "hi"}},
        })
        assert profile.name == "ops"
        assert profile.description == "oncall"
        assert profile.enabled is False
        assert profile.discord.webhook_url == "https://d"
        assert profile.telegram.chat_id == "1"
        assert profile.events["session-start"].message_template == "hi"

    def test_resolve_profiles_config(self):
        resolved = cfg.resolve_profiles_config({
            "enabled": False,
            "default_profile": "ops",
            "profiles": {
                "ops": {"name": "ops", "slack": {"enabled": True,
                                                 "webhookUrl": "https://s"}},
                "dev": {"name": "dev"},
            },
        })
        assert isinstance(resolved, NotificationProfilesConfig)
        assert resolved.enabled is False
        assert resolved.default_profile == "ops"
        assert set(resolved.profiles) == {"ops", "dev"}
        assert resolved.profiles["ops"].slack.webhook_url == "https://s"

    def test_resolve_profiles_config_defaults(self):
        resolved = cfg.resolve_profiles_config({"enabled": True})
        assert resolved.enabled is True
        assert resolved.default_profile == cfg.DEFAULT_PROFILE
        assert resolved.profiles == {}

    def test_none_raw(self):
        assert cfg.resolve_profiles_config(None) is None
        assert cfg.resolve_profiles_config({}) is None


# ---------------------------------------------------------------------------
# verbosity / 事件过滤
# ---------------------------------------------------------------------------


class TestVerbosity:
    def test_get_verbosity_from_enum(self):
        config = FullNotificationConfig(verbosity=VerbosityLevel.VERBOSE)
        assert cfg.get_verbosity(config) == VerbosityLevel.VERBOSE

    def test_get_verbosity_from_string(self):
        config = FullNotificationConfig(verbosity="agent")
        assert cfg.get_verbosity(config) == VerbosityLevel.AGENT

    def test_get_verbosity_invalid_falls_back_to_session(self):
        config = FullNotificationConfig(verbosity="shouty")
        assert cfg.get_verbosity(config) == VerbosityLevel.SESSION

    def test_get_verbosity_empty_falls_back_to_session(self):
        config = FullNotificationConfig(verbosity="")
        assert cfg.get_verbosity(config) == VerbosityLevel.SESSION

    @pytest.mark.parametrize(("verbosity", "allowed", "blocked"), [
        (VerbosityLevel.VERBOSE,
         {NotificationEvent.TASK_STARTED, NotificationEvent.ERROR_DETECTED,
          NotificationEvent.BLOCKED},
         set()),
        (VerbosityLevel.AGENT,
         {NotificationEvent.ASK_USER_QUESTION, NotificationEvent.SESSION_START,
          NotificationEvent.SESSION_IDLE},
         {NotificationEvent.TASK_STARTED, NotificationEvent.ERROR_DETECTED}),
        (VerbosityLevel.SESSION,
         {NotificationEvent.SESSION_START, NotificationEvent.SESSION_END,
          NotificationEvent.SESSION_STOP, NotificationEvent.SESSION_IDLE},
         {NotificationEvent.ASK_USER_QUESTION, NotificationEvent.TASK_STARTED}),
        (VerbosityLevel.MINIMAL,
         {NotificationEvent.SESSION_START, NotificationEvent.SESSION_END},
         {NotificationEvent.SESSION_IDLE, NotificationEvent.SESSION_STOP,
          NotificationEvent.ASK_USER_QUESTION}),
    ])
    def test_allowed_matrix(self, verbosity, allowed, blocked):
        for event in allowed:
            assert cfg.is_event_allowed_by_verbosity(event, verbosity) is True
        for event in blocked:
            assert cfg.is_event_allowed_by_verbosity(event, verbosity) is False

    def test_unknown_verbosity_allows_nothing(self):
        assert cfg.is_event_allowed_by_verbosity(
            NotificationEvent.SESSION_START, "nonsense"
        ) is False


class TestTmuxTailInclusion:
    def test_minimal_never_includes(self):
        config = FullNotificationConfig(verbosity=VerbosityLevel.MINIMAL)
        assert cfg.should_include_tmux_tail(config, NotificationEvent.SESSION_END) is False

    def test_verbose_always_includes(self):
        config = FullNotificationConfig(verbosity=VerbosityLevel.VERBOSE)
        assert cfg.should_include_tmux_tail(config, NotificationEvent.SESSION_START) is True

    def test_session_only_for_stop_and_end(self):
        config = FullNotificationConfig(verbosity=VerbosityLevel.SESSION)
        assert cfg.should_include_tmux_tail(config, NotificationEvent.SESSION_STOP) is True
        assert cfg.should_include_tmux_tail(config, NotificationEvent.SESSION_END) is True
        assert cfg.should_include_tmux_tail(config, NotificationEvent.SESSION_START) is False
        assert cfg.should_include_tmux_tail(config, NotificationEvent.SESSION_IDLE) is False


class TestIsEventEnabled:
    def test_disabled_config_blocks_everything(self):
        config = FullNotificationConfig(enabled=False)
        assert cfg.is_event_enabled(config, NotificationEvent.SESSION_START) is False

    def test_verbosity_filter_applies(self):
        config = FullNotificationConfig(
            enabled=True, verbosity=VerbosityLevel.MINIMAL
        )
        assert cfg.is_event_enabled(config, NotificationEvent.SESSION_IDLE) is False
        assert cfg.is_event_enabled(config, NotificationEvent.SESSION_START) is True

    def test_per_event_override_disables(self):
        config = FullNotificationConfig(
            enabled=True,
            verbosity=VerbosityLevel.SESSION,
            events={"session-start": EventNotificationConfig(enabled=False)},
        )
        assert cfg.is_event_enabled(config, NotificationEvent.SESSION_START) is False
        assert cfg.is_event_enabled(config, NotificationEvent.SESSION_END) is True

    def test_per_event_override_enables_unlisted_false(self):
        config = FullNotificationConfig(
            enabled=True,
            verbosity=VerbosityLevel.SESSION,
            events={"session-start": EventNotificationConfig(enabled=True)},
        )
        assert cfg.is_event_enabled(config, NotificationEvent.SESSION_START) is True


class TestGetEnabledPlatforms:
    def test_empty(self):
        assert cfg.get_enabled_platforms(FullNotificationConfig()) == []

    def test_all_platforms(self):
        config = FullNotificationConfig(
            enabled=True,
            discord=DiscordNotificationConfig(enabled=True),
            discord_bot=DiscordNotificationConfig(enabled=True),  # 同构对象即可
            telegram=TelegramNotificationConfig(enabled=True),
            slack=SlackNotificationConfig(enabled=True),
            webhook=WebhookNotificationConfig(enabled=True),
        )
        assert cfg.get_enabled_platforms(config) == [
            "discord", "discord-bot", "telegram", "slack", "webhook",
        ]

    def test_skips_disabled_platforms(self):
        config = FullNotificationConfig(
            enabled=True,
            discord=DiscordNotificationConfig(enabled=False),
            telegram=TelegramNotificationConfig(enabled=True),
        )
        assert cfg.get_enabled_platforms(config) == ["telegram"]


# ---------------------------------------------------------------------------
# 活跃 profile
# ---------------------------------------------------------------------------


class TestActiveProfile:
    def test_default_profile(self):
        assert cfg.get_active_profile_name() == cfg.DEFAULT_PROFILE

    def test_profile_from_env(self, monkeypatch):
        monkeypatch.setenv("OMX_NOTIFICATION_PROFILE", "ops")
        assert cfg.get_active_profile_name() == "ops"

    def test_blank_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("OMX_NOTIFICATION_PROFILE", "  ")
        assert cfg.get_active_profile_name() == cfg.DEFAULT_PROFILE


# ---------------------------------------------------------------------------
# 顶层组装
# ---------------------------------------------------------------------------


class TestGetNotificationConfig:
    def test_no_config_file_returns_none(self, tmp_path):
        assert cfg.get_notification_config(cwd=str(tmp_path)) is None

    def test_malformed_config_file_returns_none(self, tmp_path):
        (tmp_path / cfg.CONFIG_FILENAME).write_text("<<<", encoding="utf-8")
        assert cfg.get_notification_config(cwd=str(tmp_path)) is None

    def test_no_enabled_platform_returns_none(self, tmp_path):
        write_config(tmp_path, {
            "enabled": True,
            "telegram": {"enabled": False},
        })
        assert cfg.get_notification_config(cwd=str(tmp_path)) is None

    def test_minimal_enabled_config(self, tmp_path):
        write_config(tmp_path, {
            "enabled": True,
            "verbosity": "minimal",
            "telegram": {"enabled": True, "botToken": "t", "chatId": "1"},
        })
        config = cfg.get_notification_config(cwd=str(tmp_path))
        assert isinstance(config, FullNotificationConfig)
        assert config.enabled is True
        assert config.verbosity == "minimal"
        assert cfg.get_verbosity(config) == VerbosityLevel.MINIMAL
        assert config.telegram.chat_id == "1"
        assert config.discord is None
        assert config.events == {}

    def test_top_level_defaults_when_keys_missing(self, tmp_path):
        write_config(tmp_path, {
            "webhook": {"enabled": True, "url": "https://w"},
        })
        config = cfg.get_notification_config(cwd=str(tmp_path))
        assert config.enabled is False
        assert config.verbosity == VerbosityLevel.SESSION.value

    def test_events_and_discord_bot_snake_key(self, tmp_path):
        write_config(tmp_path, {
            "enabled": True,
            "discord_bot": {"enabled": True, "botToken": "b", "channelId": "c"},
            "events": {
                "session-end": {"enabled": False, "messageTemplate": "done"},
            },
        })
        config = cfg.get_notification_config(cwd=str(tmp_path))
        assert config.discord_bot.bot_token == "b"
        assert config.events["session-end"].enabled is False
        assert config.events["session-end"].message_template == "done"

    def test_profiles_block_is_resolved(self, tmp_path):
        write_config(tmp_path, {
            "enabled": True,
            "slack": {"enabled": True, "webhookUrl": "https://s"},
            "profiles": {
                "enabled": True,
                "default_profile": "ops",
                "profiles": {"ops": {"name": "ops"}, "dev": {"name": "dev"}},
            },
        })
        config = cfg.get_notification_config(cwd=str(tmp_path))
        assert config.profiles.default_profile == "ops"
        assert set(config.profiles.profiles) == {"ops", "dev"}

    def test_hook_templates_camel_key(self, tmp_path):
        write_config(tmp_path, {
            "enabled": True,
            "slack": {"enabled": True, "webhookUrl": "https://s"},
            "hookTemplates": {"version": "3.0", "session_start": {"enabled": False}},
        })
        config = cfg.get_notification_config(cwd=str(tmp_path))
        assert config.hook_templates.version == "3.0"
        assert config.hook_templates.session_start.enabled is False

    def test_hook_templates_snake_key(self, tmp_path):
        write_config(tmp_path, {
            "enabled": True,
            "slack": {"enabled": True, "webhookUrl": "https://s"},
            "hook_templates": {"version": "1.5"},
        })
        config = cfg.get_notification_config(cwd=str(tmp_path))
        assert config.hook_templates.version == "1.5"

    def test_absent_hook_templates_and_profiles_are_none(self, tmp_path):
        write_config(tmp_path, {
            "enabled": True,
            "slack": {"enabled": True, "webhookUrl": "https://s"},
        })
        config = cfg.get_notification_config(cwd=str(tmp_path))
        assert config.hook_templates is None
        assert config.profiles is None

    def test_reply_block_is_resolved(self, tmp_path):
        write_config(tmp_path, {
            "enabled": True,
            "slack": {"enabled": True, "webhookUrl": "https://s"},
            "reply": {"enabled": True, "poll_interval_ms": 1500},
        })
        config = cfg.get_notification_config(cwd=str(tmp_path))
        reply = getattr(config, "reply", None)
        assert reply is not None, "reply 配置应可从 config 访问"
        assert reply.poll_interval_ms == 1500

    def test_reply_absent_when_not_configured(self, tmp_path):
        write_config(tmp_path, {
            "enabled": True,
            "slack": {"enabled": True, "webhookUrl": "https://s"},
        })
        config = cfg.get_notification_config(cwd=str(tmp_path))
        assert getattr(config, "reply", None) is None

    def test_profile_name_argument_does_not_change_result(self, tmp_path):
        """当前实现忽略 profile_name（config.py:435 表达式结果被丢弃）。

        此用例固定当前可观察行为并作为缺陷记录，两处调用结果必须一致。
        """
        write_config(tmp_path, {
            "enabled": True,
            "slack": {"enabled": True, "webhookUrl": "https://s"},
            "profiles": {
                "default_profile": "ops",
                "profiles": {
                    "ops": {"name": "ops",
                            "telegram": {"enabled": True, "botToken": "t",
                                         "chatId": "1"}},
                },
            },
        })
        via_arg = cfg.get_notification_config("ops", cwd=str(tmp_path))
        via_env = cfg.get_notification_config(cwd=str(tmp_path))
        assert cfg.get_enabled_platforms(via_arg) == cfg.get_enabled_platforms(via_env)

    def test_resolve_profile_config_delegates(self, tmp_path):
        write_config(tmp_path, {
            "enabled": True,
            "telegram": {"enabled": True, "botToken": "t", "chatId": "1"},
        })
        config = cfg.resolve_profile_config("ignored", cwd=str(tmp_path))
        assert config.telegram.chat_id == "1"


class TestListProfiles:
    def test_no_file_returns_default(self, tmp_path):
        assert cfg.list_profiles(cwd=str(tmp_path)) == [cfg.DEFAULT_PROFILE]

    def test_profiles_returned(self, tmp_path):
        write_config(tmp_path, {"profiles": {"ops": {}, "dev": {}}})
        assert cfg.list_profiles(cwd=str(tmp_path)) == ["ops", "dev"]

    def test_flat_config_returns_default(self, tmp_path):
        write_config(tmp_path, {"enabled": True})
        assert cfg.list_profiles(cwd=str(tmp_path)) == [cfg.DEFAULT_PROFILE]

    def test_malformed_returns_default(self, tmp_path):
        (tmp_path / cfg.CONFIG_FILENAME).write_text("{oops", encoding="utf-8")
        assert cfg.list_profiles(cwd=str(tmp_path)) == [cfg.DEFAULT_PROFILE]
