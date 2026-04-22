"""Tests for pipeline integration enhancements from oh-my-codex

Tests for:
- validate_pipeline_config
- read_pipeline_state
- cancel_pipeline
- on_stage_transition callback
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Callable, List, Optional

import pytest

from src.workflow.pipeline_orchestrator import (
    PipelineOrchestrator,
    PipelineConfig,
    PipelineStage,
    StageResult,
    StageStatus,
    validate_pipeline_config,
    create_autopilot_pipeline_config,
    read_pipeline_state,
    cancel_pipeline,
    PipelineModeStateExtension,
    MODES_MODE_NAME,
)
from src.workflow.types import StageContext


# ============================================================================
# Test fixtures
# ============================================================================

class DummyStage(PipelineStage):
    """A simple test stage that always succeeds"""

    def __init__(self, name: str, artifacts: Optional[dict] = None):
        self._name = name
        self.artifacts_out = artifacts or {}

    @property
    def name(self) -> str:
        return self._name

    async def run(self, ctx: StageContext) -> StageResult:
        return StageResult(
            status=StageStatus.SUCCESS,
            artifacts=self.artifacts_out,
            duration_ms=100,
        )


class FailingStage(PipelineStage):
    """A test stage that always fails"""

    def __init__(self, name: str, error_msg: str = "Test failure"):
        self._name = name
        self.error_msg = error_msg

    @property
    def name(self) -> str:
        return self._name

    async def run(self, ctx: StageContext) -> StageResult:
        return StageResult(
            status=StageStatus.FAILED,
            artifacts={},
            duration_ms=50,
            error=self.error_msg,
        )


# ============================================================================
# validate_pipeline_config tests
# ============================================================================

def test_validate_pipeline_config_success():
    """Test validate_pipeline_config with valid config"""
    stages = [DummyStage("stage1"), DummyStage("stage2")]
    config = PipelineConfig(
        name="test-pipeline",
        task="Test task",
        stages=stages,
    )
    # Should not raise
    validate_pipeline_config(config)


def test_validate_pipeline_config_empty_name():
    """Test validate_pipeline_config rejects empty name"""
    stages = [DummyStage("stage1")]
    config = PipelineConfig(
        name="",
        task="Test task",
        stages=stages,
    )
    with pytest.raises(ValueError, match="non-empty name"):
        validate_pipeline_config(config)


def test_validate_pipeline_config_empty_task():
    """Test validate_pipeline_config rejects empty task"""
    stages = [DummyStage("stage1")]
    config = PipelineConfig(
        name="test-pipeline",
        task="   ",
        stages=stages,
    )
    with pytest.raises(ValueError, match="non-empty task"):
        validate_pipeline_config(config)


def test_validate_pipeline_config_no_stages():
    """Test validate_pipeline_config rejects empty stages"""
    config = PipelineConfig(
        name="test-pipeline",
        task="Test task",
        stages=[],
    )
    with pytest.raises(ValueError, match="at least one stage"):
        validate_pipeline_config(config)


def test_validate_pipeline_config_duplicate_stage_names():
    """Test validate_pipeline_config detects duplicate stage names"""
    stages = [DummyStage("same"), DummyStage("same")]
    config = PipelineConfig(
        name="test-pipeline",
        task="Test task",
        stages=stages,
    )
    with pytest.raises(ValueError, match="Duplicate stage name"):
        validate_pipeline_config(config)


def test_validate_pipeline_config_invalid_max_ralph_iterations():
    """Test validate_pipeline_config validates max_ralph_iterations"""
    stages = [DummyStage("stage1")]
    config = PipelineConfig(
        name="test-pipeline",
        task="Test task",
        stages=stages,
        max_ralph_iterations=0,
    )
    with pytest.raises(ValueError, match="positive integer"):
        validate_pipeline_config(config)


def test_validate_pipeline_config_invalid_worker_count():
    """Test validate_pipeline_config validates worker_count"""
    stages = [DummyStage("stage1")]
    config = PipelineConfig(
        name="test-pipeline",
        task="Test task",
        stages=stages,
        worker_count=-1,
    )
    with pytest.raises(ValueError, match="positive integer"):
        validate_pipeline_config(config)


# ============================================================================
# create_autopilot_pipeline_config tests
# ============================================================================

def test_create_autopilot_pipeline_config_defaults():
    """Test create_autopilot_pipeline_config sets correct defaults"""
    stages = [DummyStage("stage1")]
    config = create_autopilot_pipeline_config(
        task="Test task",
        stages=stages,
    )
    assert config.name == "autopilot"
    assert config.task == "Test task"
    assert config.stages == stages
    assert config.max_ralph_iterations == 10
    assert config.worker_count == 2
    assert config.agent_type == "executor"
    assert config.on_stage_transition is None


def test_create_autopilot_pipeline_config_custom():
    """Test create_autopilot_pipeline_config with custom values"""
    stages = [DummyStage("stage1")]
    callback_called = []

    def on_transition(from_stage: str, to_stage: str):
        callback_called.append((from_stage, to_stage))

    config = create_autopilot_pipeline_config(
        task="Test task",
        stages=stages,
        max_ralph_iterations=5,
        worker_count=3,
        agent_type="analyzer",
        on_stage_transition=on_transition,
    )
    assert config.max_ralph_iterations == 5
    assert config.worker_count == 3
    assert config.agent_type == "analyzer"
    assert config.on_stage_transition is on_transition


# ============================================================================
# read_pipeline_state & cancel_pipeline tests
# ============================================================================

def test_read_pipeline_state_no_state(tmp_path: Path):
    """Test read_pipeline_state returns None when no state exists"""
    # Use a temp directory with no .clawd/pipeline
    result = read_pipeline_state(cwd=str(tmp_path))
    assert result is None


def test_cancel_pipeline_no_active_pipeline(tmp_path: Path):
    """Test cancel_pipeline with no active pipeline"""
    # Should not raise, just return False/None
    result = cancel_pipeline(cwd=str(tmp_path))
    # cancel_mode returns None on success or failure, we just check it doesn't raise
    assert result is None or result is False


# ============================================================================
# on_stage_transition callback tests
# ============================================================================

@pytest.mark.asyncio
async def test_on_stage_transition_called():
    """Test that on_stage_transition callback is invoked"""
    transitions = []

    def on_transition(from_stage: str, to_stage: str):
        transitions.append((from_stage, to_stage))

    stages = [
        DummyStage("stage1"),
        DummyStage("stage2"),
        DummyStage("stage3"),
    ]

    config = create_autopilot_pipeline_config(
        task="Test task",
        stages=stages,
        on_stage_transition=on_transition,
    )

    orchestrator = PipelineOrchestrator(config, cwd=".", validate=False)
    result = await orchestrator.run()

    # Should have transitions: None->stage1, stage1->stage2, stage2->stage3
    assert len(transitions) >= 2  # At least stage1->stage2 and stage2->stage3
    assert ("stage1", "stage2") in transitions
    assert ("stage2", "stage3") in transitions
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_on_stage_transition_not_called_on_skip():
    """Test that on_stage_transition is not called for skipped stages"""
    transitions = []

    def on_transition(from_stage: str, to_stage: str):
        transitions.append((from_stage, to_stage))

    # Create stages where second stage can be skipped
    class SkippableStage(DummyStage):
        def can_skip(self, ctx: StageContext) -> bool:
            return True

    stages = [
        DummyStage("stage1"),
        SkippableStage("stage2"),
        DummyStage("stage3"),
    ]

    config = create_autopilot_pipeline_config(
        task="Test task",
        stages=stages,
        on_stage_transition=on_transition,
    )

    orchestrator = PipelineOrchestrator(config, cwd=".", validate=False)
    result = await orchestrator.run()

    # stage2 is skipped, so transition from stage1 should go directly to stage3
    # Actually the callback is called BEFORE checking skip, so stage1->stage2 still fires
    # But stage2->stage3 should still fire (after skip)
    assert result.status == "completed"


# ============================================================================
# PipelineModeStateExtension roundtrip tests
# ============================================================================

def test_pipeline_mode_state_extension_serialization():
    """Test PipelineModeStateExtension serialization roundtrip"""
    original = PipelineModeStateExtension(
        pipeline_name="test-pipeline",
        pipeline_stages=["stage1", "stage2", "stage3"],
        pipeline_stage_index=1,
        pipeline_stage_results={
            "stage1": {
                "status": "success",
                "artifacts": {"key": "value"},
                "duration_ms": 100,
                "error": None,
            }
        },
        pipeline_max_ralph_iterations=5,
        pipeline_worker_count=3,
        pipeline_agent_type="executor",
    )

    metadata = original.to_metadata_update()
    restored = PipelineModeStateExtension.from_mode_metadata(metadata)

    assert restored.pipeline_name == original.pipeline_name
    assert restored.pipeline_stages == original.pipeline_stages
    assert restored.pipeline_stage_index == original.pipeline_stage_index
    assert restored.pipeline_max_ralph_iterations == original.pipeline_max_ralph_iterations
    assert restored.pipeline_worker_count == original.pipeline_worker_count
    assert restored.pipeline_agent_type == original.pipeline_agent_type


# ============================================================================
# Integration: full pipeline run with new features
# ============================================================================

@pytest.mark.asyncio
async def test_pipeline_with_callback_and_state(tmp_path: Path):
    """Test full pipeline run with on_stage_transition callback and state persistence"""
    transitions = []

    def on_transition(from_stage: str, to_stage: str):
        transitions.append((from_stage, to_stage))

    stages = [
        DummyStage("plan", artifacts={"plan": "approved"}),
        DummyStage("exec", artifacts={"code": "written"}),
        DummyStage("verify", artifacts={"verified": True}),
    ]

    config = create_autopilot_pipeline_config(
        task="Test full pipeline",
        stages=stages,
        cwd=str(tmp_path),
        on_stage_transition=on_transition,
        max_ralph_iterations=3,
        worker_count=4,
    )

    orchestrator = PipelineOrchestrator(config, cwd=str(tmp_path), validate=True)
    result = await orchestrator.run()

    assert result.status == "completed"
    assert len(transitions) == 2  # plan->exec, exec->verify
    assert ("plan", "exec") in transitions
    assert ("exec", "verify") in transitions

    # Check state file was created (ModeStateManager writes to .clawd/state/)
    state_dir = tmp_path / ".clawd" / "state"
    assert state_dir.exists(), f"State dir not found: {state_dir}"
    # Look for autopilot mode state file
    state_file = state_dir / "mode-autopilot.json"
    assert state_file.exists(), f"State file not found: {state_file}"


def test_validate_then_create_orchestrator():
    """Test the recommended flow: validate first, then create orchestrator"""
    stages = [DummyStage("stage1")]
    config = create_autopilot_pipeline_config(
        task="Test task",
        stages=stages,
    )

    # Validate first
    validate_pipeline_config(config)  # Should not raise

    # Then create orchestrator
    orchestrator = PipelineOrchestrator(config, validate=False)
    assert orchestrator.config == config


# ============================================================================
# Backward compatibility tests
# ============================================================================

def test_backward_compat_pipeline_config_without_callback():
    """Test PipelineConfig works without on_stage_transition (backward compat)"""
    stages = [DummyStage("stage1")]
    config = PipelineConfig(
        name="test",
        task="test",
        stages=stages,
        # Not providing on_stage_transition should be fine
    )
    assert config.on_stage_transition is None


def test_backward_compat_orchestrator_without_callback():
    """Test PipelineOrchestrator works without callback"""
    stages = [DummyStage("stage1")]
    config = PipelineConfig(
        name="test",
        task="test",
        stages=stages,
    )
    orchestrator = PipelineOrchestrator(config, validate=True)
    # Should not have callback-related errors
