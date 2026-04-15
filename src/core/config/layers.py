"""
Config Layers — 多层级配置加载 (借鉴 Project B/GoalX)

支持以下优先级加载:
1. Built-in defaults
2. User config (~/.clawd/config.yaml)
3. Project config (./.clawd/config.yaml)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ConfigLayers:
    """配置层级容器"""
    defaults: dict[str, Any] = field(default_factory=dict)
    user: dict[str, Any] = field(default_factory=dict)
    project: dict[str, Any] = field(default_factory=dict)

    def merge_all(self) -> dict[str, Any]:
        """合并所有层级，优先级: project > user > defaults (采用深度合并逻辑)"""
        return self._deep_merge(
            self.defaults,
            self._deep_merge(self.user, self.project)
        )

    def _deep_merge(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """递归深度合并字典"""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result


def load_yaml(path: Path) -> dict[str, Any]:
    """安全加载 YAML 文件"""
    if not path.exists():
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"警告: 无法加载配置文件 {path}: {e}")
        return {}


def load_config_layers(project_root: str | Path | None = None) -> ConfigLayers:
    """
    加载所有配置层级

    Args:
        project_root: 项目根目录，默认为当前目录
    """
    layers = ConfigLayers()

    # 1. Defaults (这里可以从 src.core.config.models 加载)
    # 暂时保持为空，由 injector 的内置默认值处理

    # 2. User config (~/.clawd/config.yaml)
    home_config = Path.home() / ".clawd" / "config.yaml"
    layers.user = load_yaml(home_config)

    # 3. Project config (./.clawd/config.yaml)
    if project_root is None:
        project_root = Path.cwd()
    else:
        project_root = Path(project_root)

    project_config = project_root / ".clawd" / "config.yaml"
    layers.project = load_yaml(project_config)

    return layers
