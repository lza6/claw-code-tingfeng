"""
Quality Debt - Automated tracking of technical and verification debt.

Inspired by GoalX's quality-debt pattern.
Scans durable surfaces to identify gaps in verification, coordination, and evidence.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import os
import json
from datetime import datetime

@dataclass
class QualityDebt:
    """Represents the technical and verification debt of the current run."""

    # Gaps in success dimensions (unowned dimensions)
    success_dimension_unowned: List[str] = field(default_factory=list)

    # Gaps in proof plan (missing evidence for required items)
    proof_plan_gap: List[str] = field(default_factory=list)

    # Missing critical review or finishing gates
    critic_gate_missing: bool = False
    finisher_gate_missing: bool = False

    # Only correctness evidence present (missing variety like perf, security, etc.)
    only_correctness_evidence: bool = False

    # Missing domain context for non-trivial runs
    domain_pack_missing: bool = False

    # Evidence that is no longer fresh (stale)
    required_evidence_stale: List[str] = field(default_factory=list)

    # Cognition requirements not satisfied for scenarios
    required_cognition_unsatisfied: List[str] = field(default_factory=list)

    # Impact of changes is unknown or unresolved
    impact_resolution_unknown: bool = False

    def is_zero(self) -> bool:
        """Check if there is no quality debt."""
        return not any([
            self.success_dimension_unowned,
            self.proof_plan_gap,
            self.critic_gate_missing,
            self.finisher_gate_missing,
            self.only_correctness_evidence,
            self.domain_pack_missing,
            self.required_evidence_stale,
            self.required_cognition_unsatisfied,
            self.impact_resolution_unknown
        ])

    def to_report(self) -> str:
        """Generate a human-readable report of the quality debt."""
        if self.is_zero():
            return "✅ No quality debt detected. All verification gates are satisfied."

        lines = ["⚠️ Quality Debt Detected:"]

        if self.success_dimension_unowned:
            lines.append(f"  - Unowned success dimensions: {', '.join(self.success_dimension_unowned)}")

        if self.proof_plan_gap:
            lines.append(f"  - Proof plan gaps: {', '.join(self.proof_plan_gap)}")

        if self.critic_gate_missing:
            lines.append("  - CRITICAL: Critic gate is missing for this workflow.")

        if self.finisher_gate_missing:
            lines.append("  - CRITICAL: Finisher gate is missing.")

        if self.only_correctness_evidence:
            lines.append("  - Warning: Only correctness evidence present. Consider adding performance or security evidence.")

        if self.domain_pack_missing:
            lines.append("  - Warning: Domain pack missing for a non-trivial run.")

        if self.required_evidence_stale:
            lines.append(f"  - Stale evidence for scenarios: {', '.join(self.required_evidence_stale)}")

        if self.required_cognition_unsatisfied:
            lines.append(f"  - Cognition tier not satisfied for: {', '.join(self.required_cognition_unsatisfied)}")

        if self.impact_resolution_unknown:
            lines.append("  - Impact of changes is unknown. Run impact analysis.")

        return "\n".join(lines)


class QualityDebtManager:
    """Calculates and manages quality debt based on durable surfaces."""

    def __init__(self, surface_manager_dir: str):
        self.run_dir = surface_manager_dir

    def calculate_debt(self) -> QualityDebt:
        """
        Calculates the quality debt by reading various durable surfaces.
        Ported from GoalX cli/quality_debt.go.
        """
        debt = QualityDebt()

        # 1. Load available surfaces
        assurance_plan = self._load_surface("assurance_plan")
        coordination = self._load_surface("coordination_state")
        # objective_contract = self._load_surface("objective_contract") # Equivalent to SuccessModel
        status = self._load_surface("status_summary")
        control = self._load_surface("control_state")

        # 2. Check Success Dimensions (Objective Ownership)
        # Note: In our current implementation, we'll look at coordination vs status
        if coordination and status:
            # Check if all required dimensions in coordination have active lanes or status entries
            for dim_id, required in coordination.get("required", {}).items():
                if not required: continue

                owned = False
                # If it's the objective itself
                if dim_id == "dim-objective":
                    if status.get("global_tracking_states") or coordination.get("required"):
                        owned = True

                # Check lanes
                lanes = coordination.get("lanes", [])
                if any(lane.get("dimension_id") == dim_id for lane in lanes):
                    owned = True

                if not owned:
                    debt.success_dimension_unowned.append(dim_id)

        # 3. Check Assurance Gaps
        if assurance_plan:
            scenarios = assurance_plan.get("scenarios", {})
            for sid, scenario in scenarios.items():
                gate_policy = scenario.get("gate_policy", {})

                # Check for stale evidence (placeholder logic - would need a FreshnessState surface)
                # For now, we check if executed but older than a certain threshold or if not executed
                if gate_policy.get("closeout") == "required":
                    if not scenario.get("executed") or not scenario.get("passed"):
                        debt.proof_plan_gap.append(sid)

                # Cognition check
                # Placeholder: Assume repo-native is always satisfied, but 'graph' needs gitnexus (cognition provider)
                req_cognition = gate_policy.get("required_cognition_tier")
                if req_cognition == "graph":
                    # Logic to check if cognition provider is active
                    # For now, just mark it as unsatisfied if we don't have a record of it
                    debt.required_cognition_unsatisfied.append(sid)

        # 4. Check Roles/Gates (Workflow discipline)
        # If we have a CoordinationState, we check if roles like 'critic' or 'finisher' are assigned/active
        if coordination:
            # This logic assumes we have a list of required roles for the project
            # Placeholder: Assume non-trivial runs should have a critic if they change code
            has_changes = True # Should be determined by checking EvidenceLog or git diff

            # Simple heuristic: if we have more than 3 scenarios, we should have a critic
            if len(assurance_plan.get("scenarios", {})) > 3:
                roles = coordination.get("roles", {})
                if "critic" not in roles:
                    debt.critic_gate_missing = True
                if "finisher" not in roles:
                    debt.finisher_gate_missing = True

        # 5. Impact Analysis
        # Check if ControlState has lease or impact record
        if control:
            impact = control.get("workflow_control", {}).get("impact_level", "unknown")
            if impact == "unknown" and assurance_plan and assurance_plan.get("scenarios"):
                debt.impact_resolution_unknown = True

        return debt

    def _load_surface(self, name: str) -> Optional[Dict[str, Any]]:
        """Helper to load a surface from JSON."""
        path = os.path.join(self.run_dir, f"{name}.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None
