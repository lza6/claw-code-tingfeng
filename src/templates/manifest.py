"""
Templates Module - 任务模板清单

从 oh-my-codex-main/templates/catalog-manifest.json 转换而来。
"""

from dataclasses import dataclass, field


@dataclass
class TemplateDefinition:
    """模板定义"""
    name: str
    description: str
    category: str
    variables: dict = field(default_factory=dict)


@dataclass
class TemplateManifest:
    """模板清单"""
    schema_version: str = "1.0"
    version: str = "2026.02.28.1"
    templates: list[TemplateDefinition] = field(default_factory=list)

    @classmethod
    def from_omx(cls) -> "TemplateManifest":
        """从 OMX 模板创建"""
        templates = [
            TemplateDefinition(
                name="agent-seed",
                description="Initialize a new agent with best practices",
                category="agents",
                variables={
                    "agent_name": "string",
                    "agent_role": "string",
                    "capabilities": "list",
                },
            ),
            TemplateDefinition(
                name="skill-scaffold",
                description="Create a new skill with standard structure",
                category="skills",
                variables={
                    "skill_name": "string",
                    "category": "string",
                    "triggers": "list",
                },
            ),
            TemplateDefinition(
                name="workflow-pipeline",
                description="Set up a multi-stage workflow",
                category="workflow",
                variables={
                    "stages": "list",
                    "parallel": "boolean",
                    "error_strategy": "string",
                },
            ),
            TemplateDefinition(
                name="mcp-server",
                description="Create a new MCP server implementation",
                category="mcp",
                variables={
                    "server_name": "string",
                    "tools": "list",
                    "resources": "list",
                },
            ),
            TemplateDefinition(
                name="test-suite",
                description="Initialize test infrastructure",
                category="testing",
                variables={
                    "framework": "string",
                    "coverage_target": "number",
                    "test_types": "list",
                },
            ),
        ]
        return cls(templates=templates)

    def get_by_category(self, category: str) -> list[TemplateDefinition]:
        """按类别获取模板"""
        return [t for t in self.templates if t.category == category]

    def get(self, name: str) -> TemplateDefinition | None:
        """获取模板"""
        for t in self.templates:
            if t.name == name:
                return t
        return None


# 全局模板清单
_template_manifest: TemplateManifest | None = None


def get_template_manifest() -> TemplateManifest:
    """获取模板清单"""
    global _template_manifest
    if _template_manifest is None:
        _template_manifest = TemplateManifest.from_omx()
    return _template_manifest


class TemplateLoader:
    """模板加载器"""

    def __init__(self, manifest: TemplateManifest | None = None):
        self._manifest = manifest or get_template_manifest()

    def load(self, name: str) -> dict | None:
        """加载模板"""
        template = self._manifest.get(name)
        if not template:
            return None
        return {
            "name": template.name,
            "description": template.description,
            "category": template.category,
            "variables": template.variables,
        }

    def list_all(self) -> list[dict]:
        """列出所有模板"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "category": t.category,
            }
            for t in self._manifest.templates
        ]

    def list_by_category(self, category: str) -> list[dict]:
        """按类别列出模板"""
        return [
            {
                "name": t.name,
                "description": t.description,
            }
            for t in self._manifest.get_by_category(category)
        ]


class TemplateLoader:
    """模板加载器"""

    def __init__(self, manifest: TemplateManifest | None = None):
        self._manifest = manifest or get_template_manifest()

    def load(self, name: str) -> dict | None:
        """加载模板"""
        template = self._manifest.get(name)
        if not template:
            return None
        return {
            "name": template.name,
            "description": template.description,
            "category": template.category,
            "variables": template.variables,
        }

    def list_all(self) -> list[dict]:
        """列出所有模板"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "category": t.category,
            }
            for t in self._manifest.templates
        ]

    def list_by_category(self, category: str) -> list[dict]:
        """按类别列出模板"""
        return [
            {
                "name": t.name,
                "description": t.description,
            }
            for t in self._manifest.get_by_category(category)
        ]
