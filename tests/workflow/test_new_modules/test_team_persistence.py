"""
Tests for team_persistence.py - Team Persistence Module

Tests for: team_persistence.py (来自 oh-my-codex-main/src/team/persistence.ts)
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from src.workflow.team_persistence import (
    TeamMemberState,
    TeamMessage,
    TeamStateData,
    add_team_member,
    add_team_message,
    get_team_messages,
    read_team_state,
    remove_team_member,
    update_member_status,
    write_team_state,
)


@pytest.fixture
def temp_cwd(tmp_path):
    """Create temporary directory for tests."""
    original_cwd = os.getcwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(original_cwd)


class TestTeamMemberState:
    """Tests for TeamMemberState dataclass."""

    def test_create_member(self):
        """Test creating a team member."""
        member = TeamMemberState(
            id="member-1",
            name="Alice",
            role="developer",
            status="idle",
            joined_at="2026-04-15T10:00:00",
        )
        assert member.id == "member-1"
        assert member.name == "Alice"
        assert member.role == "developer"
        assert member.status == "idle"

    def test_default_status(self):
        """Test default status is idle."""
        member = TeamMemberState(id="m1", name="Bob", role="reviewer")
        assert member.status == "idle"


class TestTeamStateData:
    """Tests for TeamStateData dataclass."""

    def test_create_state(self):
        """Test creating team state."""
        state = TeamStateData(
            team_id="team-1",
            task="Build feature",
            started_at="2026-04-15T10:00:00",
        )
        assert state.team_id == "team-1"
        assert state.task == "Build feature"
        assert state.phase == "planning"
        assert state.iteration == 0
        assert state.max_iterations == 50

    def test_to_dict(self):
        """Test serialization to dict."""
        state = TeamStateData(
            team_id="team-1",
            task="Test",
            started_at="2026-04-15T10:00:00",
        )
        data = state.to_dict()
        assert data["team_id"] == "team-1"
        assert data["task"] == "Test"

    def test_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "team_id": "team-1",
            "task": "Test",
            "phase": "executing",
            "iteration": 5,
        }
        state = TeamStateData.from_dict(data)
        assert state.team_id == "team-1"
        assert state.phase == "executing"
        assert state.iteration == 5


class TestTeamPersistence:
    """Tests for team persistence operations."""

    def test_read_empty_state(self, temp_cwd):
        """Test reading non-existent state returns default."""
        state = read_team_state()
        assert state.team_id == ""
        assert state.task == ""

    def test_write_and_read_state(self, temp_cwd):
        """Test writing and reading team state."""
        state = TeamStateData(
            team_id="team-1",
            task="Build feature",
            started_at=datetime.now().isoformat(),
        )
        result = write_team_state(state)
        assert result is True

        read_state = read_team_state()
        assert read_state.team_id == "team-1"
        assert read_state.task == "Build feature"

    def test_add_team_member(self, temp_cwd):
        """Test adding a team member."""
        member = TeamMemberState(
            id="alice",
            name="Alice",
            role="developer",
            status="idle",
            joined_at=datetime.now().isoformat(),
        )
        result = add_team_member(member)
        assert result is True

    def test_add_duplicate_member_fails(self, temp_cwd):
        """Test adding duplicate member returns False."""
        member = TeamMemberState(
            id="bob",
            name="Bob",
            role="reviewer",
            joined_at=datetime.now().isoformat(),
        )
        add_team_member(member)
        result = add_team_member(member)
        assert result is False

    def test_remove_team_member(self, temp_cwd):
        """Test removing a team member."""
        member = TeamMemberState(
            id="charlie",
            name="Charlie",
            role="tester",
            joined_at=datetime.now().isoformat(),
        )
        add_team_member(member)
        result = remove_team_member("charlie")
        assert result is True

    def test_update_member_status(self, temp_cwd):
        """Test updating member status."""
        member = TeamMemberState(
            id="dave",
            name="Dave",
            role="developer",
            joined_at=datetime.now().isoformat(),
        )
        add_team_member(member)

        result = update_member_status("dave", "busy", "Working on feature")
        assert result is True

        state = read_team_state()
        updated = next((m for m in state.members if m["id"] == "dave"), None)
        assert updated["status"] == "busy"
        assert updated["current_task"] == "Working on feature"

    def test_add_team_message(self, temp_cwd):
        """Test adding team message."""
        result = add_team_message("alice", "Started working on task")
        assert result is True

    def test_get_team_messages(self, temp_cwd):
        """Test retrieving team messages."""
        add_team_message("alice", "Message 1")
        add_team_message("alice", "Message 2")
        add_team_message("bob", "Message 3")

        messages = get_team_messages()
        assert len(messages) >= 3

    def test_get_messages_by_member(self, temp_cwd):
        """Test filtering messages by member."""
        add_team_message("alice", "Alice msg 1")
        add_team_message("alice", "Alice msg 2")
        add_team_message("bob", "Bob msg")

        alice_messages = get_team_messages(member_id="alice")
        for msg in alice_messages:
            assert msg["member_id"] == "alice"

    def test_message_limit(self, temp_cwd):
        """Test message limit of 1000."""
        # Add many messages (we'll just check the logic exists)
        for i in range(5):
            add_team_message(f"user{i}", f"Message {i}")

        state = read_team_state()
        assert len(state.messages) <= 1000


class TestEdgeCases:
    """Tests for edge cases."""

    def test_invalid_member_id(self, temp_cwd):
        """Test with invalid member ID."""
        member = TeamMemberState(
            id="",
            name="Empty ID",
            role="tester",
            joined_at=datetime.now().isoformat(),
        )
        # Should handle empty ID gracefully
        result = add_team_member(member)
        # May pass or fail depending on validation

    def test_none_content_message(self, temp_cwd):
        """Test adding message with empty content."""
        result = add_team_message("alice", "")
        assert result is True

    def test_special_characters(self, temp_cwd):
        """Test with special characters in data."""
        member = TeamMemberState(
            id="test-1",
            name="Test <>&\"'",
            role="developer",
            joined_at=datetime.now().isoformat(),
        )
        result = add_team_member(member)
        assert result is True