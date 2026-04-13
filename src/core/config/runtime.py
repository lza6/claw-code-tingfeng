"""Runtime Config — 运行时配置覆盖（ClawGod 风格）

提取自 settings.py (v0.60.0)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import AgentSettings

from .injector import get_config_injector

logger = logging.getLogger(__name__)


def get_runtime_config(key: str, default: Any = None) -> Any:
    """
    获取运行时配置 (ClawGod 风格)

    使用 6 层配置优先级:
    0. Runtime overrides
    1. CLAUDE_INTERNAL_FC_OVERRIDES
    2. OS Environment
    3. provider.json
    4. features.json
    5. Default

    Args:
        key: 配置键
        default: 默认值

    Returns:
        配置值
    """
    return get_config_injector().get(key, default)


def set_runtime_config(key: str, value: Any, persistent: bool = False) -> None:
    """
    设置运行时配置覆盖 (ClawGod 风格)

    Args:
        key: 配置键
        value: 配置值
        persistent: 是否持久化到文件
    """
    get_config_injector().set(key, value, persistent=persistent)
    logger.debug(f"运行时配置已设置: {key} = {value}")


def reload_config() -> None:
    """重新加载所有配置 (热重载)"""
    get_config_injector().reload()
    # 重新加载负载均衡器配置
    from src.llm.balancer import get_balancer
    get_balancer().load_config()
    logger.info("配置已热重载")


def get_config_priority_report() -> str:
    """
    获取配置优先级报告

    Returns:
        格式化的报告字符串
    """
    return get_config_injector().get_priority_report()


def apply_config_overrides(settings: AgentSettings) -> AgentSettings:
    """
    应用运行时配置覆盖到 settings 对象

    借鉴 ClawGod 的 wrapper 模式，在 settings 加载后应用覆盖

    Args:
        settings: AgentSettings 实例

    Returns:
        应用覆盖后的 settings 实例
    """
    from src.core.config_injector import get_config_injector
    from src.core.settings_enums import ApprovalMode, LLMProviderEnum

    injector = get_config_injector()

    # 覆盖 LLM 配置
    if injector.has("llm_model"):
        settings.llm_model = injector.get("llm_model")
    if injector.has("llm_provider"):
        settings.llm_provider = LLMProviderEnum(injector.get("llm_provider"))
    if injector.has("llm_api_key"):
        settings.llm_api_key = injector.get("llm_api_key")
    if injector.has("llm_base_url"):
        settings.llm_base_url = injector.get("llm_base_url")

    # 覆盖 Agent 行为
    if injector.has("max_iterations"):
        settings.max_iterations = injector.get_typed("max_iterations", int, settings.max_iterations)
    if injector.has("approval_mode"):
        settings.approval_mode = ApprovalMode(injector.get("approval_mode"))

    logger.debug("运行时配置覆盖已应用")
    return settings
