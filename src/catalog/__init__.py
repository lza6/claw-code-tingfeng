"""
Catalog Module - 技能/Agent 清单管理系统

从 oh-my-codex-main/src/catalog/ 转换而来。
提供技能清单、类型定义、注册和读取功能。
"""

from src.catalog.manifest import (
    AgentCategory,
    AgentDefinition,
    CatalogManifest,
    SkillCategory,
    SkillDefinition,
    SkillStatus,
    get_catalog,
    reload_catalog,
)
from src.catalog.registry import CatalogRegistry, get_registry

__all__ = [
    "AgentCategory",
    "AgentDefinition",
    "CatalogManifest",
    "CatalogRegistry",
    "SkillCategory",
    "SkillDefinition",
    "SkillStatus",
    "get_catalog",
    "get_registry",
    "reload_catalog",
]
