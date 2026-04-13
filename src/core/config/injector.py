"""
配置注入层 - Wrapper + Forward 模式

灵感来源: ClawGod cli.js wrapper 中的配置加载逻辑

设计思想:
- 在原始配置前插入配置注入层
- 通过环境变量向子进程传递配置
- 使用空值合并实现配置优先级
- 配置 > 环境变量 > 默认值的优雅优先级链
- 支持配置热重载

配置优先级 (从高到低):
    0. Runtime overrides (编程方式设置)
    1. CLAUDE_INTERNAL_FC_OVERRIDES (JSON env var)
    2. OS Environment variables
    3. provider.json (结构化配置)
    4. .env files (分层配置)
    5. features.json (功能开关)
    6. Built-in defaults

使用示例:
    # 基础用法
    from .injector import config_injector

    # 运行时覆盖
    config_injector.set("llm_model", "gpt-4o", persistent=False)

    # 获取配置
    model = config_injector.get("llm_model")

    # 获取完整配置字典
    config = config_injector.get_full_config()

    # 热重载
    config_injector.reload()
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ConfigValue:
    """配置值及其来源"""
    value: Any
    source: str
    priority: int  # 数字越小优先级越高


@dataclass
class ConfigChangeEvent:
    """配置变更事件"""
    key: str
    old_value: Any
    new_value: Any
    source: str


class ConfigInjector:
    """
    配置注入层

    实现 Wrapper + Forward 模式:
    - 运行时配置覆盖
    - 配置优先级链
    - 热重载支持
    - 变更回调
    """
    Path = Path  # 导出 Path 以供 patch 使用

    def __init__(self):
        # 运行时覆盖（最高优先级）
        self._runtime_overrides: dict[str, ConfigValue] = {}

        # 缓存的配置
        self._config_cache: dict[str, ConfigValue] = {}

        # 变更回调
        self._change_callbacks: list[Callable[[ConfigChangeEvent], None]] = []

        # 配置文件路径 — 支持 CLAWD_CONFIG_DIR 和 CLAUDE_CONFIG_DIR (ClawGod 兼容)
        config_dir = os.environ.get("CLAWD_CONFIG_DIR") or os.environ.get("CLAUDE_CONFIG_DIR")
        if config_dir:
            self._config_home = Path(config_dir)
        else:
            self._config_home = Path.home() / ".clawd"
        self._provider_path: Path = self._config_home / "provider.json"
        self._features_path: Path = Path.cwd() / ".clawd" / "features.json"

        # 引入 Project B 风格的 YAML 解析器
        from .resolver import ConfigResolver
        self._resolver = ConfigResolver()
        self._yaml_config: dict[str, Any] = {}
        self._reload_yaml()

    def _reload_yaml(self) -> None:
        """重新解析 YAML 配置层"""
        resolved = self._resolver.resolve()
        self._yaml_config = resolved.values

    def set(
        self,
        key: str,
        value: Any,
        persistent: bool = False,
        source: str = "runtime",
    ) -> None:
        """
        设置配置值

        Args:
            key: 配置键
            value: 配置值
            persistent: 是否持久化（写入文件）
            source: 来源标识
        """
        old_value = self._runtime_overrides.get(key)

        self._runtime_overrides[key] = ConfigValue(
            value=value,
            source=source,
            priority=0,  # 最高优先级
        )

        # 清除缓存
        self._config_cache.pop(key, None)

        # 触发回调
        if self._change_callbacks:
            self._trigger_change(ConfigChangeEvent(
                key=key,
                old_value=old_value.value if old_value else None,
                new_value=value,
                source=source,
            ))

        # 持久化
        if persistent:
            self._persist_to_file(key, value)

        logger.debug(f"配置已设置: {key} = {value} (source: {source})")

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值

        按优先级查找:
        0. Runtime overrides
        1. CLAUDE_INTERNAL_FC_OVERRIDES
        2. OS Environment
        3. YAML Config Layers (Project B/GoalX 风格: Project > User)
        4. provider.json
        5. features.json
        6. Default

        Args:
            key: 配置键
            default: 默认值

        Returns:
            配置值
        """
        # 0. Runtime overrides (最高优先级)
        if key in self._runtime_overrides:
            return self._runtime_overrides[key].value

        # 1. CLAUDE_INTERNAL_FC_OVERRIDES
        internal_overrides = self._get_internal_overrides()
        if key in internal_overrides:
            return internal_overrides[key]

        # 2. OS Environment
        env_value = os.environ.get(key)
        if env_value is not None:
            # 尝试转换类型
            return self._convert_type(key, env_value)

        # 3. YAML Config Layers (新引入)
        if key in self._yaml_config:
            return self._yaml_config[key]

        # 4. provider.json
        provider_config = self._load_provider_config()
        if key in provider_config:
            return provider_config[key]

        # 4. features.json
        features_config = self._load_features_config()
        if key in features_config:
            return features_config[key]

        # 5. Default
        return default

    def get_typed(self, key: str, expected_type: type, default: Any = None) -> Any:
        """
        获取指定类型的配置值

        Args:
            key: 配置键
            expected_type: 期望的类型
            default: 默认值

        Returns:
            配置值（已转换为期望类型）
        """
        value = self.get(key, default)
        if value is None:
            return default

        try:
            if expected_type is bool:
                if isinstance(value, str):
                    return value.lower() in ("true", "1", "yes", "on")
                return bool(value)
            elif expected_type is int:
                return int(value)
            elif expected_type is float:
                return float(value)
            elif expected_type is str:
                return str(value)
            else:
                return value
        except (ValueError, TypeError):
            logger.warning(f"配置类型转换失败: {key} 期望 {expected_type.__name__}, 实际 {type(value).__name__}")
            return default

    def get_full_config(self) -> dict[str, Any]:
        """
        获取完整配置字典

        Returns:
            包含所有配置键值对的字典
        """
        config = {}

        # 收集所有键
        all_keys = set()
        all_keys.update(self._runtime_overrides.keys())
        all_keys.update(self._get_internal_overrides().keys())
        all_keys.update(os.environ.keys())
        all_keys.update(self._load_provider_config().keys())
        all_keys.update(self._load_features_config().keys())

        # 按优先级填充
        for key in all_keys:
            value = self.get(key)
            if value is not None:
                config[key] = value

        return config

    def has(self, key: str) -> bool:
        """检查配置是否存在"""
        return self.get(key) is not None

    def delete(self, key: str) -> bool:
        """
        删除运行时覆盖

        Args:
            key: 配置键

        Returns:
            是否成功删除
        """
        if key in self._runtime_overrides:
            old_value = self._runtime_overrides.pop(key)
            self._config_cache.pop(key, None)

            if self._change_callbacks:
                self._trigger_change(ConfigChangeEvent(
                    key=key,
                    old_value=old_value.value,
                    new_value=None,
                    source="runtime_delete",
                ))

            logger.debug(f"运行时配置已删除: {key}")
            return True

        return False

    def clear_runtime_overrides(self) -> int:
        """
        清除所有运行时覆盖

        Returns:
            清除的数量
        """
        count = len(self._runtime_overrides)
        self._runtime_overrides.clear()
        self._config_cache.clear()
        logger.debug(f"已清除 {count} 个运行时配置")
        return count

    def on_change(self, callback: Callable[[ConfigChangeEvent], None]) -> None:
        """
        注册配置变更回调

        Args:
            callback: 回调函数
        """
        self._change_callbacks.append(callback)
        logger.debug(f"配置变更回调已注册 (共 {len(self._change_callbacks)} 个)")

    def reload(self) -> None:
        """重新加载配置（清除缓存，重新解析 YAML）"""
        self._config_cache.clear()
        self._reload_yaml()
        logger.info("配置已重新加载 (包含 YAML 层)")

    def get_priority_report(self) -> str:
        """
        获取配置优先级报告

        Returns:
            格式化的报告字符串
        """
        lines = []
        lines.append("配置优先级报告:")
        lines.append("=" * 60)

        # 运行时覆盖
        if self._runtime_overrides:
            lines.append("\n[优先级 0] Runtime Overrides:")
            for key, cv in sorted(self._runtime_overrides.items()):
                lines.append(f"  {key} = {cv.value} ({cv.source})")

        # 内部覆盖
        internal = self._get_internal_overrides()
        if internal:
            lines.append(f"\n[优先级 1] Internal Overrides ({len(internal)} keys):")
            for key, value in sorted(internal.items()):
                lines.append(f"  {key} = {value}")

        # 环境变量
        env_keys = [k for k in os.environ if not k.startswith("_")]
        if env_keys:
            lines.append(f"\n[优先级 2] Environment Variables ({len(env_keys)} keys)")

        # provider.json
        provider = self._load_provider_config()
        if provider:
            lines.append(f"\n[优先级 3] provider.json ({len(provider)} keys):")
            for key, value in sorted(provider.items()):
                display_value = str(value)[:50] + "..." if len(str(value)) > 50 else str(value)
                lines.append(f"  {key} = {display_value}")

        # features.json
        features = self._load_features_config()
        if features:
            lines.append(f"\n[优先级 4] features.json ({len(features)} keys):")
            for key, value in sorted(features.items()):
                lines.append(f"  {key} = {value}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    # ─── 内部方法 ─────────────────────────────────────────────────────────

    def _get_internal_overrides(self) -> dict[str, Any]:
        """获取 CLAUDE_INTERNAL_FC_OVERRIDES"""
        overrides_json = os.environ.get("CLAUDE_INTERNAL_FC_OVERRIDES")
        if not overrides_json:
            return {}

        try:
            overrides = json.loads(overrides_json)
            if isinstance(overrides, dict):
                return overrides
        except json.JSONDecodeError as e:
            logger.warning(f"无效的 CLAUDE_INTERNAL_FC_OVERRIDES JSON: {e}")

        return {}

    def _load_provider_config(self) -> dict[str, Any]:
        """加载 provider.json 配置"""
        provider_paths = [
            Path.home() / ".clawd" / "provider.json",
            Path.cwd() / ".clawd" / "provider.json",
        ]

        for provider_path in provider_paths:
            if provider_path.exists():
                try:
                    data = json.loads(provider_path.read_text(encoding="utf-8"))

                    # 如果指定了 activeProvider，加载对应提供商配置
                    active = data.get("activeProvider")
                    providers = data.get("providers", {})

                    if active and active in providers:
                        return providers[active]
                    else:
                        return data
                except Exception as e:
                    logger.warning(f"加载 provider.json 失败: {e}")

        return {}

    def _load_features_config(self) -> dict[str, Any]:
        """加载 features.json 配置"""
        features_paths = [
            Path.home() / ".clawd" / "features.json",
            Path.cwd() / ".clawd" / "features.json",
        ]

        for features_path in features_paths:
            if features_path.exists():
                try:
                    return json.loads(features_path.read_text(encoding="utf-8"))
                except Exception as e:
                    logger.warning(f"加载 features.json 失败: {e}")

        return {}

    def _convert_type(self, key: str, value: str) -> Any:
        """
        根据键名推断并转换类型

        借鉴 ClawGod 的类型转换逻辑
        """
        key_lower = key.lower()
        # 布尔值
        if any(key_lower.endswith(suffix) for suffix in ["_enabled", "_enable", "enable", "debug"]):
            return value.lower() in ("true", "1", "yes", "on")

        # 整数
        if any(key_lower.endswith(suffix) for suffix in ["_timeout", "_port", "_limit", "_count", "_max", "_min"]):
            try:
                return int(value)
            except ValueError:
                pass

        # 浮点数
        if any(key_lower.endswith(suffix) for suffix in ["_rate", "_ratio", "_threshold"]):
            try:
                return float(value)
            except ValueError:
                pass

        # 默认为字符串
        return value

    def _persist_to_file(self, key: str, value: Any) -> None:
        """
        持久化配置到文件

        Args:
            key: 配置键
            value: 配置值
        """
        # 选择持久化目标
        persist_path = Path.cwd() / ".clawd" / "runtime_overrides.json"
        persist_path.parent.mkdir(parents=True, exist_ok=True)

        # 加载现有数据
        existing = {}
        if persist_path.exists():
            with contextlib.suppress(Exception):
                existing = json.loads(persist_path.read_text(encoding="utf-8"))

        # 更新并写入
        existing[key] = value
        try:
            persist_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.debug(f"配置已持久化: {key} -> {persist_path}")
        except Exception as e:
            logger.warning(f"配置持久化失败: {e}")

    def _trigger_change(self, event: ConfigChangeEvent) -> None:
        """触发配置变更回调"""
        for callback in self._change_callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.warning(f"配置变更回调执行失败: {e}")

    def load_persistent_overrides(self) -> int:
        """
        从文件加载持久化的配置覆盖

        Returns:
            加载的数量
        """
        persist_path = Path.cwd() / ".clawd" / "runtime_overrides.json"
        if not persist_path.exists():
            return 0

        try:
            data = json.loads(persist_path.read_text(encoding="utf-8"))
            count = 0
            for key, value in data.items():
                self.set(key, value, source="persistent_file")
                count += 1
            logger.info(f"已加载 {count} 个持久化配置")
            return count
        except Exception as e:
            logger.warning(f"加载持久化配置失败: {e}")
            return 0


# ─── 全局单例 ─────────────────────────────────────────────────────────

_config_injector: ConfigInjector | None = None


def get_config_injector() -> ConfigInjector:
    """获取全局配置注入器实例"""
    global _config_injector
    if _config_injector is None:
        _config_injector = ConfigInjector()
        _config_injector.load_persistent_overrides()
    return _config_injector


def reset_config_injector() -> None:
    """重置全局配置注入器（用于测试）"""
    global _config_injector
    _config_injector = None


# 便捷函数
def set_config(key: str, value: Any, persistent: bool = False) -> None:
    """便捷函数：设置配置"""
    get_config_injector().set(key, value, persistent=persistent)


def get_config(key: str, default: Any = None) -> Any:
    """便捷函数：获取配置"""
    return get_config_injector().get(key, default)


def get_full_config() -> dict[str, Any]:
    """便捷函数：获取完整配置"""
    return get_config_injector().get_full_config()


# 向后兼容别名（模块级 property 不可用，改为直接引用单例）
config_injector = get_config_injector()
