"""状态持久化语义回归测试（P0-5）。

覆盖：
- 原子写 + schema_version / attempt / working_path
- attempt fence：旧执行者不得覆盖新状态
- 更高 schema 拒绝恢复
- 加锁并发写不产生半截 JSON
"""
from __future__ import annotations

import json
import threading

import pytest

from src.utils.file_ops import atomic_write_json, file_lock, locked_atomic_write_json
from src.workflow.pipeline_orchestrator import (
    PIPELINE_ARTIFACTS_KEY,
    PIPELINE_ATTEMPT_KEY,
    PIPELINE_SCHEMA_VERSION_KEY,
    PIPELINE_STAGES_KEY,
    PIPELINE_UPDATED_AT_KEY,
    PIPELINE_WORKING_PATH_KEY,
    PipelineState,
    StaleStateError,
)
from src.workflow.types import StageResult, StageStatus


def test_save_writes_schema_attempt_and_working_path(tmp_path):
    path = tmp_path / "state.json"
    state = PipelineState("demo", stage_names=["identify", "plan"])
    state.save(str(path))

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data[PIPELINE_SCHEMA_VERSION_KEY] == 1
    assert data[PIPELINE_ATTEMPT_KEY] == 1
    assert data[PIPELINE_STAGES_KEY] == ["identify", "plan"]
    assert data[PIPELINE_WORKING_PATH_KEY]
    assert data[PIPELINE_UPDATED_AT_KEY]


def test_attempt_increments_on_each_save(tmp_path):
    path = tmp_path / "state.json"
    state = PipelineState("demo")
    state.save(str(path))
    state.save(str(path))

    assert json.loads(path.read_text(encoding="utf-8"))[PIPELINE_ATTEMPT_KEY] == 2
    assert state.attempt == 2


def test_stale_attempt_is_rejected_and_does_not_overwrite(tmp_path):
    path = tmp_path / "state.json"
    state = PipelineState("demo")
    state.save(str(path))  # disk attempt = 1
    before = path.read_text(encoding="utf-8")

    with pytest.raises(StaleStateError):
        state.save(str(path), expected_attempt=0)

    assert path.read_text(encoding="utf-8") == before


def test_matching_attempt_is_allowed(tmp_path):
    path = tmp_path / "state.json"
    state = PipelineState("demo")
    state.save(str(path))  # attempt 1

    state.save(str(path), expected_attempt=1)
    assert json.loads(path.read_text(encoding="utf-8"))[PIPELINE_ATTEMPT_KEY] == 2


def test_newer_schema_is_refused(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps({"pipeline_name": "future", "schema_version": 999}),
        encoding="utf-8",
    )
    assert PipelineState.load(str(path)) is None


def test_roundtrip_preserves_results_and_artifacts(tmp_path):
    path = tmp_path / "state.json"
    state = PipelineState("demo", stage_names=["a", "b"])
    state.stage_results["a"] = StageResult(
        status=StageStatus.SUCCESS,
        artifacts={"note": "ok"},
        duration_ms=12,
    )
    state.artifacts = {"shared": {"x": 1}}
    state.save(str(path))

    loaded = PipelineState.load(str(path))
    assert loaded is not None
    assert loaded.stage_names == ["a", "b"]
    assert loaded.stage_results["a"].status is StageStatus.SUCCESS
    assert loaded.artifacts == {"shared": {"x": 1}}
    assert loaded.attempt == 1
    assert loaded.updated_at


def test_save_serializes_non_json_artifacts(tmp_path):
    from pathlib import Path

    path = tmp_path / "state.json"
    state = PipelineState("demo")
    state.artifacts = {"path": Path("a") / "b"}
    state.save(str(path))

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data[PIPELINE_ARTIFACTS_KEY]["path"] == str(Path("a") / "b")


def test_legacy_state_without_schema_is_still_loadable(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps({"pipeline_name": "legacy", "pipeline_stages": ["a"]}),
        encoding="utf-8",
    )
    loaded = PipelineState.load(str(path))
    assert loaded is not None
    assert loaded.pipeline_name == "legacy"
    assert loaded.stage_names == ["a"]
    assert loaded.attempt == 0


def test_locked_atomic_write_is_valid_json_under_concurrency(tmp_path):
    path = tmp_path / "shared.json"
    errors: list[BaseException] = []

    def worker(value: int) -> None:
        try:
            for _ in range(20):
                locked_atomic_write_json(path, {"value": value, "pad": "x" * 200})
        except BaseException as exc:  # noqa: BLE001 - 测试记录任何失败
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["value"] in {0, 1, 2, 3}
    assert not list(tmp_path.glob("*.tmp"))


def test_file_lock_times_out_when_held_by_another_thread(tmp_path):
    target = tmp_path / "locked.json"
    acquired = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with file_lock(target, timeout=5, stale_after=0):
            acquired.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    assert acquired.wait(2)

    try:
        with pytest.raises(TimeoutError):
            with file_lock(target, timeout=0.2, stale_after=0):
                pass
    finally:
        release.set()
        thread.join()


def test_file_lock_is_reentrant_in_same_thread(tmp_path):
    target = tmp_path / "reentrant.json"
    with file_lock(target, timeout=2):
        with file_lock(target, timeout=2):
            locked_atomic_write_json(target, {"ok": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}


def test_mode_state_update_concurrent_no_lost_updates(tmp_path):
    """直接测生产函数 ModeStateManager.update_state 的读改写锁。"""
    from src.workflow.mode_state import ModeStateManager

    manager = ModeStateManager(cwd=str(tmp_path))
    manager.start_mode("pipeline", "task")
    errors: list[BaseException] = []

    def worker(tid: int) -> None:
        try:
            for i in range(10):
                manager.update_state("pipeline", {f"k{tid}_{i}": i})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发更新异常: {errors!r}"
    state = manager.read_state("pipeline")
    assert state is not None
    missing = [
        f"k{tid}_{i}"
        for tid in range(4)
        for i in range(10)
        if f"k{tid}_{i}" not in state.metadata
    ]
    assert not missing, f"丢失更新: {missing[:5]}"


def test_add_progress_entry_concurrent_no_lost_updates(tmp_path):
    """直接测生产函数 add_progress_entry 的读改写锁。"""
    from src.workflow.ralph_ledger import add_progress_entry, read_ralph_progress

    errors: list[BaseException] = []

    def worker(tid: int) -> None:
        try:
            for i in range(10):
                add_progress_entry(f"{tid}-{i}", cwd=str(tmp_path))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发写入异常: {errors!r}"
    ledger = read_ralph_progress(cwd=str(tmp_path))
    assert len(ledger.entries) == 40, f"丢失更新: 只有 {len(ledger.entries)} 条"


def test_locked_read_modify_write_does_not_lose_updates(tmp_path):
    """锁必须覆盖 read -> modify -> write，而不只是写。"""
    target = tmp_path / "counter.json"
    atomic_write_json(target, {"n": 0})
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(25):
                with file_lock(target, timeout=10):
                    data = json.loads(target.read_text(encoding="utf-8"))
                    data["n"] += 1
                    atomic_write_json(target, data)
        except BaseException as exc:  # noqa: BLE001 - 测试记录线程异常
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发写入出现异常: {errors!r}"
    final = json.loads(target.read_text(encoding="utf-8"))["n"]
    assert final == 100, f"丢失更新: n={final}, errors={errors!r}"
