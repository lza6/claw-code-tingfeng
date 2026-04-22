"""
Mailbox 消息系统

借鉴 oh-my-codex-main/crates/omx-runtime-core/src/mailbox.rs
提供 Worker 之间的可靠异步消息传递，追踪消息生命周期。
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class MailboxRecord:
    """邮件记录（对标 Rust MailboxRecord）"""
    message_id: str
    from_worker: str
    to_worker: str
    body: str
    created_at: str
    notified_at: str | None = None
    delivered_at: str | None = None


class MailboxError(Exception):
    """邮件错误基类"""
    pass


class MailboxNotFoundError(MailboxError):
    """消息未找到"""

    def __init__(self, message_id: str):
        super().__init__(f"mailbox record not found: {message_id}")
        self.message_id = message_id


class MailboxAlreadyDeliveredError(MailboxError):
    """消息已被投递"""

    def __init__(self, message_id: str):
        super().__init__(f"mailbox message already delivered: {message_id}")
        self.message_id = message_id


@dataclass
class MailboxLog:
    """邮件日志（对标 Rust MailboxLog）"""
    records: list[MailboxRecord] = field(default_factory=list)

    def create(
        self,
        message_id: str,
        from_worker: str,
        to_worker: str,
        body: str,
    ) -> None:
        """创建新消息"""
        self.records.append(MailboxRecord(
            message_id=message_id,
            from_worker=from_worker,
            to_worker=to_worker,
            body=body,
            created_at=_now_iso(),
        ))

    def mark_notified(self, message_id: str) -> None:
        """
        标记消息已通知（worker 已接收）
        对应 Rust: mark_notified
        """
        record = self._find_mut(message_id)
        if record.delivered_at is not None:
            raise MailboxAlreadyDeliveredError(message_id)
        record.notified_at = _now_iso()

    def mark_delivered(self, message_id: str) -> None:
        """
        标记消息已投递（worker 已处理）
        对应 Rust: mark_delivered
        """
        record = self._find_mut(message_id)
        if record.delivered_at is not None:
            raise MailboxAlreadyDeliveredError(message_id)
        record.delivered_at = _now_iso()

    def records(self) -> list[MailboxRecord]:
        """获取所有记录（只读）"""
        return self.records.copy()

    def get_by_id(self, message_id: str) -> MailboxRecord | None:
        """根据 ID 查找记录"""
        for record in self.records:
            if record.message_id == message_id:
                return record
        return None

    def _find_mut(self, message_id: str) -> MailboxRecord:
        """查找可修改的记录（内部方法）"""
        for record in self.records:
            if record.message_id == message_id:
                return record
        raise MailboxNotFoundError(message_id)

    def to_snapshot(self) -> dict:
        """转换为快照字典（用于序列化）"""
        return {
            "records": [
                {
                    "message_id": r.message_id,
                    "from_worker": r.from_worker,
                    "to_worker": r.to_worker,
                    "body": r.body,
                    "created_at": r.created_at,
                    "notified_at": r.notified_at,
                    "delivered_at": r.delivered_at,
                }
                for r in self.records
            ]
        }

    @classmethod
    def from_snapshot(cls, data: dict) -> "MailboxLog":
        """从快照字典重建"""
        log = cls()
        for record_data in data.get("records", []):
            log.records.append(MailboxRecord(
                message_id=record_data["message_id"],
                from_worker=record_data["from_worker"],
                to_worker=record_data["to_worker"],
                body=record_data["body"],
                created_at=record_data["created_at"],
                notified_at=record_data.get("notified_at"),
                delivered_at=record_data.get("delivered_at"),
            ))
        return log


def _now_iso() -> str:
    """生成当前 ISO 8601 时间戳（UTC）"""
    return datetime.now(timezone.utc).isoformat()


# ===== 测试 =====

if __name__ == "__main__":
    # 简单测试
    log = MailboxLog()
    log.create("msg-1", "worker-a", "worker-b", "hello")
    assert len(log.records()) == 1
    r = log.records()[0]
    assert r.message_id == "msg-1"
    assert r.notified_at is None

    log.mark_notified("msg-1")
    assert log.records()[0].notified_at is not None

    log.mark_delivered("msg-1")
    assert log.records()[0].delivered_at is not None

    # 快照测试
    snapshot = log.to_snapshot()
    restored = MailboxLog.from_snapshot(snapshot)
    assert len(restored.records()) == 1

    print("[Mailbox] 基本测试通过")
