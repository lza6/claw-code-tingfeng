"""任务分派日志 (Dispatch Log)

汲取 oh-my-codex-main/crates/omx-runtime-core/src/dispatch.rs

提供任务分派的状态跟踪和审计功能，状态机：
    PENDING ──(mark_notified)──> NOTIFIED ──(mark_delivered)──> DELIVERED
       │                                │
       └────────(mark_failed)──────────┘

作者: Kilo Code (整合 oh-my-codex 设计, 2026-04-17)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# Enums & Errors
# =============================================================================

class DispatchStatus(Enum):
    """分派状态枚举"""
    PENDING = "pending"
    NOTIFIED = "notified"
    DELIVERED = "delivered"
    FAILED = "failed"

    def __str__(self) -> str:
        return self.value


class DispatchError(Exception):
    """分派操作基类错误"""
    pass


class NotFoundError(DispatchError):
    """记录未找到错误"""
    def __init__(self, request_id: str):
        super().__init__(f"dispatch record not found: {request_id!r}")
        self.request_id = request_id


class InvalidTransitionError(DispatchError):
    """无效状态转换错误"""
    def __init__(self, request_id: str, from_status: str, to_status: str):
        super().__init__(
            f"invalid transition for {request_id!r}: {from_status!r} -> {to_status!r}"
        )
        self.request_id = request_id
        self.from_status = from_status
        self.to_status = to_status


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class DispatchRecord:
    """分派记录 — 跟踪一个任务的完整流转

    属性:
        request_id: 请求唯一标识
        target: 目标 worker/agent
        status: 当前状态
        created_at: 创建时间(ISO)
        notified_at: 通知确认时间
        delivered_at: 交付完成时间
        failed_at: 失败时间
        reason: 失败原因或确认渠道
        metadata: 附加元数据（优先级、标签等）
    """
    request_id: str
    target: str
    status: DispatchStatus
    created_at: str
    notified_at: str | None = None
    delivered_at: str | None = None
    failed_at: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] | None = None

    def can_transition_to(self, new_status: DispatchStatus) -> bool:
        """检查是否允许转换到目标状态"""
        transitions = {
            DispatchStatus.PENDING: [DispatchStatus.NOTIFIED, DispatchStatus.FAILED],
            DispatchStatus.NOTIFIED: [DispatchStatus.DELIVERED, DispatchStatus.FAILED],
            DispatchStatus.DELIVERED: [],
            DispatchStatus.FAILED: [],
        }
        return new_status in transitions.get(self.status, [])

    def is_terminal(self) -> bool:
        """是否已达终端状态（不再允许转换）"""
        return self.status in (DispatchStatus.DELIVERED, DispatchStatus.FAILED)


# =============================================================================
# DispatchLog (主类)
# =============================================================================

class DispatchLog:
    """任务分派日志 — 维护任务分派的完整 audit trail

    职责:
        - 记录任务分派从创建到完成/失败的全生命周期
        - 提供状态机验证（防止非法转换）
        - 生成待办快照供监控面板使用
        - 支持日志压缩清理

    状态机:
        PENDING ──(mark_notified)──> NOTIFIED ──(mark_delivered)──> DELIVERED
           │                                │
           └────────(mark_failed)──────────┘

    使用示例:
        >>> log = DispatchLog()
        >>> log.queue("req-1", "worker-1", {"priority": "high"})
        >>> log.mark_notified("req-1", "tmux")
        >>> log.mark_delivered("req-1")
        >>> snap = log.to_backlog_snapshot()
    """

    def __init__(self) -> None:
        self._records: list[DispatchRecord] = []

    @classmethod
    def new(cls) -> DispatchLog:
        """创建新的分派日志"""
        return cls()

    # ==================== 写入操作 ====================

    def queue(
        self,
        request_id: str,
        target: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """入队一个新分派请求

        Args:
            request_id: 请求唯一标识（ caller 生成）
            target: 目标 worker/agent ID
            metadata: 附加元数据（优先级、标签、超时等）

        幂等性：多次调用 queue 相同 request_id 会创建重复记录（需 caller 保证唯一性）
        """
        self._records.append(DispatchRecord(
            request_id=request_id,
            target=target,
            status=DispatchStatus.PENDING,
            created_at=_now_iso(),
            metadata=metadata,
        ))
        logger.debug(f"[Dispatch] queued: {request_id} -> {target}")

    def mark_notified(self, request_id: str, channel: str) -> None:
        """标记为已通知（worker 已收到消息）

        Args:
            request_id: 请求ID
            channel: 通知渠道（tmux、websocket、direct 等）

        状态转换: PENDING -> NOTIFIED
        """
        record = self._find_mut(request_id)
        if record.status != DispatchStatus.PENDING:
            raise InvalidTransitionError(
                request_id, record.status.value, DispatchStatus.NOTIFIED.value
            )
        record.status = DispatchStatus.NOTIFIED
        record.notified_at = _now_iso()
        record.reason = channel
        logger.debug(f"[Dispatch] notified: {request_id} via {channel}")

    def mark_delivered(self, request_id: str) -> None:
        """标记为已交付（worker 完成处理）

        Args:
            request_id: 请求ID

        状态转换: NOTIFIED -> DELIVERED
        """
        record = self._find_mut(request_id)
        if record.status != DispatchStatus.NOTIFIED:
            raise InvalidTransitionError(
                request_id, record.status.value, DispatchStatus.DELIVERED.value
            )
        record.status = DispatchStatus.DELIVERED
        record.delivered_at = _now_iso()
        logger.debug(f"[Dispatch] delivered: {request_id}")

    def mark_failed(self, request_id: str, reason: str) -> None:
        """标记为失败

        Args:
            request_id: 请求ID
            reason: 失败原因（简短描述）

        状态转换:
            PENDING -> FAILED (目标解析失败等)
            NOTIFIED -> FAILED (执行过程中失败)
        """
        record = self._find_mut(request_id)
        if record.status not in (DispatchStatus.PENDING, DispatchStatus.NOTIFIED):
            raise InvalidTransitionError(
                request_id, record.status.value, DispatchStatus.FAILED.value
            )
        record.status = DispatchStatus.FAILED
        record.failed_at = _now_iso()
        record.reason = reason
        logger.debug(f"[Dispatch] failed: {request_id} - {reason}")

    # ==================== 查询操作 ====================

    def records(self) -> list[DispatchRecord]:
        """获取所有记录的副本"""
        return list(self._records)

    def get_record(self, request_id: str) -> DispatchRecord | None:
        """根据请求ID查找记录"""
        for record in self._records:
            if record.request_id == request_id:
                return record
        return None

    def get_pending(self) -> list[DispatchRecord]:
        """获取所有待处理记录（PENDING 状态）"""
        return [r for r in self._records if r.status == DispatchStatus.PENDING]

    def get_notified(self) -> list[DispatchRecord]:
        """获取所有已通知未交付记录（NOTIFIED 状态）"""
        return [r for r in self._records if r.status == DispatchStatus.NOTIFIED]

    def get_delivered(self) -> list[DispatchRecord]:
        """获取所有已交付记录"""
        return [r for r in self._records if r.status == DispatchStatus.DELIVERED]

    def get_failed(self) -> list[DispatchRecord]:
        """获取所有失败记录"""
        return [r for r in self._records if r.status == DispatchStatus.FAILED]

    def to_backlog_snapshot(self) -> BacklogSnapshot:
        """生成待办快照 — 用于仪表板、HUD 显示

        Returns:
            包含各状态计数器的快照
        """
        snap = BacklogSnapshot()
        for record in self._records:
            if record.status == DispatchStatus.PENDING:
                snap.pending += 1
            elif record.status == DispatchStatus.NOTIFIED:
                snap.notified += 1
            elif record.status == DispatchStatus.DELIVERED:
                snap.delivered += 1
            elif record.status == DispatchStatus.FAILED:
                snap.failed += 1
        return snap

    # ==================== 维护操作 ====================

    def compact(self, keep_pending: bool = True) -> None:
        """压缩日志 — 清理已达终端状态的记录

        Args:
            keep_pending: 是否保持 PENDING 状态记录（通常为 True，
                         只有那些已经完成或失败的任务才会被清理）

        清理策略：
            - 移除所有 DELIVERED 记录
            - 移除所有 FAILED 记录
            - 可选的保留 PENDING 记录
            - NOTIFIED 记录保留（除非后续实现更智能的清理策略）
        """
        terminal_statuses = {DispatchStatus.DELIVERED, DispatchStatus.FAILED}
        original_len = len(self._records)

        if keep_pending:
            self._records = [
                r for r in self._records
                if r.status not in terminal_statuses
            ]
        else:
            # 极端模式：只保留 PENDING 和 NOTIFIED
            self._records = [
                r for r in self._records
                if r.status in (DispatchStatus.PENDING, DispatchStatus.NOTIFIED)
            ]

        removed = original_len - len(self._records)
        if removed > 0:
            logger.info(f"[Dispatch] compacted: removed {removed} terminal records")

    def clear(self) -> None:
        """清空所有记录（测试用）"""
        self._records.clear()

    # ==================== 私有工具 ====================

    def _find_mut(self, request_id: str) -> DispatchRecord:
        """查找并返回可变记录引用"""
        for record in self._records:
            if record.request_id == request_id:
                return record
        raise NotFoundError(request_id)


# =============================================================================
# BacklogSnapshot (待办快照)
# =============================================================================

@dataclass
class BacklogSnapshot:
    """待办快照—各类状态计数器的不可变视图"""
    pending: int = 0
    notified: int = 0
    delivered: int = 0
    failed: int = 0

    def __str__(self) -> str:
        return (
            f"pending={self.pending} notified={self.notified} "
            f"delivered={self.delivered} failed={self.failed}"
        )

    def total_active(self) -> int:
        """获取活跃（未完成）任务数"""
        return self.pending + self.notified

    def completion_rate(self) -> float:
        """计算完成率（已交付任务占比）"""
        total = self.pending + self.notified + self.delivered + self.failed
        if total == 0:
            return 0.0
        return self.delivered / total


# =============================================================================
# 辅助函数
# =============================================================================

def _now_iso() -> str:
    """当前时间的 ISO 8601 格式（毫秒精度）"""
    return datetime.now().isoformat(timespec="milliseconds") + "Z"


# =============================================================================
# 导出
# =============================================================================

__all__ = [
    # Models
    "BacklogSnapshot",
    # Errors
    "DispatchError",
    "DispatchLog",
    "DispatchRecord",
    # Enums
    "DispatchStatus",
    "InvalidTransitionError",
    "NotFoundError",
]
