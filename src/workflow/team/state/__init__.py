"""团队状态（精简后）—— 以 `team_persistence` 为单入口

2026-10-30（v0.88.6）：此前的 `tasks` / `mailbox` / `dispatch` / `dispatch_lock` /
`approvals` / `monitor` 六个模块（合计 1198 行）与 `src/workflow/team_persistence.py`
语义重叠，且**完全不可达**（`reachability.py` 实测无任何生产调用方）→ 按拍板删除，
团队状态统一由 `team_persistence` 落盘，避免两套账。

只保留 `locks.py`：它是真实的跨进程文件锁（有独立测试 `tests/workflow/test_team_state_locks.py`），
`with_*_lock` 系列在需要串行化团队操作时可直接复用。
"""

from __future__ import annotations

from .locks import (
    LockInfo,
    LockStore,
    with_mailbox_lock,
    with_mailbox_lock_decorator,
    with_scaling_lock,
    with_task_claim_lock,
    with_task_claim_lock_decorator,
    with_team_lock,
)

__all__ = [
    "LockInfo",
    "LockStore",
    "with_mailbox_lock",
    "with_mailbox_lock_decorator",
    "with_scaling_lock",
    "with_task_claim_lock",
    "with_task_claim_lock_decorator",
    "with_team_lock",
]
