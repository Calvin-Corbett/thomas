"""
thomas/core/persistence.py
──────────────────────────
Persistence engine for Thomas.

Saves and loads full runtime state across sessions so new-chat memory loss
is eliminated.  State is written to `./thomas_state.json` on every turn and
a human-readable daily summary is appended to
`./thomas_daily_report_YYYY-MM-DD.md`.

Usage (from loop.py or server startup):
    from thomas.core.persistence import PersistenceEngine
    pe = PersistenceEngine()
    pe.load()                         # restore state at startup
    pe.record_turn(channel, user_msg, assistant_msg, tool_calls)  # each turn
    pe.save()                         # flush to disk (called automatically by record_turn)
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_DEFAULT_STATE_FILE = Path("thomas_state.json")
_DEFAULT_REPORT_DIR = Path(".")  # reports land next to state file


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
class TurnRecord:
    """A single conversation turn stored in state."""

    def __init__(
        self,
        channel: str,
        user_msg: str,
        assistant_msg: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        ts: Optional[str] = None,
    ) -> None:
        self.channel = channel
        self.user_msg = user_msg[:2000]          # cap to avoid bloat
        self.assistant_msg = assistant_msg[:4000]
        self.tool_calls: List[Dict[str, Any]] = tool_calls or []
        self.ts = ts or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel": self.channel,
            "user_msg": self.user_msg,
            "assistant_msg": self.assistant_msg,
            "tool_calls": self.tool_calls,
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TurnRecord":
        return cls(
            channel=d.get("channel", "unknown"),
            user_msg=d.get("user_msg", ""),
            assistant_msg=d.get("assistant_msg", ""),
            tool_calls=d.get("tool_calls", []),
            ts=d.get("ts"),
        )


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------
class PersistenceEngine:
    """
    Manages Thomas's cross-session state.

    Thread-safe: internal lock serialises all reads/writes.

    State schema (thomas_state.json):
    {
        "version":       1,
        "last_saved":    "<ISO timestamp>",
        "goals":         [{"id": str, "text": str, "status": str, "created": str}],
        "facts":         {"key": "value"},          # curated global preferences
        "tool_registry": {"tool_name": {...}},      # registered tool schemas
        "auth_sessions": {"channel": {"expires": str, "level": int}},
        "turn_history":  [TurnRecord, ...]          # capped at MAX_TURNS
    }
    """

    MAX_TURNS = 500          # cap stored turns to avoid unbounded growth
    SCHEMA_VERSION = 1
    DAILY_REPORT_HOUR = 3    # write daily report at 3 AM local time

    def __init__(
        self,
        state_file: Optional[Path] = None,
        report_dir: Optional[Path] = None,
        auto_save: bool = True,
    ) -> None:
        self.state_file = Path(state_file or _DEFAULT_STATE_FILE)
        self.report_dir = Path(report_dir or _DEFAULT_REPORT_DIR)
        self.auto_save = auto_save

        self._lock = threading.Lock()
        self._last_report_date: Optional[str] = None

        # Mutable state
        self.goals: List[Dict[str, Any]] = []
        self.facts: Dict[str, Any] = {}
        self.tool_registry: Dict[str, Any] = {}
        self.auth_sessions: Dict[str, Any] = {}
        self.turn_history: List[TurnRecord] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> bool:
        """Load state from disk. Returns True if state was found and loaded."""
        if not self.state_file.exists():
            log.info("PersistenceEngine: no state file found at %s — starting fresh.", self.state_file)
            return False
        try:
            with self._lock:
                raw = json.loads(self.state_file.read_text(encoding="utf-8"))
                self._apply(raw)
            log.info(
                "PersistenceEngine: loaded %d turns, %d goals, %d facts from %s",
                len(self.turn_history),
                len(self.goals),
                len(self.facts),
                self.state_file,
            )
            return True
        except Exception as e:
            log.warning("PersistenceEngine: failed to load state (%s) — starting fresh.", e)
            return False

    def save(self) -> bool:
        """Flush state to disk. Returns True on success."""
        try:
            with self._lock:
                payload = self._serialise()
            self.state_file.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            log.debug("PersistenceEngine: state saved (%d turns).", len(self.turn_history))
            return True
        except Exception as e:
            log.error("PersistenceEngine: save failed: %s", e)
            return False

    def record_turn(
        self,
        channel: str,
        user_msg: str,
        assistant_msg: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Record a completed conversation turn and auto-save."""
        turn = TurnRecord(channel, user_msg, assistant_msg, tool_calls)
        with self._lock:
            self.turn_history.append(turn)
            # Trim history to cap
            if len(self.turn_history) > self.MAX_TURNS:
                self.turn_history = self.turn_history[-self.MAX_TURNS:]
        if self.auto_save:
            self.save()
        self._maybe_write_daily_report()

    def upsert_goal(self, goal_id: str, text: str, status: str = "open") -> None:
        """Add or update a goal by ID."""
        with self._lock:
            for g in self.goals:
                if g["id"] == goal_id:
                    g["text"] = text
                    g["status"] = status
                    return
            self.goals.append({
                "id": goal_id,
                "text": text,
                "status": status,
                "created": datetime.now(timezone.utc).isoformat(),
            })
        if self.auto_save:
            self.save()

    def close_goal(self, goal_id: str) -> None:
        """Mark a goal as complete."""
        with self._lock:
            for g in self.goals:
                if g["id"] == goal_id:
                    g["status"] = "done"
        if self.auto_save:
            self.save()

    def set_fact(self, key: str, value: Any) -> None:
        """Store a curated global fact / preference."""
        with self._lock:
            self.facts[key] = value
        if self.auto_save:
            self.save()

    def get_fact(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self.facts.get(key, default)

    def register_tool(self, name: str, schema: Dict[str, Any]) -> None:
        """Register a tool schema into the persistent registry."""
        with self._lock:
            self.tool_registry[name] = schema
        if self.auto_save:
            self.save()

    def recent_turns(self, channel: Optional[str] = None, n: int = 20) -> List[TurnRecord]:
        """Return the most recent N turns, optionally filtered by channel."""
        with self._lock:
            turns = self.turn_history
            if channel:
                turns = [t for t in turns if t.channel == channel]
            return turns[-n:]

    def open_goals(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [g for g in self.goals if g.get("status") == "open"]

    def summary_text(self) -> str:
        """Return a compact human-readable snapshot of current state."""
        with self._lock:
            open_g = [g for g in self.goals if g.get("status") == "open"]
            lines = [
                f"## Thomas State Snapshot — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                f"- Turns recorded: {len(self.turn_history)}",
                f"- Open goals: {len(open_g)}",
                f"- Stored facts: {len(self.facts)}",
                f"- Registered tools: {len(self.tool_registry)}",
                "",
            ]
            if open_g:
                lines.append("### Open Goals")
                for g in open_g:
                    lines.append(f"- [{g['id']}] {g['text']}")
            if self.facts:
                lines.append("\n### Key Facts")
                for k, v in list(self.facts.items())[:10]:
                    lines.append(f"- {k}: {v}")
            return "\n".join(lines)

    # ------------------------------------------------------------------
    # Daily report
    # ------------------------------------------------------------------

    def _maybe_write_daily_report(self) -> None:
        """Write a daily markdown report if we haven't yet today."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self._last_report_date == today:
            return
        now_hour = datetime.now().hour
        if now_hour < self.DAILY_REPORT_HOUR:
            return
        self._last_report_date = today
        self._write_daily_report(today)

    def _write_daily_report(self, date_str: str) -> None:
        """Append a daily markdown summary report."""
        try:
            report_path = self.report_dir / f"thomas_daily_report_{date_str}.md"
            content = (
                f"\n---\n\n"
                f"# Daily Report — {date_str} (generated {datetime.now().strftime('%H:%M')})\n\n"
                + self.summary_text()
                + "\n"
            )
            with open(report_path, "a", encoding="utf-8") as f:
                f.write(content)
            log.info("PersistenceEngine: daily report written to %s", report_path)
        except Exception as e:
            log.warning("PersistenceEngine: daily report write failed: %s", e)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def _serialise(self) -> Dict[str, Any]:
        return {
            "version": self.SCHEMA_VERSION,
            "last_saved": datetime.now(timezone.utc).isoformat(),
            "goals": self.goals,
            "facts": self.facts,
            "tool_registry": self.tool_registry,
            "auth_sessions": self.auth_sessions,
            "turn_history": [t.to_dict() for t in self.turn_history],
        }

    def _apply(self, raw: Dict[str, Any]) -> None:
        """Deserialise state from raw dict (called under lock)."""
        self.goals = raw.get("goals", [])
        self.facts = raw.get("facts", {})
        self.tool_registry = raw.get("tool_registry", {})
        self.auth_sessions = raw.get("auth_sessions", {})
        self.turn_history = [
            TurnRecord.from_dict(t) for t in raw.get("turn_history", [])
        ]


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_engine: Optional[PersistenceEngine] = None
_engine_lock = threading.Lock()


def get_persistence() -> PersistenceEngine:
    """Return the process-level singleton, created on first call."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = PersistenceEngine()
                _engine.load()
    return _engine
