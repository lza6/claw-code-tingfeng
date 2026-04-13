"""
Assurance Plan - Verification strategy for the run

Defines how to verify that obligations are satisfied and the objective is achieved.
Includes test scenarios, acceptance criteria, and verification methods.

Inspired by GoalX's assurance-plan pattern.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional
from enum import Enum


class VerificationMethod(Enum):
    """How to verify an obligation."""
    UNIT_TEST = "unit_test"
    INTEGRATION_TEST = "integration_test"
    E2E_TEST = "e2e_test"
    MANUAL_CHECK = "manual_check"
    CODE_REVIEW = "code_review"
    STATIC_ANALYSIS = "static_analysis"
    RUNTIME_CHECK = "runtime_check"
    DOCUMENTATION = "documentation"


@dataclass
class AssuranceHarness:
    """Test execution harness"""
    kind: str = "cli"
    command: str = ""

@dataclass
class AssuranceOracleCheck:
    """Specific check for an oracle"""
    kind: str = "exit_code"
    equals: str = "0"

@dataclass
class AssuranceOracle:
    """Verification oracle to determine success"""
    kind: str = "exit_code"
    checks: List[AssuranceOracleCheck] = field(default_factory=lambda: [AssuranceOracleCheck()])

@dataclass
class AssuranceEvidenceRequirement:
    """Required evidence type"""
    kind: str = "stdout"

@dataclass
class AssuranceTouchpoints:
    """Affected areas to verify"""
    files: List[str] = field(default_factory=list)
    symbols: List[str] = field(default_factory=list)
    processes: List[str] = field(default_factory=list)

@dataclass
class AssuranceGatePolicy:
    """Policy for passing verification gates"""
    verify_lane: str = "required"
    required_cognition_tier: str = "repo-native"
    closeout: str = "required"
    merge: str = "required"


@dataclass
class AssuranceScenario:
    """A single verification scenario. (GoalX style)"""

    id: str
    name: str = ""
    description: str = ""
    method: VerificationMethod = VerificationMethod.UNIT_TEST

    # What to verify (GoalX CoversObligations)
    obligation_ids: List[str] = field(default_factory=list)  # Which obligations this verifies

    # GoalX advanced fields
    harness: AssuranceHarness = field(default_factory=AssuranceHarness)
    oracle: AssuranceOracle = field(default_factory=AssuranceOracle)
    evidence_reqs: List[AssuranceEvidenceRequirement] = field(default_factory=lambda: [AssuranceEvidenceRequirement()])
    touchpoints: AssuranceTouchpoints = field(default_factory=AssuranceTouchpoints)
    gate_policy: AssuranceGatePolicy = field(default_factory=AssuranceGatePolicy)

    # Legacy / How to verify
    test_command: Optional[str] = None  # Command to run (e.g., "pytest tests/test_foo.py")
    expected_outcome: str = ""  # What should happen
    acceptance_criteria: List[str] = field(default_factory=list)  # Specific criteria

    # Status
    executed: bool = False
    passed: bool = False
    execution_log: str = ""
    executed_at: Optional[str] = None

    # Metadata
    priority: int = 0
    tags: List[str] = field(default_factory=list)

    def __post_init__(self):
        # Sync legacy command to harness if harness is empty but test_command is set
        if self.test_command and not self.harness.command:
            self.harness.command = self.test_command


@dataclass
class AssurancePlan:
    """
    Plan for verifying that the objective is achieved.

    Contains scenarios that must pass before the run can be considered complete.
    """

    scenarios: Dict[str, AssuranceScenario] = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # Overall strategy
    strategy_notes: str = ""  # High-level verification approach
    required_coverage: float = 80.0  # Minimum test coverage percentage

    @classmethod
    def create_default(cls) -> "AssurancePlan":
        """Create an empty assurance plan."""
        return cls(scenarios={}, strategy_notes="")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AssurancePlan":
        """Load from dictionary."""
        scenarios = {}
        for scenario_id, scenario_data in data.get("scenarios", {}).items():
            # Parse GoalX nested structs
            harness_data = scenario_data.get("harness", {})
            harness = AssuranceHarness(
                kind=harness_data.get("kind", "cli"),
                command=harness_data.get("command", "")
            )

            oracle_data = scenario_data.get("oracle", {})
            checks = [
                AssuranceOracleCheck(kind=c.get("kind", "exit_code"), equals=c.get("equals", "0"))
                for c in oracle_data.get("checks", [])
            ]
            oracle = AssuranceOracle(
                kind=oracle_data.get("kind", "exit_code"),
                checks=checks or [AssuranceOracleCheck()]
            )

            evidence_reqs = [
                AssuranceEvidenceRequirement(kind=e.get("kind", "stdout"))
                for e in scenario_data.get("evidence_reqs", [{"kind": "stdout"}])
            ]

            touchpoints_data = scenario_data.get("touchpoints", {})
            touchpoints = AssuranceTouchpoints(
                files=touchpoints_data.get("files", []),
                symbols=touchpoints_data.get("symbols", []),
                processes=touchpoints_data.get("processes", [])
            )

            gate_data = scenario_data.get("gate_policy", {})
            gate_policy = AssuranceGatePolicy(
                verify_lane=gate_data.get("verify_lane", "required"),
                required_cognition_tier=gate_data.get("required_cognition_tier", "repo-native"),
                closeout=gate_data.get("closeout", "required"),
                merge=gate_data.get("merge", "required")
            )

            scenarios[scenario_id] = AssuranceScenario(
                id=scenario_data["id"],
                name=scenario_data.get("name", ""),
                description=scenario_data.get("description", ""),
                method=VerificationMethod(scenario_data.get("method", VerificationMethod.UNIT_TEST.value)),
                obligation_ids=scenario_data.get("obligation_ids", scenario_data.get("covers_obligations", [])),
                harness=harness,
                oracle=oracle,
                evidence_reqs=evidence_reqs,
                touchpoints=touchpoints,
                gate_policy=gate_policy,
                test_command=scenario_data.get("test_command"),
                expected_outcome=scenario_data.get("expected_outcome", ""),
                acceptance_criteria=scenario_data.get("acceptance_criteria", []),
                executed=scenario_data.get("executed", False),
                passed=scenario_data.get("passed", False),
                execution_log=scenario_data.get("execution_log", ""),
                executed_at=scenario_data.get("executed_at"),
                priority=scenario_data.get("priority", 0),
                tags=scenario_data.get("tags", [])
            )

        return cls(
            scenarios=scenarios,
            updated_at=data.get("updated_at", datetime.utcnow().isoformat()),
            strategy_notes=data.get("strategy_notes", ""),
            required_coverage=data.get("required_coverage", 80.0)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        scenarios_dict = {}
        for scenario_id, scenario in self.scenarios.items():
            scenarios_dict[scenario_id] = {
                "id": scenario.id,
                "name": scenario.name,
                "description": scenario.description,
                "method": scenario.method.value,
                "obligation_ids": scenario.obligation_ids,
                "covers_obligations": scenario.obligation_ids,  # GoalX compatibility
                "harness": {
                    "kind": scenario.harness.kind,
                    "command": scenario.harness.command
                },
                "oracle": {
                    "kind": scenario.oracle.kind,
                    "checks": [{"kind": c.kind, "equals": c.equals} for c in scenario.oracle.checks]
                },
                "evidence_reqs": [{"kind": e.kind} for e in scenario.evidence_reqs],
                "touchpoints": {
                    "files": scenario.touchpoints.files,
                    "symbols": scenario.touchpoints.symbols,
                    "processes": scenario.touchpoints.processes
                },
                "gate_policy": {
                    "verify_lane": scenario.gate_policy.verify_lane,
                    "required_cognition_tier": scenario.gate_policy.required_cognition_tier,
                    "closeout": scenario.gate_policy.closeout,
                    "merge": scenario.gate_policy.merge
                },
                "test_command": scenario.test_command,
                "expected_outcome": scenario.expected_outcome,
                "acceptance_criteria": scenario.acceptance_criteria,
                "executed": scenario.executed,
                "passed": scenario.passed,
                "execution_log": scenario.execution_log,
                "executed_at": scenario.executed_at,
                "priority": scenario.priority,
                "tags": scenario.tags
            }

        return {
            "scenarios": scenarios_dict,
            "updated_at": self.updated_at,
            "strategy_notes": self.strategy_notes,
            "required_coverage": self.required_coverage
        }

    def add_scenario(self, scenario: AssuranceScenario) -> None:
        """Add a verification scenario."""
        self.scenarios[scenario.id] = scenario
        self.updated_at = datetime.utcnow().isoformat()

    def execute_scenario(self, scenario_id: str, passed: bool, execution_log: str) -> None:
        """Record the result of executing a scenario."""
        if scenario_id not in self.scenarios:
            raise ValueError(f"Scenario not found: {scenario_id}")

        scenario = self.scenarios[scenario_id]
        scenario.executed = True
        scenario.passed = passed
        scenario.execution_log = execution_log
        scenario.executed_at = datetime.utcnow().isoformat()
        self.updated_at = datetime.utcnow().isoformat()

    def get_pending_scenarios(self) -> List[AssuranceScenario]:
        """Get scenarios that haven't been executed yet."""
        pending = [s for s in self.scenarios.values() if not s.executed]
        pending.sort(key=lambda s: s.priority, reverse=True)
        return pending

    def get_failed_scenarios(self) -> List[AssuranceScenario]:
        """Get scenarios that were executed but failed."""
        return [s for s in self.scenarios.values() if s.executed and not s.passed]

    def get_pass_rate(self) -> float:
        """Calculate percentage of scenarios that passed."""
        if not self.scenarios:
            return 0.0

        executed = [s for s in self.scenarios.values() if s.executed]
        if not executed:
            return 0.0

        passed = sum(1 for s in executed if s.passed)
        return (passed / len(executed)) * 100

    def is_complete(self) -> bool:
        """Check if all scenarios have been executed and passed."""
        if not self.scenarios:
            return False

        return all(s.executed and s.passed for s in self.scenarios.values())

    def __str__(self) -> str:
        """Human-readable representation."""
        total = len(self.scenarios)
        executed = sum(1 for s in self.scenarios.values() if s.executed)
        passed = sum(1 for s in self.scenarios.values() if s.executed and s.passed)
        failed = sum(1 for s in self.scenarios.values() if s.executed and not s.passed)

        lines = [
            f"Assurance Plan: {executed}/{total} scenarios executed",
            f"  Passed: {passed}",
            f"  Failed: {failed}",
            f"  Pending: {total - executed}",
            f"  Pass Rate: {self.get_pass_rate():.1f}%",
        ]

        if self.strategy_notes:
            lines.append(f"\nStrategy: {self.strategy_notes}")

        return "\n".join(lines)
