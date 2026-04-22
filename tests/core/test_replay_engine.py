"""Tests for ReplayEngine functionality.

Covers basic event recording, flushing, loading, and summary generation.
"""

import os
import json
import shutil
from pathlib import Path

import pytest

from src.core.replay_engine import (
    ReplayEngine,
    EventType,
    get_replay_engine,
    record_event,
    get_session_summary,
)

@pytest.fixture(scope="function")
def temp_state_dir(tmp_path):
    # Provide a temporary directory for replay logs
    dir_path = tmp_path / "state"
    dir_path.mkdir()
    yield str(dir_path)
    # Cleanup after test
    if os.path.exists(dir_path):
        shutil.rmtree(dir_path)

def test_record_and_load_event(temp_state_dir):
    engine = ReplayEngine(state_dir=temp_state_dir)
    session = "test-session"
    # Record a single event, buffer size < flush threshold, then manually flush
    engine.record_event(EventType.WORKFLOW_STARTED, session)
    # Force flush to ensure it is written
    engine._flush_to_disk(session)
    loaded = engine.load_events(session)
    assert len(loaded) == 1
    ev = loaded[0]
    assert ev.event_type == EventType.WORKFLOW_STARTED.value
    assert ev.session_id == session

def test_flush_and_summary(temp_state_dir):
    engine = ReplayEngine(state_dir=temp_state_dir)
    session = "summary-session"
    # Record multiple events to trigger auto-flush (flush size = 10)
    for i in range(12):
        engine.record_event(EventType.AGENT_DISPATCHED, session, {"index": i})
    # Force flush remaining events in buffer
    engine.flush_all()
    # At this point all events should be flushed
    summary = engine.get_session_summary(session)
    assert summary["event_count"] == 12
    assert summary["event_type_counts"].get(EventType.AGENT_DISPATCHED.value) == 12
    assert "duration_seconds" in summary

def test_helper_functions(temp_state_dir):
    # Using module-level helper should create/reuse a default engine
    ev = record_event(EventType.USER_INPUT, "helper-session", {"msg": "hi"}, state_dir=temp_state_dir)
    assert ev.session_id == "helper-session"
    # Flush to ensure event is written to disk
    from src.core.replay_engine import get_replay_engine
    engine = get_replay_engine(temp_state_dir)
    engine.flush_all()
    # Retrieve summary via helper
    summary = get_session_summary("helper-session", state_dir=temp_state_dir)
    assert summary["event_count"] == 1

def test_clear_session(temp_state_dir):
    engine = ReplayEngine(state_dir=temp_state_dir)
    session = "clear-session"
    engine.record_event(EventType.USER_OUTPUT, session)
    engine._flush_to_disk(session)
    # Ensure file exists
    log_path = Path(temp_state_dir) / ".clawd" / "replay" / f"{session}.jsonl"
    assert log_path.exists()
    # Clear it
    cleared = engine.clear_session(session)
    assert cleared is True
    assert not log_path.exists()

"""End of tests"""
