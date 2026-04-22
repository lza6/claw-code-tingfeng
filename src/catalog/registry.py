"""Catalog Registry - 技能注册表"""


from src.catalog.manifest import AgentDefinition, CatalogManifest, SkillDefinition, get_catalog


class CatalogRegistry:
    """技能/Agent 注册表"""

    def __init__(self, manifest: CatalogManifest | None = None):
        self._manifest = manifest or get_catalog()
        self._skill_cache: dict[str, SkillDefinition] = {}
        self._agent_cache: dict[str, AgentDefinition] = {}
        self._build_cache()

    def _build_cache(self):
        """构建缓存"""
        for skill in self._manifest.skills:
            self._skill_cache[skill.name] = skill
        for agent in self._manifest.agents:
            self._agent_cache[agent.name] = agent

    def get_skill(self, name: str) -> SkillDefinition | None:
        """获取技能定义"""
        resolved = self._manifest.resolve_canonical(name)
        return self._skill_cache.get(resolved)

    def get_agent(self, name: str) -> AgentDefinition | None:
        """获取 Agent 定义"""
        resolved = self._manifest.resolve_canonical(name)
        return self._agent_cache.get(resolved)

    def list_skills(self, category: str | None = None, active_only: bool = False) -> list[SkillDefinition]:
        """列出技能"""
        skills = self._manifest.skills
        if active_only:
            skills = [s for s in skills if s.status.value == "active"]
        if category:
            skills = [s for s in skills if s.category.value == category]
        return skills

    def list_agents(self, category: str | None = None, active_only: bool = False) -> list[AgentDefinition]:
        """列出 Agent"""
        agents = self._manifest.agents
        if active_only:
            agents = [a for a in agents if a.status == "active"]
        if category:
            agents = [a for a in agents if a.category.value == category]
        return agents

    def search(self, query: str) -> dict[str, list]:
        """搜索技能和 Agent"""
        query_lower = query.lower()
        skills = [s for s in self._manifest.skills if query_lower in s.name]
        agents = [a for a in self._manifest.agents if query_lower in a.name]
        return {"skills": skills, "agents": agents}


# 全局注册表实例
_registry: CatalogRegistry | None = None


def get_registry() -> CatalogRegistry:
    """获取全局注册表"""
    global _registry
    if _registry is None:
        _registry = CatalogRegistry()
    return _registry
