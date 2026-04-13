"""
Integration tests for durable surfaces system
"""

import pytest
from pathlib import Path
import tempfile
import shutil
from datetime import datetime

from src.core.durable.surface_manager import SurfaceManager, SurfaceError, SurfaceValidationError
from src.core.durable.surfaces.objective_contract import ObjectiveContract
from src.core.durable.surfaces.obligation_model import ObligationModel, Obligation, ObligationStatus
from src.core.durable.surfaces.assurance_plan import AssurancePlan, AssuranceScenario, VerificationMethod
from src.core.durable.surfaces.evidence_log import EvidenceLog, EvidenceEntry, EvidenceType
from src.core.durable.surfaces.coordination_state import CoordinationState, SessionInfo, SessionState
from src.core.durable.surfaces.status_summary import StatusSummary, RunPhase


@pytest.fixture
def temp_run_dir():
    """Create a temporary run directory."""
    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def surface_manager(temp_run_dir):
    """Create a surface manager."""
    return SurfaceManager(temp_run_dir)


class TestSurfaceManager:
    """Test surface manager operations."""

    def test_create_and_load_surface(self, surface_manager):
        """Test creating and loading a surface."""
        # Create objective contract
        contract = ObjectiveContract(
            objective="Test objective",
            created_at=datetime.utcnow().isoformat(),
            run_id="test-run-1"
        )

        # Save it
        surface_manager.save_surface("objective_contract", contract)

        # Load it back
        loaded = surface_manager.load_surface(
            "objective_contract",
            ObjectiveContract,
            create_if_missing=False
        )

        assert loaded.objective == "Test objective"
        assert loaded.run_id == "test-run-1"

    def test_surface_caching(self, surface_manager):
        """Test that surfaces are cached."""
        contract = ObjectiveContract(
            objective="Test",
            created_at=datetime.utcnow().isoformat(),
            run_id="test-run"
        )

        surface_manager.save_surface("objective_contract", contract)

        # Load twice
        loaded1 = surface_manager.load_surface("objective_contract", ObjectiveContract)
        loaded2 = surface_manager.load_surface("objective_contract", ObjectiveContract)

        # Should be the same instance (cached)
        assert loaded1 is loaded2

    def test_atomic_write(self, surface_manager):
        """Test atomic write with backup."""
        contract = ObjectiveContract(
            objective="Original",
            created_at=datetime.utcnow().isoformat(),
            run_id="test-run"
        )

        surface_manager.save_surface("objective_contract", contract)

        # Modify and save again
        contract.objective = "Modified"
        surface_manager.save_surface("objective_contract", contract)

        # Backup should exist
        backup_path = surface_manager.surfaces_dir / "objective_contract.json.bak"
        assert backup_path.exists()

    def test_snapshot_and_restore(self, surface_manager):
        """Test snapshot and restore functionality."""
        # Create multiple surfaces
        contract = ObjectiveContract(
            objective="Test",
            created_at=datetime.utcnow().isoformat(),
            run_id="test-run"
        )
        surface_manager.save_surface("objective_contract", contract)

        obligations = ObligationModel.create_default()
        surface_manager.save_surface("obligation_model", obligations)

        # Create snapshot
        snapshot_dir = surface_manager.snapshot("before-change")
        assert snapshot_dir.exists()

        # Modify surfaces
        contract.objective = "Modified"
        surface_manager.save_surface("objective_contract", contract)

        # Restore snapshot
        surface_manager.restore_snapshot(snapshot_dir)

        # Should be back to original
        loaded = surface_manager.load_surface("objective_contract", ObjectiveContract)
        assert loaded.objective == "Test"


class TestObjectiveContract:
    """Test objective contract surface."""

    def test_create_default(self):
        """Test creating default contract."""
        contract = ObjectiveContract.create_default()
        assert contract.objective == ""
        assert contract.run_id == ""

    def test_serialization(self):
        """Test to_dict and from_dict."""
        contract = ObjectiveContract(
            objective="Build a feature",
            created_at=datetime.utcnow().isoformat(),
            run_id="run-123",
            constraints=["No breaking changes"],
            success_criteria=["All tests pass"]
        )

        # Serialize
        data = contract.to_dict()

        # Deserialize
        loaded = ObjectiveContract.from_dict(data)

        assert loaded.objective == contract.objective
        assert loaded.run_id == contract.run_id
        assert loaded.constraints == contract.constraints


class TestObligationModel:
    """Test obligation model surface."""

    def test_add_obligation(self):
        """Test adding obligations."""
        model = ObligationModel.create_default()

        obl = Obligation(
            id="obl-1",
            text="Implement feature X",
            status=ObligationStatus.OPEN
        )

        model.add_obligation(obl)
        assert len(model.required) == 1
        assert model.required[0].id == "obl-1"

    def test_satisfy_obligation(self):
        """Test satisfying an obligation."""
        model = ObligationModel.create_default()

        obl = Obligation(id="obl-1", text="Test", status=ObligationStatus.OPEN)
        model.add_obligation(obl)

        model.satisfy_obligation("obl-1", ["Test passed"])

        assert model.get_obligation("obl-1").status == ObligationStatus.SATISFIED
        assert "Test passed" in model.get_obligation("obl-1").evidence_paths

    def test_get_ready_obligations(self):
        """Test getting ready obligations."""
        model = ObligationModel.create_default()

        # Add obligations with dependencies
        obl1 = Obligation(id="obl-1", text="First", status=ObligationStatus.OPEN)
        obl2 = Obligation(
            id="obl-2",
            text="Second",
            status=ObligationStatus.OPEN,
            depends_on=["obl-1"]
        )

        model.add_obligation(obl1)
        model.add_obligation(obl2)

        # Only obl-1 should be ready (no dependencies)
        ready = model.get_ready_obligations()
        assert len(ready) == 1
        assert ready[0].id == "obl-1"

        # Satisfy obl-1
        model.satisfy_obligation("obl-1", ["Done"])

        # Now obl-2 should be ready
        ready = model.get_ready_obligations()
        assert len(ready) == 1
        assert ready[0].id == "obl-2"

    def test_completion_percentage(self):
        """Test completion percentage calculation."""
        model = ObligationModel.create_default()

        obl1 = Obligation(id="obl-1", text="First", status=ObligationStatus.OPEN)
        obl2 = Obligation(id="obl-2", text="Second", status=ObligationStatus.OPEN)

        model.add_obligation(obl1)
        model.add_obligation(obl2)

        assert model.get_completion_percentage() == 0.0

        model.satisfy_obligation("obl-1", ["Done"])
        assert model.get_completion_percentage() == 50.0

        model.satisfy_obligation("obl-2", ["Done"])
        assert model.get_completion_percentage() == 100.0


class TestAssurancePlan:
    """Test assurance plan surface."""

    def test_add_scenario(self):
        """Test adding verification scenarios."""
        plan = AssurancePlan.create_default()

        scenario = AssuranceScenario(
            id="scenario-1",
            name="Unit tests",
            description="Run unit tests",
            method=VerificationMethod.UNIT_TEST,
            test_command="pytest tests/"
        )

        plan.add_scenario(scenario)
        assert "scenario-1" in plan.scenarios

    def test_execute_scenario(self):
        """Test executing a scenario."""
        plan = AssurancePlan.create_default()

        scenario = AssuranceScenario(
            id="scenario-1",
            name="Test",
            description="Test",
            method=VerificationMethod.UNIT_TEST
        )

        plan.add_scenario(scenario)
        plan.execute_scenario("scenario-1", passed=True, execution_log="All tests passed")

        assert plan.scenarios["scenario-1"].executed
        assert plan.scenarios["scenario-1"].passed

    def test_pass_rate(self):
        """Test pass rate calculation."""
        plan = AssurancePlan.create_default()

        s1 = AssuranceScenario(id="s1", name="T1", description="", method=VerificationMethod.UNIT_TEST)
        s2 = AssuranceScenario(id="s2", name="T2", description="", method=VerificationMethod.UNIT_TEST)

        plan.add_scenario(s1)
        plan.add_scenario(s2)

        plan.execute_scenario("s1", passed=True, execution_log="")
        plan.execute_scenario("s2", passed=False, execution_log="")

        assert plan.get_pass_rate() == 50.0


class TestEvidenceLog:
    """Test evidence log surface."""

    def test_record_evidence(self):
        """Test recording evidence."""
        log = EvidenceLog.create_default()

        entry = EvidenceEntry(
            id="ev-1",
            type=EvidenceType.TEST_RESULT,
            description="Unit tests passed",
            recorded_at=datetime.utcnow().isoformat(),
            obligation_id="obl-1"
        )

        log.record_evidence(entry)
        assert len(log.entries) == 1

    def test_get_evidence_for_obligation(self):
        """Test filtering evidence by obligation."""
        log = EvidenceLog.create_default()

        e1 = EvidenceEntry(
            id="e1",
            type=EvidenceType.TEST_RESULT,
            description="Test",
            recorded_at=datetime.utcnow().isoformat(),
            obligation_id="obl-1"
        )

        e2 = EvidenceEntry(
            id="e2",
            type=EvidenceType.CODE_REVIEW,
            description="Review",
            recorded_at=datetime.utcnow().isoformat(),
            obligation_id="obl-2"
        )

        log.record_evidence(e1)
        log.record_evidence(e2)

        evidence = log.get_evidence_for_obligation("obl-1")
        assert len(evidence) == 1
        assert evidence[0].id == "e1"


class TestCoordinationState:
    """Test coordination state surface."""

    def test_add_session(self):
        """Test adding a session."""
        coord = CoordinationState.create_default()

        session = SessionInfo(
            session_id="session-1",
            state=SessionState.IDLE,
            created_at=datetime.utcnow().isoformat()
        )

        coord.add_session(session)
        assert "session-1" in coord.sessions

    def test_assign_obligation(self):
        """Test assigning obligation to session."""
        coord = CoordinationState.create_default()

        session = SessionInfo(
            session_id="session-1",
            state=SessionState.IDLE,
            created_at=datetime.utcnow().isoformat()
        )

        coord.add_session(session)
        coord.assign_obligation("session-1", "obl-1")

        assert "obl-1" in coord.sessions["session-1"].assigned_obligations
        assert "session-1" in coord.coverage_map["obl-1"]

    def test_get_uncovered_obligations(self):
        """Test finding uncovered obligations."""
        coord = CoordinationState.create_default()

        session = SessionInfo(
            session_id="session-1",
            state=SessionState.IDLE,
            created_at=datetime.utcnow().isoformat()
        )

        coord.add_session(session)
        coord.assign_obligation("session-1", "obl-1")

        all_obligations = ["obl-1", "obl-2", "obl-3"]
        uncovered = coord.get_uncovered_obligations(all_obligations)

        assert "obl-1" not in uncovered
        assert "obl-2" in uncovered
        assert "obl-3" in uncovered


class TestStatusSummary:
    """Test status summary surface."""

    def test_create_default(self):
        """Test creating default status."""
        status = StatusSummary.create_default()
        assert status.phase == RunPhase.INITIALIZING
        assert status.progress_percentage == 0.0

    def test_update_progress(self):
        """Test updating progress."""
        status = StatusSummary.create_default()

        status.update_progress(
            obligations_satisfied=5,
            obligations_total=10,
            scenarios_passed=3,
            scenarios_total=5
        )

        # 70% weight on obligations (50%) + 30% weight on scenarios (60%) = 53%
        assert status.progress_percentage == pytest.approx(53.0, rel=0.1)

    def test_health_status(self):
        """Test health status tracking."""
        status = StatusSummary.create_default()
        assert status.health_status == "healthy"

        status.add_warning("Low memory")
        assert status.health_status == "degraded"

        status.add_error("Build failed")
        assert status.health_status == "unhealthy"

        status.clear_errors()
        assert status.health_status == "degraded"

        status.clear_warnings()
        assert status.health_status == "healthy"
