"""生产路径 RunStateManager 的并发回归。

背景：`src/core/persistence/run_state.py` 是生产可达实现（被
`workflow/engine.py`、`status_dashboard.py` 等使用）。它此前：
- `_write_atomic` 使用固定 `<name>.tmp`、无锁、无 fsync；
- `record_evidence_event` 的 JSONL 追加无锁；
- `update_task` 的读改写无锁（OCC 检查与实际写入不在同一临界区）。

本文件直接驱动生产函数验证并发安全。
"""
from __future__ import annotations

import json
import threading

from src.core.persistence.run_state import RunStateManager
from src.workflow.models import WorkflowStatus


def test_update_task_concurrent_no_lost_updates(tmp_path):
    manager = RunStateManager(tmp_path)
    errors: list[BaseException] = []

    def worker(tid: int) -> None:
        try:
            for i in range(5):
                manager.update_task(f"task-{tid}-{i}", WorkflowStatus.RUNNING)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发更新异常: {errors!r}"
    data = manager.load()
    assert data is not None
    task_ids = {task["task_id"] for task in data.get("tasks", [])}
    expected = {f"task-{tid}-{i}" for tid in range(4) for i in range(5)}
    assert expected <= task_ids, f"丢失任务: {sorted(expected - task_ids)}"


def test_record_evidence_event_concurrent_no_lost_lines(tmp_path):
    manager = RunStateManager(tmp_path)
    errors: list[BaseException] = []

    def worker(tid: int) -> None:
        try:
            for i in range(10):
                manager.record_evidence_event(
                    scenario_id=f"s-{tid}-{i}",
                    harness_kind="unit",
                    result={"ok": True},
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发追加异常: {errors!r}"
    lines = [
        line for line in manager.evidence_log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 40, f"丢失事件: 只有 {len(lines)} 行"
    # 每行都必须是合法 JSON（并发交错会破坏行结构）
    for line in lines:
        json.loads(line)
