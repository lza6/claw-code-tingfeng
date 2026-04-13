"""Workflow Engine - 数据模型（枚举 + 冻结 dataclass）"""

from dataclasses import dataclass, field
from enum import Enum


class WorkflowPhase(str, Enum):
    """五阶段执行生命周期"""
    IDENTIFY = "identify"
    PLAN = "plan"
    EXECUTE = "execute"
    REVIEW = "review"
    DISCOVER = "discover"


class WorkflowPhaseCategory(str, Enum):
    """阶段内的子步骤，用于细粒度事件发布"""
    IDENTIFY_ANALYZE = "identify.analyze"
    IDENTIFY_PROFILE = "identify.profile"
    IDENTIFY_DISCOVER = "identify.discover"
    PLAN_TODO = "plan.todo"
    PLAN_SPLIT = "plan.split"
    EXECUTE_STEP = "execute.step"
    EXECUTE_VERIFY = "execute.verify"
    EXECUTE_VALIDATE = "execute.validate"
    REVIEW_GLOBAL = "review.global"
    REVIEW_CLEANUP = "review.cleanup"
    REVIEW_DOCUMENT = "review.document"
    REVIEW_REPORT = "review.report"
    DISCOVER_OPTIMIZE = "discover.optimize"


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowIntent(str, Enum):
    """工作流意图 (借鉴 GoalX)"""
    DELIVER = "deliver"     # 默认结果交付路径
    EXPLORE = "explore"     # 证据优先的调查
    EVOLVE = "evolve"       # 开放式的持续优化
    DEBATE = "debate"       # 挑战和细化先前的发现
    IMPLEMENT = "implement" # 基于先前证据的构建


class ObjectiveClauseKind(str, Enum):
    """目标合同条款类型 (借鉴 GoalX)"""
    DELIVERY = "delivery"
    QUALITY_BAR = "quality_bar"
    VERIFICATION = "verification"
    GUARDRAIL = "guardrail"
    OPERATING_RULE = "operating_rule"


class ObjectiveRequiredSurface(str, Enum):
    """条款要求的持久化表面"""
    OBLIGATION = "obligation"
    ASSURANCE = "assurance"


@dataclass(frozen=True)
class ObjectiveClause:
    """目标合同条款 (借鉴 GoalX)"""
    id: str
    text: str
    kind: ObjectiveClauseKind
    source_excerpt: str
    required_surfaces: list[ObjectiveRequiredSurface] = field(default_factory=list)


@dataclass(frozen=True)
class ObjectiveContract:
    """目标合同 (借鉴 GoalX)"""
    version: int
    objective_hash: str
    state: str  # "draft" | "locked"
    clauses: list[ObjectiveClause] = field(default_factory=list)
    created_at: str = ""
    locked_at: str = ""


class AssuranceVerificationMode(str, Enum):
    """保证验证模式"""
    UNIT_TEST = "unit_test"
    INTEGRATION_TEST = "integration_test"
    E2E_TEST = "e2e_test"
    MANUAL_REVIEW = "manual_review"
    STATIC_ANALYSIS = "static_analysis"


@dataclass(frozen=True)
class AssuranceProcedure:
    """保证程序 (借鉴 GoalX)"""
    id: str
    title: str
    strategy: str
    verification_mode: AssuranceVerificationMode
    target_surface: str  # e.g., "src/core/auth.py"
    covers_clauses: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AssurancePlan:
    """保证计划 (借鉴 GoalX)"""
    version: int
    objective_contract_hash: str
    procedures: list[AssuranceProcedure] = field(default_factory=list)
    created_at: str = ""


class ObligationItemState(str, Enum):
    """义务项状态"""
    OPEN = "open"
    CLAIMED = "claimed"
    WAIVED = "waived"


@dataclass(frozen=True)
class ObligationItem:
    """义务项 (借鉴 GoalX)"""
    id: str
    text: str
    kind: str  # "outcome" | "proof" | "guardrail"
    source: str = "master"
    state: ObligationItemState = ObligationItemState.OPEN
    covers_clauses: list[str] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)
    note: str = ""
    approval_ref: str = ""
    assurance_required: bool = False


@dataclass(frozen=True)
class ObligationModel:
    """义务模型 (借鉴 GoalX)"""
    version: int
    objective_contract_hash: str
    required: list[ObligationItem] = field(default_factory=list)
    optional: list[ObligationItem] = field(default_factory=list)
    guardrails: list[ObligationItem] = field(default_factory=list)
    updated_at: str = ""


class VersionBumpType(str, Enum):
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"
    PRERELEASE = "prerelease"


class TechDebtPriority(str, Enum):
    """技术债务优先级，按严重性降序"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EffortLevel(str, Enum):
    """执行力度级别 (借鉴 GoalX)"""
    AUTO = "auto"
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAX = "max"


class DimensionSource(str, Enum):
    BUILTIN = "builtin"
    CONFIG = "config"
    INLINE = "inline"


@dataclass(frozen=True)
class Dimension:
    """引导维度 (借鉴 GoalX)"""
    name: str
    guidance: str
    source: DimensionSource = DimensionSource.BUILTIN


@dataclass(frozen=True)
class DispatchableSlice:
    """可调度的任务切片 (借鉴 GoalX)"""
    title: str
    why: str = ""
    mode: str = "worker"
    suggested_owner: str = ""
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WorkflowTask:
    """工作流任务"""
    task_id: str                          # e.g. "plan-001", "exec-003"
    phase: WorkflowPhase
    title: str
    description: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    result: str | None = None
    depends_on: list[str] = field(default_factory=list)  # 依赖的其他任务 ID
    dimensions: list[Dimension] = field(default_factory=list) # 关联的维度
    slices: list[DispatchableSlice] = field(default_factory=list) # 任务拆解出的切片
    evidence_paths: list[str] = field(default_factory=list) # [v0.51.0] 任务执行证据
    worktree_id: str | None = None # [v0.51.0] 关联的隔离工作树 ID
    verification_criteria: str = "" # [v0.51.0] 任务完成的验证标准 (借鉴 GoalX)
    retry_count: int = 0  # 新增：重试计数

    def to_dict(self) -> dict:
        """转换为可序列化的字典"""
        return {
            "task_id": self.task_id,
            "phase": self.phase.value if hasattr(self.phase, 'value') else self.phase,
            "title": self.title,
            "description": self.description,
            "status": self.status.value if hasattr(self.status, 'value') else self.status,
            "result": self.result,
            "depends_on": self.depends_on,
            "dimensions": [
                {
                    "name": d.name,
                    "guidance": d.guidance,
                    "source": d.source.value if hasattr(d.source, 'value') else d.source
                } for d in self.dimensions
            ],
            "slices": [
                {
                    "title": s.title,
                    "why": s.why,
                    "mode": s.mode,
                    "suggested_owner": s.suggested_owner,
                    "evidence": s.evidence
                } for s in self.slices
            ],
            "evidence_paths": self.evidence_paths,
            "worktree_id": self.worktree_id,
            "verification_criteria": self.verification_criteria,
            "retry_count": self.retry_count
        }


@dataclass(frozen=True)
class WorkflowResult:
    """工作流执行结果"""
    status: WorkflowStatus
    phase_summary: dict[WorkflowPhase, str] = field(default_factory=dict)
    total_tasks: int = 0
    completed_tasks: int = 0
    optimization_points: list[str] = field(default_factory=list)
    report: str = ""


@dataclass(frozen=True)
class TechDebtRecord:
    """技术债务记录"""
    record_id: str                         # TD-0001
    issue_id: str                          # 外部问题引用
    priority: TechDebtPriority
    description: str
    affected_files: list[str] = field(default_factory=list)
    created_at: str = ""                   # ISO 日期
    resolved: bool = False
    resolved_at: str | None = None


@dataclass(frozen=True)
class VersionInfo:
    """版本信息"""
    current_version: str                   # "0.23.1"
    bump_type: VersionBumpType
    new_version: str
    changelog_entries: list[str] = field(default_factory=list)
