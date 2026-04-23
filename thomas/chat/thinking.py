"""Thinking/reasoning tracker for frontend display.

Accumulates reasoning blocks at every decision point so the frontend
can render collapsible "Thought for X.Xs" sections like Claude/ChatGPT.

Each block has a phase label (planning, delegating, synthesizing, etc.)
and duration tracking for the frontend timer display.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ThinkingBlock:
    """Single reasoning section with timing."""

    phase: str
    text: str = ""
    started_at: float = field(default_factory=time.monotonic)
    ended_at: float | None = None

    @property
    def duration_ms(self) -> int:
        end = self.ended_at or time.monotonic()
        return int((end - self.started_at) * 1000)

    @property
    def is_open(self) -> bool:
        return self.ended_at is None

    def close(self) -> None:
        if self.ended_at is None:
            self.ended_at = time.monotonic()

    def to_event(self) -> dict[str, Any]:
        """Convert to NDJSON event dict for streaming."""
        return {
            "type": "thinking",
            "phase": self.phase,
            "text": self.text,
            "duration_ms": self.duration_ms,
        }


class ThinkingTracker:
    """Accumulate thinking/reasoning blocks for a single chat turn.

    Usage::

        tracker = ThinkingTracker()
        tracker.start("planning")
        tracker.append("Analysing user intent...")
        tracker.append("This looks like a coding request.")
        tracker.end()

        tracker.start("delegating")
        tracker.append("Routing to CodingSpecialist...")
        tracker.end()

        # Stream all events
        for event in tracker.events():
            await send(event)

        # Summary for 'done' event
        summary = tracker.summary()  # "Thought for 2.3s"
    """

    def __init__(self) -> None:
        self._blocks: list[ThinkingBlock] = []
        self._current: ThinkingBlock | None = None
        self._started_at: float = time.monotonic()

    def start(self, phase: str) -> None:
        """Start a new thinking block.  Closes any open block first."""
        if self._current and self._current.is_open:
            self._current.close()
        self._current = ThinkingBlock(phase=phase)
        self._blocks.append(self._current)

    # Backward-compatible alias retained for callers/tests that still use the old
    # method name.
    def start_phase(self, phase: str, text: str = "") -> None:
        self.start(phase)
        if text:
            self.append(text)

    def append(self, text: str) -> None:
        """Append text to the current thinking block."""
        if self._current is None:
            self.start("thinking")
        assert self._current is not None
        if self._current.text:
            self._current.text += "\n" + text
        else:
            self._current.text = text

    def end(self) -> ThinkingBlock | None:
        """Close the current thinking block.  Returns it."""
        if self._current and self._current.is_open:
            self._current.close()
            block = self._current
            self._current = None
            return block
        return None

    # Backward-compatible alias retained for callers/tests that still use the old
    # method name.
    def end_phase(self, phase: str | None = None) -> ThinkingBlock | None:
        return self.end()

    def events(self) -> list[dict[str, Any]]:
        """Return all thinking blocks as NDJSON event dicts."""
        return [b.to_event() for b in self._blocks if b.text]

    @property
    def total_ms(self) -> int:
        """Total thinking time across all blocks."""
        return sum(b.duration_ms for b in self._blocks)

    @property
    def total_text(self) -> str:
        """Concatenated thinking text from all blocks."""
        parts = []
        for b in self._blocks:
            if b.text:
                parts.append(f"[{b.phase}] {b.text}")
        return "\n\n".join(parts)

    def summary(self) -> str:
        """Human-readable summary for the 'done' event."""
        secs = self.total_ms / 1000.0
        phases = [b.phase for b in self._blocks if b.text]
        if not phases:
            return ""
        return f"Thought for {secs:.1f}s ({', '.join(phases)})"

    @property
    def block_count(self) -> int:
        return len(self._blocks)

    @property
    def phases(self) -> list[str]:
        """Backward-compatible list of phase names for completed/started thinking blocks."""
        return [b.phase for b in self._blocks]

    def to_summary_event(self) -> dict[str, Any]:
        """Summary event for inclusion in the 'done' payload."""
        return {
            "thinking_summary": self.summary(),
            "total_thinking_ms": self.total_ms,
            "thinking_phases": [b.phase for b in self._blocks if b.text],
            "thinking_block_count": self.block_count,
        }
