"""
配置验证器 - 借鉴 Onyx 的配置验证模式

提供运行时配置验证，确保配置正确性。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ConfigValidator:
    """配置验证器基类"""

    def __init__(self):
        self._validators: dict[str, list[Callable[[Any], bool]]] = {}

    def register(self, key: str, validator: Callable[[Any], bool]) -> None:
        """注册验证器"""
        if key not in self._validators:
            self._validators[key] = []
        self._validators[key].append(validator)

    def validate(self, key: str, value: Any) -> tuple[bool, str]:
        """验证配置值

        Returns:
            (is_valid, error_message)
        """
        validators = self._validators.get(key, [])
        for validator in validators:
            try:
                if not validator(value):
                    return False, f"Validation failed for {key}"
            except Exception as e:
                return False, f"Validation error for {key}: {e}"
        return True, ""


# 全局验证器实例
_validator = ConfigValidator()


def get_validator() -> ConfigValidator:
    """获取全局验证器"""
    return _validator


def validate_config(key: str, value: Any) -> tuple[bool, str]:
    """验证配置值"""
    return _validator.validate(key, value)


# 内置验证器
def register_default_validators() -> None:
    """注册默认验证器"""
    # API Key 验证
    _validator.register("llm_api_key", lambda v: v is None or (isinstance(v, str) and len(v) >= 10))

    # 端口验证
    _validator.register("agent_server_port", lambda v: 1 <= v <= 65535)

    # Token 数量验证
    _validator.register("max_context_tokens", lambda v: 1000 <= v <= 128000)
    _validator.register("map_tokens", lambda v: 0 <= v <= 32000)


# 初始化时注册默认验证器
register_default_validators()
