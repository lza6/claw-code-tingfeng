"""
Templates Module - 任务模板系统

从 oh-my-codex-main/templates/ 转换而来。
提供模板清单和加载功能。
"""

from src.templates.manifest import (
    TemplateManifest,
    TemplateDefinition,
    TemplateLoader,
    get_template_manifest,
)

__all__ = [
    "TemplateManifest",
    "TemplateDefinition",
    "TemplateLoader",
    "get_template_manifest",
]