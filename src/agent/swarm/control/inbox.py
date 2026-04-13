"""
Control Inbox - Persistent message passing system

Implements GoalX-style inbox-based communication between master and workers.
Messages are append-only JSONL files with cursor tracking for read state.

Key features:
- Durable: Messages survive process restarts
- Ordered: JSONL append-only preserves order
- Cursor-based: Track read/unread state
- Urgent escalation: Priority messages
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Any, Dict
import json
from enum import Enum


class MessagePriority(Enum):
    """Message priority levels."""
    NORMAL = "normal"
    URGENT = "urgent"
    CRITICAL = "critical"


@dataclass
class Message:
    """A single message in the inbox."""

    id: str  # Unique message ID
    from_id: str  # Sender (master or session-N)
    to_id: str  # Recipient (master or session-N)
    content: str  # Message content
    priority: MessagePriority = MessagePriority.NORMAL
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_jsonl(self) -> str:
        """Convert to JSONL line."""
        return json.dumps({
            "id": self.id,
            "from": self.from_id,
            "to": self.to_id,
            "content": self.content,
            "priority": self.priority.value,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }, ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> "Message":
        """Parse from JSONL line."""
        data = json.loads(line)
        return cls(
            id=data["id"],
            from_id=data["from"],
            to_id=data["to"],
            content=data["content"],
            priority=MessagePriority(data.get("priority", "normal")),
            timestamp=data["timestamp"],
            metadata=data.get("metadata", {})
        )


class Inbox:
    """
    Persistent inbox for a single recipient.

    Messages are stored in JSONL format (one JSON object per line).
    Cursor tracks the last read position.
    """

    def __init__(self, inbox_dir: Path, recipient_id: str):
        """
        Initialize inbox.

        Args:
            inbox_dir: Directory containing all inboxes
            recipient_id: ID of the recipient (e.g., "master", "session-1")
        """
        self.inbox_dir = inbox_dir
        self.recipient_id = recipient_id
        self.inbox_file = inbox_dir / f"{recipient_id}.jsonl"
        self.cursor_file = inbox_dir / f"{recipient_id}.cursor"

        # Ensure directory exists
        self.inbox_dir.mkdir(parents=True, exist_ok=True)

        # Initialize files if they don't exist
        if not self.inbox_file.exists():
            self.inbox_file.touch()
        if not self.cursor_file.exists():
            self._write_cursor(0)

    def append(self, message: Message) -> None:
        """
        Append a message to the inbox.

        Args:
            message: Message to append
        """
        with open(self.inbox_file, 'a', encoding='utf-8') as f:
            f.write(message.to_jsonl() + '\n')

    def read_all(self) -> List[Message]:
        """Read all messages in the inbox."""
        messages = []
        if not self.inbox_file.exists():
            return messages

        with open(self.inbox_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    messages.append(Message.from_jsonl(line))

        return messages

    def read_unread(self) -> List[Message]:
        """Read only unread messages (after cursor position)."""
        cursor = self._read_cursor()
        all_messages = self.read_all()
        return all_messages[cursor:]

    def mark_read(self, count: Optional[int] = None) -> None:
        """
        Mark messages as read by advancing the cursor.

        Args:
            count: Number of messages to mark as read. If None, mark all as read.
        """
        if count is None:
            # Mark all as read
            total = len(self.read_all())
            self._write_cursor(total)
        else:
            # Mark specific count as read
            cursor = self._read_cursor()
            self._write_cursor(cursor + count)

    def get_unread_count(self) -> int:
        """Get count of unread messages."""
        return len(self.read_unread())

    def has_urgent(self) -> bool:
        """Check if there are any urgent or critical unread messages."""
        unread = self.read_unread()
        return any(
            msg.priority in [MessagePriority.URGENT, MessagePriority.CRITICAL]
            for msg in unread
        )

    def get_urgent_messages(self) -> List[Message]:
        """Get all urgent/critical unread messages."""
        unread = self.read_unread()
        return [
            msg for msg in unread
            if msg.priority in [MessagePriority.URGENT, MessagePriority.CRITICAL]
        ]

    def clear(self) -> None:
        """Clear all messages and reset cursor."""
        if self.inbox_file.exists():
            self.inbox_file.unlink()
        self.inbox_file.touch()
        self._write_cursor(0)

    def _read_cursor(self) -> int:
        """Read cursor position."""
        if not self.cursor_file.exists():
            return 0

        with open(self.cursor_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            return int(content) if content else 0

    def _write_cursor(self, position: int) -> None:
        """Write cursor position."""
        with open(self.cursor_file, 'w', encoding='utf-8') as f:
            f.write(str(position))


class ControlSystem:
    """
    Central control system managing all inboxes.

    Provides high-level operations for sending messages between
    master and workers.
    """

    def __init__(self, control_dir: Path):
        """
        Initialize control system.

        Args:
            control_dir: Directory for control files (e.g., .clawd/runs/run-123/control)
        """
        self.control_dir = control_dir
        self.inbox_dir = control_dir / "inbox"
        self.inbox_dir.mkdir(parents=True, exist_ok=True)

        # Cache of inbox instances
        self._inboxes: Dict[str, Inbox] = {}

    def get_inbox(self, recipient_id: str) -> Inbox:
        """Get or create inbox for a recipient."""
        if recipient_id not in self._inboxes:
            self._inboxes[recipient_id] = Inbox(self.inbox_dir, recipient_id)
        return self._inboxes[recipient_id]

    def send(
        self,
        from_id: str,
        to_id: str,
        content: str,
        priority: MessagePriority = MessagePriority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Message:
        """
        Send a message.

        Args:
            from_id: Sender ID
            to_id: Recipient ID
            content: Message content
            priority: Message priority
            metadata: Optional metadata

        Returns:
            The sent message
        """
        message = Message(
            id=f"{from_id}-{to_id}-{datetime.utcnow().timestamp()}",
            from_id=from_id,
            to_id=to_id,
            content=content,
            priority=priority,
            metadata=metadata or {}
        )

        inbox = self.get_inbox(to_id)
        inbox.append(message)

        return message

    def broadcast(
        self,
        from_id: str,
        recipient_ids: List[str],
        content: str,
        priority: MessagePriority = MessagePriority.NORMAL
    ) -> List[Message]:
        """
        Broadcast a message to multiple recipients.

        Args:
            from_id: Sender ID
            recipient_ids: List of recipient IDs
            content: Message content
            priority: Message priority

        Returns:
            List of sent messages
        """
        messages = []
        for to_id in recipient_ids:
            msg = self.send(from_id, to_id, content, priority)
            messages.append(msg)
        return messages

    def list_inboxes(self) -> List[str]:
        """List all inbox IDs."""
        return [
            p.stem for p in self.inbox_dir.glob("*.jsonl")
        ]

    def get_all_unread_counts(self) -> Dict[str, int]:
        """Get unread counts for all inboxes."""
        counts = {}
        for inbox_id in self.list_inboxes():
            inbox = self.get_inbox(inbox_id)
            counts[inbox_id] = inbox.get_unread_count()
        return counts
