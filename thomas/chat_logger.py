"""Conversation logger and training mode for Thomas chat.

Provides structured logging of the entire chat pipeline so that issues
can be diagnosed in real-time or reviewed after the fact.  Also implements
a "training mode" that records behavioral observations and allows a
review agent (or the user) to flag corrections.

Usage:
    from thomas.chat_logger import chat_logger, TrainingMode

    # Log a pipeline event
    chat_logger.log_event("routing", {"path": "casual_chat", "confidence": 0.82})

    # Enable training mode
    TrainingMode.enable()

    # Check if a response needs correction
    obs = TrainingMode.observe_response(user_text, assistant_text, route, ...)
    if obs.flagged:
        print(obs.reason)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chat Pipeline Logger
# ---------------------------------------------------------------------------

_LOG_DIR_ENV = "THOMAS_CHAT_LOG_DIR"


def _default_log_dir() -> Path:
    try:
        from thomas.core.config import resolve_thomas_data_dir

        return (resolve_thomas_data_dir() / "logs" / "chat").resolve()
    except Exception:
        return (Path.home() / ".thomas" / "chat_logs").resolve()


_DEFAULT_LOG_DIR = _default_log_dir()


class ChatEventKind(str, Enum):
    """Categories of chat pipeline events."""

    REQUEST_IN = "request_in"
    CONTROL_INTERCEPT = "control_intercept"
    QUICK_REPLY = "quick_reply"
    ROUTING = "routing"
    PROMPT_BUILD = "prompt_build"
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    TONE_FILTER = "tone_filter"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    RESPONSE_OUT = "response_out"
    ERROR = "error"
    TRAINING_FLAG = "training_flag"
    SESSION_STATE = "session_state"


@dataclass
class ChatEvent:
    """Single event in the chat pipeline."""

    kind: str
    timestamp: float = field(default_factory=time.time)
    session_id: str = ""
    run_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ts": self.timestamp,
            "iso": datetime.fromtimestamp(self.timestamp).isoformat(),
            "session_id": self.session_id,
            "run_id": self.run_id,
            "data": self.data,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


class ChatLogger:
    """Structured logger for the entire chat pipeline.

    Events are written as JSONL to a rotating log file and also emitted
    to the standard Python logger at DEBUG level.
    """

    def __init__(self) -> None:
        self._enabled = True
        self._log_dir: Path | None = None
        self._current_session: str = ""
        self._current_run: str = ""
        self._event_buffer: list[ChatEvent] = []
        self._max_buffer = 200
        self._file_handle: Any | None = None
        self._observers: list[Any] = []  # callables notified on each event

    def configure(self, log_dir: str | None = None, enabled: bool = True) -> None:
        """Configure the logger destination."""
        self._enabled = enabled
        if log_dir:
            self._log_dir = Path(log_dir)
        elif os.environ.get(_LOG_DIR_ENV):
            self._log_dir = Path(os.environ[_LOG_DIR_ENV])
        elif self._log_dir is None:
            self._log_dir = _DEFAULT_LOG_DIR
        if self._log_dir:
            self._log_dir.mkdir(parents=True, exist_ok=True)

    def set_session(self, session_id: str, run_id: str = "") -> None:
        """Set the current session/run context for subsequent events."""
        self._current_session = session_id
        self._current_run = run_id

    def add_observer(self, callback: Any) -> None:
        """Register a callback that receives each ChatEvent."""
        self._observers.append(callback)

    def remove_observer(self, callback: Any) -> None:
        """Remove a registered observer."""
        try:
            self._observers.remove(callback)
        except ValueError:
            pass

    def log_event(
        self,
        kind: str,
        data: dict[str, Any] | None = None,
        *,
        session_id: str = "",
        run_id: str = "",
    ) -> ChatEvent:
        """Log a single chat pipeline event."""
        evt = ChatEvent(
            kind=kind,
            session_id=session_id or self._current_session,
            run_id=run_id or self._current_run,
            data=data or {},
        )

        if not self._enabled:
            return evt

        # Emit to python logger
        log.debug("[chat:%s] sid=%s %s", kind, evt.session_id[:12], json.dumps(evt.data, default=str)[:300])

        # Buffer in memory
        self._event_buffer.append(evt)
        if len(self._event_buffer) > self._max_buffer:
            self._event_buffer = self._event_buffer[-self._max_buffer :]

        # Write to file if configured
        self._write_to_file(evt)

        # Notify observers
        for obs in self._observers:
            try:
                obs(evt)
            except Exception as e:
                log.debug("Chat logger observer error: %s", e)

        return evt

    def get_recent_events(self, n: int = 50, kind: str | None = None) -> list[ChatEvent]:
        """Get recent events from the in-memory buffer."""
        events = self._event_buffer
        if kind:
            events = [e for e in events if e.kind == kind]
        return events[-n:]

    def get_session_events(self, session_id: str) -> list[ChatEvent]:
        """Get all buffered events for a specific session."""
        return [e for e in self._event_buffer if e.session_id == session_id]

    def _write_to_file(self, evt: ChatEvent) -> None:
        if not self._log_dir:
            return
        try:
            date_str = datetime.now().strftime("%Y-%m-%d")
            log_file = self._log_dir / f"chat_{date_str}.jsonl"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(evt.to_json() + "\n")
        except Exception as e:
            log.debug("Chat log file write failed: %s", e)

    def flush(self) -> None:
        """Flush any pending writes."""
        pass  # writes are immediate in current impl

    def summary(self, session_id: str | None = None) -> dict[str, Any]:
        """Generate a summary of recent chat activity."""
        events = self._event_buffer
        if session_id:
            events = [e for e in events if e.session_id == session_id]

        kinds: dict[str, int] = {}
        errors = 0
        flags = 0
        for e in events:
            kinds[e.kind] = kinds.get(e.kind, 0) + 1
            if e.kind == ChatEventKind.ERROR:
                errors += 1
            if e.kind == ChatEventKind.TRAINING_FLAG:
                flags += 1

        return {
            "total_events": len(events),
            "event_counts": kinds,
            "errors": errors,
            "training_flags": flags,
            "session_id": session_id or "(all)",
        }


# Singleton
chat_logger = ChatLogger()


# ---------------------------------------------------------------------------
# Training Mode
# ---------------------------------------------------------------------------


class ResponseQuality(str, Enum):
    """Quality classification for a response."""

    GOOD = "good"
    NEEDS_IMPROVEMENT = "needs_improvement"
    BAD = "bad"
    CRITICAL = "critical"


@dataclass
class BehaviorObservation:
    """Result of observing a single response turn."""

    quality: str = ResponseQuality.GOOD
    flagged: bool = False
    reasons: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


import re as _re

# Patterns that indicate poor response quality
_ROBOTIC_PATTERNS = [
    _re.compile(r"^\s*(?:Certainly|Absolutely|Of course|Sure thing|Great question)[!.,]", _re.I),
    _re.compile(r"^\s*I(?:'d| would) be (?:happy|glad|delighted) to\b", _re.I),
    _re.compile(r"^\s*(?:That's a great|What a great|Excellent) (?:question|point)", _re.I),
    _re.compile(r"\bAs an AI\b", _re.I),
    _re.compile(r"\bI don't have (?:personal )?(?:feelings|opinions|experiences)\b", _re.I),
]

# Patterns that indicate the response ignored context
_CONTEXT_IGNORE_PATTERNS = [
    _re.compile(r"(?:Could you (?:please )?(?:provide|clarify|specify)|What (?:do you mean|exactly))", _re.I),
]

# Patterns that indicate excessive verbosity for simple questions
_VERBOSE_OPENERS = [
    _re.compile(r"^\s*(?:Let me|Allow me to|I'll) (?:help you|assist you|break (?:this|that) down)", _re.I),
]


class TrainingMode:
    """Behavioral monitoring and correction system.

    When enabled, every response is evaluated against quality criteria
    and flagged responses are logged for review.

    The training log can be consumed by a review agent or displayed to
    the user for manual correction.
    """

    _enabled: bool = False
    _observations: list[BehaviorObservation] = []
    _corrections: list[dict[str, Any]] = []
    _max_observations: int = 500
    _log_dir: Path | None = None

    @classmethod
    def enable(cls, log_dir: str | None = None) -> None:
        """Enable training mode."""
        cls._enabled = True
        if log_dir:
            cls._log_dir = Path(log_dir)
            cls._log_dir.mkdir(parents=True, exist_ok=True)
        log.info("Training mode ENABLED")

    @classmethod
    def disable(cls) -> None:
        """Disable training mode."""
        cls._enabled = False
        log.info("Training mode DISABLED")

    @classmethod
    def is_enabled(cls) -> bool:
        return cls._enabled

    @classmethod
    def observe_response(
        cls,
        user_text: str,
        assistant_text: str,
        route_path: str = "",
        confidence: float = 0.0,
        mode: str = "auto",
        elapsed_ms: float = 0.0,
        tool_calls: int = 0,
        session_id: str = "",
    ) -> BehaviorObservation:
        """Evaluate a response and record the observation.

        This is the core quality gate. It checks:
        1. Robotic language patterns
        2. Context awareness (did the response address the question?)
        3. Response length appropriateness
        4. Unnecessary verbosity
        5. Conversation flow naturalness
        """
        if not cls._enabled:
            return BehaviorObservation()

        obs = BehaviorObservation()
        obs.metrics = {
            "route": route_path,
            "confidence": confidence,
            "mode": mode,
            "elapsed_ms": elapsed_ms,
            "tool_calls": tool_calls,
            "user_len": len(user_text),
            "assistant_len": len(assistant_text),
            "session_id": session_id,
        }

        user_lower = user_text.lower().strip()
        assistant_lower = assistant_text.lower().strip()
        user_words = len(user_text.split())
        assistant_words = len(assistant_text.split())

        # Check 1: Robotic language
        for pat in _ROBOTIC_PATTERNS:
            if pat.search(assistant_text):
                obs.reasons.append(f"Robotic pattern detected: {pat.pattern[:60]}")
                obs.suggestions.append("Remove robotic filler; lead with the actual answer")
                obs.quality = ResponseQuality.NEEDS_IMPROVEMENT

        # Check 2: Response length vs question length
        if user_words <= 5 and assistant_words > 100:
            obs.reasons.append(f"Over-verbose: {user_words} word question got {assistant_words} word response")
            obs.suggestions.append("Match response length to question complexity")
            obs.quality = ResponseQuality.NEEDS_IMPROVEMENT

        # Check 3: Verbose openers
        for pat in _VERBOSE_OPENERS:
            if pat.search(assistant_text):
                obs.reasons.append("Verbose opener detected")
                obs.suggestions.append("Start with the answer, not 'Let me help you'")
                if obs.quality == ResponseQuality.GOOD:
                    obs.quality = ResponseQuality.NEEDS_IMPROVEMENT

        # Check 4: Asking for clarification on clear input
        if user_words >= 8:  # reasonably specific question
            for pat in _CONTEXT_IGNORE_PATTERNS:
                if pat.search(assistant_text) and not _re.search(r"\?.*\?", user_text):
                    obs.reasons.append("Unnecessary clarification request on clear input")
                    obs.suggestions.append("Answer the question directly; ask only if truly ambiguous")
                    obs.quality = ResponseQuality.NEEDS_IMPROVEMENT

        # Check 5: Empty or near-empty response
        if len(assistant_text.strip()) < 2:
            obs.reasons.append("Empty or near-empty response")
            obs.quality = ResponseQuality.BAD

        # Check 6: Response is just the user's question restated
        if assistant_lower.startswith(user_lower[:30]) and len(user_lower) > 10:
            obs.reasons.append("Response starts by restating the question")
            obs.suggestions.append("Lead with the answer, not a restatement")
            if obs.quality == ResponseQuality.GOOD:
                obs.quality = ResponseQuality.NEEDS_IMPROVEMENT

        # Check 7: Route confidence too low — may indicate misrouting
        if confidence < 0.45 and route_path:
            obs.reasons.append(f"Low routing confidence ({confidence:.2f}) for {route_path}")
            obs.suggestions.append("Consider fallback to general route or request clarification naturally")

        # Check 8: Response mentions internal details unprompted
        if _re.search(r"\b(agent loop|token economy|route path|system prompt)\b", assistant_lower):
            if not _re.search(r"\b(agent|loop|token|route|system|prompt)\b", user_lower):
                obs.reasons.append("Leaking internal implementation details")
                obs.suggestions.append("Never mention internal architecture unless asked")
                obs.quality = ResponseQuality.BAD

        obs.flagged = obs.quality != ResponseQuality.GOOD

        # Record
        cls._observations.append(obs)
        if len(cls._observations) > cls._max_observations:
            cls._observations = cls._observations[-cls._max_observations :]

        # Log if flagged
        if obs.flagged:
            chat_logger.log_event(
                ChatEventKind.TRAINING_FLAG,
                {
                    "quality": obs.quality,
                    "reasons": obs.reasons,
                    "suggestions": obs.suggestions,
                    "user_preview": user_text[:100],
                    "assistant_preview": assistant_text[:100],
                    "metrics": obs.metrics,
                },
                session_id=session_id,
            )

            # Write to training log file
            cls._write_observation(obs, user_text, assistant_text)

        return obs

    @classmethod
    def add_correction(
        cls,
        user_text: str,
        bad_response: str,
        corrected_response: str,
        reason: str = "",
    ) -> None:
        """Record a behavioral correction for future reference."""
        correction = {
            "timestamp": time.time(),
            "user_text": user_text,
            "bad_response": bad_response[:500],
            "corrected_response": corrected_response[:500],
            "reason": reason,
        }
        cls._corrections.append(correction)
        chat_logger.log_event(
            ChatEventKind.TRAINING_FLAG,
            {"type": "correction", **correction},
        )
        cls._write_correction(correction)

    @classmethod
    def get_report(cls) -> dict[str, Any]:
        """Generate a training mode report."""
        if not cls._observations:
            return {
                "enabled": cls._enabled,
                "total": 0,
                "corrections_recorded": len(cls._corrections),
                "message": "No observations yet",
            }

        total = len(cls._observations)
        flagged = sum(1 for o in cls._observations if o.flagged)
        quality_dist: dict[str, int] = {}
        all_reasons: dict[str, int] = {}

        for obs in cls._observations:
            q = obs.quality
            quality_dist[q] = quality_dist.get(q, 0) + 1
            for r in obs.reasons:
                # Normalize reason to first 40 chars for grouping
                key = r[:40]
                all_reasons[key] = all_reasons.get(key, 0) + 1

        top_issues = sorted(all_reasons.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "enabled": cls._enabled,
            "total_observations": total,
            "flagged": flagged,
            "flag_rate": round(flagged / max(total, 1) * 100, 1),
            "quality_distribution": quality_dist,
            "top_issues": [{"reason": r, "count": c} for r, c in top_issues],
            "corrections_recorded": len(cls._corrections),
        }

    @classmethod
    def reset(cls) -> None:
        """Reset all training data (use when behavior is corrected)."""
        cls._observations.clear()
        cls._corrections.clear()
        log.info("Training mode data RESET")

    @classmethod
    def _write_observation(cls, obs: BehaviorObservation, user_text: str, assistant_text: str) -> None:
        if not cls._log_dir:
            return
        try:
            log_file = cls._log_dir / "training_observations.jsonl"
            entry = {
                "ts": obs.timestamp,
                "iso": datetime.fromtimestamp(obs.timestamp).isoformat(),
                "quality": obs.quality,
                "reasons": obs.reasons,
                "suggestions": obs.suggestions,
                "user": user_text[:200],
                "assistant": assistant_text[:200],
                "metrics": obs.metrics,
            }
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            log.debug("Training observation write failed: %s", e)

    @classmethod
    def _write_correction(cls, correction: dict[str, Any]) -> None:
        if not cls._log_dir:
            return
        try:
            log_file = cls._log_dir / "training_corrections.jsonl"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(correction, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            log.debug("Training correction write failed: %s", e)
