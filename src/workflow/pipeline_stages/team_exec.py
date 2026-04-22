"""
Team execution stage for pipeline orchestrator.

Wraps the existing team mode (tmux-based Codex CLI workers) into a
PipelineStage. The execution backend is always teams.
"""

from dataclasses import dataclass
from typing import Any

from .types import StageContext, StageResult


@dataclass
class TeamExecStageOptions:
    """Options for team execution stage."""
    worker_count: int = 2
    agent_type: str = "executor"
    use_worktrees: bool = False
    extra_env: dict[str, str] | None = None


@dataclass
class TeamExecDescriptor:
    """Descriptor for a team execution run."""
    task: str
    worker_count: int
    agent_type: str
    available_agent_types: list[str] = None
    staffing_plan: dict[str, Any] | None = None
    use_worktrees: bool = False
    cwd: str = ""
    extra_env: dict[str, str] | None = None

    def __post_init__(self):
        if self.available_agent_types is None:
            self.available_agent_types = []
        if self.staffing_plan is None:
            self.staffing_plan = {}


def create_team_exec_stage(options: TeamExecStageOptions = None) -> dict[str, Any]:
    """
    Create a team-exec pipeline stage.

    This stage delegates to the existing team infrastructure, which
    starts Codex CLI workers in tmux panes. The stage collects the
    plan artifacts from the previous RALPLAN stage and passes them as
    the team task description.

    Args:
        options: Configuration options for the stage

    Returns:
        PipelineStage dictionary with run method
    """
    if options is None:
        options = TeamExecStageOptions()

    worker_count = options.worker_count
    agent_type = options.agent_type

    stage = {
        "name": "team-exec",
        "run": None,
    }

    async def run(ctx: StageContext) -> StageResult:
        """Execute the team execution stage."""
        import time
        start_time = int(time.time() * 1000)

        try:
            # Extract plan context from previous stage artifacts
            ralplan_artifacts = ctx.artifacts.get("ralplan", {})
            plan_context = (
                f"Plan from RALPLAN stage:\n{ralplan_artifacts}\n\nTask: {ctx.task}"
                if ralplan_artifacts
                else ctx.task
            )

            # Build team execution descriptor
            team_descriptor = TeamExecDescriptor(
                task=plan_context,
                worker_count=worker_count,
                agent_type=agent_type,
                available_agent_types=[],  # Would be populated from resolveAvailableAgentTypes
                staffing_plan={},  # Would be populated from buildFollowupStaffingPlan
                use_worktrees=options.use_worktrees,
                cwd=ctx.cwd,
                extra_env=options.extra_env,
            )

            return StageResult(
                status="completed",
                artifacts={
                    "team_descriptor": team_descriptor.__dict__,
                    "worker_count": worker_count,
                    "agent_type": agent_type,
                    "stage": "team-exec",
                    "instruction": build_team_instruction(team_descriptor),
                },
                duration_ms=int(time.time() * 1000) - start_time,
            )
        except Exception as err:
            return StageResult(
                status="failed",
                artifacts={},
                duration_ms=int(time.time() * 1000) - start_time,
                error=f"Team execution stage failed: {err!s}",
            )

    stage["run"] = run
    return stage


def build_team_instruction(descriptor: TeamExecDescriptor) -> str:
    """
    Build the `omx team` CLI instruction from a descriptor.

    Args:
        descriptor: Team execution descriptor

    Returns:
        CLI instruction string
    """
    import json
    staffing_summary = ""
    if descriptor.staffing_plan:
        staffing_summary = descriptor.staffing_plan.get("staffing_summary", "")

    verification_summary = ""
    if descriptor.staffing_plan:
        verification_summary = descriptor.staffing_plan.get("verification_plan", {}).get("summary", "")

    launch_command = f"team {descriptor.worker_count}:{descriptor.agent_type} {json.dumps(descriptor.task)}"
    return f"{launch_command} # staffing={staffing_summary} # verify={verification_summary}"
