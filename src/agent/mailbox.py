"""Mailbox 消息传递系统

汲取 oh-my-codex-main/crates/omx-runtime-core/src/mailbox.rs

提供可靠的跨 Worker 消息传递与确认机制，生命周期：
    created → notified → delivered

作者: Kilo Code (整合 oh-my-codex 设计, 2026-04-17)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


# =============================================================================
# Errors
# =============================================================================

class MailboxError(Exception):
    """邮箱操作基类错误"""
    pass


class MailboxNotFoundError(MailboxError):
    """消息未找到错误"""
    def __init__(self, message_id: str):
        super().__init__(f"mailbox record not found: {message_id!r}")
        self.message_id = message_id


class AlreadyDeliveredError(MailboxError):
    """消息已被投递错误"""
    def __init__(self, message_id: str):
        super().__init__(f"mailbox message already delivered: {message_id!r}")
        self.message_id = message_id


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class MailboxRecord:
    """邮箱记录 — 跨 Worker 的消息传递

    属性:
        message_id: 消息唯一标识
        from_worker: 发件人 Worker ID
        to_worker: 收件人 Worker ID
        body: 消息内容
        created_at: 创建时间(ISO)
        notified_at: 通知确认时间（收件人已收到）
        delivered_at: 投递完成时间（收件人已处理）
    """
    message_id: str
    from_worker: str
    to_worker: str
    body: str
    created_at: str
    notified_at: str | None = None
    delivered_at: str | None = None

    def is_delivered(self) -> bool:
        """是否已投递"""
        return self.delivered_at is not None


# =============================================================================
# MailboxLog
# =============================================================================

class MailboxLog:
    """消息邮箱日志 — 可靠的消息传递与确认

    职责:
        - 记录 Worker 间的消息传递
        - 跟踪通知确认（notified）
        - 跟踪投递确认（delivered）
        - 支持消息持久化和恢复

    生命周期:
        created ──(mark_notified)──> notified ──(mark_delivered)──> delivered
                   (or timeout)       (or error)

    用途:
        - Orchestrator -> Worker 的任务分发确认
        - Worker -> Worker 的异步消息
        - 结果回传确认

    使用示例:
        >>> mailbox = MailboxLog()
        >>> mailbox.create("msg-1", "orchestrator", "worker-1", "task: fix-bug-123")
        >>> mailbox.mark_notified("msg-1")
        >>> mailbox.mark_delivered("msg-1")
    """

    def __init__(self) -> None:
        self._records: list[MailboxRecord] = []

    @classmethod
    def new(cls) -> MailboxLog:
        """创建新的邮箱"""
        return cls()

    # ==================== 写入操作 ====================

    def create(
        self,
        message_id: str,
        from_worker: str,
        to_worker: str,
        body: str,
    ) -> None:
        """创建一条新消息

        Args:
            message_id: 消息唯一标识
            from_worker: 发件人 Worker ID（通常是 Orchestrator）
            to_worker: 收件人 Worker ID
            body: 消息内容（任务描述、结果数据等）

        注意：
        - Caller 需保证 message_id 唯一
        - body 可能很大，建议仅传元数据引用
        """
        self._records.append(MailboxRecord(
            message_id=message_id,
            from_worker=from_worker,
            to_worker=to_worker,
            body=body,
            created_at=_now_iso(),
        ))
        logger.debug(f"[Mailbox] created: {message_id} {from_worker} -> {to_worker}")

    def mark_notified(self, message_id: str) -> None:
        """标记消息已通知（收件人已收到消息）

        Args:
            message_id: 消息ID

        状态转换: (new) -> notified
        Raises:
            MailboxNotFoundError: 消息不存在
            AlreadyDeliveredError: 消息已投递（不应重复通知）
        """
        record = self._find_mut(message_id)
        if record.delivered_at is not None:
            raise AlreadyDeliveredError(message_id)
        record.notified_at = _now_iso()
        logger.debug(f"[Mailbox] notified: {message_id}")

    def mark_delivered(self, message_id: str) -> None:
        """标记消息已投递（收件人已处理完成）

        Args:
            message_id: 消息ID

        状态转换: notified -> delivered
        Raises:
            MailboxNotFoundError: 消息不存在
            AlreadyDeliveredError: 消息已投递（幂等）
        """
        record = self._find_mut(message_id)
        if record.delivered_at is not None:
            raise AlreadyDeliveredError(message_id)
        record.delivered_at = _now_iso()
        logger.debug(f"[Mailbox] delivered: {message_id}")

    # ==================== 查询操作 ====================

    def records(self) -> list[MailboxRecord]:
        """获取所有记录副本"""
        return list(self._records)

    def get_message(self, message_id: str) -> MailboxRecord | None:
        """根据ID查找消息"""
        for record in self._records:
            if record.message_id == message_id:
                return record
        return None

    def get_undelivered(self) -> list[MailboxRecord]:
        """获取所有未投递消息（包括新建和已通知）"""
        return [r for r in self._records if r.delivered_at is None]

    def get_pending_for(self, worker_id: str) -> list[MailboxRecord]:
        """获取指定 Worker 的待处理消息"""
        return [
            r for r in self._records
            if r.to_worker == worker_id and r.delivered_at is None
        ]

    def get_delivered(self) -> list[MailboxRecord]:
        """获取所有已投递消息"""
        return [r for r in self._records if r.delivered_at is not None]

    # ==================== 维护操作 ====================

    def compact(self) -> None:
        """压缩日志 — 清理已投递记录"""
        original_len = len(self._records)
        self._records = [
            r for r in self._records
            if r.delivered_at is None
        ]
        removed = original_len - len(self._records)
        if removed > 0:
            logger.info(f"[Mailbox] compacted: removed {removed} delivered records")

    def clear(self) -> None:
        """清空所有记录（测试用）"""
        self._records.clear()

    # ==================== 私有工具 ====================

    def _find_mut(self, message_id: str) -> MailboxRecord:
        """查找并返回可变记录引用"""
        for record in self._records:
            if record.message_id == message_id:
                return record
        raise MailboxNotFoundError(message_id)


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
    # Errors
    "AlreadyDeliveredError",
    "MailboxError",
    # Models
    "MailboxLog",
    "MailboxNotFoundError",
    "MailboxRecord",
]
