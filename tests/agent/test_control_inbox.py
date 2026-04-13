"""
Integration tests for control inbox system
"""

import pytest
from pathlib import Path
import tempfile
import shutil

from src.agent.swarm.control.inbox import (
    Inbox,
    Message,
    MessagePriority,
    ControlSystem,
)


@pytest.fixture
def temp_control_dir():
    """Create a temporary control directory."""
    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def control_system(temp_control_dir):
    """Create a control system."""
    return ControlSystem(temp_control_dir)


class TestInbox:
    """Test inbox operations."""

    def test_create_inbox(self, temp_control_dir):
        """Test creating an inbox."""
        inbox = Inbox(temp_control_dir / "inbox", "master")
        assert inbox.inbox_file.exists()
        assert inbox.cursor_file.exists()

    def test_append_and_read(self, temp_control_dir):
        """Test appending and reading messages."""
        inbox = Inbox(temp_control_dir / "inbox", "master")

        msg = Message(
            id="msg-1",
            from_id="session-1",
            to_id="master",
            content="Hello master"
        )

        inbox.append(msg)

        messages = inbox.read_all()
        assert len(messages) == 1
        assert messages[0].content == "Hello master"

    def test_unread_messages(self, temp_control_dir):
        """Test reading unread messages."""
        inbox = Inbox(temp_control_dir / "inbox", "master")

        # Append 3 messages
        for i in range(3):
            msg = Message(
                id=f"msg-{i}",
                from_id="session-1",
                to_id="master",
                content=f"Message {i}"
            )
            inbox.append(msg)

        # All should be unread
        unread = inbox.read_unread()
        assert len(unread) == 3

        # Mark 2 as read
        inbox.mark_read(2)

        # Only 1 should be unread
        unread = inbox.read_unread()
        assert len(unread) == 1
        assert unread[0].content == "Message 2"

    def test_urgent_messages(self, temp_control_dir):
        """Test urgent message detection."""
        inbox = Inbox(temp_control_dir / "inbox", "master")

        # Normal message
        msg1 = Message(
            id="msg-1",
            from_id="session-1",
            to_id="master",
            content="Normal",
            priority=MessagePriority.NORMAL
        )
        inbox.append(msg1)

        # Urgent message
        msg2 = Message(
            id="msg-2",
            from_id="session-1",
            to_id="master",
            content="Urgent!",
            priority=MessagePriority.URGENT
        )
        inbox.append(msg2)

        assert inbox.has_urgent()

        urgent = inbox.get_urgent_messages()
        assert len(urgent) == 1
        assert urgent[0].content == "Urgent!"

    def test_cursor_persistence(self, temp_control_dir):
        """Test that cursor persists across inbox instances."""
        inbox_dir = temp_control_dir / "inbox"

        # Create inbox and add messages
        inbox1 = Inbox(inbox_dir, "master")
        for i in range(5):
            msg = Message(
                id=f"msg-{i}",
                from_id="session-1",
                to_id="master",
                content=f"Message {i}"
            )
            inbox1.append(msg)

        # Mark 3 as read
        inbox1.mark_read(3)

        # Create new inbox instance (simulating restart)
        inbox2 = Inbox(inbox_dir, "master")

        # Should still have 2 unread
        unread = inbox2.read_unread()
        assert len(unread) == 2


class TestControlSystem:
    """Test control system operations."""

    def test_send_message(self, control_system):
        """Test sending a message."""
        msg = control_system.send(
            from_id="master",
            to_id="session-1",
            content="Start working on task X"
        )

        assert msg.from_id == "master"
        assert msg.to_id == "session-1"

        # Check it's in the inbox
        inbox = control_system.get_inbox("session-1")
        messages = inbox.read_all()
        assert len(messages) == 1

    def test_broadcast(self, control_system):
        """Test broadcasting to multiple recipients."""
        messages = control_system.broadcast(
            from_id="master",
            recipient_ids=["session-1", "session-2", "session-3"],
            content="All sessions: pause work"
        )

        assert len(messages) == 3

        # Check each inbox
        for i in range(1, 4):
            inbox = control_system.get_inbox(f"session-{i}")
            msgs = inbox.read_all()
            assert len(msgs) == 1
            assert msgs[0].content == "All sessions: pause work"

    def test_bidirectional_communication(self, control_system):
        """Test master <-> worker communication."""
        # Master sends to worker
        control_system.send(
            from_id="master",
            to_id="session-1",
            content="Do task X"
        )

        # Worker reads
        worker_inbox = control_system.get_inbox("session-1")
        msgs = worker_inbox.read_unread()
        assert len(msgs) == 1

        # Worker responds
        control_system.send(
            from_id="session-1",
            to_id="master",
            content="Task X completed"
        )

        # Master reads
        master_inbox = control_system.get_inbox("master")
        msgs = master_inbox.read_unread()
        assert len(msgs) == 1
        assert msgs[0].content == "Task X completed"

    def test_priority_messages(self, control_system):
        """Test priority message handling."""
        # Send normal message
        control_system.send(
            from_id="session-1",
            to_id="master",
            content="Progress update",
            priority=MessagePriority.NORMAL
        )

        # Send critical message
        control_system.send(
            from_id="session-2",
            to_id="master",
            content="Build failed!",
            priority=MessagePriority.CRITICAL
        )

        master_inbox = control_system.get_inbox("master")
        assert master_inbox.has_urgent()

        urgent = master_inbox.get_urgent_messages()
        assert len(urgent) == 1
        assert urgent[0].content == "Build failed!"

    def test_list_inboxes(self, control_system):
        """Test listing all inboxes."""
        # Send messages to create inboxes
        control_system.send("master", "session-1", "msg1")
        control_system.send("master", "session-2", "msg2")
        control_system.send("session-1", "master", "msg3")

        inboxes = control_system.list_inboxes()
        assert "master" in inboxes
        assert "session-1" in inboxes
        assert "session-2" in inboxes

    def test_unread_counts(self, control_system):
        """Test getting unread counts for all inboxes."""
        # Send messages
        control_system.send("master", "session-1", "msg1")
        control_system.send("master", "session-1", "msg2")
        control_system.send("master", "session-2", "msg3")

        counts = control_system.get_all_unread_counts()
        assert counts["session-1"] == 2
        assert counts["session-2"] == 1

    def test_message_metadata(self, control_system):
        """Test message metadata."""
        msg = control_system.send(
            from_id="master",
            to_id="session-1",
            content="Task assignment",
            metadata={
                "task_id": "task-123",
                "obligation_id": "obl-456",
                "deadline": "2026-04-13T00:00:00Z"
            }
        )

        inbox = control_system.get_inbox("session-1")
        messages = inbox.read_all()
        assert messages[0].metadata["task_id"] == "task-123"
        assert messages[0].metadata["obligation_id"] == "obl-456"
