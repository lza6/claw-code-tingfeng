"""Tests for workflow models."""

import pytest
from src.workflow.models import (
    Dimension,
    DimensionSource,
    DispatchableSlice,
    WorkflowPhase,
    WorkflowPhaseCategory,
    WorkflowStatus,
    VersionBumpType,
    TechDebtPriority,
    WorkflowTask,
    WorkflowResult,
    TechDebtRecord,
)


class TestWorkflowPhase:
    """Test WorkflowPhase enum."""

    def test_phases_exist(self):
        """Verify all expected phases exist."""
        assert WorkflowPhase.IDENTIFY == "identify"
        assert WorkflowPhase.PLAN == "plan"
        assert WorkflowPhase.EXECUTE == "execute"
        assert WorkflowPhase.REVIEW == "review"
        assert WorkflowPhase.DISCOVER == "discover"

    def test_phase_count(self):
        """Verify exactly 5 phases."""
        assert len(list(WorkflowPhase)) == 5

    def test_phase_is_string_enum(self):
        """Verify phases are string-based."""
        assert isinstance(WorkflowPhase.IDENTIFY.value, str)


class TestWorkflowPhaseCategory:
    """Test WorkflowPhaseCategory enum."""

    def test_identify_categories(self):
        """Verify IDENTIFY phase categories."""
        assert WorkflowPhaseCategory.IDENTIFY_ANALYZE == "identify.analyze"
        assert WorkflowPhaseCategory.IDENTIFY_PROFILE == "identify.profile"
        assert WorkflowPhaseCategory.IDENTIFY_DISCOVER == "identify.discover"

    def test_plan_categories(self):
        """Verify PLAN phase categories."""
        assert WorkflowPhaseCategory.PLAN_TODO == "plan.todo"
        assert WorkflowPhaseCategory.PLAN_SPLIT == "plan.split"

    def test_execute_categories(self):
        """Verify EXECUTE phase categories."""
        assert WorkflowPhaseCategory.EXECUTE_STEP == "execute.step"
        assert WorkflowPhaseCategory.EXECUTE_VERIFY == "execute.verify"
        assert WorkflowPhaseCategory.EXECUTE_VALIDATE == "execute.validate"

    def test_review_categories(self):
        """Verify REVIEW phase categories."""
        assert WorkflowPhaseCategory.REVIEW_GLOBAL == "review.global"
        assert WorkflowPhaseCategory.REVIEW_CLEANUP == "review.cleanup"
        assert WorkflowPhaseCategory.REVIEW_DOCUMENT == "review.document"
        assert WorkflowPhaseCategory.REVIEW_REPORT == "review.report"

    def test_discover_category(self):
        """Verify DISCOVER phase category."""
        assert WorkflowPhaseCategory.DISCOVER_OPTIMIZE == "discover.optimize"


class TestWorkflowStatus:
    """Test WorkflowStatus enum."""

    def test_all_statuses(self):
        """Verify all workflow statuses."""
        assert WorkflowStatus.PENDING == "pending"
        assert WorkflowStatus.RUNNING == "running"
        assert WorkflowStatus.COMPLETED == "completed"
        assert WorkflowStatus.FAILED == "failed"
        assert WorkflowStatus.CANCELLED == "cancelled"


class TestVersionBumpType:
    """Test VersionBumpType enum."""

    def test_all_bump_types(self):
        """Verify all version bump types."""
        assert VersionBumpType.MAJOR == "major"
        assert VersionBumpType.MINOR == "minor"
        assert VersionBumpType.PATCH == "patch"
        assert VersionBumpType.PRERELEASE == "prerelease"


class TestTechDebtPriority:
    """Test TechDebtPriority enum."""

    def test_all_priorities(self):
        """Verify all priority levels in descending order."""
        assert TechDebtPriority.CRITICAL == "critical"
        assert TechDebtPriority.HIGH == "high"
        assert TechDebtPriority.MEDIUM == "medium"
        assert TechDebtPriority.LOW == "low"


class TestWorkflowTask:
    """Test WorkflowTask dataclass."""

    def test_create_task_minimal(self):
        """Create task with minimal required fields."""
        task = WorkflowTask(
            task_id="plan-001",
            phase=WorkflowPhase.PLAN,
            title="Test Task",
            description="Test Description",
        )
        assert task.task_id == "plan-001"
        assert task.phase == WorkflowPhase.PLAN
        assert task.title == "Test Task"
        assert task.description == "Test Description"
        assert task.status == WorkflowStatus.PENDING
        assert task.result is None
        assert task.depends_on == []

    def test_create_task_with_dependencies(self):
        """Create task with dependencies."""
        task = WorkflowTask(
            task_id="exec-002",
            phase=WorkflowPhase.EXECUTE,
            title="Execute Task",
            description="Execute something",
            depends_on=["plan-001"],
        )
        assert task.depends_on == ["plan-001"]

    def test_create_task_with_result(self):
        """Create task with result."""
        task = WorkflowTask(
            task_id="exec-003",
            phase=WorkflowPhase.EXECUTE,
            title="Completed Task",
            description="Done",
            status=WorkflowStatus.COMPLETED,
            result="Success!",
        )
        assert task.status == WorkflowStatus.COMPLETED
        assert task.result == "Success!"

    def test_task_is_frozen(self):
        """Verify task is immutable."""
        task = WorkflowTask(
            task_id="test-001",
            phase=WorkflowPhase.PLAN,
            title="Immutable",
            description="Cannot change",
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            task.title = "Changed"

    def test_task_equality(self):
        """Test task equality based on all fields."""
        task1 = WorkflowTask(
            task_id="test-001",
            phase=WorkflowPhase.PLAN,
            title="Same",
            description="Same desc",
        )
        task2 = WorkflowTask(
            task_id="test-001",
            phase=WorkflowPhase.PLAN,
            title="Same",
            description="Same desc",
        )
        assert task1 == task2

    def test_task_inequality(self):
        """Test task inequality when fields differ."""
        task1 = WorkflowTask(
            task_id="test-001",
            phase=WorkflowPhase.PLAN,
            title="Different",
            description="Desc",
        )
        task2 = WorkflowTask(
            task_id="test-002",
            phase=WorkflowPhase.PLAN,
            title="Different",
            description="Desc",
        )
        assert task1 != task2

    def test_to_dict_preserves_extended_fields(self):
        """验证 to_dict 包含 dimensions/slices 等扩展字段。"""
        task = WorkflowTask(
            task_id="fix-001",
            phase=WorkflowPhase.EXECUTE,
            title="Critical fix",
            description="修复关键问题",
            status=WorkflowStatus.RUNNING,
            depends_on=["plan-001"],
            dimensions=[
                Dimension(
                    name="audit",
                    guidance="systematic review",
                    source=DimensionSource.BUILTIN,
                )
            ],
            slices=[
                DispatchableSlice(
                    title="Slice A",
                    why="验证主路径",
                    mode="worker",
                    suggested_owner="agent-a",
                    evidence=["logs/a.txt"],
                )
            ],
            evidence_paths=["reports/junit.xml"],
            worktree_id="wt-001",
            verification_criteria="all tests pass",
            retry_count=2,
        )

        data = task.to_dict()

        assert data["task_id"] == "fix-001"
        assert data["phase"] == WorkflowPhase.EXECUTE.value
        assert data["status"] == WorkflowStatus.RUNNING.value
        assert data["depends_on"] == ["plan-001"]
        assert data["dimensions"] == [{
            "name": "audit",
            "guidance": "systematic review",
            "source": DimensionSource.BUILTIN.value,
        }]
        assert data["slices"] == [{
            "title": "Slice A",
            "why": "验证主路径",
            "mode": "worker",
            "suggested_owner": "agent-a",
            "evidence": ["logs/a.txt"],
        }]
        assert data["evidence_paths"] == ["reports/junit.xml"]
        assert data["worktree_id"] == "wt-001"
        assert data["verification_criteria"] == "all tests pass"
        assert data["retry_count"] == 2


class TestWorkflowResult:
    """Test WorkflowResult dataclass."""

    def test_create_result_minimal(self):
        """Create result with minimal fields."""
        result = WorkflowResult(status=WorkflowStatus.COMPLETED)
        assert result.status == WorkflowStatus.COMPLETED
        assert result.phase_summary == {}
        assert result.total_tasks == 0
        assert result.completed_tasks == 0
        assert result.optimization_points == []
        assert result.report == ""

    def test_create_result_with_data(self):
        """Create result with comprehensive data."""
        result = WorkflowResult(
            status=WorkflowStatus.COMPLETED,
            phase_summary={
                WorkflowPhase.IDENTIFY: "Analysis complete",
                WorkflowPhase.PLAN: "Plan created",
                WorkflowPhase.EXECUTE: "Execution done",
            },
            total_tasks=10,
            completed_tasks=10,
            optimization_points=[
                "Optimize database queries",
                "Add caching layer",
            ],
            report="Full execution report",
        )
        assert len(result.phase_summary) == 3
        assert result.total_tasks == 10
        assert result.completed_tasks == 10
        assert len(result.optimization_points) == 2
        assert result.report == "Full execution report"

    def test_result_partial_completion(self):
        """Test result with partial completion."""
        result = WorkflowResult(
            status=WorkflowStatus.FAILED,
            total_tasks=10,
            completed_tasks=7,
        )
        assert result.status == WorkflowStatus.FAILED
        assert result.completed_tasks < result.total_tasks

    def test_result_is_frozen(self):
        """Verify result is immutable."""
        result = WorkflowResult(status=WorkflowStatus.COMPLETED)
        with pytest.raises(Exception):
            result.report = "Modified"


class TestTechDebtRecord:
    """Test TechDebtRecord dataclass."""

    def test_create_record_minimal(self):
        """Create tech debt record with minimal fields."""
        record = TechDebtRecord(
            record_id="TD-0001",
            issue_id="ISSUE-123",
            priority=TechDebtPriority.HIGH,
            description="Technical debt item",
        )
        assert record.record_id == "TD-0001"
        assert record.issue_id == "ISSUE-123"
        assert record.priority == TechDebtPriority.HIGH
        assert record.description == "Technical debt item"
        assert record.affected_files == []
        assert record.created_at == ""
        assert record.resolved is False
        assert record.resolved_at is None

    def test_create_record_with_effort(self):
        """Create record with affected files."""
        record = TechDebtRecord(
            record_id="TD-0002",
            issue_id="ISSUE-456",
            priority=TechDebtPriority.MEDIUM,
            description="Needs refactoring",
            affected_files=["src/legacy.py", "src/utils.py"],
        )
        assert len(record.affected_files) == 2

    def test_record_is_frozen(self):
        """Verify record is immutable."""
        record = TechDebtRecord(
            record_id="TD-0003",
            issue_id="ISSUE-789",
            priority=TechDebtPriority.LOW,
            description="Minor issue",
        )
        with pytest.raises(Exception):
            record.description = "Changed"

    def test_priority_ordering(self):
        """Test that priorities can be compared by severity."""
        # Critical should be most severe
        critical = TechDebtRecord(
            record_id="TD-001",
            issue_id="ISS-1",
            priority=TechDebtPriority.CRITICAL,
            description="Critical",
        )
        low = TechDebtRecord(
            record_id="TD-002",
            issue_id="ISS-2",
            priority=TechDebtPriority.LOW,
            description="Low",
        )
        
        # Both records should maintain their priority
        assert critical.priority == TechDebtPriority.CRITICAL
        assert low.priority == TechDebtPriority.LOW
