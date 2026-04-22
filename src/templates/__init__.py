"""
Templates Module - 任务模板系统

从 oh-my-codex-main/templates/ 转换而来。
提供模板清单和加载功能。
"""

from src.templates.manifest import (
    TemplateDefinition,
    TemplateLoader,
    TemplateManifest,
    get_template_manifest,
)

__all__ = [
    "TemplateDefinition",
    "TemplateLoader",
    "TemplateManifest",
    "get_template_manifest",
]
