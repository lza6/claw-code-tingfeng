---
name: pipeline_orchestrator
description: Configurable pipeline orchestrator for sequencing RALPLAN -> team-exec -> ralph
---

# Pipeline Orchestrator Skill

`$pipeline_orchestrator` provides configurable pipeline orchestration for Clawd Code.

It sequences stages through a uniform `PipelineStage` interface, with state persistence and resume support.

## Default Pipeline

The canonical pipeline sequences:

```
RALPLAN (consensus planning) -> team-exec (agent swarm) -> ralph (verification)
```

## Configuration

Pipeline parameters are configurable per run:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_ralph_iterations` | 10 | Ralph verification iteration ceiling |
| `worker_count` | 2 | Number of agent workers |
| `agent_type` | `executor` | Agent type for workers |

## Stage Interface

Every stage implements the `PipelineStage` interface:

```python
class PipelineStage(Protocol):
    name: str
    async def run(ctx: StageContext) -> StageResult: ...
    def can_skip(ctx: StageContext) -> bool: ...
```

Stages receive a `StageContext` with accumulated artifacts from prior stages and return a `StageResult` with status, artifacts, and duration.

## Built-in Stages

- **ralplan**: Consensus planning phase. Generates structured task breakdown, dependencies, and risks using the planner agent. Skips only when both `prd-*.md` and `test-spec-*.md` planning artifacts already exist.
- **team-exec**: Parallel agent swarm execution using team mode. Always the execution backend for Clawd Code.
- **ralph-verify**: Iterative verification loop using the ralph agent with configurable iteration count.

## State Management

Pipeline state persists in `.claude/workflow/pipeline_state.json` (compatible with GoalX durable surfaces).

- **On start**: `state_write({mode: "pipeline", active: True, current_phase: "stage:ralplan"})`
- **On stage transitions**: `state_write({mode: "pipeline", current_phase: "stage:<name>"})`
- **On completion**: `state_write({mode: "pipeline", active: False, current_phase: "complete"})`

The HUD dashboard renders pipeline phase automatically. Resume is supported from the last incomplete stage.

## API

```python
from src.workflow.pipeline_orchestrator import (
    run_pipeline,
    create_autopilot_pipeline_config,
    create_ralplan_stage,
    create_team_exec_stage,
    create_ralph_verify_stage,
)

config = create_autopilot_pipeline_config(
    task="Build feature X",
    stages=[
        create_ralplan_stage(),
        create_team_exec_stage(worker_count=3, agent_type="executor"),
        create_ralph_verify_stage(max_iterations=15),
    ]
)

result = await run_pipeline(config)
```

## Relationship to Other Modes

- **team**: Pipeline delegates execution to team mode (agent swarm)
- **ralph**: Pipeline delegates verification to ralph mode (configurable iterations)
- **ralplan**: Pipeline's first stage runs RALPLAN consensus planning  
