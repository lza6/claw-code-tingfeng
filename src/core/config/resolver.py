"""
Config Resolver — 配置解析与验证 (借鉴 Project B/GoalX)

负责将原始配置字典“解析”为经过验证、上下文补充后的最终配置对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .dimensions import ResolvedDimension, resolve_dimension_specs
from .layers import ConfigLayers, load_config_layers


@dataclass
class ResolvedConfig:
    """最终解析出的配置对象"""
    values: dict[str, Any]
    explicit_selection: bool = False  # 是否显式指定了模型/引擎
    dimensions: list[ResolvedDimension] = field(default_factory=list)
    source_layers: ConfigLayers = field(default_factory=ConfigLayers)

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


class ConfigResolver:
    """配置解析器"""

    def __init__(self, project_root: str | None = None):
        self.project_root = project_root
        self.layers = load_config_layers(project_root)

    def resolve(self, overrides: dict[str, Any] | None = None, preview: bool = False) -> ResolvedConfig:
        """
        执行解析逻辑 (汲取 GoalX 预览模式)

        Args:
            overrides: 运行时覆盖
            preview: 是否为预览模式（不执行严格校验）
        """
        # 合并层级
        merged_values = self.layers.merge_all()

        # 应用覆盖
        if overrides:
            merged_values.update(overrides)

        # 解析维度 (汲取 GoalX Dimensions)
        dimension_names = merged_values.get("dimensions", [])
        if isinstance(dimension_names, str):
            dimension_names = [d.strip() for d in dimension_names.split(",") if d.strip()]

        # 合并来自 project 配置的强制维度
        forced_dimensions = merged_values.get("forced_dimensions", [])
        if forced_dimensions:
            dimension_names.extend(forced_dimensions)
            dimension_names = list(set(dimension_names))

        resolved_dimensions = resolve_dimension_specs(
            dimension_names,
            custom=merged_values.get("custom_dimensions")
        )

        # 检查是否显式指定了关键配置
        explicit = "llm_model" in merged_values or "llm_provider" in merged_values

        # 模拟 GoalX 的隐式选择策略探测 (未来可接入 Provider 状态)
        if not explicit and not preview:
            self._apply_implicit_policy(merged_values)

        return ResolvedConfig(
            values=merged_values,
            explicit_selection=explicit,
            dimensions=resolved_dimensions,
            source_layers=self.layers
        )

    def _apply_implicit_policy(self, values: dict[str, Any]) -> None:
        """隐式策略应用 (自动补全缺省模型)"""
        # 这是一个占位逻辑，实际应根据当前环境变量或 Provider 可用性选择
        if "llm_provider" not in values:
            values["llm_provider"] = "anthropic"
        if "llm_model" not in values:
            values["llm_model"] = "claude-3-5-sonnet-latest"


def resolve_config(project_root: str | None = None, overrides: dict[str, Any] | None = None) -> ResolvedConfig:
    """便捷入口"""
    resolver = ConfigResolver(project_root)
    return resolver.resolve(overrides)
