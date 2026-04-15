"""Journal Entry - 结构化日志条目 (从 GoalX journal.go 汲取)

每条日志记录 Agent 执行过程中的关键决策点:
- Round: 当前迭代轮次
- Commit: 关联的 git commit
- Status: 执行状态
- Confidence: 置信度评估
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DispatchableSlice:
    """可执行的下一步 (从 GoalX DispatchableSlice 汲取)

    由研究阶段发现的小型可执行步骤。
    """
    title: str
    why: str = ""
    mode: str = ""
    suggested_owner: str = ""
    suggested_action: str = ""
    covers_required: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


@dataclass
class JournalEntry:
    """结构化日志条目 (从 GoalX JournalEntry 汲取)

    支持两种模式:
    - Subagent: round-based 执行，包含 commit、desc、confidence 等
    - Master: ts-based 动作记录，包含 action、session、finding 等
    """
    # Subagent 字段
    round: int = 0
    commit: str = ""
    desc: str = ""
    confidence: str = ""
    status: str = ""
    quality: str = ""
    owner_scope: str = ""
    blocked_by: str = ""
    depends_on: list[str] = field(default_factory=list)
    can_split: bool = False
    suggested_next: str = ""
    dispatchable_slices: list[DispatchableSlice] = field(default_factory=list)

    # Master 字段
    ts: str = ""
    action: str = ""
    session: str = ""
    finding: str = ""
    reason: str = ""
    guidance: str = ""

    # 通用元数据
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典 (用于 JSON 序列化)"""
        return {
            # Subagent 字段
            "round": self.round or None,
            "commit": self.commit or None,
            "desc": self.desc or None,
            "confidence": self.confidence or None,
            "status": self.status or None,
            "quality": self.quality or None,
            "owner_scope": self.owner_scope or None,
            "blocked_by": self.blocked_by or None,
            "depends_on": self.depends_on or None,
            "can_split": self.can_split or None,
            "suggested_next": self.suggested_next or None,
            "dispatchable_slices": [
                {
                    "title": s.title,
                    "why": s.why,
                    "mode": s.mode,
                    "suggested_owner": s.suggested_owner,
                    "suggested_action": s.suggested_action,
                    "covers_required": s.covers_required,
                    "evidence": s.evidence,
                }
                for s in self.dispatchable_slices
            ] or None,
            # Master 字段
            "ts": self.ts or None,
            "action": self.action or None,
            "session": self.session or None,
            "finding": self.finding or None,
            "reason": self.reason or None,
            "guidance": self.guidance or None,
            # 元数据
            "metadata": self.metadata or None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JournalEntry:
        """从字典创建 JournalEntry"""
        slices_data = data.get("dispatchable_slices") or []
        slices = [
            DispatchableSlice(
                title=s.get("title", ""),
                why=s.get("why", ""),
                mode=s.get("mode", ""),
                suggested_owner=s.get("suggested_owner", ""),
                suggested_action=s.get("suggested_action", ""),
                covers_required=s.get("covers_required", []),
                evidence=s.get("evidence", []),
            )
            for s in slices_data
        ]

        return cls(
            round=data.get("round") or 0,
            commit=data.get("commit") or "",
            desc=data.get("desc") or "",
            confidence=data.get("confidence") or "",
            status=data.get("status") or "",
            quality=data.get("quality") or "",
            owner_scope=data.get("owner_scope") or "",
            blocked_by=data.get("blocked_by") or "",
            depends_on=data.get("depends_on") or [],
            can_split=data.get("can_split") or False,
            suggested_next=data.get("suggested_next") or "",
            dispatchable_slices=slices,
            ts=data.get("ts") or "",
            action=data.get("action") or "",
            session=data.get("session") or "",
            finding=data.get("finding") or "",
            reason=data.get("reason") or "",
            guidance=data.get("guidance") or "",
            metadata=data.get("metadata") or {},
        )

    def summary(self) -> str:
        """返回一行摘要"""
        if self.round > 0:
            if self.status == "stuck" and self.blocked_by:
                return f"round {self.round}: {self.desc} (stuck: {self.blocked_by})"
            return f"round {self.round}: {self.desc} ({self.status})"
        if self.action:
            return f"[{self.action}] {self.session}: {self.finding}"
        return self.desc or "empty entry"
