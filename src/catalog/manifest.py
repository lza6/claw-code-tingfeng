"""
Catalog Module - 技能/Agent 清单管理

从 oh-my-codex-main/src/catalog/ 转换而来。
提供技能清单、类型定义和注册功能。
"""

from dataclasses import dataclass, field
from enum import Enum


class SkillCategory(str, Enum):
    """技能类别"""
    EXECUTION = "execution"
    PLANNING = "planning"
    SHORTCUT = "shortcut"
    UTILITY = "utility"


class SkillStatus(str, Enum):
    """技能状态"""
    ACTIVE = "active"
    MERGED = "merged"
    ALIAS = "alias"
    INTERNAL = "internal"


class AgentCategory(str, Enum):
    """Agent类别"""
    BUILD = "build"
    REVIEW = "review"
    DOMAIN = "domain"
    PRODUCT = "product"
    COORDINATION = "coordination"


@dataclass
class SkillDefinition:
    """技能定义"""
    name: str
    category: SkillCategory
    status: SkillStatus
    core: bool = False
    canonical: str | None = None


@dataclass
class AgentDefinition:
    """Agent定义"""
    name: str
    category: AgentCategory
    status: str  # 'active', 'merged', 'alias', 'internal'
    core: bool = False
    canonical: str | None = None


@dataclass
class CatalogManifest:
    """清单清单"""
    schema_version: int = 1
    catalog_version: str = "2026.02.28.1"
    skills: list[SkillDefinition] = field(default_factory=list)
    agents: list[AgentDefinition] = field(default_factory=list)

    @classmethod
    def from_omx(cls) -> "CatalogManifest":
        """从 OMX 清单创建"""
        skills = [
            # Execution
            SkillDefinition("autopilot", SkillCategory.EXECUTION, SkillStatus.ACTIVE, core=True),
            SkillDefinition("ralph", SkillCategory.EXECUTION, SkillStatus.ACTIVE, core=True),
            SkillDefinition("ultrawork", SkillCategory.EXECUTION, SkillStatus.ACTIVE, core=True),
            SkillDefinition("team", SkillCategory.EXECUTION, SkillStatus.ACTIVE, core=True),
            SkillDefinition("ecomode", SkillCategory.EXECUTION, SkillStatus.MERGED, canonical="ultrawork"),
            SkillDefinition("ultraqa", SkillCategory.EXECUTION, SkillStatus.MERGED, canonical="ralph"),
            SkillDefinition("swarm", SkillCategory.EXECUTION, SkillStatus.ALIAS, canonical="team"),
            # Planning
            SkillDefinition("plan", SkillCategory.PLANNING, SkillStatus.ACTIVE),
            SkillDefinition("ralplan", SkillCategory.PLANNING, SkillStatus.ACTIVE, core=True, canonical="plan"),
            SkillDefinition("deep-interview", SkillCategory.PLANNING, SkillStatus.ACTIVE),
            # Shortcut
            SkillDefinition("analyze", SkillCategory.SHORTCUT, SkillStatus.ALIAS, canonical="debugger"),
            SkillDefinition("deepsearch", SkillCategory.SHORTCUT, SkillStatus.ALIAS, canonical="explore"),
            SkillDefinition("tdd", SkillCategory.SHORTCUT, SkillStatus.ALIAS, canonical="test-engineer"),
            SkillDefinition("build-fix", SkillCategory.SHORTCUT, SkillStatus.ALIAS, canonical="build-fixer"),
            SkillDefinition("ai-slop-cleaner", SkillCategory.SHORTCUT, SkillStatus.ACTIVE),
            SkillDefinition("code-review", SkillCategory.SHORTCUT, SkillStatus.ACTIVE, canonical="code-reviewer"),
            SkillDefinition("security-review", SkillCategory.SHORTCUT, SkillStatus.ACTIVE, canonical="security-reviewer"),
            SkillDefinition("visual-verdict", SkillCategory.SHORTCUT, SkillStatus.ACTIVE, canonical="vision"),
            SkillDefinition("web-clone", SkillCategory.SHORTCUT, SkillStatus.ACTIVE, canonical="vision"),
            SkillDefinition("frontend-ui-ux", SkillCategory.SHORTCUT, SkillStatus.ALIAS, canonical="designer"),
            SkillDefinition("git-master", SkillCategory.SHORTCUT, SkillStatus.ALIAS, canonical="git-master"),
            SkillDefinition("review", SkillCategory.SHORTCUT, SkillStatus.ALIAS, canonical="plan --review"),
            SkillDefinition("ask-claude", SkillCategory.SHORTCUT, SkillStatus.ACTIVE),
            SkillDefinition("ask-gemini", SkillCategory.SHORTCUT, SkillStatus.ACTIVE),
            # Utility
            SkillDefinition("cancel", SkillCategory.UTILITY, SkillStatus.ACTIVE),
            SkillDefinition("doctor", SkillCategory.UTILITY, SkillStatus.ACTIVE),
            SkillDefinition("help", SkillCategory.UTILITY, SkillStatus.ACTIVE),
            SkillDefinition("note", SkillCategory.UTILITY, SkillStatus.ACTIVE),
            SkillDefinition("trace", SkillCategory.UTILITY, SkillStatus.ACTIVE),
            SkillDefinition("skill", SkillCategory.UTILITY, SkillStatus.ACTIVE),
            SkillDefinition("hud", SkillCategory.UTILITY, SkillStatus.ACTIVE),
            SkillDefinition("omx-setup", SkillCategory.UTILITY, SkillStatus.ACTIVE),
            SkillDefinition("configure-notifications", SkillCategory.UTILITY, SkillStatus.ACTIVE, core=False),
            SkillDefinition("configure-discord", SkillCategory.UTILITY, SkillStatus.MERGED, canonical="configure-notifications", core=False),
            SkillDefinition("configure-telegram", SkillCategory.UTILITY, SkillStatus.MERGED, canonical="configure-notifications", core=False),
            SkillDefinition("configure-slack", SkillCategory.UTILITY, SkillStatus.MERGED, canonical="configure-notifications", core=False),
            SkillDefinition("configure-openclaw", SkillCategory.UTILITY, SkillStatus.MERGED, canonical="configure-notifications", core=False),
            SkillDefinition("ralph-init", SkillCategory.UTILITY, SkillStatus.MERGED, canonical="plan"),
            SkillDefinition("worker", SkillCategory.UTILITY, SkillStatus.INTERNAL, internal_required=True),
        ]

        agents = [
            # Build
            AgentDefinition("explore", AgentCategory.BUILD, "active"),
            AgentDefinition("analyst", AgentCategory.BUILD, "active"),
            AgentDefinition("planner", AgentCategory.BUILD, "active"),
            AgentDefinition("architect", AgentCategory.BUILD, "active"),
            AgentDefinition("debugger", AgentCategory.BUILD, "active"),
            AgentDefinition("executor", AgentCategory.BUILD, "active"),
            AgentDefinition("team-executor", AgentCategory.BUILD, "internal"),
            AgentDefinition("verifier", AgentCategory.BUILD, "active"),
            # Review
            AgentDefinition("style-reviewer", AgentCategory.REVIEW, "merged", canonical="code-reviewer"),
            AgentDefinition("quality-reviewer", AgentCategory.REVIEW, "merged", canonical="code-reviewer"),
            AgentDefinition("api-reviewer", AgentCategory.REVIEW, "merged", canonical="code-reviewer"),
            AgentDefinition("security-reviewer", AgentCategory.REVIEW, "active"),
            AgentDefinition("performance-reviewer", AgentCategory.REVIEW, "merged", canonical="code-reviewer"),
            AgentDefinition("code-reviewer", AgentCategory.REVIEW, "active"),
            # Domain
            AgentDefinition("dependency-expert", AgentCategory.DOMAIN, "active"),
            AgentDefinition("test-engineer", AgentCategory.DOMAIN, "active"),
            AgentDefinition("quality-strategist", AgentCategory.DOMAIN, "merged", canonical="verifier"),
            AgentDefinition("build-fixer", AgentCategory.DOMAIN, "active"),
            AgentDefinition("designer", AgentCategory.DOMAIN, "active"),
            AgentDefinition("writer", AgentCategory.DOMAIN, "active"),
            AgentDefinition("qa-tester", AgentCategory.DOMAIN, "merged", canonical="test-engineer"),
            AgentDefinition("git-master", AgentCategory.DOMAIN, "active"),
            AgentDefinition("code-simplifier", AgentCategory.DOMAIN, "internal"),
            AgentDefinition("researcher", AgentCategory.DOMAIN, "active"),
            # Product
            AgentDefinition("product-manager", AgentCategory.PRODUCT, "merged", canonical="analyst"),
            AgentDefinition("ux-researcher", AgentCategory.PRODUCT, "merged", canonical="designer"),
            AgentDefinition("information-architect", AgentCategory.PRODUCT, "merged", canonical="designer"),
            AgentDefinition("product-analyst", AgentCategory.PRODUCT, "merged", canonical="analyst"),
            # Coordination
            AgentDefinition("critic", AgentCategory.COORDINATION, "active"),
            AgentDefinition("vision", AgentCategory.COORDINATION, "active"),
        ]

        return cls(skills=skills, agents=agents)

    def get_active_skills(self) -> list[SkillDefinition]:
        """获取活跃技能"""
        return [s for s in self.skills if s.status == SkillStatus.ACTIVE]

    def get_active_agents(self) -> list[AgentDefinition]:
        """获取活跃 Agent"""
        return [a for a in self.agents if a.status == "active"]

    def resolve_canonical(self, name: str) -> str:
        """解析别名到规范名称"""
        for skill in self.skills:
            if skill.name == name and skill.canonical:
                return skill.canonical
        for agent in self.agents:
            if agent.name == name and agent.canonical:
                return agent.canonical
        return name


# 全局清单实例
_catalog: CatalogManifest | None = None


def get_catalog() -> CatalogManifest:
    """获取全局清单实例"""
    global _catalog
    if _catalog is None:
        _catalog = CatalogManifest.from_omx()
    return _catalog


def reload_catalog() -> CatalogManifest:
    """重新加载清单"""
    global _catalog
    _catalog = CatalogManifest.from_omx()
    return _catalog
