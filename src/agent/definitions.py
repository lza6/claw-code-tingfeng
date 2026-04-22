"""Agent Role Definitions for Clawd Code

借鉴 oh-my-codex 的精细化角色分类体系。
每个 Agent 有: 名称、描述、推理级别、姿态、模型类别、路由角色、工具访问模式、分类。
"""

from dataclasses import dataclass
from enum import Enum


class ReasoningEffort(str, Enum):
    """推理努力级别"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"


class AgentPosture(str, Enum):
    """Agent 姿态 (借鉴 OMX)"""
    FRONTIER_ORCHESTRATOR = "frontier-orchestrator"  # 顶层路由和决策
    DEEP_WORKER = "deep-worker"                      # 深度执行专家
    FAST_LANE = "fast-lane"                          # 快速通道 (读/分析)


class ModelClass(str, Enum):
    """模型类别"""
    FRONTIER = "frontier"   # 最强模型 (o1/Claude Sonnet)
    STANDARD = "standard"   # 标准模型 (GPT-4o, Claude)
    FAST = "fast"          # 快速模型 (GPT-4o-mini, Haiku)


class RoutingRole(str, Enum):
    """路由角色"""
    LEADER = "leader"       # 领导/协调角色
    SPECIALIST = "specialist"  # 专项专家
    EXECUTOR = "executor"   # 执行者


class ToolAccess(str, Enum):
    """工具访问模式"""
    READ_ONLY = "read-only"    # 只读 (浏览/分析)
    ANALYSIS = "analysis"      # 分析 (需要计算)
    EXECUTION = "execution"    # 执行 (修改文件/运行)
    DATA = "data"             # 数据操作


class AgentCategory(str, Enum):
    """Agent 分类"""
    BUILD = "build"         # 构建/实现
    REVIEW = "review"       # 审查/质量
    DOMAIN = "domain"       # 领域专家
    PRODUCT = "product"     # 产品/需求
    COORDINATION = "coordination"  # 协调


@dataclass(frozen=True)
class AgentDefinition:
    """Agent 定义"""
    name: str
    description: str
    reasoningEffort: ReasoningEffort
    posture: AgentPosture
    modelClass: ModelClass
    routingRole: RoutingRole
    tools: ToolAccess
    category: AgentCategory


# ==================== 核心 Agent 定义 (借鉴 oh-my-codex) ====================

EXECUTOR_AGENT = AgentDefinition(
    name='executor',
    description='Code implementation, refactoring, feature work',
    reasoningEffort=ReasoningEffort.HIGH,
    posture=AgentPosture.DEEP_WORKER,
    modelClass=ModelClass.STANDARD,
    routingRole=RoutingRole.EXECUTOR,
    tools=ToolAccess.EXECUTION,
    category=AgentCategory.BUILD,
)

TEAM_EXECUTOR_AGENT = AgentDefinition(
    name='team-executor',
    description='Supervised team execution for conservative delivery lanes',
    reasoningEffort=ReasoningEffort.MEDIUM,
    posture=AgentPosture.DEEP_WORKER,
    modelClass=ModelClass.FRONTIER,
    routingRole=RoutingRole.EXECUTOR,
    tools=ToolAccess.EXECUTION,
    category=AgentCategory.BUILD,
)


# ==================== Agent 定义注册表 ====================

AGENT_DEFINITIONS: dict[str, AgentDefinition] = {
    # ========== 构建/分析车道 ==========
    'explore': AgentDefinition(
        name='explore',
        description='Fast codebase search and file/symbol mapping',
        reasoningEffort=ReasoningEffort.LOW,
        posture=AgentPosture.FAST_LANE,
        modelClass=ModelClass.FAST,
        routingRole=RoutingRole.SPECIALIST,
        tools=ToolAccess.READ_ONLY,
        category=AgentCategory.BUILD,
    ),
    'analyst': AgentDefinition(
        name='analyst',
        description='Requirements clarity, acceptance criteria, hidden constraints',
        reasoningEffort=ReasoningEffort.MEDIUM,
        posture=AgentPosture.FRONTIER_ORCHESTRATOR,
        modelClass=ModelClass.FRONTIER,
        routingRole=RoutingRole.LEADER,
        tools=ToolAccess.ANALYSIS,
        category=AgentCategory.BUILD,
    ),
    'planner': AgentDefinition(
        name='planner',
        description='Task sequencing, execution plans, risk flags',
        reasoningEffort=ReasoningEffort.MEDIUM,
        posture=AgentPosture.FRONTIER_ORCHESTRATOR,
        modelClass=ModelClass.FRONTIER,
        routingRole=RoutingRole.LEADER,
        tools=ToolAccess.ANALYSIS,
        category=AgentCategory.BUILD,
    ),
    'architect': AgentDefinition(
        name='architect',
        description='System design, boundaries, interfaces, long-horizon tradeoffs',
        reasoningEffort=ReasoningEffort.HIGH,
        posture=AgentPosture.FRONTIER_ORCHESTRATOR,
        modelClass=ModelClass.FRONTIER,
        routingRole=RoutingRole.LEADER,
        tools=ToolAccess.READ_ONLY,
        category=AgentCategory.BUILD,
    ),
    'debugger': AgentDefinition(
        name='debugger',
        description='Root-cause analysis, regression isolation, failure diagnosis',
        reasoningEffort=ReasoningEffort.HIGH,
        posture=AgentPosture.DEEP_WORKER,
        modelClass=ModelClass.STANDARD,
        routingRole=RoutingRole.EXECUTOR,
        tools=ToolAccess.ANALYSIS,
        category=AgentCategory.BUILD,
    ),
    'executor': EXECUTOR_AGENT,
    'team-executor': TEAM_EXECUTOR_AGENT,
    'verifier': AgentDefinition(
        name='verifier',
        description='Completion evidence, claim validation, test adequacy',
        reasoningEffort=ReasoningEffort.HIGH,
        posture=AgentPosture.FRONTIER_ORCHESTRATOR,
        modelClass=ModelClass.STANDARD,
        routingRole=RoutingRole.LEADER,
        tools=ToolAccess.ANALYSIS,
        category=AgentCategory.BUILD,
    ),

    # ========== 审查车道 ==========
    'style-reviewer': AgentDefinition(
        name='style-reviewer',
        description='Formatting, naming, idioms, lint conventions',
        reasoningEffort=ReasoningEffort.LOW,
        posture=AgentPosture.FAST_LANE,
        modelClass=ModelClass.FAST,
        routingRole=RoutingRole.SPECIALIST,
        tools=ToolAccess.READ_ONLY,
        category=AgentCategory.REVIEW,
    ),
    'quality-reviewer': AgentDefinition(
        name='quality-reviewer',
        description='Logic defects, maintainability, anti-patterns',
        reasoningEffort=ReasoningEffort.MEDIUM,
        posture=AgentPosture.FRONTIER_ORCHESTRATOR,
        modelClass=ModelClass.STANDARD,
        routingRole=RoutingRole.LEADER,
        tools=ToolAccess.READ_ONLY,
        category=AgentCategory.REVIEW,
    ),
    'api-reviewer': AgentDefinition(
        name='api-reviewer',
        description='API contracts, versioning, backward compatibility',
        reasoningEffort=ReasoningEffort.MEDIUM,
        posture=AgentPosture.FRONTIER_ORCHESTRATOR,
        modelClass=ModelClass.STANDARD,
        routingRole=RoutingRole.LEADER,
        tools=ToolAccess.READ_ONLY,
        category=AgentCategory.REVIEW,
    ),
    'security-reviewer': AgentDefinition(
        name='security-reviewer',
        description='Vulnerabilities, trust boundaries, authn/authz',
        reasoningEffort=ReasoningEffort.MEDIUM,
        posture=AgentPosture.FRONTIER_ORCHESTRATOR,
        modelClass=ModelClass.FRONTIER,
        routingRole=RoutingRole.LEADER,
        tools=ToolAccess.READ_ONLY,
        category=AgentCategory.REVIEW,
    ),
    'performance-reviewer': AgentDefinition(
        name='performance-reviewer',
        description='Hotspots, complexity, memory/latency optimization',
        reasoningEffort=ReasoningEffort.MEDIUM,
        posture=AgentPosture.FRONTIER_ORCHESTRATOR,
        modelClass=ModelClass.STANDARD,
        routingRole=RoutingRole.LEADER,
        tools=ToolAccess.READ_ONLY,
        category=AgentCategory.REVIEW,
    ),
    'code-reviewer': AgentDefinition(
        name='code-reviewer',
        description='Comprehensive review across all concerns',
        reasoningEffort=ReasoningEffort.HIGH,
        posture=AgentPosture.FRONTIER_ORCHESTRATOR,
        modelClass=ModelClass.FRONTIER,
        routingRole=RoutingRole.LEADER,
        tools=ToolAccess.READ_ONLY,
        category=AgentCategory.REVIEW,
    ),

    # ========== 领域专家 ==========
    'dependency-expert': AgentDefinition(
        name='dependency-expert',
        description='External SDK/API/package evaluation',
        reasoningEffort=ReasoningEffort.HIGH,
        posture=AgentPosture.FRONTIER_ORCHESTRATOR,
        modelClass=ModelClass.STANDARD,
        routingRole=RoutingRole.SPECIALIST,
        tools=ToolAccess.ANALYSIS,
        category=AgentCategory.DOMAIN,
    ),
    'test-engineer': AgentDefinition(
        name='test-engineer',
        description='Test strategy, coverage, flaky-test hardening',
        reasoningEffort=ReasoningEffort.MEDIUM,
        posture=AgentPosture.DEEP_WORKER,
        modelClass=ModelClass.FRONTIER,
        routingRole=RoutingRole.EXECUTOR,
        tools=ToolAccess.EXECUTION,
        category=AgentCategory.DOMAIN,
    ),
    'quality-strategist': AgentDefinition(
        name='quality-strategist',
        description='Quality strategy, release readiness, risk assessment',
        reasoningEffort=ReasoningEffort.MEDIUM,
        posture=AgentPosture.FRONTIER_ORCHESTRATOR,
        modelClass=ModelClass.STANDARD,
        routingRole=RoutingRole.LEADER,
        tools=ToolAccess.ANALYSIS,
        category=AgentCategory.DOMAIN,
    ),
    'build-fixer': AgentDefinition(
        name='build-fixer',
        description='Build/toolchain/type failures resolution',
        reasoningEffort=ReasoningEffort.HIGH,
        posture=AgentPosture.DEEP_WORKER,
        modelClass=ModelClass.STANDARD,
        routingRole=RoutingRole.EXECUTOR,
        tools=ToolAccess.EXECUTION,
        category=AgentCategory.DOMAIN,
    ),
    'designer': AgentDefinition(
        name='designer',
        description='UX/UI architecture, interaction design',
        reasoningEffort=ReasoningEffort.HIGH,
        posture=AgentPosture.DEEP_WORKER,
        modelClass=ModelClass.STANDARD,
        routingRole=RoutingRole.EXECUTOR,
        tools=ToolAccess.EXECUTION,
        category=AgentCategory.DOMAIN,
    ),
    'writer': AgentDefinition(
        name='writer',
        description='Documentation, migration notes, user guidance',
        reasoningEffort=ReasoningEffort.HIGH,
        posture=AgentPosture.FAST_LANE,
        modelClass=ModelClass.STANDARD,
        routingRole=RoutingRole.SPECIALIST,
        tools=ToolAccess.EXECUTION,
        category=AgentCategory.DOMAIN,
    ),
    'qa-tester': AgentDefinition(
        name='qa-tester',
        description='Interactive CLI/service runtime validation',
        reasoningEffort=ReasoningEffort.LOW,
        posture=AgentPosture.DEEP_WORKER,
        modelClass=ModelClass.STANDARD,
        routingRole=RoutingRole.EXECUTOR,
        tools=ToolAccess.EXECUTION,
        category=AgentCategory.DOMAIN,
    ),
    'git-master': AgentDefinition(
        name='git-master',
        description='Commit strategy, history hygiene, rebasing',
        reasoningEffort=ReasoningEffort.HIGH,
        posture=AgentPosture.DEEP_WORKER,
        modelClass=ModelClass.STANDARD,
        routingRole=RoutingRole.EXECUTOR,
        tools=ToolAccess.EXECUTION,
        category=AgentCategory.DOMAIN,
    ),
    'code-simplifier': AgentDefinition(
        name='code-simplifier',
        description='Simplifies recently modified code for clarity and consistency without changing behavior',
        reasoningEffort=ReasoningEffort.HIGH,
        posture=AgentPosture.DEEP_WORKER,
        modelClass=ModelClass.FRONTIER,
        routingRole=RoutingRole.EXECUTOR,
        tools=ToolAccess.EXECUTION,
        category=AgentCategory.DOMAIN,
    ),
    'researcher': AgentDefinition(
        name='researcher',
        description='External documentation and reference research',
        reasoningEffort=ReasoningEffort.HIGH,
        posture=AgentPosture.FAST_LANE,
        modelClass=ModelClass.STANDARD,
        routingRole=RoutingRole.SPECIALIST,
        tools=ToolAccess.ANALYSIS,
        category=AgentCategory.DOMAIN,
    ),

    # ========== 产品车道 ==========
    'product-manager': AgentDefinition(
        name='product-manager',
        description='Problem framing, personas/JTBD, PRDs',
        reasoningEffort=ReasoningEffort.MEDIUM,
        posture=AgentPosture.FRONTIER_ORCHESTRATOR,
        modelClass=ModelClass.STANDARD,
        routingRole=RoutingRole.LEADER,
        tools=ToolAccess.ANALYSIS,
        category=AgentCategory.PRODUCT,
    ),
    'ux-researcher': AgentDefinition(
        name='ux-researcher',
        description='Heuristic audits, usability, accessibility',
        reasoningEffort=ReasoningEffort.MEDIUM,
        posture=AgentPosture.FRONTIER_ORCHESTRATOR,
        modelClass=ModelClass.STANDARD,
        routingRole=RoutingRole.SPECIALIST,
        tools=ToolAccess.ANALYSIS,
        category=AgentCategory.PRODUCT,
    ),
    'information-architect': AgentDefinition(
        name='information-architect',
        description='Taxonomy, navigation, findability',
        reasoningEffort=ReasoningEffort.LOW,
        posture=AgentPosture.FRONTIER_ORCHESTRATOR,
        modelClass=ModelClass.STANDARD,
        routingRole=RoutingRole.SPECIALIST,
        tools=ToolAccess.ANALYSIS,
        category=AgentCategory.PRODUCT,
    ),
    'product-analyst': AgentDefinition(
        name='product-analyst',
        description='Product metrics, funnel analysis, experiments',
        reasoningEffort=ReasoningEffort.LOW,
        posture=AgentPosture.FRONTIER_ORCHESTRATOR,
        modelClass=ModelClass.STANDARD,
        routingRole=RoutingRole.SPECIALIST,
        tools=ToolAccess.ANALYSIS,
        category=AgentCategory.PRODUCT,
    ),

    # ========== 协调角色 ==========
    'critic': AgentDefinition(
        name='critic',
        description='Plan/design critical challenge and review',
        reasoningEffort=ReasoningEffort.HIGH,
        posture=AgentPosture.FRONTIER_ORCHESTRATOR,
        modelClass=ModelClass.FRONTIER,
        routingRole=RoutingRole.LEADER,
        tools=ToolAccess.READ_ONLY,
        category=AgentCategory.COORDINATION,
    ),
    'vision': AgentDefinition(
        name='vision',
        description='Image/screenshot/diagram analysis',
        reasoningEffort=ReasoningEffort.LOW,
        posture=AgentPosture.FAST_LANE,
        modelClass=ModelClass.FRONTIER,
        routingRole=RoutingRole.SPECIALIST,
        tools=ToolAccess.READ_ONLY,
        category=AgentCategory.COORDINATION,
    ),
}


# ==================== 工具函数 ====================

def get_agent(name: str) -> AgentDefinition | None:
    """根据名称获取 Agent 定义"""
    return AGENT_DEFINITIONS.get(name)


def get_agents_by_category(category: AgentCategory) -> list[AgentDefinition]:
    """按分类获取所有 Agent"""
    return [a for a in AGENT_DEFINITIONS.values() if a.category == category]


def get_agent_names() -> list[str]:
    """获取所有 Agent 名称"""
    return list(AGENT_DEFINITIONS.keys())


def get_agents_by_posture(posture: AgentPosture) -> list[AgentDefinition]:
    """按姿态获取 Agent"""
    return [a for a in AGENT_DEFINITIONS.values() if a.posture == posture]


def get_agents_by_routing_role(routing_role: RoutingRole) -> list[AgentDefinition]:
    """按路由角色获取 Agent"""
    return [a for a in AGENT_DEFINITIONS.values() if a.routingRole == routing_role]


def select_agent_for_task(task_description: str, required_tools: str | None = None) -> AgentDefinition:
    """
    Fallback: 当 intent_router 不可用时返回默认 agent。

    注意: 真正的 Agent 路由应该由 intent_router.py 或 LLM-based router 处理。
    此函数仅作为降级策略，避免在路由失败时系统崩溃。

    Args:
        task_description: 任务描述（未使用，保留接口兼容性）
        required_tools: 所需工具访问模式（未使用，保留接口兼容性）

    Returns:
        默认的 executor agent
    """
    # 简单兜底：始终返回 executor
    return AGENT_DEFINITIONS['executor']


# 导出所有公共符号
__all__ = [
    'AGENT_DEFINITIONS',
    'AgentCategory',
    'AgentDefinition',
    'AgentPosture',
    'ModelClass',
    'ReasoningEffort',
    'RoutingRole',
    'ToolAccess',
    'get_agent',
    'get_agent_names',
    'get_agents_by_category',
    'get_agents_by_posture',
    'get_agents_by_routing_role',
    'select_agent_for_task',
]
