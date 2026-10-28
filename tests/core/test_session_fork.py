"""会话分叉与元数据（借鉴 OpenCode Session: ParentSessionID / Title / SummaryMessageID）"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.session_store import (
    StoredSession,
    fork_session,
    list_sessions,
    load_session,
    save_session,
    session_chain,
    update_session_meta,
)


@pytest.fixture
def store(tmp_path: Path) -> Path:
    d = tmp_path / "sessions"
    d.mkdir()
    return d


def _make(store: Path, sid: str, *, title: str = "", turns: int = 2) -> StoredSession:
    s = StoredSession(
        session_id=sid, messages=("u1", "a1"), input_tokens=100, output_tokens=50,
        title=title, turn_count=turns, total_cost=0.01, model="m", provider="p",
    )
    save_session(s, store)
    return s


class TestFork:
    def test_fork_copies_history_and_marks_parent(self, store: Path):
        _make(store, "root", title="原始会话")

        forked = fork_session("root", "child", directory=store)

        assert forked.session_id == "child"
        assert forked.parent_session_id == "root"
        assert forked.messages == ("u1", "a1")
        assert forked.input_tokens == 100
        assert "fork" in forked.title
        assert load_session("child", store).parent_session_id == "root"

    def test_fork_does_not_modify_parent(self, store: Path):
        _make(store, "root", title="原始")
        fork_session("root", "child", directory=store)

        parent = load_session("root", store)

        assert parent.parent_session_id == ""
        assert parent.title == "原始"

    def test_fork_custom_title(self, store: Path):
        _make(store, "root")
        forked = fork_session("root", "child", title="实验分支", directory=store)
        assert forked.title == "实验分支"

    def test_fork_missing_parent_raises(self, store: Path):
        with pytest.raises(FileNotFoundError):
            fork_session("ghost", "child", directory=store)


class TestMetadata:
    def test_update_title(self, store: Path):
        _make(store, "s1")

        updated = update_session_meta("s1", title="登录接口改造", directory=store)

        assert updated.title == "登录接口改造"
        assert load_session("s1", store).title == "登录接口改造"

    def test_link_summary_message(self, store: Path):
        _make(store, "s1")

        updated = update_session_meta("s1", summary_message_id="msg-42", directory=store)

        assert updated.summary_message_id == "msg-42"
        assert load_session("s1", store).summary_message_id == "msg-42"

    def test_partial_update_keeps_other_fields(self, store: Path):
        _make(store, "s1")
        update_session_meta("s1", title="T", directory=store)
        updated = update_session_meta("s1", summary_message_id="m1", directory=store)

        assert updated.title == "T"
        assert updated.messages == ("u1", "a1")
        assert updated.input_tokens == 100


class TestListAndChain:
    def test_list_exposes_title_and_parent(self, store: Path):
        _make(store, "root", title="根")
        fork_session("root", "child", directory=store)

        rows = {r["session_id"]: r for r in list_sessions(store)}

        assert rows["root"]["title"] == "根"
        assert rows["child"]["parent_session_id"] == "root"
        assert rows["root"]["input_tokens"] == 100

    def test_chain_walks_to_root(self, store: Path):
        _make(store, "a", title="a")
        fork_session("a", "b", directory=store)
        fork_session("b", "c", directory=store)

        assert session_chain("c", store) == ["c", "b", "a"]

    def test_chain_stops_on_missing_parent(self, store: Path):
        _make(store, "root")
        assert session_chain("root", store) == ["root"]

    def test_backward_compatible_load_without_new_fields(self, store: Path):
        """老格式会话文件（无新字段）必须能读，不能因为缺字段就崩"""
        import json

        (store / "legacy.json").write_text(json.dumps({
            "session_id": "legacy", "messages": ["x"], "input_tokens": 1,
            "output_tokens": 2,
        }), encoding="utf-8")

        loaded = load_session("legacy", store)

        assert loaded.parent_session_id == ""
        assert loaded.title == ""
        assert loaded.summary_message_id == ""
