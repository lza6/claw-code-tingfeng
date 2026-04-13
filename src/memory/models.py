"""Memory Models - 记忆数据模型

从 claude-code-rust-master 和 goalx-main 汲取的架构优点:
- 多层记忆架构 (Semantic/Episodic/Working)
- 细粒度记忆分类 (goalx MemoryKind: fact/procedure/pitfall/secret_ref/success_prior)
- 清晰的记忆类型定义
- 支持重要性评分和标签
- 记忆选择器 (selectors) 用于精准检索
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MemoryType(str, Enum):
    """记忆类型"""
    SEMANTIC = "semantic"     # 语义记忆 - 抽象知识/模式/规则
    EPISODIC = "episodic"     # 情景记忆 - 具体经验/事件
    WORKING = "working"       # 工作记忆 - 当前会话上下文


class MemoryKind(str, Enum):
    """记忆细粒度分类 (从 goalx-main 整合)

    - FACT: 事实性知识 (如: "Python 3.11 支持异常组")
    - PROCEDURE: 程序性知识 (如: "部署步骤: 1. build 2. deploy 3. verify")
    - PITFALL: 避坑指南 (如: "Windows 下路径分隔符必须用 raw string")
    - SECRET_REF: 密钥引用 (如: "API_KEY 存储在 ~/.clawd/.env 中")
    - SUCCESS_PRIOR: 成功先验 (如: "使用 asyncio.gather 并发下载速度提升 3x")
    """
    FACT = "fact"
    PROCEDURE = "procedure"
    PITFALL = "pitfall"
    SECRET_REF = "secret_ref"
    SUCCESS_PRIOR = "success_prior"


class MemorySource(str, Enum):
    """记忆来源"""
    USER_FEEDBACK = "user_feedback"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    RETROSPECTIVE = "retrospective"
    AUTO_EXTRACT = "auto_extract"


@dataclass
class MemoryEvidence:
    """记忆证据引用 (从 goalx-main 整合)

    用于追踪记忆的证据来源，如文件路径、运行记录等。
    """
    kind: str = ""    # 证据类型 (file, run, session, etc.)
    path: str = ""    # 证据路径


@dataclass
class MemoryEntry:
    """记忆条目

    统一的记忆数据结构,支持多种记忆类型和来源。

    属性:
    - id: 唯一标识
    - memory_type: 记忆类型
    - kind: 记忆细粒度分类 (fact/procedure/pitfall/secret_ref/success_prior)
    - content: 记忆内容
    - source: 记忆来源
    - importance: 重要性评分 (0.0-1.0)
    - tags: 标签列表
    - selectors: 选择器 (用于精准检索，如 project/environment/tool)
    - evidence: 证据列表
    - metadata: 元数据
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    memory_type: MemoryType = MemoryType.WORKING
    kind: MemoryKind = MemoryKind.FACT
    content: str = ""
    source: MemorySource = MemorySource.AUTO_EXTRACT
    importance: float = 0.5
    tags: list[str] = field(default_factory=list)
    selectors: dict[str, str] = field(default_factory=dict)
    evidence: list[MemoryEvidence] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    access_count: int = 0
    last_accessed: float | None = None

    # 记忆生命周期追踪
    verification_state: str = "unverified"  # unverified, verified, contradicted
    confidence: str = "medium"              # low, medium, high
    success_association_count: int = 0      # 成功关联次数
    contradicted_count: int = 0             # 被反驳次数
    superseded_by: str = ""                 # 被哪个记忆替代

    def with_importance(self, importance: float) -> MemoryEntry:
        """设置重要性评分"""
        self.importance = max(0.0, min(1.0, importance))
        return self

    def with_tags(self, tags: list[str]) -> MemoryEntry:
        """设置标签"""
        self.tags = tags
        return self

    def add_tag(self, tag: str) -> MemoryEntry:
        """添加标签"""
        if tag not in self.tags:
            self.tags.append(tag)
        return self

    def with_selectors(self, selectors: dict[str, str]) -> MemoryEntry:
        """设置选择器 (用于精准检索)"""
        self.selectors = selectors
        return self

    def add_evidence(self, kind: str, path: str) -> MemoryEntry:
        """添加证据"""
        self.evidence.append(MemoryEvidence(kind=kind, path=path))
        return self

    def with_metadata(self, key: str, value: Any) -> MemoryEntry:
        """添加元数据"""
        self.metadata[key] = value
        return self

    def access(self) -> None:
        """记录访问"""
        self.access_count += 1
        self.last_accessed = time.time()

    def record_success(self) -> None:
        """记录成功关联"""
        self.success_association_count += 1
        self.confidence = "high" if self.success_association_count >= 3 else self.confidence

    def record_contradiction(self) -> None:
        """记录反驳"""
        self.contradicted_count += 1
        if self.contradicted_count >= 3:
            self.verification_state = "contradicted"

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "memory_type": self.memory_type.value,
            "kind": self.kind.value,
            "content": self.content,
            "source": self.source.value,
            "importance": self.importance,
            "tags": self.tags,
            "selectors": self.selectors,
            "evidence": [{"kind": e.kind, "path": e.path} for e in self.evidence],
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
            "verification_state": self.verification_state,
            "confidence": self.confidence,
            "success_association_count": self.success_association_count,
            "contradicted_count": self.contradicted_count,
            "superseded_by": self.superseded_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEntry:
        """从字典创建"""
        evidence_data = data.get("evidence", [])
        evidence = [MemoryEvidence(kind=e.get("kind", ""), path=e.get("path", "")) for e in evidence_data]

        entry = cls(
            id=data.get("id", str(uuid.uuid4())),
            memory_type=MemoryType(data.get("memory_type", "working")),
            kind=MemoryKind(data.get("kind", "fact")),
            content=data.get("content", ""),
            source=MemorySource(data.get("source", "auto_extract")),
            importance=data.get("importance", 0.5),
            tags=data.get("tags", []),
            selectors=data.get("selectors", {}),
            evidence=evidence,
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            access_count=data.get("access_count", 0),
            last_accessed=data.get("last_accessed"),
            verification_state=data.get("verification_state", "unverified"),
            confidence=data.get("confidence", "medium"),
            success_association_count=data.get("success_association_count", 0),
            contradicted_count=data.get("contradicted_count", 0),
            superseded_by=data.get("superseded_by", ""),
        )
        return entry


@dataclass
class SemanticPattern:
    """语义模式 - 可跨上下文复用的抽象模式和规则

    存储从经验中抽象出的通用模式,用于指导未来决策。
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    category: str = ""
    pattern: str = ""           # 模式描述
    problem: str = ""           # 解决的问题
    solution: str = ""          # 解决方案
    confidence: float = 0.5     # 置信度
    applications: int = 0       # 应用次数
    target_skills: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def apply(self) -> None:
        """记录应用"""
        self.applications += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "pattern": self.pattern,
            "problem": self.problem,
            "solution": self.solution,
            "confidence": self.confidence,
            "applications": self.applications,
            "target_skills": self.target_skills,
            "created_at": self.created_at,
        }


@dataclass
class EpisodicMemory:
    """情景记忆 - 具体经验和发生的事情

    记录特定时间、特定场景下的经验和教训。
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    skill_used: str = ""
    situation: str = ""          # 情况描述
    root_cause: str = ""         # 根本原因
    solution: str = ""           # 解决方案
    lesson: str = ""             # 教训
    related_pattern_id: str = "" # 关联的模式 ID
    user_rating: float | None = None  # 用户评分 (1-10)
    user_comments: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "skill_used": self.skill_used,
            "situation": self.situation,
            "root_cause": self.root_cause,
            "solution": self.solution,
            "lesson": self.lesson,
            "related_pattern_id": self.related_pattern_id,
            "user_rating": self.user_rating,
            "user_comments": self.user_comments,
        }


@dataclass
class WorkingMemory:
    """工作记忆 - 当前会话上下文

    存储当前会话的临时数据,会话结束后可能被清理或整合。
    """
    session_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None

    def set(self, key: str, value: Any) -> WorkingMemory:
        """设置数据"""
        self.data[key] = value
        return self

    def get(self, key: str, default: Any = None) -> Any:
        """获取数据"""
        return self.data.get(key, default)

    def clear(self) -> None:
        """清空数据"""
        self.data.clear()


@dataclass
class JournalEntry:
    """Agent 操作日志 (从 goalx-main 整合)

    记录 Agent 执行过程中的每一步决策、动作、置信度和结果。
    用于任务恢复、自我反思和执行链分析。
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    agent_id: str = ""           # 执行 Agent 的 ID
    intent: str = ""             # 意图 (deliver/explore/evolve/debate/implement)
    task_id: str = ""            # 关联的任务 ID
    action: str = ""             # 采取的动作 (tool_use, planning, etc.)
    thought: str = ""            # Agent 的思考过程
    confidence: float = 0.5      # 该动作的置信度 (0.0-1.0)
    evidence: list[MemoryEvidence] = field(default_factory=list) # 相关证据
    status: str = "pending"      # pending, success, failed, partially_successful
    result_summary: str = ""     # 结果简要描述
    error_code: str | None = None # 如果失败，对应的错误码

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "agent_id": self.agent_id,
            "intent": self.intent,
            "task_id": self.task_id,
            "action": self.action,
            "thought": self.thought,
            "confidence": self.confidence,
            "evidence": [{"kind": e.kind, "path": e.path} for e in self.evidence],
            "status": self.status,
            "result_summary": self.result_summary,
            "error_code": self.error_code,
        }


@dataclass
class MemoryStatus:
    """记忆状态摘要"""
    total_memories: int = 0
    semantic_count: int = 0
    episodic_count: int = 0
    working_count: int = 0
    pattern_count: int = 0
    last_consolidation: float | None = None
    storage_size_bytes: int = 0
    # 细粒度分类计数 (从 goalx-main 整合)
    fact_count: int = 0
    procedure_count: int = 0
    pitfall_count: int = 0
    secret_ref_count: int = 0
    success_prior_count: int = 0
