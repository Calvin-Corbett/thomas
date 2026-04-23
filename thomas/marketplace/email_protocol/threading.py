"""
Email threading and conversation grouping.

Implements JWZ threading algorithm for building conversation threads
from References and In-Reply-To headers.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from thomas.marketplace.email_protocol._types import EmailMessage
from thomas.marketplace.email_protocol.headers import normalize_subject


@dataclass
class ThreadNode:
    """Node in email thread tree.

    Attributes:
        message_id: Message-ID of this node
        message: Email message
        children: Child thread nodes
        parent: Parent thread node
    """

    message_id: str
    message: EmailMessage | None = None
    children: list["ThreadNode"] = field(default_factory=list)
    parent: Optional["ThreadNode"] = None

    def add_child(self, node: "ThreadNode") -> None:
        """Add child node.

        Args:
            node: Child node to add
        """
        node.parent = self
        self.children.append(node)

    def is_empty(self) -> bool:
        """Check if node is empty (no message)."""
        return self.message is None

    def get_root(self) -> "ThreadNode":
        """Get root node of thread."""
        if self.parent:
            return self.parent.get_root()
        return self


@dataclass
class Thread:
    """Represents an email thread/conversation.

    Attributes:
        root: Root node of thread
        messages: All messages in thread (in chronological order)
        subject: Thread subject
        participants: Senders in thread
        date_range: (earliest, latest) dates
        unread_count: Number of unread messages
    """

    root: ThreadNode
    messages: list[EmailMessage] = field(default_factory=list)
    subject: str = ""
    participants: set[str] = field(default_factory=set)
    date_range: tuple[datetime | None, datetime | None] = (None, None)
    unread_count: int = 0

    def __post_init__(self) -> None:
        """Initialize thread statistics."""
        self._calculate_statistics()

    def _calculate_statistics(self) -> None:
        """Calculate thread statistics from messages."""
        if not self.messages:
            return

        dates = [msg.envelope.date for msg in self.messages if msg.envelope.date]
        if dates:
            self.date_range = (min(dates), max(dates))

        self.participants = set()
        for msg in self.messages:
            if msg.envelope.from_addr:
                self.participants.add(msg.envelope.from_addr.address)

        from thomas.marketplace.email_protocol._types import Flag

        self.unread_count = sum(1 for msg in self.messages if Flag.SEEN not in msg.flags)

    def get_subject_lines(self) -> list[str]:
        """Get all unique subject lines in thread."""
        subjects = set()
        for msg in self.messages:
            subjects.add(msg.envelope.subject)
        return sorted(subjects)


class ThreadingEngine:
    """Email threading engine implementing JWZ algorithm.

    Builds thread trees from message References and In-Reply-To headers.
    """

    def __init__(self) -> None:
        """Initialize threading engine."""
        self.message_cache: dict[str, EmailMessage] = {}
        self.id_table: dict[str, ThreadNode] = {}

    def build_threads(self, messages: list[EmailMessage]) -> list[Thread]:
        """Build threads from messages using JWZ algorithm.

        Args:
            messages: List of messages to thread

        Returns:
            List of Thread objects

        Raises:
            ValueError: If message has no Message-ID
        """
        self.message_cache.clear()
        self.id_table.clear()

        for msg in messages:
            self.message_cache[msg.envelope.message_id or ""] = msg

        for msg in messages:
            self._process_message(msg)

        threads = self._extract_threads()
        return threads

    def _process_message(self, message: EmailMessage) -> ThreadNode | None:
        """Process a single message into thread tree.

        Args:
            message: Message to process

        Returns:
            Thread node for this message
        """
        msg_id = message.envelope.message_id
        if not msg_id:
            return None

        if msg_id in self.id_table:
            node = self.id_table[msg_id]
            if node.is_empty():
                node.message = message
            return node

        node = ThreadNode(msg_id, message)
        self.id_table[msg_id] = node

        ref_ids = self._get_references(message)
        if ref_ids:
            parent_id = ref_ids[-1]
            if parent_id not in self.id_table:
                self.id_table[parent_id] = ThreadNode(parent_id)

            parent_node = self.id_table[parent_id]
            parent_node.add_child(node)

        return node

    def _get_references(self, message: EmailMessage) -> list[str]:
        """Get ordered list of parent message IDs.

        Args:
            message: Message to get references for

        Returns:
            List of message-IDs in order
        """
        references = message.envelope.references.copy() if message.envelope.references else []

        if message.envelope.in_reply_to:
            if message.envelope.in_reply_to not in references:
                references.append(message.envelope.in_reply_to)

        return references

    def _extract_threads(self) -> list[Thread]:
        """Extract thread objects from ID table.

        Returns:
            List of Thread objects
        """
        roots = []
        processed = set()

        for msg_id, node in self.id_table.items():
            if node.parent is None and msg_id not in processed:
                root = self._build_thread_from_node(node)
                roots.append(root)
                processed.update(self._collect_ids(node))

        roots.sort(key=lambda t: t.date_range[0] or datetime.min, reverse=True)
        return roots

    def _build_thread_from_node(self, root_node: ThreadNode) -> Thread:
        """Build Thread object from root node.

        Args:
            root_node: Root node of thread tree

        Returns:
            Thread object
        """
        messages = self._collect_messages(root_node)
        messages.sort(key=lambda m: m.envelope.date or datetime.min)

        subject = ""
        if messages:
            subject = messages[0].envelope.subject

        thread = Thread(
            root=root_node,
            messages=messages,
            subject=subject,
        )

        return thread

    def _collect_messages(self, node: ThreadNode) -> list[EmailMessage]:
        """Recursively collect all messages in thread.

        Args:
            node: Root node of thread

        Returns:
            List of all messages
        """
        messages = []

        if node.message:
            messages.append(node.message)

        for child in node.children:
            messages.extend(self._collect_messages(child))

        return messages

    def _collect_ids(self, node: ThreadNode) -> set[str]:
        """Recursively collect all message IDs in thread.

        Args:
            node: Root node

        Returns:
            Set of message-IDs
        """
        ids = {node.message_id}

        for child in node.children:
            ids.update(self._collect_ids(child))

        return ids


class SubjectThreading:
    """Fallback subject-based threading for messages without References."""

    @staticmethod
    def group_by_subject(messages: list[EmailMessage]) -> dict[str, list[EmailMessage]]:
        """Group messages by normalized subject.

        Args:
            messages: Messages to group

        Returns:
            Dictionary of subject -> messages
        """
        groups: dict[str, list[EmailMessage]] = {}

        for msg in messages:
            normalized = normalize_subject(msg.envelope.subject)
            if normalized not in groups:
                groups[normalized] = []
            groups[normalized].append(msg)

        return groups

    @staticmethod
    def sort_groups(groups: dict[str, list[EmailMessage]]) -> list[list[EmailMessage]]:
        """Sort grouped messages by date.

        Args:
            groups: Groups of messages

        Returns:
            List of sorted message lists
        """
        sorted_groups = []

        for subject, messages in groups.items():
            messages.sort(key=lambda m: m.envelope.date or datetime.min)
            sorted_groups.append(messages)

        sorted_groups.sort(
            key=lambda group: group[0].envelope.date or datetime.min,
            reverse=True,
        )

        return sorted_groups


class ConversationView:
    """Represents a conversation view of threading results.

    Attributes:
        threads: List of Thread objects
        expanded: Which threads are expanded in view
    """

    def __init__(self, threads: list[Thread]) -> None:
        """Initialize conversation view.

        Args:
            threads: Threads to display
        """
        self.threads = threads
        self.expanded: set[str] = set()

    def expand_thread(self, subject: str) -> None:
        """Expand a thread to show all messages.

        Args:
            subject: Thread subject
        """
        self.expanded.add(subject)

    def collapse_thread(self, subject: str) -> None:
        """Collapse a thread to show only summary.

        Args:
            subject: Thread subject
        """
        self.expanded.discard(subject)

    def get_visible_messages(self) -> list[EmailMessage]:
        """Get messages visible in current view.

        Returns:
            List of visible messages
        """
        visible = []

        for thread in self.threads:
            if thread.subject in self.expanded:
                visible.extend(thread.messages)
            elif thread.messages:
                visible.append(thread.messages[0])

        return visible

    def get_summary(self, thread: Thread) -> dict[str, any]:
        """Get summary information for a thread.

        Args:
            thread: Thread to summarize

        Returns:
            Dictionary with summary data
        """
        return {
            "subject": thread.subject,
            "message_count": len(thread.messages),
            "participants": sorted(thread.participants),
            "date_range": thread.date_range,
            "unread_count": thread.unread_count,
            "latest_message": thread.messages[-1] if thread.messages else None,
        }
