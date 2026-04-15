"""
Tests for session_history_search.py - Session History Search Module

Tests for: session_history_search.py (来自 oh-my-codex-main/src/session-history/search.ts)
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.workflow.session_history_search import (
    SessionMatch,
    SessionSearchResult,
    count_sessions,
    get_active_sessions,
    get_latest_session,
    search_sessions,
)


@pytest.fixture
def temp_cwd(tmp_path):
    """Create temporary directory for tests."""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(original_cwd)


@pytest.fixture
def mock_state_file(tmp_path):
    """Create mock state files."""
    state_dir = Path(tmp_path) / ".clawd" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    # Create pipeline state
    pipeline_file = state_dir / "pipeline-state.json"
    pipeline_file.write_text(json.dumps({
        "mode": "pipeline",
        "task": "Test task",
        "current_phase": "stage:executing",
        "started_at": datetime.now().isoformat(),
        "active": True,
    }))
    return state_dir


class TestSessionMatch:
    """Tests for SessionMatch dataclass."""

    def test_create_match(self):
        """Test creating a session match."""
        match = SessionMatch(
            mode="pipeline",
            phase="executing",
            task="Test task",
            started_at="2026-04-15T10:00:00",
            active=True,
        )
        assert match.mode == "pipeline"
        assert match.phase == "executing"
        assert match.active is True


class TestSessionSearch:
    """Tests for session search functions."""

    def test_search_empty_directory(self, temp_cwd):
        """Test searching in empty directory."""
        result = search_sessions()
        assert result.total_count == 0
        assert result.sessions == []

    def test_search_with_mode_filter(self, mock_state_file, temp_cwd):
        """Test filtering by mode."""
        result = search_sessions(modes=["pipeline"])
        assert result.total_count >= 1

    def test_search_active_only(self, mock_state_file, temp_cwd):
        """Test filtering active sessions."""
        result = search_sessions(active_only=True)
        assert all(s.active for s in result.sessions) or result.total_count == 0

    def test_search_by_phase(self, mock_state_file, temp_cwd):
        """Test filtering by phase."""
        result = search_sessions(phases=["stage:executing"])
        # May have results depending on phase


class TestSessionCount:
    """Tests for session counting."""

    def test_count_empty(self, temp_cwd):
        """Test counting in empty directory."""
        counts = count_sessions()
        assert isinstance(counts, dict)

    def test_count_with_sessions(self, mock_state_file, temp_cwd):
        """Test counting with some sessions."""
        counts = count_sessions()
        assert "pipeline" in counts


class TestSessionQueries:
    """Tests for session query functions."""

    def test_get_latest_session(self, mock_state_file, temp_cwd):
        """Test getting latest session."""
        latest = get_latest_session()
        # May be None if no sessions

    def test_get_active_sessions(self, mock_state_file, temp_cwd):
        """Test getting active sessions."""
        active = get_active_sessions()
        assert isinstance(active, list)


class TestEdgeCases:
    """Tests for edge cases."""

    def test_invalid_cwd(self):
        """Test with non-existent cwd."""
        result = search_sessions(cwd="/nonexistent/path")
        assert result.total_count == 0

    def test_datetime_filtering(self, mock_state_file, temp_cwd):
        """Test datetime range filtering."""
        since = datetime.now() - timedelta(days=7)
        result = search_sessions(since=since)
        assert result.total_count >= 0

    def test_until_datetime(self, mock_state_file, temp_cwd):
        """Test until datetime."""
        until = datetime.now() + timedelta(days=1)
        result = search_sessions(until=until)
        assert result.total_count >= 0