"""Settings Enums — 配置相关枚举和数据类型

提取自 settings.py (v0.60.0)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LLMProviderEnum(str, Enum):
    """支持的 LLM 提供商"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENROUTER = "openrouter"
    GOOGLE = "google"
    GROQ = "groq"
    TOGETHER = "together"
    MISTRAL = "mistral"
    DEEPSEEK = "deepseek"


class LogLevelEnum(str, Enum):
    """日志级别"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ConfigSourceKind(str, Enum):
    """配置来源类型 (Ported from Project B)"""
    CLI = "cli"
    ENV = "env"
    SETTINGS = "settings"
    USER_SETTINGS = "user_settings"
    DEFAULT = "default"
    COMPUTED = "computed"
    PROGRAMMATIC = "programmatic"
    UNKNOWN = "unknown"

    def __str__(self):
        return self.value


@dataclass
class ConfigSource:
    """配置来源元数据 (Ported from Project B)"""
    kind: ConfigSourceKind
    detail: str | None = None
    env_key: str | None = None
    file_path: str | None = None


# 向后兼容: 从新位置导入 ApprovalMode
from ..approval_mode import ApprovalMode

__all__ = [
    "ApprovalMode",
    "ConfigSource",
    "ConfigSourceKind",
    "LLMProviderEnum",
    "LogLevelEnum",
]
