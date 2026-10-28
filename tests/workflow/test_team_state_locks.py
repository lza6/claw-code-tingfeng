"""团队锁行为测试。

覆盖 ``src/workflow/team/state/locks.py`` 的真实行为：
锁获取/续租/释放、超时接管、损坏文件隔离、上下文管理器与装饰器的持有边界。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.workflow.team.state.locks import (
    LockInfo,
    LockStore,
    with_mailbox_lock,
    with_mailbox_lock_decorator,
    with_scaling_lock,
    with_task_claim_lock,
    with_task_claim_lock_decorator,
    with_team_lock,
)


@pytest.fixture
def state_dir(tmp_path):
    return tmp_path / "state"


@pytest.fixture
def store(state_dir):
    return LockStore(state_dir, "team")


def _write_lock(store: LockStore, lock_id: str, *, owner: str, offset_seconds: float) -> Path:
    """直接写入一条锁记录，offset_seconds < 0 表示已过期。"""
    now = datetime.now()
    lock = LockInfo(
        lock_id=lock_id,
        owner=owner,
        acquired_at=now + timedelta(seconds=offset_seconds),
        expires_at=now + timedelta(seconds=offset_seconds + 30),
    )
    path = store._lock_path(lock_id)
    path.write_text(json.dumps(lock.to_dict()), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# LockInfo
# --------------------------------------------------------------------------


def test_lock_info_expiry_boundary():
    now = datetime.now()
    expired = LockInfo("l", "o", now - timedelta(seconds=10), now - timedelta(seconds=1))
    alive = LockInfo("l", "o", now, now + timedelta(seconds=10))

    assert expired.is_expired() is True
    assert alive.is_expired() is False


def test_lock_info_roundtrip_preserves_fields():
    now = datetime.now().replace(microsecond=0)
    original = LockInfo("l1", "owner-a", now, now + timedelta(seconds=30), {"reason": "test"})

    restored = LockInfo.from_dict(original.to_dict())

    assert restored.lock_id == "l1"
    assert restored.owner == "owner-a"
    assert restored.acquired_at == now
    assert restored.expires_at == now + timedelta(seconds=30)
    assert restored.metadata == {"reason": "test"}


def test_lock_info_roundtrip_defaults_metadata():
    now = datetime.now()
    data = LockInfo("l1", "o", now, now + timedelta(seconds=1)).to_dict()
    del data["metadata"]

    assert LockInfo.from_dict(data).metadata == {}


# --------------------------------------------------------------------------
# LockStore 目录与文件布局
# --------------------------------------------------------------------------


def test_lock_store_creates_type_specific_directory(state_dir):
    LockStore(state_dir, "team")
    LockStore(state_dir, "mailbox")

    assert (state_dir / "team_locks").is_dir()
    assert (state_dir / "mailbox_locks").is_dir()


def test_lock_path_uses_json_suffix(store):
    assert store._lock_path("abc").name == "abc.json"


# --------------------------------------------------------------------------
# acquire / renew / release / get
# --------------------------------------------------------------------------


def test_acquire_writes_lock_owned_by_caller(store):
    lock = store.acquire("team_x", "owner-1", ttl_seconds=45)

    assert lock is not None
    assert (lock.lock_id, lock.owner) == ("team_x", "owner-1")
    assert lock.is_expired() is False
    ttl = (lock.expires_at - lock.acquired_at).total_seconds()
    assert ttl == pytest.approx(45, abs=1)

    on_disk = json.loads(store._lock_path("team_x").read_text(encoding="utf-8"))
    assert on_disk["owner"] == "owner-1"


def test_acquire_returns_none_when_held_by_another_owner(store):
    assert store.acquire("team_x", "owner-1") is not None
    before = store._lock_path("team_x").read_text(encoding="utf-8")

    assert store.acquire("team_x", "owner-2") is None
    # 未拿到锁的一方不得改写他人锁文件
    assert store._lock_path("team_x").read_text(encoding="utf-8") == before


def test_acquire_renews_for_same_owner(store):
    first = store.acquire("team_x", "owner-1", ttl_seconds=10)
    second = store.acquire("team_x", "owner-1", ttl_seconds=60)

    assert first is not None and second is not None
    assert second.expires_at > first.expires_at
    assert store.get("team_x").owner == "owner-1"


def test_acquire_takes_over_expired_lock(store):
    _write_lock(store, "team_x", owner="owner-1", offset_seconds=-120)

    lock = store.acquire("team_x", "owner-2")

    assert lock is not None
    assert lock.owner == "owner-2"
    assert store.get("team_x").owner == "owner-2"


def test_renew_extends_ttl_for_same_owner(store):
    first = store.acquire("team_x", "owner-1", ttl_seconds=5)
    renewed = store.renew("team_x", "owner-1", ttl_seconds=90)

    assert first is not None and renewed is not None
    assert renewed.expires_at > first.expires_at
    assert store.get("team_x").owner == "owner-1"


def test_release_by_owner_removes_file(store):
    store.acquire("team_x", "owner-1")

    assert store.release("team_x", "owner-1") is True
    assert store._lock_path("team_x").exists() is False
    assert store.get("team_x") is None


def test_release_by_other_owner_is_refused(store):
    store.acquire("team_x", "owner-1")

    assert store.release("team_x", "owner-2") is False
    assert store.get("team_x").owner == "owner-1"


def test_release_missing_lock_returns_false(store):
    assert store.release("never-taken", "owner-1") is False


def test_get_returns_none_for_missing_lock(store):
    assert store.get("never-taken") is None


def test_get_returns_none_for_corrupt_lock(store, caplog):
    store._lock_path("team_x").write_text("not-json", encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        assert store.get("team_x") is None
    # get() 对损坏文件是静默返回 None（只读路径，不告警）
    assert "team_x" not in caplog.text


# --------------------------------------------------------------------------
# 损坏锁文件的处理（并发安全关键路径）
# --------------------------------------------------------------------------


def test_acquire_quarantines_corrupt_lock_and_rebuilds(store, caplog):
    corrupt = store._lock_path("team_x")
    corrupt.write_text("{ broken json", encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        lock = store.acquire("team_x", "owner-1")

    assert lock is not None
    assert lock.owner == "owner-1"
    # 损坏文件被隔离而不是被悄悄覆盖
    quarantined = list(store.lock_dir.glob("team_x.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{ broken json"
    # 新锁文件是合法 JSON
    assert json.loads(corrupt.read_text(encoding="utf-8"))["owner"] == "owner-1"
    assert "锁文件损坏" in caplog.text


def test_acquire_still_succeeds_when_quarantine_rename_fails(store, monkeypatch):
    corrupt = store._lock_path("team_x")
    corrupt.write_text("{ broken json", encoding="utf-8")

    def failing_rename(self, target):
        raise OSError("cannot rename")

    monkeypatch.setattr(Path, "rename", failing_rename)

    lock = store.acquire("team_x", "owner-1")

    assert lock is not None
    assert list(store.lock_dir.glob("team_x.corrupt-*")) == []
    assert store.get("team_x").owner == "owner-1"


def test_release_on_corrupt_lock_returns_false_and_logs(store, caplog):
    store._lock_path("team_x").write_text("garbage", encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        assert store.release("team_x", "owner-1") is False

    assert "释放锁失败" in caplog.text
    # 文件保留，交由后续 acquire 做隔离处理
    assert store._lock_path("team_x").exists() is True


# --------------------------------------------------------------------------
# 上下文管理器
# --------------------------------------------------------------------------


def test_team_lock_is_held_inside_block_and_released_after(state_dir):
    probe = LockStore(state_dir, "team")

    with with_team_lock("alpha", "owner-1", state_dir=state_dir):
        held = probe.get("team_alpha")
        assert held is not None
        assert held.owner == "owner-1"

    assert probe.get("team_alpha") is None


def test_team_lock_releases_even_when_body_raises(state_dir):
    probe = LockStore(state_dir, "team")

    with pytest.raises(ValueError, match="boom"):
        with with_team_lock("alpha", "owner-1", state_dir=state_dir):
            raise ValueError("boom")

    assert probe.get("team_alpha") is None
    # 释放后可被他人重新获取
    assert probe.acquire("team_alpha", "owner-2") is not None


def test_team_lock_conflict_blocks_second_holder(state_dir):
    """已知缺陷（locks.py:157）：``ErrorCode.CONFLICT`` 不存在，冲突时抛 AttributeError。

    期望是 ClawdError(CONFLICT)，实际透出 AttributeError；此处锁定真实行为，
    修复后本用例应相应更新。关键断言是：第二个持有者进不去临界区。
    """
    probe = LockStore(state_dir, "team")
    assert probe.acquire("team_alpha", "owner-1") is not None
    entered = []

    with pytest.raises(AttributeError):
        with with_team_lock("alpha", "owner-2", state_dir=state_dir):
            entered.append("should-not-happen")

    assert entered == []
    assert probe.get("team_alpha").owner == "owner-1"


def test_task_claim_lock_uses_dedicated_store(state_dir):
    claim = LockStore(state_dir, "task_claim")

    with with_task_claim_lock("task-9", "owner-1", state_dir=state_dir):
        assert claim.get("task_claim_task-9").owner == "owner-1"
        # 与团队锁目录互不干扰
        assert not (state_dir / "team_locks").exists()

    assert claim.get("task_claim_task-9") is None


def test_mailbox_lock_uses_short_default_ttl(state_dir):
    mailbox = LockStore(state_dir, "mailbox")

    with with_mailbox_lock("agent-1", "owner-1", state_dir=state_dir):
        held = mailbox.get("mailbox_agent-1")
        assert held is not None
        assert (held.expires_at - held.acquired_at).total_seconds() == pytest.approx(10, abs=1)

    assert mailbox.get("mailbox_agent-1") is None


def test_context_managers_default_state_dir_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with with_team_lock("alpha", "owner-1"):
        assert (tmp_path / ".clawd" / "team_locks" / "team_alpha.json").is_file()

    assert (tmp_path / ".clawd" / "team_locks" / "team_alpha.json").exists() is False


def test_task_claim_lock_defaults_state_dir_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with with_task_claim_lock("task-1", "owner-1"):
        assert (tmp_path / ".clawd" / "task_claim_locks" / "task_claim_task-1.json").is_file()


def test_mailbox_lock_defaults_state_dir_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with with_mailbox_lock("agent-1", "owner-1"):
        assert (tmp_path / ".clawd" / "mailbox_locks" / "mailbox_agent-1.json").is_file()


# --------------------------------------------------------------------------
# 装饰器
# --------------------------------------------------------------------------


def test_scaling_lock_decorator_holds_lock_during_call(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    probe = LockStore(tmp_path / ".clawd", "scaling")
    observed = {}

    @with_scaling_lock("scale-1", "owner-a", ttl_seconds=20)
    def work(value: int) -> int:
        lock = probe.get("scale-1")
        observed["owner"] = lock.owner if lock else None
        return value * 2

    assert work(21) == 42
    assert work.__name__ == "work"  # functools.wraps 生效
    assert observed["owner"] == "owner-a"
    assert probe.get("scale-1") is None


def test_scaling_lock_decorator_conflict_blocks_call(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    probe = LockStore(tmp_path / ".clawd", "scaling")
    assert probe.acquire("scale-1", "other-owner") is not None
    called = []

    @with_scaling_lock("scale-1", "owner-a")
    def work() -> str:
        called.append("ran")
        return "done"

    with pytest.raises(AttributeError):
        work()

    assert called == []
    assert probe.get("scale-1").owner == "other-owner"


def test_scaling_lock_decorator_releases_on_exception(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    probe = LockStore(tmp_path / ".clawd", "scaling")

    @with_scaling_lock("scale-1", "owner-a")
    def work() -> None:
        raise RuntimeError("inner failure")

    with pytest.raises(RuntimeError, match="inner failure"):
        work()

    assert probe.get("scale-1") is None


def test_task_claim_decorator_lifecycle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    probe = LockStore(tmp_path / ".clawd", "task_claim")

    @with_task_claim_lock_decorator("task-7", "owner-a")
    def work() -> str:
        return probe.get("task_claim_task-7").owner

    assert work() == "owner-a"
    assert probe.get("task_claim_task-7") is None


def test_mailbox_decorator_lifecycle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    probe = LockStore(tmp_path / ".clawd", "mailbox")

    @with_mailbox_lock_decorator("agent-3", "owner-a")
    def work() -> str:
        return probe.get("mailbox_agent-3").owner

    assert work() == "owner-a"
    assert probe.get("mailbox_agent-3") is None


def test_task_claim_lock_conflict_blocks_second_holder(state_dir):
    """同 locks.py:182 —— task claim 冲突路径同样因 ``ErrorCode.CONFLICT`` 缺失抛 AttributeError。"""
    probe = LockStore(state_dir, "task_claim")
    assert probe.acquire("task_claim_task-9", "owner-1") is not None
    entered = []

    with pytest.raises(AttributeError):
        with with_task_claim_lock("task-9", "owner-2", state_dir=state_dir):
            entered.append("should-not-happen")

    assert entered == []
    assert probe.get("task_claim_task-9").owner == "owner-1"


def test_mailbox_decorator_conflict_blocks_call(state_dir, tmp_path, monkeypatch):
    """同 locks.py:289 —— mailbox 装饰器冲突路径同样抛 AttributeError。"""
    monkeypatch.chdir(tmp_path)
    probe = LockStore(tmp_path / ".clawd", "mailbox")
    assert probe.acquire("mailbox_agent-3", "other-owner") is not None
    called = []

    @with_mailbox_lock_decorator("agent-3", "owner-a")
    def work() -> str:
        called.append("ran")
        return "done"

    with pytest.raises(AttributeError):
        work()

    assert called == []
    assert probe.get("mailbox_agent-3").owner == "other-owner"


# --------------------------------------------------------------------------
# 锁的独立性（不同 lock_type 不应互相阻塞）
# --------------------------------------------------------------------------


def test_lock_types_are_independent(state_dir):
    team = LockStore(state_dir, "team")
    claim = LockStore(state_dir, "task_claim")
    mailbox = LockStore(state_dir, "mailbox")

    assert team.acquire("shared-id", "owner-1") is not None
    assert claim.acquire("shared-id", "owner-1") is not None
    assert mailbox.acquire("shared-id", "owner-1") is not None

    assert team.get("shared-id").owner == "owner-1"
    assert claim.get("shared-id").owner == "owner-1"
    assert mailbox.get("shared-id").owner == "owner-1"
