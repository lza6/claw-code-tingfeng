"""状态持久化的跨平台与并发回归。

背景：
- `src/core/state_impl.py` 的 `save_snapshot` 曾在函数内 `import fcntl`；
  Windows 上必然 ImportError，导致快照保存永远失败。
- `src/core/state/persistence.py` 的 `append_event` 是读全量 → 追加 → 重写，
  没有锁，并发会丢事件。
"""
from __future__ import annotations

import json
import threading

from src.core.state.persistence import StateManager as PersistenceStateManager
from src.core.state_impl import StateManager as ImplStateManager


class _DummySnapshot:
    def to_json(self, indent: int = 2) -> str:
        return json.dumps({"ok": True}, indent=indent)


def test_state_impl_save_snapshot_works_cross_platform(tmp_path):
    manager = ImplStateManager(tmp_path)
    manager.save_snapshot(_DummySnapshot())

    data = json.loads((tmp_path / "snapshot.json").read_text(encoding="utf-8"))
    assert data["ok"] is True


def test_persistence_append_event_concurrent_no_lost_events(tmp_path):
    manager = PersistenceStateManager(tmp_path)
    errors: list[BaseException] = []

    def worker(tid: int) -> None:
        try:
            for i in range(10):
                manager.append_event({"tid": tid, "i": i})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发追加异常: {errors!r}"
    events = manager.load_events()
    assert len(events) == 40, f"丢失事件: 只有 {len(events)} 条"
