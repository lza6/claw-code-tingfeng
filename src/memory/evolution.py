from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any
import hashlib
import json

class MemoryKind:
    FACT = "fact"
    PROCEDURE = "procedure"
    PITFALL = "pitfall"
    SECRET_REF = "secret_ref"
    SUCCESS_PRIOR = "success_prior"

class VerificationLevel:
    PROPOSED = "proposed"
    REPEATED = "repeated"
    VALIDATED = "validated"

@dataclass
class MemoryEvidence:
    run_id: str
    content: str
    kind: str = "observation"  # observation, test_result, review_comment
    status: str = "unverified" # unverified, verified, disputed
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

@dataclass
class MemoryProposal:
    kind: str
    statement: str
    selectors: Dict[str, str]
    evidence: List[MemoryEvidence] = field(default_factory=list)
    source_runs: List[str] = field(default_factory=list)
    state: str = "open" # open, rejected, expired, promoted
    rejection_reason: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def add_evidence(self, run_id: str, content: str, kind: str = "observation") -> None:
        """添加证据并自动更新源运行列表"""
        self.evidence.append(MemoryEvidence(run_id=run_id, content=content, kind=kind))
        if run_id not in self.source_runs:
            self.source_runs.append(run_id)

@dataclass
class MemoryEntry:
    id: str
    kind: str
    statement: str
    selectors: Dict[str, str]
    verification: str = VerificationLevel.PROPOSED
    evidence_count: int = 0
    source_runs: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

class MemoryEvolver:
    def __init__(self, store):
        self.store = store

    def generate_id(self, kind: str, selectors: Dict[str, str], statement: str) -> str:
        sel_str = json.dumps(selectors, sort_keys=True)
        raw = f"{kind}:{sel_str}:{statement.strip()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def aggregate_proposals(self, proposals: List[MemoryProposal]) -> List[MemoryEntry]:
        aggregates: Dict[str, MemoryEntry] = {}

        for p in proposals:
            if p.state in ["rejected", "expired"]:
                continue

            entry_id = self.generate_id(p.kind, p.selectors, p.statement)
            if entry_id not in aggregates:
                aggregates[entry_id] = MemoryEntry(
                    id=entry_id,
                    kind=p.kind,
                    statement=p.statement,
                    selectors=p.selectors,
                    source_runs=list(set(p.source_runs)),
                    evidence_count=len(p.evidence),
                    created_at=p.created_at
                )
            else:
                entry = aggregates[entry_id]
                entry.source_runs = list(set(entry.source_runs + p.source_runs))
                entry.evidence_count += len(p.evidence)
                entry.updated_at = datetime.utcnow().isoformat()

        # Apply promotion logic
        promoted = []
        for entry in aggregates.values():
            if self._is_promotable(entry):
                entry.verification = self._determine_verification(entry)
                promoted.append(entry)

        return promoted

    def _is_promotable(self, entry: MemoryEntry) -> bool:
        if entry.kind in [MemoryKind.FACT, MemoryKind.SECRET_REF]:
            return True

        # Procedure/Pitfall/SuccessPrior need at least 2 runs or strong evidence
        return len(entry.source_runs) >= 2 or entry.evidence_count >= 3

    def _determine_verification(self, entry: MemoryEntry) -> str:
        if entry.kind in [MemoryKind.FACT, MemoryKind.SECRET_REF]:
            return VerificationLevel.VALIDATED
            
        if len(entry.source_runs) >= 3:
            return VerificationLevel.VALIDATED
        if len(entry.source_runs) >= 2:
            return VerificationLevel.REPEATED
            
        return VerificationLevel.PROPOSED
