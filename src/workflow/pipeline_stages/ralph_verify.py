"""
Ralph verification stage for pipeline orchestrator.

Wraps the ralph persistence loop into a PipelineStage for the
verification phase. Uses configurable iteration count.
"""

from dataclasses import dataclass
from typing import Any

from .types import StageContext, StageResult


@dataclass
class RalphVerifyStageOptions:
    """Options for Ralph verification stage."""
    max_iterations: int = 10


@dataclass
class RalphVerifyDescriptor:
    """Descriptor for a Ralph verification run."""
    task: str
    max_iterations: int
    cwd: str
    session_id: str | None = None
    available_agent_types: list[str] = None
    staffing_plan: dict[str, Any] | None = None
    execution_artifacts: dict[str, Any] | None = None

    def __post_init__(self):
        if self.available_agent_types is None:
            self.available_agent_types = []
        if self.staffing_plan is None:
            self.staffing_plan = {}
        if self.execution_artifacts is None:
            self.execution_artifacts = {}


def create_ralph_verify_stage(options: RalphVerifyStageOptions = None) -> dict[str, Any]:
    """
    Create a ralph-verify pipeline stage.

    This stage wraps the ralph persistence loop for the verification phase
    of the pipeline. It takes the execution results from team-exec and
    orchestrates architect-verified completion.

    Args:
        options: Configuration options for the stage

    Returns:
        PipelineStage dictionary with run method
    """
    if options is None:
        options = RalphVerifyStageOptions()

    max_iterations = options.max_iterations

    stage = {
        "name": "ralph-verify",
        "run": None,  # Will be set below
    }

    async def run(ctx: StageContext) -> StageResult:
        """Execute the ralph verification stage."""
        import time
        start_time = int(time.time() * 1000)

        try:
            # Extract execution context from previous stage
            team_artifacts = ctx.artifacts.get("team-exec", {})

            # Build ralph verification descriptor
            verify_descriptor = RalphVerifyDescriptor(
                task=ctx.task,
                max_iterations=max_iterations,
                cwd=ctx.cwd,
                session_id=ctx.session_id,
                available_agent_types=[],  # Would be populated from resolveAvailableAgentTypes
                staffing_plan={},  # Would be populated from buildFollowupStaffingPlan
                execution_artifacts=team_artifacts,
            )

            return StageResult(
                status="completed",
                artifacts={
                    "verify_descriptor": verify_descriptor.__dict__,
                    "max_iterations": max_iterations,
                    "stage": "ralph-verify",
                    "instruction": build_ralph_instruction(verify_descriptor),
                },
                duration_ms=int(time.time() * 1000) - start_time,
            )
        except Exception as err:
            return StageResult(
                status="failed",
                artifacts={},
                duration_ms=int(time.time() * 1000) - start_time,
                error=f"Ralph verification stage failed: {err!s}",
            )

    stage["run"] = run
    return stage


def build_ralph_instruction(descriptor: RalphVerifyDescriptor) -> str:
    """
    Build the ralph CLI instruction from a descriptor.

    Args:
        descriptor: Ralph verification descriptor

    Returns:
        CLI instruction string
    """
    staffing_summary = ""
    if descriptor.staffing_plan:
        staffing_summary = descriptor.staffing_plan.get("staffing_summary", "")

    verification_summary = ""
    if descriptor.staffing_plan:
        verification_summary = descriptor.staffing_plan.get("verification_plan", {}).get("summary", "")

    return f"ralph {descriptor.task} # max_iterations={descriptor.max_iterations} # staffing={staffing_summary} # verify={verification_summary}"
