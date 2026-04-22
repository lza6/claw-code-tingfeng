"""Team State Management - 团队状态管理

提供完整的团队状态管理功能:
- 任务状态管理 (tasks)
- 消息队列 (mailbox)
- 分发管理 (dispatch, dispatch_lock)
- 审批管理 (approvals)
- 监控 (monitor)
- 锁管理 (locks)
"""

from __future__ import annotations

__all__ = [
    # 审批管理
    "ApprovalStore",
    # 分发锁
    "DispatchLock",
    "DispatchLockStore",
    # 分发管理
    "DispatchRequest",
    "DispatchStore",
    # 锁管理
    "LockInfo",
    "LockStore",
    # 消息队列
    "MailboxStore",
    # 监控
    "MonitorSnapshot",
    "MonitorStore",
    "TaskApproval",
    # 任务管理
    "TaskStateStore",
    "TeamMessage",
    "TeamSummary",
    "TeamTask",
    "TeamTaskClaim",
    "broadcast_message",
    "can_transition_task_status",
    "claim_task",
    "dispatch",
    "dispatch_lock",
    "enqueue_dispatch_request",
    "get_team_summary",
    "is_terminal_task_status",
    "list_dispatch_requests",
    "list_mailbox_messages",
    "list_pending_approvals",
    "locks",
    "mailbox",
    "mark_dispatch_request_delivered",
    "mark_dispatch_request_notified",
    "monitor",
    "read_dispatch_request",
    "read_monitor_snapshot",
    "read_task_approval",
    "reclaim_expired_task_claims",
    "release_task_claim",
    "send_direct_message",
    "send_task_assign",
    "send_task_result",
    "tasks",
    "transition_dispatch_request",
    "with_dispatch_lock",
    "with_mailbox_lock",
    "with_mailbox_lock_decorator",
    "with_scaling_lock",
    "with_task_claim_lock",
    "with_task_claim_lock_decorator",
    "with_team_lock",
    "write_monitor_snapshot",
    "write_task_approval",
]

# 导入子模块
from . import approvals, dispatch, dispatch_lock, locks, mailbox, monitor, tasks
