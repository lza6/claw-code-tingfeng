"""
Mode-Specific Config — 模式特定配置路由

对齐 oh-my-codex 的 `.omx-config.json` 设计：
- 每个模式有独立的配置文件 (.omx-mode-{mode}.json)
- 支持 mode 配置覆盖全局配置
- 支持跨会话的 mode 状态持久化

参考: oh-my-codex-main/src/config/mode-config.ts
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 模式配置文件命名模式
MODE_CONFIG_PATTERN = ".omx-mode-{mode}.json"
GLOBAL_MODE_CONFIG = ".omx-modes.json"


@dataclass
class ModeConfig:
    """单个模式的配置"""
    mode: str
    enabled: bool = True
    model: str | None = None  # 覆盖默认模型
    provider: str | None = None  # 覆盖默认 provider
    timeout_ms: int | None = None  # 覆盖超时
    max_tokens: int | None = None  # 覆盖 max_tokens
    temperature: float | None = None  # 覆盖 temperature
    system_prompt: str | None = None  # 模式专用 system prompt
    hooks_enabled: bool = True  # 启用 hooks
    notification_enabled: bool = True  # 启用通知
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典"""
        result = {"mode": self.mode, "enabled": self.enabled}
        if self.model:
            result["model"] = self.model
        if self.provider:
            result["provider"] = self.provider
        if self.timeout_ms is not None:
            result["timeoutMs"] = self.timeout_ms
        if self.max_tokens is not None:
            result["maxTokens"] = self.max_tokens
        if self.temperature is not None:
            result["temperature"] = self.temperature
        if self.system_prompt:
            result["systemPrompt"] = self.system_prompt
        if self.hooks_enabled is not True:
            result["hooksEnabled"] = self.hooks_enabled
        if self.notification_enabled is not True:
            result["notificationEnabled"] = self.notification_enabled
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModeConfig:
        """从字典反序列化"""
        return cls(
            mode=data.get("mode", ""),
            enabled=data.get("enabled", True),
            model=data.get("model"),
            provider=data.get("provider"),
            timeout_ms=data.get("timeoutMs"),
            max_tokens=data.get("maxTokens"),
            temperature=data.get("temperature"),
            system_prompt=data.get("systemPrompt"),
            hooks_enabled=data.get("hooksEnabled", True),
            notification_enabled=data.get("notificationEnabled", True),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ModeConfigRouter:
    """模式配置路由器

    负责加载和管理各模式的特定配置。
    支持跨会话的 mode 状态持久化。
    """

    def __init__(self, cwd: str | Path | None = None) -> None:
        self.cwd = Path(cwd) if cwd else Path.cwd()
        self._configs: dict[str, ModeConfig] = {}
        self._loaded = False

    def load_all(self) -> None:
        """加载所有模式配置"""
        if self._loaded:
            return

        # 1. 加载全局模式配置 (.omx-modes.json)
        global_config_path = self.cwd / GLOBAL_MODE_CONFIG
        if global_config_path.exists():
            try:
                data = json.loads(global_config_path.read_text(encoding="utf-8"))
                modes = data.get("modes", {})
                for mode_name, mode_data in modes.items():
                    if isinstance(mode_data, dict):
                        mode_data["mode"] = mode_name
                        self._configs[mode_name] = ModeConfig.from_dict(mode_data)
            except Exception:
                pass

        # 2. 加载独立模式配置文件 (.omx-mode-{mode}.json)
        for mode_file in self.cwd.glob(".omx-mode-*.json"):
            mode_name = mode_file.stem.replace(".omx-mode-", "")
            try:
                data = json.loads(mode_file.read_text(encoding="utf-8"))
                data["mode"] = mode_name
                self._configs[mode_name] = ModeConfig.from_dict(data)
            except Exception:
                pass

        self._loaded = True

    def get_config(self, mode: str) -> ModeConfig | None:
        """获取指定模式的配置

        Args:
            mode: 模式名称 (ralph, team, plan, etc.)

        Returns:
            ModeConfig 如果找到，否则返回 None
        """
        if not self._loaded:
            self.load_all()

        return self._configs.get(mode)

    def is_mode_enabled(self, mode: str) -> bool:
        """检查模式是否启用"""
        config = self.get_config(mode)
        return config.enabled if config else True

    def get_model_for_mode(self, mode: str, default: str | None = None) -> str | None:
        """获取模式指定的模型

        Args:
            mode: 模式名称
            default: 默认模型（如果模式未指定）

        Returns:
            模型名称
        """
        config = self.get_config(mode)
        return config.model if config and config.model else default

    def get_provider_for_mode(self, mode: str, default: str | None = None) -> str | None:
        """获取模式指定的 provider"""
        config = self.get_config(mode)
        return config.provider if config and config.provider else default

    def get_timeout_for_mode(self, mode: str, default: int | None = None) -> int | None:
        """获取模式指定的超时"""
        config = self.get_config(mode)
        return config.timeout_ms if config and config.timeout_ms else default

    def get_system_prompt_for_mode(self, mode: str) -> str | None:
        """获取模式的专用 system prompt"""
        config = self.get_config(mode)
        return config.system_prompt if config else None

    def list_modes(self) -> list[str]:
        """列出所有已配置的模式"""
        if not self._loaded:
            self.load_all()
        return list(self._configs.keys())

    def save_mode_config(self, mode: str, config: ModeConfig) -> None:
        """保存模式配置

        Args:
            mode: 模式名称
            config: 模式配置
        """
        self._configs[mode] = config

        # 保存到独立文件
        config_path = self.cwd / MODE_CONFIG_PATTERN.format(mode=mode)
        config_path.write_text(
            json.dumps(config.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )


# 全局路由器实例（懒加载）
_default_router: ModeConfigRouter | None = None


def get_mode_config_router(cwd: str | Path | None = None) -> ModeConfigRouter:
    """获取全局模式配置路由器"""
    global _default_router
    if _default_router is None:
        _default_router = ModeConfigRouter(cwd)
    return _default_router


def get_mode_config(mode: str, cwd: str | Path | None = None) -> ModeConfig | None:
    """便捷函数：获取指定模式的配置"""
    router = get_mode_config_router(cwd)
    return router.get_config(mode)


def is_mode_enabled(mode: str, cwd: str | Path | None = None) -> bool:
    """便捷函数：检查模式是否启用"""
    router = get_mode_config_router(cwd)
    return router.is_mode_enabled(mode)


__all__ = [
    "ModeConfig",
    "ModeConfigRouter",
    "get_mode_config",
    "get_mode_config_router",
    "is_mode_enabled",
]
