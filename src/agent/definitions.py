"""
Agent Definitions - Agent角色定义

从 oh-my-codex-main/src/agents/definitions.ts 转换而来。
定义所有可用的Agent角色及其配置。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AgentPosture(str, Enum):
    """Agent姿态"""
    FRONTIER_ORCHESTRATOR = "frontier-orchestrator"
    DEEP_WORKER = "deep-worker"
    FAST_LANE = "fast-lane"


class AgentModelClass(str, Enum):
    """模型类别"""
    FRONTIER = "frontier"
    STANDARD = "standard"
    FAST = "fast"


class AgentRoutingRole(str, Enum):
    """路由角色"""
    LEADER = "leader"
    SPECIALIST = "specialist"
    EXECUTOR = "executor"


class AgentToolAccess(str, Enum):
    """工具访问模式"""
    READ_ONLY = "read-only"
    ANALYSIS = "analysis"
    EXECUTION = "execution"
    DATA = "data"


class AgentCategory(str, Enum):
    """Agent类别"""
    BUILD = "build"
    REVIEW = "review"
    DOMAIN = "domain"
    PRODUCT = "product"
    COORDINATION = "coordination"


@dataclass
class AgentDefinition:
    """Agent定义"""
    name: str
    description: str
    reasoning_effort: str  # 'low' | 'medium' | 'high'
    posture: str  # AgentPosture
    model_class: str  # AgentModelClass
    routing_role: str  # AgentRoutingRole
    tools: str  # AgentToolAccess
    category: str  # AgentCategory


# ===== Agent定义 =====
AGENT_DEFINITIONS: dict[str, AgentDefinition] = {
    # Build/Analysis Lane
    "explore": AgentDefinition(
        name="explore",
        description="Fast codebase search and file/symbol mapping",
        reasoning_effort="low",
        posture=AgentPosture.FAST_LANE.value,
        model_class=AgentModelClass.FAST.value,
        routing_role=AgentRoutingRole.SPECIALIST.value,
        tools=AgentToolAccess.READ_ONLY.value,
        category=AgentCategory.BUILD.value,
    ),
    "analyst": AgentDefinition(
        name="analyst",
        description="Requirements clarity, acceptance criteria, hidden constraints",
        reasoning_effort="medium",
        posture=AgentPosture.FRONTIER_ORCHESTRATOR.value,
        model_class=AgentModelClass.FRONTIER.value,
        routing_role=AgentRoutingRole.LEADER.value,
        tools=AgentToolAccess.ANALYSIS.value,
        category=AgentCategory.BUILD.value,
    ),
    "planner": AgentDefinition(
        name="planner",
        description="Task sequencing, execution plans, risk flags",
        reasoning_effort="medium",
        posture=AgentPosture.FRONTIER_ORCHESTRATOR.value,
        model_class=AgentModelClass.FRONTIER.value,
        routing_role=AgentRoutingRole.LEADER.value,
        tools=AgentToolAccess.ANALYSIS.value,
        category=AgentCategory.BUILD.value,
    ),
    "architect": AgentDefinition(
        name="architect",
        description="System design, boundaries, interfaces, long-horizon tradeoffs",
        reasoning_effort="high",
        posture=AgentPosture.FRONTIER_ORCHESTRATOR.value,
        model_class=AgentModelClass.FRONTIER.value,
        routing_role=AgentRoutingRole.LEADER.value,
        tools=AgentToolAccess.READ_ONLY.value,
        category=AgentCategory.BUILD.value,
    ),
    "debugger": AgentDefinition(
        name="debugger",
        description="Root-cause analysis, regression isolation, failure diagnosis",
        reasoning_effort="high",
        posture=AgentPosture.DEEP_WORKER.value,
        model_class=AgentModelClass.STANDARD.value,
        routing_role=AgentRoutingRole.EXECUTOR.value,
        tools=AgentToolAccess.ANALYSIS.value,
        category=AgentCategory.BUILD.value,
    ),
    "executor": AgentDefinition(
        name="executor",
        description="Code implementation, refactoring, feature work",
        reasoning_effort="high",
        posture=AgentPosture.DEEP_WORKER.value,
        model_class=AgentModelClass.STANDARD.value,
        routing_role=AgentRoutingRole.EXECUTOR.value,
        tools=AgentToolAccess.EXECUTION.value,
        category=AgentCategory.BUILD.value,
    ),
    "team-executor": AgentDefinition(
        name="team-executor",
        description="Supervised team execution for conservative delivery lanes",
        reasoning_effort="medium",
        posture=AgentPosture.DEEP_WORKER.value,
        model_class=AgentModelClass.FRONTIER.value,
        routing_role=AgentRoutingRole.EXECUTOR.value,
        tools=AgentToolAccess.EXECUTION.value,
        category=AgentCategory.BUILD.value,
    ),
    "verifier": AgentDefinition(
        name="verifier",
        description="Completion evidence, claim validation, test adequacy",
        reasoning_effort="high",
        posture=AgentPosture.FRONTIER_ORCHESTRATOR.value,
        model_class=AgentModelClass.STANDARD.value,
        routing_role=AgentRoutingRole.LEADER.value,
        tools=AgentToolAccess.ANALYSIS.value,
        category=AgentCategory.BUILD.value,
    ),

    # Review Lane
    "style-reviewer": AgentDefinition(
        name="style-reviewer",
        description="Formatting, naming, idioms, lint conventions",
        reasoning_effort="low",
        posture=AgentPosture.FAST_LANE.value,
        model_class=AgentModelClass.FAST.value,
        routing_role=AgentRoutingRole.SPECIALIST.value,
        tools=AgentToolAccess.READ_ONLY.value,
        category=AgentCategory.REVIEW.value,
    ),
    "quality-reviewer": AgentDefinition(
        name="quality-reviewer",
        description="Logic defects, maintainability, anti-patterns",
        reasoning_effort="medium",
        posture=AgentPosture.FRONTIER_ORCHESTRATOR.value,
        model_class=AgentModelClass.STANDARD.value,
        routing_role=AgentRoutingRole.LEADER.value,
        tools=AgentToolAccess.READ_ONLY.value,
        category=AgentCategory.REVIEW.value,
    ),
    "api-reviewer": AgentDefinition(
        name="api-reviewer",
        description="API contracts, versioning, backward compatibility",
        reasoning_effort="medium",
        posture=AgentPosture.FRONTIER_ORCHESTRATOR.value,
        model_class=AgentModelClass.STANDARD.value,
        routing_role=AgentRoutingRole.LEADER.value,
        tools=AgentToolAccess.READ_ONLY.value,
        category=AgentCategory.REVIEW.value,
    ),
    "security-reviewer": AgentDefinition(
        name="security-reviewer",
        description="Vulnerabilities, trust boundaries, authn/authz",
        reasoning_effort="medium",
        posture=AgentPosture.FRONTIER_ORCHESTRATOR.value,
        model_class=AgentModelClass.FRONTIER.value,
        routing_role=AgentRoutingRole.LEADER.value,
        tools=AgentToolAccess.READ_ONLY.value,
        category=AgentCategory.REVIEW.value,
    ),
    "performance-reviewer": AgentDefinition(
        name="performance-reviewer",
        description="Hotspots, complexity, memory/latency optimization",
        reasoning_effort="medium",
        posture=AgentPosture.FRONTIER_ORCHESTRATOR.value,
        model_class=AgentModelClass.STANDARD.value,
        routing_role=AgentRoutingRole.LEADER.value,
        tools=AgentToolAccess.READ_ONLY.value,
        category=AgentCategory.REVIEW.value,
    ),
    "code-reviewer": AgentDefinition(
        name="code-reviewer",
        description="Comprehensive review across all concerns",
        reasoning_effort="high",
        posture=AgentPosture.FRONTIER_ORCHESTRATOR.value,
        model_class=AgentModelClass.FRONTIER.value,
        routing_role=AgentRoutingRole.LEADER.value,
        tools=AgentToolAccess.READ_ONLY.value,
        category=AgentCategory.REVIEW.value,
    ),

    # Domain Specialists
    "dependency-expert": AgentDefinition(
        name="dependency-expert",
        description="External SDK/API/package evaluation",
        reasoning_effort="high",
        posture=AgentPosture.FRONTIER_ORCHESTRATOR.value,
        model_class=AgentModelClass.STANDARD.value,
        routing_role=AgentRoutingRole.SPECIALIST.value,
        tools=AgentToolAccess.ANALYSIS.value,
        category=AgentCategory.DOMAIN.value,
    ),
    "test-engineer": AgentDefinition(
        name="test-engineer",
        description="Test strategy, coverage, flaky-test hardening",
        reasoning_effort="medium",
        posture=AgentPosture.DEEP_WORKER.value,
        model_class=AgentModelClass.FRONTIER.value,
        routing_role=AgentRoutingRole.EXECUTOR.value,
        tools=AgentToolAccess.EXECUTION.value,
        category=AgentCategory.DOMAIN.value,
    ),
    "quality-strategist": AgentDefinition(
        name="quality-strategist",
        description="Quality strategy, release readiness, risk assessment",
        reasoning_effort="medium",
        posture=AgentPosture.FRONTIER_ORCHESTRATOR.value,
        model_class=AgentModelClass.STANDARD.value,
        routing_role=AgentRoutingRole.LEADER.value,
        tools=AgentToolAccess.ANALYSIS.value,
        category=AgentCategory.DOMAIN.value,
    ),
    "build-fixer": AgentDefinition(
        name="build-fixer",
        description="Build/toolchain/type failures resolution",
        reasoning_effort="high",
        posture=AgentPosture.DEEP_WORKER.value,
        model_class=AgentModelClass.STANDARD.value,
        routing_role=AgentRoutingRole.EXECUTOR.value,
        tools=AgentToolAccess.EXECUTION.value,
        category=AgentCategory.DOMAIN.value,
    ),
    "designer": AgentDefinition(
        name="designer",
        description="UX/UI architecture, interaction design",
        reasoning_effort="high",
        posture=AgentPosture.DEEP_WORKER.value,
        model_class=AgentModelClass.STANDARD.value,
        routing_role=AgentRoutingRole.EXECUTOR.value,
        tools=AgentToolAccess.EXECUTION.value,
        category=AgentCategory.DOMAIN.value,
    ),
    "writer": AgentDefinition(
        name="writer",
        description="Documentation, migration notes, user guidance",
        reasoning_effort="high",
        posture=AgentPosture.FAST_LANE.value,
        model_class=AgentModelClass.STANDARD.value,
        routing_role=AgentRoutingRole.SPECIALIST.value,
        tools=AgentToolAccess.EXECUTION.value,
        category=AgentCategory.DOMAIN.value,
    ),
    "qa-tester": AgentDefinition(
        name="qa-tester",
        description="Interactive CLI/service runtime validation",
        reasoning_effort="low",
        posture=AgentPosture.DEEP_WORKER.value,
        model_class=AgentModelClass.STANDARD.value,
        routing_role=AgentRoutingRole.EXECUTOR.value,
        tools=AgentToolAccess.EXECUTION.value,
        category=AgentCategory.DOMAIN.value,
    ),
    "git-master": AgentDefinition(
        name="git-master",
        description="Commit strategy, history hygiene, rebasing",
        reasoning_effort="high",
        posture=AgentPosture.DEEP_WORKER.value,
        model_class=AgentModelClass.STANDARD.value,
        routing_role=AgentRoutingRole.EXECUTOR.value,
        tools=AgentToolAccess.EXECUTION.value,
        category=AgentCategory.DOMAIN.value,
    ),
    "code-simplifier": AgentDefinition(
        name="code-simplifier",
        description="Simplifies recently modified code for clarity and consistency without changing behavior",
        reasoning_effort="high",
        posture=AgentPosture.DEEP_WORKER.value,
        model_class=AgentModelClass.FRONTIER.value,
        routing_role=AgentRoutingRole.EXECUTOR.value,
        tools=AgentToolAccess.EXECUTION.value,
        category=AgentCategory.DOMAIN.value,
    ),
    "researcher": AgentDefinition(
        name="researcher",
        description="External documentation and reference research",
        reasoning_effort="high",
        posture=AgentPosture.FAST_LANE.value,
        model_class=AgentModelClass.STANDARD.value,
        routing_role=AgentRoutingRole.SPECIALIST.value,
        tools=AgentToolAccess.ANALYSIS.value,
        category=AgentCategory.DOMAIN.value,
    ),

    # Product Lane
    "product-manager": AgentDefinition(
        name="product-manager",
        description="Problem framing, personas/JTBD, PRDs",
        reasoning_effort="medium",
        posture=AgentPosture.FRONTIER_ORCHESTRATOR.value,
        model_class=AgentModelClass.STANDARD.value,
        routing_role=AgentRoutingRole.LEADER.value,
        tools=AgentToolAccess.ANALYSIS.value,
        category=AgentCategory.PRODUCT.value,
    ),
    "ux-researcher": AgentDefinition(
        name="ux-researcher",
        description="Heuristic audits, usability, accessibility",
        reasoning_effort="medium",
        posture=AgentPosture.FRONTIER_ORCHESTRATOR.value,
        model_class=AgentModelClass.STANDARD.value,
        routing_role=AgentRoutingRole.SPECIALIST.value,
        tools=AgentToolAccess.ANALYSIS.value,
        category=AgentCategory.PRODUCT.value,
    ),
    "information-architect": AgentDefinition(
        name="information-architect",
        description="Taxonomy, navigation, findability",
        reasoning_effort="low",
        posture=AgentPosture.FRONTIER_ORCHESTRATOR.value,
        model_class=AgentModelClass.STANDARD.value,
        routing_role=AgentRoutingRole.SPECIALIST.value,
        tools=AgentToolAccess.ANALYSIS.value,
        category=AgentCategory.PRODUCT.value,
    ),
    "product-analyst": AgentDefinition(
        name="product-analyst",
        description="Product metrics, funnel analysis, experiments",
        reasoning_effort="low",
        posture=AgentPosture.FRONTIER_ORCHESTRATOR.value,
        model_class=AgentModelClass.STANDARD.value,
        routing_role=AgentRoutingRole.SPECIALIST.value,
        tools=AgentToolAccess.ANALYSIS.value,
        category=AgentCategory.PRODUCT.value,
    ),

    # Coordination
    "critic": AgentDefinition(
        name="critic",
        description="Plan/design critical challenge and review",
        reasoning_effort="high",
        posture=AgentPosture.FRONTIER_ORCHESTRATOR.value,
        model_class=AgentModelClass.FRONTIER.value,
        routing_role=AgentRoutingRole.LEADER.value,
        tools=AgentToolAccess.READ_ONLY.value,
        category=AgentCategory.COORDINATION.value,
    ),
    "vision": AgentDefinition(
        name="vision",
        description="Image/screenshot/diagram analysis",
        reasoning_effort="low",
        posture=AgentPosture.FAST_LANE.value,
        model_class=AgentModelClass.FRONTIER.value,
        routing_role=AgentRoutingRole.SPECIALIST.value,
        tools=AgentToolAccess.READ_ONLY.value,
        category=AgentCategory.COORDINATION.value,
    ),
}


def get_agent(name: str) -> Optional[AgentDefinition]:
    """获取Agent定义"""
    return AGENT_DEFINITIONS.get(name)


def get_agents_by_category(category: str) -> list[AgentDefinition]:
    """获取指定类别的所有Agent"""
    return [a for a in AGENT_DEFINITIONS.values() if a.category == category]


def get_agent_names() -> list[str]:
    """获取所有Agent名称"""
    return list(AGENT_DEFINITIONS.keys())


# ===== 导出 =====
__all__ = [
    "AgentDefinition",
    "AgentPosture",
    "AgentModelClass",
    "AgentRoutingRole",
    "AgentToolAccess",
    "AgentCategory",
    "AGENT_DEFINITIONS",
    "get_agent",
    "get_agents_by_category",
    "get_agent_names",
]
