"""Session context tracker for conversational awareness.

Tracks what the user is working on, recent topics, emotional state,
and interaction preferences across turns. Lightweight — just string
analysis and a sliding window, zero dependencies.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Signal Detection Patterns ────────────────────────────────

_FILE_PATH_RE = re.compile(
    r"(?:[A-Za-z]:\\|/)?(?:[\w.-]+[/\\])+[\w.-]+\.(?:py|js|ts|go|rs|java|rb|sh|toml|json|yaml|md|html|css)\b"
)
_TASK_VERB_RE = re.compile(
    r"\b(fix|build|implement|create|write|debug|refactor|test|deploy|update|add|remove|install|configure)\b",
    re.I,
)
_FRUSTRATED_RE = re.compile(
    r"\b(frustrat\w*|annoy\w*|this sucks|not working|broken|ugh|wtf|confused|confusing|"
    r"doesn'?t make sense|what\??$|huh\??$|you keep|stop doing that|wrong)\b",
    re.I,
)
_CURIOUS_RE = re.compile(
    r"\b(how does|what is|why does|can you explain|tell me about|curious|interesting|"
    r"what do you think|what if|could we)\b",
    re.I,
)
_EXCITED_RE = re.compile(
    r"\b(amazing|awesome|perfect|great|love it|nice|brilliant|wow|yes!|let'?s go|nailed it)\b",
    re.I,
)
_TOPIC_KEYWORDS_RE = re.compile(r"\b[A-Za-z][a-z]{2,}\b")


@dataclass
class ConversationContext:
    """Snapshot of current conversation state."""

    current_task: str = ""
    recent_topics: list[str] = field(default_factory=list)
    user_mood: str = "neutral"
    interaction_style: str = "normal"
    recent_confusions: list[str] = field(default_factory=list)
    files_mentioned: list[str] = field(default_factory=list)
    turn_count: int = 0


class ContextTracker:
    """Tracks conversation context across turns.

    Maintains a sliding window of recent messages and extracts
    contextual signals for injection into system prompts.

    Args:
        max_turns: Maximum turns to keep in window
        max_topics: Maximum recent topics to track
    """

    def __init__(self, max_turns: int = 10, max_topics: int = 5) -> None:
        self._max_topics = max_topics
        self._turns: deque[dict[str, str]] = deque(maxlen=max_turns)
        self._topics: deque[str] = deque(maxlen=max_topics)
        self._files: list[str] = []
        self._current_task: str = ""
        self._mood: str = "neutral"
        self._confusions: deque[str] = deque(maxlen=3)
        self._turn_count: int = 0
        self._last_user_msg: str = ""
        self._last_assistant_msg: str = ""

    def update(self, role: str, text: str) -> None:
        """Ingest a message and update context signals.

        Args:
            role: 'user' or 'assistant'
            text: Message content
        """
        clean = str(text or "").strip()
        if not clean:
            return

        self._turns.append({"role": role, "text": clean})
        self._turn_count += 1

        if role == "user":
            self._last_user_msg = clean
            self._extract_files(clean)
            self._infer_task(clean)
            self._extract_topic(clean)
            self._detect_mood(clean)
            self._detect_confusion(clean)
        else:
            self._last_assistant_msg = clean

    def get_context(self) -> ConversationContext:
        """Get a snapshot of current conversation context."""
        return ConversationContext(
            current_task=self._current_task,
            recent_topics=list(self._topics),
            user_mood=self._mood,
            interaction_style=self._infer_style(),
            recent_confusions=list(self._confusions),
            files_mentioned=self._files[-5:],
            turn_count=self._turn_count,
        )

    def to_prompt_block(self, max_chars: int = 600) -> str:
        """Generate a compact context block for prompt injection.

        Args:
            max_chars: Maximum character length

        Returns:
            Formatted context string
        """
        parts = []

        if self._current_task:
            parts.append(f"Current task: {self._current_task}")

        if self._topics:
            parts.append(f"Recent topics: {', '.join(self._topics)}")

        if self._files:
            recent = self._files[-3:]
            parts.append(f"Files mentioned: {', '.join(recent)}")

        if self._mood != "neutral":
            parts.append(f"User mood: {self._mood}")

        if self._confusions:
            parts.append(f"Recent confusions: {'; '.join(self._confusions)}")

        result = "\n".join(parts)
        if len(result) > max_chars:
            result = result[:max_chars].rsplit("\n", 1)[0]
        return result

    def detect_topic_shift(self, new_message: str) -> bool:
        """Check if a new message represents a topic shift.

        Args:
            new_message: The incoming user message

        Returns:
            True if this looks like a new topic
        """
        if not self._topics or not new_message:
            return False

        new_words = set(_TOPIC_KEYWORDS_RE.findall(new_message.lower()))
        last_topic = self._topics[-1] if self._topics else ""
        last_words = set(_TOPIC_KEYWORDS_RE.findall(last_topic.lower()))

        if not last_words:
            return False

        overlap = new_words & last_words
        return len(overlap) < 2

    @property
    def current_task(self) -> str:
        """The currently inferred task."""
        return self._current_task

    @property
    def mood(self) -> str:
        """The user's detected mood."""
        return self._mood

    @property
    def turn_count(self) -> int:
        """Number of turns processed."""
        return self._turn_count

    # ── Private Extraction Methods ───────────────────────────

    def _extract_files(self, text: str) -> None:
        """Extract file paths from message."""
        found = _FILE_PATH_RE.findall(text)
        for f in found:
            if f not in self._files:
                self._files.append(f)
        if len(self._files) > 10:
            self._files = self._files[-10:]

    def _infer_task(self, text: str) -> None:
        """Infer what task the user is working on."""
        verbs = _TASK_VERB_RE.findall(text)
        files = _FILE_PATH_RE.findall(text)

        if verbs and files:
            self._current_task = f"{verbs[0]} {files[0]}"
        elif verbs and len(text) < 200:
            # Short message with action verb — likely a task description
            self._current_task = text[:100]
        # Don't clear task if no signals — it persists

    def _extract_topic(self, text: str) -> None:
        """Extract the topic of a message."""
        if len(text) < 5:
            return
        # Use first meaningful clause as topic summary
        topic = text[:80].split(".")[0].split("?")[0].strip()
        if topic and topic not in self._topics:
            self._topics.append(topic)

    def _detect_mood(self, text: str) -> None:
        """Detect emotional state from message content."""
        if _FRUSTRATED_RE.search(text):
            self._mood = "frustrated"
        elif _EXCITED_RE.search(text):
            self._mood = "positive"
        elif _CURIOUS_RE.search(text):
            self._mood = "curious"
        elif len(text) < 20 and text.endswith("?"):
            self._mood = "neutral"
        # Mood persists — only updated on clear signals

    def _detect_confusion(self, text: str) -> None:
        """Detect if the user is confused by prior response."""
        confusion_signals = [
            "what do you mean",
            "i don't understand",
            "that doesn't make sense",
            "huh",
            "no i meant",
            "that's not what i asked",
            "you misunderstood",
            "try again",
        ]
        lower = text.lower()
        for signal in confusion_signals:
            if signal in lower:
                self._confusions.append(text[:60])
                break

    def _infer_style(self) -> str:
        """Infer the user's interaction style from patterns."""
        if self._turn_count < 3:
            return "normal"

        user_msgs = [t["text"] for t in self._turns if t["role"] == "user"]
        if not user_msgs:
            return "normal"

        avg_len = sum(len(m) for m in user_msgs) / len(user_msgs)
        if avg_len < 30:
            return "terse"
        elif avg_len > 200:
            return "verbose"
        return "normal"
