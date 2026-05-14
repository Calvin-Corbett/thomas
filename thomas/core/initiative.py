"""
thomas/core/initiative.py
─────────────────────────
Autonomous Initiative Engine — monitors idle time and open goals, then
picks the highest-ROI next step and executes it without waiting for the user.

Behaviour:
  - Polls every POLL_INTERVAL_S (default 60s) in a daemon thread.
  - If no new user message for >IDLE_THRESHOLD_S (default 30 min) AND
    open goals exist → picks highest-ROI goal, calls executor_fn, notifies
    user only on completion, blocker, or daily summary.
  - Absolutely does NOT interrupt mid-conversation or fire while user is active.

Wire-in (once, at server startup):
    from thomas.core.initiative import get_initiative_engine
    engine = get_initiative_engine()
    engine.start(executor_fn=my_async_executor, notify_fn=my_notify)

AGENTS.md note:
    Initiative Engine: thomas/core/initiative.py — fires only when idle >30min
    + open goals exist. Notifies on completion/blocker/daily summary only.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
IDLE_THRESHOLD_S: float = 30 * 60   # 30 minutes
POLL_INTERVAL_S: float = 60          # polling cadence
DAILY_SUMMARY_HOUR: int = 8          # send daily summary at 8am local time


# ---------------------------------------------------------------------------
# ROI scoring
# ---------------------------------------------------------------------------

_ROI_KEYWORDS: dict[str, int] = {
    "crash": 12, "broken": 12, "fix": 10, "bug": 10, "error": 10,
    "deploy": 8, "ship": 8, "release": 8,
    "test": 6, "verify": 6, "check": 5,
    "improve": 4, "refactor": 4, "clean": 3,
    "document": 2, "research": 2,
}


def _score_goal(goal: dict[str, Any]) -> int:
    """Return an ROI priority score for a goal."""
    text = (goal.get("text", "") + " " + goal.get("id", "")).lower()
    score = sum(w for kw, w in _ROI_KEYWORDS.items() if kw in text)
    # Older goals get a small seniority boost
    created = goal.get("created", "")
    if created:
        try:
            age_h = (
                datetime.now(timezone.utc) -
                datetime.fromisoformat(created.replace("Z", "+00:00"))
            ).total_seconds() / 3600
            score += min(int(age_h / 4), 10)
        except Exception:
            pass
    return score


def pick_highest_roi(goals: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the open goal with the highest ROI score, or None."""
    open_goals = [g for g in goals if g.get("status") == "open"]
    return max(open_goals, key=_score_goal) if open_goals else None


# ---------------------------------------------------------------------------
# Initiative Engine
# ---------------------------------------------------------------------------

class InitiativeEngine:
    """
    Background loop that executes open goals when Thomas is idle.

    Key callables injected at start():
      executor_fn(goal_text: str) -> str   — async or sync, runs the actual work
      notify_fn(message: str)              — sends unsolicited message to user
    """

    def __init__(self) -> None:
        self._last_user_ts: float = time.monotonic()
        self._running: bool = False
        self._thread: threading.Thread | None = None
        self._executor_fn: Callable | None = None
        self._notify_fn: Callable | None = None
        self._last_summary_date: str | None = None
        self._active_goal_ids: set = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(
        self,
        executor_fn: Callable,
        notify_fn: Callable | None = None,
    ) -> None:
        """Start the background polling daemon thread."""
        self._executor_fn = executor_fn
        self._notify_fn = notify_fn or _log_notify
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="thomas-initiative",
        )
        self._thread.start()
        log.info("InitiativeEngine started (idle threshold: %.0fs).", IDLE_THRESHOLD_S)

    def stop(self) -> None:
        self._running = False

    def record_user_message(self) -> None:
        """Call on every incoming user message to reset the idle clock."""
        self._last_user_ts = time.monotonic()

    def is_idle(self) -> bool:
        return (time.monotonic() - self._last_user_ts) >= IDLE_THRESHOLD_S

    def idle_seconds(self) -> float:
        return time.monotonic() - self._last_user_ts

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        while self._running:
            time.sleep(POLL_INTERVAL_S)
            try:
                self._tick()
            except Exception as e:
                log.error("InitiativeEngine tick error: %s", e)

    def _tick(self) -> None:
        self._maybe_daily_summary()
        if not self.is_idle():
            return
        try:
            from thomas.core.persistence import get_persistence
            goals = get_persistence().open_goals()
        except Exception as e:
            log.debug("InitiativeEngine: cannot get goals: %s", e)
            return
        goal = pick_highest_roi(goals)
        if goal is None or goal.get("id") in self._active_goal_ids:
            return
        log.info(
            "InitiativeEngine: idle=%.0fs, executing goal %r.",
            self.idle_seconds(), goal.get("id"),
        )
        self._active_goal_ids.add(goal.get("id"))
        threading.Thread(
            target=self._run_goal,
            args=(goal,),
            daemon=True,
            name=f"thomas-goal-{goal.get('id', 'x')[:8]}",
        ).start()

    def _run_goal(self, goal: dict[str, Any]) -> None:
        goal_id = goal.get("id", "")
        goal_text = goal.get("text", "")
        try:
            fn = self._executor_fn
            if fn is None:
                return
            if asyncio.iscoroutinefunction(fn):
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(fn(goal_text))
                finally:
                    loop.close()
            else:
                result = fn(goal_text)

            # Mark done
            try:
                from thomas.core.persistence import get_persistence
                get_persistence().close_goal(goal_id)
            except Exception:
                pass

            self._notify(
                f"✅ **Initiative Engine** completed goal during idle time:\n"
                f"**Goal:** {goal_text}\n"
                f"**Result:** {str(result)[:400]}"
            )
        except _BlockerError as e:
            self._notify(
                f"🚧 **Initiative Engine** blocked on goal:\n"
                f"**Goal:** {goal_text}\n"
                f"**Blocker:** {e}"
            )
        except Exception as e:
            log.error("InitiativeEngine: goal %r failed: %s", goal_id, e)
        finally:
            self._active_goal_ids.discard(goal_id)

    def _maybe_daily_summary(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if self._last_summary_date == today or datetime.now().hour != DAILY_SUMMARY_HOUR:
            return
        self._last_summary_date = today
        try:
            from thomas.core.persistence import get_persistence
            summary = get_persistence().summary_text()
        except Exception as e:
            summary = f"(state unavailable: {e})"
        self._notify(f"📊 **Daily Summary — {today}**\n\n{summary}")

    def _notify(self, message: str) -> None:
        if self._notify_fn:
            try:
                self._notify_fn(message)
            except Exception as e:
                log.warning("InitiativeEngine: notify failed: %s", e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _BlockerError(Exception):
    """Raise inside executor_fn to signal a human-required blocker."""


def _log_notify(message: str) -> None:
    log.info("InitiativeEngine [notify]: %s", message[:200])


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine: InitiativeEngine | None = None
_engine_lock = threading.Lock()


def get_initiative_engine() -> InitiativeEngine:
    """Return the process-level InitiativeEngine (call .start() to activate)."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = InitiativeEngine()
    return _engine
