"""RuntimeEngine 基础单元测试

从 oh-my-codex 的 Rust 测试移植并适配为 Python 版本。
参考: omx-runtime-core/tests/

作者: Kilo Code (整合 oh-my-codex, 2026-04-17)
"""

import tempfile
from pathlib import Path

import pytest

from src.runtime.engine import (
    RuntimeEngine,
    AuthorityLease,
    AuthorityError,
    DispatchLog,
    DispatchStatus,
    NotFoundError,
    InvalidTransitionError,
    DispatchRecord,
    MailboxLog,
    MailboxRecord,
    MailboxError,
    MailboxNotFoundError,
    AlreadyDeliveredError,
    ReplayState,
    BacklogSnapshot,
    RuntimeSnapshot,
    ReadinessSnapshot,
    AuthoritySnapshot,
    AcquireAuthorityCommand,
    QueueDispatchCommand,
    MarkNotifiedCommand,
    MarkDeliveredCommand,
    MarkFailedCommand,
    AuthorityAcquiredEvent,
    DispatchQueuedEvent,
    DispatchNotifiedEvent,
    DispatchDeliveredEvent,
    DispatchFailedEvent,
    MailboxMessageCreatedEvent,
    RUNTIME_SCHEMA_VERSION,
    derive_readiness,
)


# =============================================================================
# AuthorityLease 测试
# =============================================================================

class TestAuthorityLease:
    """权威租赁测试"""

    def test_acquire_and_renew_happy_path(self):
        lease = AuthorityLease()
        assert not lease.is_held()

        lease.acquire("worker-1", "lease-1", "2026-04-18T00:00:00Z")
        assert lease.is_held()
        assert lease.current_owner() == "worker-1"
        assert lease.lease_id == "lease-1"

        # 续期
        lease.renew("worker-1", "lease-2", "2026-04-18T12:00:00Z")
        assert lease.lease_id == "lease-2"

    def test_acquire_fails_if_held_by_other(self):
        lease = AuthorityLease()
        lease.acquire("worker-1", "lease-1", "2026-04-18T00:00:00Z")

        with pytest.raises(AuthorityError, match="lease already held"):
            lease.acquire("worker-2", "lease-2", "2026-04-19T00:00:00Z")

    def test_acquire_succeeds_for_same_owner(self):
        lease = AuthorityLease()
        lease.acquire("worker-1", "lease-1", "2026-04-18T00:00:00Z")
        # 同一owner重新acquire应成功
        lease.acquire("worker-1", "lease-2", "2026-04-18T01:00:00Z")
        assert lease.lease_id == "lease-2"

    def test_renew_fails_if_not_held(self):
        lease = AuthorityLease()
        with pytest.raises(AuthorityError, match="no lease currently held"):
            lease.renew("worker-1", "lease-1", "2026-04-18T00:00:00Z")

    def test_renew_fails_if_owner_mismatch(self):
        lease = AuthorityLease()
        lease.acquire("worker-1", "lease-1", "2026-04-18T00:00:00Z")
        with pytest.raises(AuthorityError, match="owner mismatch"):
            lease.renew("worker-2", "lease-2", "2026-04-18T01:00:00Z")

    def test_force_release_clears_everything(self):
        lease = AuthorityLease()
        lease.acquire("worker-1", "lease-1", "2026-04-18T00:00:00Z")
        lease.mark_stale("timeout")
        assert lease.is_stale()

        lease.force_release()
        assert not lease.is_held()
        assert not lease.is_stale()
        assert lease.current_owner() is None

    def test_stale_marking_and_clearing(self):
        lease = AuthorityLease()
        lease.acquire("worker-1", "lease-1", "2026-04-18T00:00:00Z")

        lease.mark_stale("heartbeat timeout")
        assert lease.is_stale()

        lease.clear_stale()
        assert not lease.is_stale()

    def test_snapshot_reflects_current_state(self):
        lease = AuthorityLease()
        lease.acquire("worker-x", "lease-42", "2026-04-18T00:00:00Z")
        snap = lease.to_snapshot()

        assert snap.owner == "worker-x"
        assert snap.lease_id == "lease-42"
        assert not snap.stale
        assert snap.is_held()


# =============================================================================
# DispatchLog 测试
# =============================================================================

class TestDispatchLog:
    """分派日志测试"""

    def test_queue_and_transition_happy_path(self):
        log = DispatchLog()
        log.queue("req-1", "worker-1", None)
        assert len(log.records()) == 1
        record = log.records()[0]
        assert record.status == DispatchStatus.PENDING

        log.mark_notified("req-1", "tmux")
        assert record.status == DispatchStatus.NOTIFIED
        assert record.notified_at is not None

        log.mark_delivered("req-1")
        assert record.status == DispatchStatus.DELIVERED
        assert record.delivered_at is not None

    def test_mark_failed_from_notified(self):
        log = DispatchLog()
        log.queue("req-1", "worker-1", None)
        log.mark_notified("req-1", "tmux")
        log.mark_failed("req-1", "execution error")
        record = log.records()[0]
        assert record.status == DispatchStatus.FAILED
        assert record.reason == "execution error"

    def test_mark_failed_from_pending(self):
        log = DispatchLog()
        log.queue("req-1", "worker-1", None)
        log.mark_failed("req-1", "target resolution failed")
        record = log.records()[0]
        assert record.status == DispatchStatus.FAILED

    def test_invalid_transition_errors(self):
        log = DispatchLog()
        log.queue("req-1", "worker-1", None)

        # Pending -> Delivered 是非法的
        with pytest.raises(InvalidTransitionError):
            log.mark_delivered("req-1")

        # Delivered -> Failed 是非法的
        log.mark_notified("req-1", "tmux")
        log.mark_delivered("req-1")
        with pytest.raises(InvalidTransitionError):
            log.mark_failed("req-1", "already done")

    def test_not_found_errors(self):
        log = DispatchLog()
        with pytest.raises(NotFoundError):
            log.mark_notified("nonexistent", "tmux")

    def test_backlog_snapshot_counts(self):
        log = DispatchLog()
        log.queue("req-1", "w1", None)
        log.queue("req-2", "w2", None)
        log.queue("req-3", "w3", None)

        log.mark_notified("req-2", "tmux")
        log.mark_notified("req-3", "tmux")
        log.mark_delivered("req-2")
        log.mark_failed("req-3", "error")

        snap = log.to_backlog_snapshot()
        assert snap.pending == 1
        assert snap.notified == 0
        assert snap.delivered == 1
        assert snap.failed == 1

    def test_queue_with_metadata_round_trips(self):
        log = DispatchLog()
        meta = {"priority": "high", "tags": ["urgent"]}
        log.queue("req-meta", "worker-1", meta)

        record = log.records()[0]
        assert record.metadata == meta

    def test_compact_removes_terminal_records(self):
        log = DispatchLog()
        log.queue("req-pending", "w1", None)
        log.queue("req-delivered", "w2", None)
        log.queue("req-failed", "w3", None)

        log.mark_notified("req-delivered", "tmux")
        log.mark_delivered("req-delivered")

        log.mark_notified("req-failed", "tmux")
        log.mark_failed("req-failed", "timeout")

        assert len(log.records()) == 3
        log.compact()
        # 只保留 pending 记录
        assert len(log.records()) == 1
        assert log.records()[0].request_id == "req-pending"

    def test_getters(self):
        log = DispatchLog()
        log.queue("req-p1", "w1", None)
        log.queue("req-p2", "w2", None)

        pending = log.get_pending()
        assert len(pending) == 2

        log.mark_notified("req-p1", "tmux")
        notified = log.get_notified()
        assert len(notified) == 1


# =============================================================================
# BacklogSnapshot 测试
# =============================================================================

class TestBacklogSnapshot:
    def test_str_representation(self):
        snap = BacklogSnapshot(pending=1, notified=2, delivered=3, failed=4)
        s = str(snap)
        assert "pending=1" in s
        assert "notified=2" in s
        assert "delivered=3" in s
        assert "failed=4" in s

    def test_total_active(self):
        snap = BacklogSnapshot(pending=5, notified=3)
        assert snap.total_active() == 8

    def test_completion_rate(self):
        snap = BacklogSnapshot(pending=2, notified=1, delivered=8, failed=4)
        rate = snap.completion_rate()
        assert rate == pytest.approx(0.8, 0.01)


# =============================================================================
# MailboxLog 测试
# =============================================================================

class TestMailboxLog:
    """邮箱测试"""

    def test_create_and_lifecycle(self):
        mb = MailboxLog()
        mb.create("msg-1", "from-worker", "to-worker", "task payload")

        record = mb.records()[0]
        assert record.message_id == "msg-1"
        assert record.from_worker == "from-worker"
        assert record.to_worker == "to-worker"
        assert record.body == "task payload"
        assert record.created_at is not None
        assert record.notified_at is None
        assert record.delivered_at is None

        mb.mark_notified("msg-1")
        record = mb.get_message("msg-1")
        assert record.notified_at is not None

        mb.mark_delivered("msg-1")
        assert record.delivered_at is not None
        assert record.is_delivered()

    def test_mark_notified_twice_fails(self):
        mb = MailboxLog()
        mb.create("msg-1", "a", "b", "body")
        mb.mark_notified("msg-1")  # OK
        mb.mark_delivered("msg-1")

        # 再次标记 notified （已delivered应报错）
        with pytest.raises(AlreadyDeliveredError):
            mb.mark_notified("msg-1")

    def test_mark_delivered_twice_fails(self):
        mb = MailboxLog()
        mb.create("msg-1", "a", "b", "body")
        mb.mark_delivered("msg-1")
        with pytest.raises(AlreadyDeliveredError):
            mb.mark_delivered("msg-1")

    def test_not_found(self):
        mb = MailboxLog()
        with pytest.raises(MailboxNotFoundError):
            mb.mark_notified("missing")

    def test_get_undelivered(self):
        mb = MailboxLog()
        mb.create("msg-1", "a", "b", "body")
        mb.create("msg-2", "a", "b", "body")
        mb.mark_delivered("msg-1")

        undelivered = mb.get_undelivered()
        assert len(undelivered) == 1
        assert undelivered[0].message_id == "msg-2"

    def test_get_pending_for_worker(self):
        mb = MailboxLog()
        mb.create("msg-1", "orchestrator", "worker-a", "task A")
        mb.create("msg-2", "orchestrator", "worker-b", "task B")
        mb.create("msg-3", "orchestrator", "worker-a", "task C")

        pending_a = mb.get_pending_for("worker-a")
        assert len(pending_a) == 2

        mb.mark_delivered("msg-1")
        pending_a = mb.get_pending_for("worker-a")
        assert len(pending_a) == 1

    def test_serialization_round_trip(self):
        mb = MailboxLog()
        mb.create("msg-1", "a", "b", "payload")
        mb.mark_notified("msg-1")

        import json
        data = json.dumps([r.__dict__ for r in mb.records()])
        loaded = json.loads(data)

        assert len(loaded) == 1
        assert loaded[0]["message_id"] == "msg-1"
        assert loaded[0]["notified_at"] is not None


# =============================================================================
# RuntimeEngine 集成测试
# =============================================================================

class TestRuntimeEngine:
    """运行时引擎集成测试"""

    def test_process_acquire_authority(self):
        """测试获取权威租赁"""
        engine = RuntimeEngine.new()
        event = engine.process(AcquireAuthorityCommand(
            owner="w1",
            lease_id="l1",
            leased_until="2026-04-18T00:00:00Z"
        ))
        assert isinstance(event, AuthorityAcquiredEvent)
        assert engine.authority.is_held()
        assert engine.authority.current_owner() == "w1"
        assert len(engine.get_event_log()) == 1

    def test_process_full_dispatch_cycle(self):
        """测试完整分派周期"""
        engine = RuntimeEngine.new()
        engine.process(AcquireAuthorityCommand("w1", "l1", "2026-04-18T00:00:00Z"))

        # Queue -> Notify -> Delivered
        engine.process(QueueDispatchCommand(request_id="req-1", target="worker-2"))
        assert engine.dispatch.records()[0].status == DispatchStatus.PENDING

        ev_notified = engine.process(MarkNotifiedCommand(request_id="req-1", channel="tmux"))
        assert isinstance(ev_notified, DispatchNotifiedEvent)
        record = engine.dispatch.records()[0]
        assert record.status == DispatchStatus.NOTIFIED

        ev_delivered = engine.process(MarkDeliveredCommand(request_id="req-1"))
        assert isinstance(ev_delivered, DispatchDeliveredEvent)
        assert record.status == DispatchStatus.DELIVERED

    def test_snapshot_shows_blocked_without_authority(self):
        engine = RuntimeEngine.new()
        snap = engine.snapshot()
        assert not snap.ready()
        assert "authority lease not acquired" in snap.readiness.reasons

    def test_snapshot_shows_ready(self):
        engine = RuntimeEngine.new()
        engine.process(AcquireAuthorityCommand("w1", "l1", "2026-04-18T00:00:00Z"))
        snap = engine.snapshot()
        assert snap.ready()
        assert snap.backlog.pending == 0

    def test_derive_readiness_stale_authority(self):
        lease = AuthorityLease()
        lease.acquire("w1", "l1", "2026-04-18T00:00:00Z")
        lease.mark_stale("lease expired")

        dispatch = DispatchLog()
        replay = ReplayState()

        readiness = derive_readiness(lease, dispatch, replay)
        assert not readiness.ready
        assert any("stale" in r for r in readiness.reasons)

    def test_mark_failed_dispatch(self):
        engine = RuntimeEngine.new()
        engine.process(AcquireAuthorityCommand("w1", "l1", "2026-04-18T00:00:00Z"))
        engine.process(QueueDispatchCommand(request_id="req-1", target="worker-2"))

        ev_failed = engine.process(MarkFailedCommand(request_id="req-1", reason="timeout"))
        assert isinstance(ev_failed, DispatchFailedEvent)
        snapshot = engine.snapshot()
        assert snapshot.backlog.failed == 1

    def test_queue_dispatch_with_metadata(self):
        engine = RuntimeEngine.new()
        meta = {"priority": "high", "worker_type": "codex"}
        engine.process(QueueDispatchCommand(request_id="req-meta", target="worker-3", metadata=meta))

        event = engine.event_log[0]
        assert isinstance(event, DispatchQueuedEvent)
        assert event.metadata == meta

    def test_compact_removes_delivered_and_failed(self):
        engine = RuntimeEngine.new()
        engine.process(AcquireAuthorityCommand("w1", "l1", "2026-04-18T00:00:00Z"))

        # 多个分派
        engine.process(QueueDispatchCommand(request_id="req-pending", target="w1"))
        engine.process(QueueDispatchCommand(request_id="req-delivered", target="w2"))
        engine.process(QueueDispatchCommand(request_id="req-failed", target="w3"))

        # 标记 delivered
        engine.process(MarkNotifiedCommand(request_id="req-delivered", channel="tmux"))
        engine.process(MarkDeliveredCommand(request_id="req-delivered"))

        # 标记 failed
        engine.process(MarkNotifiedCommand(request_id="req-failed", channel="tmux"))
        engine.process(MarkFailedCommand(request_id="req-failed", reason="timeout"))

        assert len(engine.event_log) == 7
        engine.compact()

        # 只保留 pending 的 queued 事件
        remaining = [e for e in engine.event_log if isinstance(e, DispatchQueuedEvent)]
        assert len(remaining) == 1
        assert remaining[0].request_id == "req-pending"

    def test_persist_and_load_round_trip(self):
        """测试持久化和恢复"""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "runtime_state"
            # 初始状态
            engine = RuntimeEngine.with_state_dir(state_dir)
            engine.process(AcquireAuthorityCommand("w1", "l1", "2026-04-18T00:00:00Z"))
            engine.process(QueueDispatchCommand(request_id="req-1", target="worker-2"))
            engine.process(MarkNotifiedCommand(request_id="req-1", channel="tmux"))
            engine.persist()

            # 清理内存状态
            engine = None

            # 重新加载
            loaded = RuntimeEngine.load(state_dir)
            assert loaded.authority.current_owner() == "w1"
            assert len(loaded.dispatch.records()) == 1
            assert len(loaded.get_event_log()) == 3

    def test_write_compatibility_view(self):
        """测试兼容性视图文件写入"""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "runtime_state"
            engine = RuntimeEngine.with_state_dir(state_dir)
            engine.process(AcquireAuthorityCommand("w1", "l1", "2026-04-18T00:00:00Z"))
            engine.write_compatibility_view()

            files_expected = [
                "authority.json",
                "backlog.json",
                "readiness.json",
                "replay.json",
                "dispatch.json",
                "mailbox.json",
            ]
            for fname in files_expected:
                assert (state_dir / fname).exists(), f"{fname} missing"


# =============================================================================
# ReplayState 测试
# =============================================================================

class TestReplayState:
    def test_new_has_zero_pending(self):
        state = ReplayState.new()
        assert state.pending_events == 0

    def test_queue_and_mark_replayed(self):
        state = ReplayState.new()
        state.queue_event()
        assert state.pending_events == 1

        state.mark_replayed("evt-1")
        assert state.pending_events == 0
        assert state.last_replayed_event_id == "evt-1"

    def test_defer_leader_notification(self):
        state = ReplayState.new()
        state.defer_leader_notification()
        assert state.deferred_leader_notification
        state.clear_deferred_leader_notification()
        assert not state.deferred_leader_notification


# =============================================================================
# 辅助函数测试
# =============================================================================

class TestHelperFunctions:
    def test_schema_version(self):
        assert RUNTIME_SCHEMA_VERSION == 1

    def test_derive_readiness_without_authority(self):
        lease = AuthorityLease()
        dispatch = DispatchLog()
        replay = ReplayState()
        readiness = derive_readiness(lease, dispatch, replay)
        assert not readiness.ready
        assert "authority lease not acquired" in readiness.reasons

    def test_derive_readiness_with_stale(self):
        lease = AuthorityLease()
        lease.acquire("w1", "l1", "2026-04-18T00:00:00Z")
        lease.mark_stale("expired")
        dispatch = DispatchLog()
        replay = ReplayState()
        readiness = derive_readiness(lease, dispatch, replay)
        assert not readiness.ready
        assert any("stale" in r for r in readiness.reasons)
