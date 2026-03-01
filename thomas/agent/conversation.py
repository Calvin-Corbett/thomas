"""Conversation intelligence for multi-turn coherence.

Handles follow-up detection, reference resolution, confusion
recovery, and topic continuity across turns.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Detection Patterns ───────────────────────────────────────

_FOLLOWUP_STARTERS = re.compile(
    r"^(?:and |also |what about |how about |but |ok |okay |yeah |yes |no |"
    r"then |so |can you |could you |wait |actually |oh |hmm )",
    re.I,
)
_PRONOUN_RE = re.compile(r"\b(it|that|this|those|these|them)\b", re.I)
_CONFUSION_RE = re.compile(
    r"\b(what do you mean|huh\??|i don'?t understand|that'?s not what|"
    r"no i meant|you misunderstood|try again|what\?|wrong|"
    r"that doesn'?t make sense|confused|i said)\b",
    re.I,
)
_QUESTION_RE = re.compile(r"\?$")
_REPEAT_THRESHOLD = 0.6  # Token overlap ratio to detect repeated questions


@dataclass
class TurnRecord:
    """A single conversation turn."""

    role: str
    text: str
    topic: str = ""


class ConversationIntelligence:
    """Multi-turn conversation coherence engine.

    Tracks conversation flow and provides intelligence about
    follow-ups, references, confusion, and topic continuity.

    Args:
        max_turns: Number of recent turns to track
    """

    def __init__(self, max_turns: int = 12) -> None:
        self._turns: deque[TurnRecord] = deque(maxlen=max_turns)
        self._current_topic: str = ""
        self._prior_topics: deque[str] = deque(maxlen=5)

    def update(self, role: str, text: str) -> None:
        """Record a conversation turn.

        Args:
            role: 'user' or 'assistant'
            text: Message content
        """
        clean = str(text or "").strip()
        if not clean:
            return

        topic = self._extract_topic(clean) if role == "user" else self._current_topic
        self._turns.append(TurnRecord(role=role, text=clean, topic=topic))

        if role == "user" and topic:
            if topic != self._current_topic:
                if self._current_topic:
                    self._prior_topics.append(self._current_topic)
                self._current_topic = topic

    def is_followup(self, message: str) -> bool:
        """Detect if a message is a follow-up to the prior turn.

        Args:
            message: User message to check

        Returns:
            True if this appears to be a follow-up
        """
        text = str(message or "").strip()
        if not text or not self._turns:
            return False

        # Short messages after prior exchange are usually follow-ups
        if len(text) < 40 and len(self._turns) >= 2:
            return True

        # Starts with follow-up connector words
        if _FOLLOWUP_STARTERS.match(text):
            return True

        # Contains pronouns referencing prior context
        if _PRONOUN_RE.search(text) and len(text) < 100:
            return True

        return False

    def resolve_references(self, message: str) -> str:
        """Resolve pronouns/references by injecting conversation context.

        Instead of just appending a topic, builds a proper context window
        from recent turns when the message is actually ambiguous.

        Args:
            message: User message with potential references

        Returns:
            Message with conversation context injected if ambiguous, else original
        """
        text = str(message or "").strip()
        if not text or not self._turns:
            return text

        # Only add context for actually ambiguous messages
        is_ambiguous = (
            (len(text) < 40 and len(self._turns) >= 2) or  # Very short + conversation ongoing
            (self.is_followup(text)) or  # Detected as follow-up
            (_PRONOUN_RE.search(text) and len(text) < 120)  # Has pronouns and short
        )

        if not is_ambiguous:
            return text

        # Build context window with recent turns
        context = self.build_context_window(text)
        if context:
            return f"{text}\n\n{context}"

        return text

    def detect_confusion(
        self,
        user_message: str,
        prior_assistant_message: str = "",
    ) -> bool:
        """Detect if the user is confused by the prior response.

        Args:
            user_message: Current user message
            prior_assistant_message: What the assistant said last

        Returns:
            True if user appears confused
        """
        text = str(user_message or "").strip()
        if not text:
            return False

        # Explicit confusion signals
        if _CONFUSION_RE.search(text):
            return True

        # User is repeating their earlier question (rephrased)
        if self._is_repeated_question(text):
            return True

        return False

    def detect_topic_shift(self, message: str) -> bool:
        """Check if the message represents a topic shift.

        Args:
            message: User message to check

        Returns:
            True if this is a new topic
        """
        if not self._current_topic:
            return False

        new_topic = self._extract_topic(message)
        if not new_topic:
            return False

        current_words = set(self._current_topic.lower().split())
        new_words = set(new_topic.lower().split())
        overlap = current_words & new_words

        return len(overlap) < min(2, len(current_words) // 2)

    def generate_continuity_hint(self) -> str:
        """Generate a one-line summary of conversation state.

        Returns:
            Brief context hint for routing and prompts
        """
        parts = []
        if self._current_topic:
            parts.append(f"Discussing: {self._current_topic}")

        user_turns = [t for t in self._turns if t.role == "user"]
        if len(user_turns) >= 2:
            parts.append(f"Turn {len(user_turns)} of conversation")

        recent_user = self._last_user_turn()
        if recent_user and len(recent_user.text) < 30:
            parts.append("Last message was short (likely follow-up)")

        return " | ".join(parts) if parts else ""

    def get_prior_route_hint(self) -> str | None:
        """Get the topic that should inform routing decisions.

        Returns:
            The current topic if available, else None
        """
        return self._current_topic if self._current_topic else None

    def build_context_window(self, message: str, max_turns: int = 4) -> str:
        """Build a formatted context block of recent conversation turns.

        This creates a structured context window showing the last N turns,
        useful for injecting conversation history when a follow-up or
        ambiguous message is detected.

        Args:
            message: The current message (used to determine relevance)
            max_turns: Maximum number of turns to include in context window

        Returns:
            Formatted context string, or empty string if no relevant history
        """
        if not self._turns or len(self._turns) < 2:
            return ""

        # Collect recent turns (both user and assistant)
        recent = list(self._turns)[-max_turns:]

        if not recent:
            return ""

        # Build formatted context
        lines = []
        turn_count = len(recent)
        lines.append(f"[Conversation context — last {turn_count} turns:")

        for turn in recent:
            role_label = "User" if turn.role == "user" else "Assistant"
            # Truncate long messages to keep context window manageable
            text = turn.text[:150]
            if len(turn.text) > 150:
                text = text.rsplit(" ", 1)[0] + "..."
            lines.append(f"- {role_label}: {text}")

        lines.append("]")
        return "\n".join(lines)

    @property
    def current_topic(self) -> str:
        """The current conversation topic."""
        return self._current_topic

    @property
    def turn_count(self) -> int:
        """Number of recorded turns."""
        return len(self._turns)

    # ── Private Helpers ──────────────────────────────────────

    def _extract_topic(self, text: str) -> str:
        """Extract topic from a message.

        Skips common filler prefixes like 'can you', 'please', 'I want to'
        before extracting the topic from the first clause.
        """
        cleaned = text.strip()

        # Skip common filler prefixes
        filler_prefixes = [
            r"^can you\s+",
            r"^could you\s+",
            r"^would you\s+",
            r"^please\s+",
            r"^i want to\s+",
            r"^i need to\s+",
            r"^i'd like to\s+",
            r"^let me\s+",
            r"^help me\s+",
            r"^show me\s+",
            r"^tell me\s+",
            r"^what'?s\s+",
            r"^how\s+",
            r"^when\s+",
            r"^why\s+",
            r"^where\s+",
            r"^who\s+",
        ]

        for pattern in filler_prefixes:
            match = re.match(pattern, cleaned, re.I)
            if match:
                cleaned = cleaned[match.end():].strip()
                break

        # Use first clause as topic
        for delim in [".", "?", "!", "\n"]:
            if delim in cleaned:
                topic = cleaned.split(delim)[0].strip()
                if len(topic) > 5:
                    return topic[:80]
        return cleaned[:80] if len(cleaned) > 5 else ""

    def _find_likely_referent(self) -> str | None:
        """Find the most likely referent for pronouns.

        Returns the actual last assistant response text (truncated to 200 chars)
        rather than just the topic, to avoid lossy topic extraction.
        """
        # Look at last assistant response for the actual text
        for turn in reversed(self._turns):
            if turn.role == "assistant":
                # Return the actual response text, truncated to 200 chars
                truncated = turn.text[:200]
                if len(turn.text) > 200:
                    truncated = truncated.rsplit(" ", 1)[0] + "..."
                return truncated
        # Fall back to last user topic if no assistant response found
        for turn in reversed(self._turns):
            if turn.role == "user" and turn.topic:
                return turn.topic
        return None

    def _last_user_turn(self) -> TurnRecord | None:
        """Get the most recent user turn."""
        for turn in reversed(self._turns):
            if turn.role == "user":
                return turn
        return None

    def _is_repeated_question(self, text: str) -> bool:
        """Check if user is repeating an earlier question."""
        if not _QUESTION_RE.search(text):
            return False

        new_words = set(re.findall(r"\w+", text.lower()))
        if len(new_words) < 3:
            return False

        user_questions = [t.text for t in self._turns if t.role == "user" and "?" in t.text]

        for prior_q in user_questions[-3:]:
            prior_words = set(re.findall(r"\w+", prior_q.lower()))
            if not prior_words:
                continue
            overlap = new_words & prior_words
            ratio = len(overlap) / max(len(new_words), len(prior_words))
            if ratio >= _REPEAT_THRESHOLD:
                return True

        return False
