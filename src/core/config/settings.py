"""Enterprise Settings — 基于 pydantic-settings 的配置验证系统

提供类型安全、自动验证、文档化的配置管理。
替代原有的裸环境变量加载方式。

整合 ClawGod 设计:
- 配置注入层 (ConfigInjector) 提供 6 层配置优先级
- 运行时配置覆盖支持
- 配置热重载

迁移说明 (v0.60.0):
- 已拆分为多个模块:
  - settings_enums.py: 枚举和数据类型
  - settings_model.py: AgentSettings 模型和加载函数
  - runtime_config.py: 运行时配置覆盖
- 此文件保留为向后兼容接口
"""
from __future__ import annotations

# 向后兼容: 从新模块重新导出所有公共接口
# Enums & Dataclasses
from .enums import (
    ApprovalMode,
    ConfigSource,
    ConfigSourceKind,
    LLMProviderEnum,
    LogLevelEnum,
)

# AgentSettings Model
from .models import (
    AgentSettings,
    get_settings,
    load_settings,
    reload_settings,
    reset_settings,
)

# 从 settings_model 导入 load_settings 并应用覆盖
from .models import load_settings as _base_load_settings

# Runtime Config (ClawGod 风格)
from .runtime import (
    apply_config_overrides,
    get_config_priority_report,
    get_runtime_config,
    reload_config,
    set_runtime_config,
)


def load_settings() -> AgentSettings:
    """加载配置并应用运行时覆盖"""
    return apply_config_overrides(_base_load_settings())


# ─── 模块元信息 ─────────────────────────────────────────────────────────

__all__ = [
    # Model & Functions
    "AgentSettings",
    "ApprovalMode",
    "ConfigSource",
    "ConfigSourceKind",
    # Enums
    "LLMProviderEnum",
    "LogLevelEnum",
    "apply_config_overrides",
    "get_config_priority_report",
    # Runtime Config
    "get_runtime_config",
    "get_settings",
    "load_settings",
    "reload_config",
    "reload_settings",
    "reset_settings",
    "set_runtime_config",
]
