"""
Success Model - Success dimensions and anti-goals (Inspired by GoalX)

Defines the criteria by which a session's outcomes are judged:
- Success dimensions: measurable quality/performance/correctness/usability targets
- Anti-goals: conditions that must NOT occur
- Proof requirements: evidence needed to demonstrate dimension coverage
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional
import uuid


class DimensionKind(str, Enum):
    """Kinds of success dimensions."""
    QUALITY = "quality"
    PERFORMANCE = "performance"
    CORRECTNESS = "correctness"
    USABILITY = "usability"


class ProofKind(str, Enum):
    """Kinds of proof required to cover a dimension."""
    TEST = "test"
    REVIEW = "review"
    METRIC = "metric"
    MANUAL = "manual"


@dataclass
class SuccessDimension:
    """A measurable criterion that defines what success looks like."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    kind: DimensionKind = DimensionKind.QUALITY
    text: str = ""
    required: bool = True
    failure_modes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value if isinstance(self.kind, DimensionKind) else self.kind,
            "text": self.text,
            "required": self.required,
            "failure_modes": self.failure_modes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SuccessDimension":
        kind = data.get("kind", DimensionKind.QUALITY)
        if isinstance(kind, str):
            kind = DimensionKind(kind)
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            kind=kind,
            text=data.get("text", ""),
            required=data.get("required", True),
            failure_modes=data.get("failure_modes", []),
        )


@dataclass
class AntiGoal:
    """A condition that must NOT occur during the session."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AntiGoal":
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            text=data.get("text", ""),
        )


@dataclass
class ProofRequirement:
    """Evidence needed to demonstrate that a success dimension has been covered."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    covers_dimensions: List[str] = field(default_factory=list)
    kind: ProofKind = ProofKind.TEST
    required: bool = True
    source_surface: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "covers_dimensions": self.covers_dimensions,
            "kind": self.kind.value if isinstance(self.kind, ProofKind) else self.kind,
            "required": self.required,
            "source_surface": self.source_surface,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProofRequirement":
        kind = data.get("kind", ProofKind.TEST)
        if isinstance(kind, str):
            kind = ProofKind(kind)
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            covers_dimensions=data.get("covers_dimensions", []),
            kind=kind,
            required=data.get("required", True),
            source_surface=data.get("source_surface", ""),
        )


@dataclass
class SuccessModel:
    """
    Success Model defines the dimensions of success, anti-goals to avoid,
    and proof requirements needed to demonstrate coverage.

    Produced by the assurance_plan surface to guide the session toward
    verifiable outcomes.
    """
    objective_contract_hash: str = ""
    obligation_model_hash: str = ""
    dimensions: List[SuccessDimension] = field(default_factory=list)
    anti_goals: List[AntiGoal] = field(default_factory=list)
    proof_requirements: List[ProofRequirement] = field(default_factory=list)
    version: str = "1"
    compiled_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @classmethod
    def create_default(cls, objective_contract_hash: str = "", obligation_model_hash: str = "") -> "SuccessModel":
        """Create a success model with default dimensions."""
        now = datetime.utcnow().isoformat()
        dimensions = [
            SuccessDimension(
                id="dim-quality",
                kind=DimensionKind.QUALITY,
                text="Code follows project style and conventions",
                required=True,
                failure_modes=["style violations in lint", "inconsistent naming"],
            ),
            SuccessDimension(
                id="dim-correctness",
                kind=DimensionKind.CORRECTNESS,
                text="All tests pass with no regressions",
                required=True,
                failure_modes=["test failures", "regression bugs"],
            ),
            SuccessDimension(
                id="dim-performance",
                kind=DimensionKind.PERFORMANCE,
                text="No significant performance degradation",
                required=False,
                failure_modes=["N+1 queries", "unbounded loops"],
            ),
        ]
        anti_goals = [
            AntiGoal(id="anti-secrets", text="No hardcoded secrets or credentials"),
            AntiGoal(id="anti-breaking", text="No breaking API changes without migration"),
        ]
        proof_requirements = [
            ProofRequirement(
                id="proof-lint",
                covers_dimensions=["dim-quality"],
                kind=ProofKind.TEST,
                required=True,
                source_surface="assurance_plan",
            ),
            ProofRequirement(
                id="proof-tests",
                covers_dimensions=["dim-correctness"],
                kind=ProofKind.TEST,
                required=True,
                source_surface="assurance_plan",
            ),
        ]
        return cls(
            objective_contract_hash=objective_contract_hash,
            obligation_model_hash=obligation_model_hash,
            dimensions=dimensions,
            anti_goals=anti_goals,
            proof_requirements=proof_requirements,
            version="1",
            compiled_at=now,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SuccessModel":
        """Load from dictionary."""
        return cls(
            objective_contract_hash=data.get("objective_contract_hash", ""),
            obligation_model_hash=data.get("obligation_model_hash", ""),
            dimensions=[
                SuccessDimension.from_dict(d)
                for d in data.get("dimensions", [])
            ],
            anti_goals=[
                AntiGoal.from_dict(a)
                for a in data.get("anti_goals", [])
            ],
            proof_requirements=[
                ProofRequirement.from_dict(p)
                for p in data.get("proof_requirements", [])
            ],
            version=data.get("version", "1"),
            compiled_at=data.get("compiled_at", datetime.utcnow().isoformat()),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "objective_contract_hash": self.objective_contract_hash,
            "obligation_model_hash": self.obligation_model_hash,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "anti_goals": [a.to_dict() for a in self.anti_goals],
            "proof_requirements": [p.to_dict() for p in self.proof_requirements],
            "version": self.version,
            "compiled_at": self.compiled_at,
        }

    def add_dimension(self, kind: DimensionKind, text: str, required: bool = True, failure_modes: Optional[List[str]] = None) -> SuccessDimension:
        """Add a new success dimension."""
        dim = SuccessDimension(
            kind=kind,
            text=text,
            required=required,
            failure_modes=failure_modes or [],
        )
        self.dimensions.append(dim)
        return dim

    def mark_dimension_covered(self, dimension_id: str, proof_kind: ProofKind = ProofKind.TEST, source_surface: str = "assurance_plan") -> ProofRequirement:
        """
        Mark a dimension as covered by adding a proof requirement.
        Returns the created proof requirement.
        Raises ValueError if dimension not found.
        """
        found = any(d.id == dimension_id for d in self.dimensions)
        if not found:
            raise ValueError(f"Dimension '{dimension_id}' not found in success model")
        proof = ProofRequirement(
            covers_dimensions=[dimension_id],
            kind=proof_kind,
            required=True,
            source_surface=source_surface,
        )
        self.proof_requirements.append(proof)
        return proof
