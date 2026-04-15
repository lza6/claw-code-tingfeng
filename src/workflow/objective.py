import json
from dataclasses import dataclass, field
from datetime import datetime


class GoalItemState:
    OPEN = "open"
    CLAIMED = "claimed"
    WAIVED = "waived"

class GoalItemRole:
    OUTCOME = "outcome"
    ENABLER = "enabler"
    PROOF = "proof"
    GUARDRAIL = "guardrail"

class GoalItemSource:
    USER = "user"
    MASTER = "master"

@dataclass
class GoalItem:
    id: str
    text: str
    source: str = GoalItemSource.USER
    role: str = GoalItemRole.OUTCOME
    covers: list[str] = field(default_factory=list)
    state: str = GoalItemState.OPEN
    evidence_paths: list[str] = field(default_factory=list)
    note: str = ""
    approval_ref: str = ""

    def to_dict(self):
        return {
            "id": self.id,
            "text": self.text,
            "source": self.source,
            "role": self.role,
            "covers": self.covers,
            "state": self.state,
            "evidence_paths": self.evidence_paths,
            "note": self.note,
            "approval_ref": self.approval_ref
        }

@dataclass
class GoalState:
    version: int = 1
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    required: list[GoalItem] = field(default_factory=list)
    optional: list[GoalItem] = field(default_factory=list)

    def summarize(self) -> dict:
        summary = {
            "version": self.version,
            "required_total": len(self.required),
            "required_satisfied": 0,
            "required_remaining": 0,
            "optional_open": 0
        }

        for item in self.required:
            if item.state == GoalItemState.CLAIMED or (item.state == GoalItemState.WAIVED and item.approval_ref):
                summary["required_satisfied"] += 1
            else:
                summary["required_remaining"] += 1

        for item in self.optional:
            if item.state == GoalItemState.OPEN:
                summary["optional_open"] += 1

        return summary

    def validate_for_verification(self):
        if not self.required:
            raise ValueError("Goal state has no required outcomes")

        for item in self.required:
            if not item.id:
                raise ValueError("Goal state has required item with empty id")
            if not item.text:
                raise ValueError(f"Goal item {item.id} is missing text")

            if item.state == GoalItemState.CLAIMED:
                if not item.evidence_paths:
                    raise ValueError(f"Goal item {item.id} is claimed but has no evidence_paths")
            elif item.state == GoalItemState.WAIVED:
                if not item.approval_ref:
                    raise ValueError(f"Goal item {item.id} is waived without explicit approval_ref")
            else:
                raise ValueError(f"Goal item {item.id} remains open")

        return self.summarize()

    def to_json(self):
        return json.dumps({
            "version": self.version,
            "updated_at": self.updated_at,
            "required": [i.to_dict() for i in self.required],
            "optional": [i.to_dict() for i in self.optional]
        }, indent=2)

def parse_goal_state(data: str) -> GoalState:
    raw = json.loads(data)
    state = GoalState(
        version=raw.get("version", 1),
        updated_at=raw.get("updated_at", datetime.utcnow().isoformat()),
        required=[GoalItem(**i) for i in raw.get("required", [])],
        optional=[GoalItem(**i) for i in raw.get("optional", [])]
    )
    return state
