"""
thomas/core/persistence.py
──────────────────────────
Persistence engine for Thomas.

Saves and loads full runtime state across sessions so new-chat memory loss
is eliminated. State is written under the active Thomas data directory on
every turn (for example `%LOCALAPPDATA%\\Thomas\\<profile>\\thomas_state.json`
on Windows with profiles), and a human-readable daily summary is appended
under the same data root.

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
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
def _default_data_root() -> Path:
    try:
        from thomas.core.config import resolve_thomas_data_dir

        return resolve_thomas_data_dir()
    except Exception:
        return (Path.home() / ".thomas").resolve()


_DEFAULT_STATE_FILE = Path(os.environ.get("THOMAS_STATE_FILE") or (_default_data_root() / "thomas_state.json"))
_DEFAULT_REPORT_DIR = Path(os.environ.get("THOMAS_DAILY_REPORT_DIR") or (_default_data_root() / "reports"))


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
        tool_calls: list[dict[str, Any]] | None = None,
        ts: str | None = None,
    ) -> None:
        self.channel = channel
        self.user_msg = user_msg[:2000]  # cap to avoid bloat
        self.assistant_msg = assistant_msg[:4000]
        self.tool_calls: list[dict[str, Any]] = tool_calls or []
        self.ts = ts or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "user_msg": self.user_msg,
            "assistant_msg": self.assistant_msg,
            "tool_calls": self.tool_calls,
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TurnRecord:
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

    MAX_TURNS = 500  # cap stored turns to avoid unbounded growth
    SCHEMA_VERSION = 1
    DAILY_REPORT_HOUR = 3  # write daily report at 3 AM local time

    def __init__(
        self,
        state_file: Path | None = None,
        report_dir: Path | None = None,
        auto_save: bool = True,
    ) -> None:
        self.state_file = Path(state_file or _DEFAULT_STATE_FILE)
        self.report_dir = Path(report_dir or _DEFAULT_REPORT_DIR)
        self.auto_save = auto_save
        self.data_dir = self.state_file.parent
        self.runtime_dir = self.data_dir
        self.storage_dir = self.data_dir
        self.base_dir = self.data_dir

        self._lock = threading.Lock()
        self._last_report_date: str | None = None

        # Mutable state
        self.goals: list[dict[str, Any]] = []
        self.facts: dict[str, Any] = {}
        self.tool_registry: dict[str, Any] = {}
        self.auth_sessions: dict[str, Any] = {}
        self.turn_history: list[TurnRecord] = []

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
                # Pre-validate serialization before touching the filesystem
                try:
                    serialized = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
                except (TypeError, ValueError) as ser_err:
                    log.error("PersistenceEngine: serialization failed: %s", ser_err)
                    return False
                self.state_file.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
                tmp_path.write_text(serialized, encoding="utf-8")
                os.replace(tmp_path, self.state_file)
            log.debug("PersistenceEngine: state saved (%d turns).", len(self.turn_history))
            return True
        except Exception as e:
            log.error("PersistenceEngine: save failed: %s", e)
            # Clean up temp file if it was left behind
            try:
                tmp_path = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def record_turn(
        self,
        channel: str,
        user_msg: str,
        assistant_msg: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """Record a completed conversation turn and auto-save."""
        turn = TurnRecord(channel, user_msg, assistant_msg, tool_calls)
        with self._lock:
            self.turn_history.append(turn)
            # Trim history to cap
            if len(self.turn_history) > self.MAX_TURNS:
                self.turn_history = self.turn_history[-self.MAX_TURNS :]
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
            self.goals.append(
                {
                    "id": goal_id,
                    "text": text,
                    "status": status,
                    "created": datetime.now(timezone.utc).isoformat(),
                }
            )
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

    def register_tool(self, name: str, schema: dict[str, Any]) -> None:
        """Register a tool schema into the persistent registry."""
        with self._lock:
            self.tool_registry[name] = schema
        if self.auto_save:
            self.save()

    def recent_turns(self, channel: str | None = None, n: int = 20) -> list[TurnRecord]:
        """Return the most recent N turns, optionally filtered by channel."""
        with self._lock:
            turns = self.turn_history
            if channel:
                turns = [t for t in turns if t.channel == channel]
            return turns[-n:]

    def open_goals(self) -> list[dict[str, Any]]:
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

    def _serialise(self) -> dict[str, Any]:
        return {
            "version": self.SCHEMA_VERSION,
            "last_saved": datetime.now(timezone.utc).isoformat(),
            "goals": self.goals,
            "facts": self.facts,
            "tool_registry": self.tool_registry,
            "auth_sessions": self.auth_sessions,
            "turn_history": [t.to_dict() for t in self.turn_history],
        }

    def _apply(self, raw: dict[str, Any]) -> None:
        """Deserialise state from raw dict (called under lock)."""
        self.goals = raw.get("goals", [])
        self.facts = raw.get("facts", {})
        self.tool_registry = raw.get("tool_registry", {})
        self.auth_sessions = raw.get("auth_sessions", {})
        self.turn_history = [TurnRecord.from_dict(t) for t in raw.get("turn_history", [])]


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_engine: PersistenceEngine | None = None
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
