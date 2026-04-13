import json
from pathlib import Path

import pytest

from src.core.persistence.run_state import RunStateManager
from src.workflow.models import WorkflowStatus


def test_sync_persists_intent_iteration_and_optimization_points(tmp_path):
    manager = RunStateManager(workdir=tmp_path, run_id="run-001")

    manager.sync(
        {
            "goal": "improve workflow",
            "intent": "evolve",
            "iteration": 2,
            "tasks": [{"task_id": "fix-001", "status": "pending"}],
            "optimization_points": ["point-a"],
        }
    )

    saved = json.loads((manager.coordination_file).read_text(encoding="utf-8"))
    assert saved["goal"] == "improve workflow"
    assert saved["intent"] == "evolve"
    assert saved["iteration"] == 2
    assert saved["tasks"] == [{"task_id": "fix-001", "status": "pending"}]
    assert saved["optimization_points"] == ["point-a"]


def test_update_task_updates_existing_task_and_keeps_other_fields(tmp_path):
    manager = RunStateManager(workdir=tmp_path, run_id="run-002")

    manager.sync(
        {
            "goal": "repair",
            "intent": "implement",
            "iteration": 1,
            "tasks": [
                {
                    "task_id": "fix-001",
                    "status": "pending",
                    "result": None,
                    "evidence_paths": [],
                    "dimensions": [{"name": "audit"}],
                }
            ],
        }
    )

    manager.update_task(
        "fix-001",
        WorkflowStatus.COMPLETED,
        result="done",
        evidence=["report.xml"],
    )

    saved = manager.load()
    assert saved is not None
    task = next(t for t in saved["tasks"] if t["task_id"] == "fix-001")
    assert task["status"] == WorkflowStatus.COMPLETED.value
    assert task["result"] == "done"
    assert "report.xml" in task["evidence_paths"]
    assert task["dimensions"] == [{"name": "audit"}]


def test_update_task_appends_when_missing(tmp_path):
    manager = RunStateManager(workdir=tmp_path, run_id="run-003")
    manager.sync({"goal": "new", "tasks": []})

    manager.update_task("fix-009", WorkflowStatus.FAILED, result="boom")

    saved = manager.load()
    assert saved is not None
    task = next(t for t in saved["tasks"] if t["task_id"] == "fix-009")
    assert task["status"] == WorkflowStatus.FAILED.value
    assert task["result"] == "boom"


def test_record_evidence_event_raises_on_write_failure(tmp_path, monkeypatch):
    manager = RunStateManager(workdir=tmp_path, run_id="run-004")

    def fail_open(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", fail_open)

    with pytest.raises(OSError, match="disk full"):
        manager.record_evidence_event(
            scenario_id="verify-fix-001",
            harness_kind="pytest",
            result={"status": "failed"},
        )


def test_sync_raises_on_write_failure(tmp_path, monkeypatch):
    manager = RunStateManager(workdir=tmp_path, run_id="run-005")

    def fail_open(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", fail_open)

    with pytest.raises(RuntimeError, match="原子写入失败"):
        manager.sync({"goal": "persist"})


def test_write_atomic_raises_runtime_error_on_write_failure(tmp_path, monkeypatch):
    manager = RunStateManager(workdir=tmp_path, run_id="run-006")

    def fail_open(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", fail_open)

    with pytest.raises(RuntimeError, match="原子写入失败"):
        manager._write_atomic(manager.contract_file, {"k": "v"})
