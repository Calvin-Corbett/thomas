"""
thomas/core/engine_manager.py
─────────────────────────────
Unified Engine Manager — starts ALL background engines automatically.

Engines managed:
  1. persistence    — cross-session state survival
  2. tool_factory   — reusable tool extraction
  3. initiative     — autonomous work when idle
  4. testing_suite  — background quality testing

Usage (automatic on server start):
    from thomas.core.engine_manager import EngineManager
    manager = EngineManager()
    manager.start_all()  # One call = everything alive

Consumer rules:
  - Normal user sees nothing complicated
  - Super-user toggle in Settings shows advanced stuff
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class EngineStatus:
    """Status of a single engine."""
    name: str
    running: bool = False
    started_at: Optional[str] = None
    error: Optional[str] = None
    cycles_completed: int = 0
    last_activity: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "running": self.running,
            "started_at": self.started_at,
            "error": self.error,
            "cycles_completed": self.cycles_completed,
            "last_activity": self.last_activity,
        }


class EngineManager:
    """
    Orchestrates all Thomas background engines.

    One call to start_all() brings up:
      - PersistenceEngine (state survival)
      - ToolFactory (reusable tools)
      - InitiativeEngine (idle autonomous work)
      - TestingSuite (background quality cycles)
    """

    def __init__(self) -> None:
        self._engines: Dict[str, Any] = {}
        self._status: Dict[str, EngineStatus] = {}
        self._lock = threading.Lock()
        self._running = False
        self._notify_fn: Optional[Callable[[str], None]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_all(
        self,
        executor_fn: Optional[Callable] = None,
        notify_fn: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, bool]:
        """
        Start all engines. Returns dict of {engine_name: success}.
        """
        self._notify_fn = notify_fn
        results = {}

        # 1. Persistence Engine (always first - others depend on it)
        results["persistence"] = self._start_persistence()

        # 2. Tool Factory
        results["tool_factory"] = self._start_tool_factory()

        # 3. Initiative Engine (autonomous work when idle)
        results["initiative"] = self._start_initiative(executor_fn, notify_fn)

        # 4. Testing Suite (background quality testing)
        results["testing_suite"] = self._start_testing_suite(executor_fn, notify_fn)

        self._running = True
        log.info("EngineManager: all engines started — %s", results)

        # Notify user (consumer-friendly)
        if notify_fn:
            started = [k for k, v in results.items() if v]
            notify_fn(f"🚀 Thomas engines active: {', '.join(started)}")

        return results

    def stop_all(self) -> None:
        """Stop all engines gracefully."""
        self._running = False

        # Stop initiative
        try:
            from thomas.core.initiative import get_initiative_engine
            get_initiative_engine().stop()
        except Exception:
            pass

        # Stop testing suite
        try:
            from thomas.core.testing_suite import get_testing_suite
            get_testing_suite().stop()
        except Exception:
            pass

        # Save persistence state
        try:
            from thomas.core.persistence import get_persistence
            get_persistence().save()
        except Exception:
            pass

        log.info("EngineManager: all engines stopped.")

    def status(self) -> Dict[str, Any]:
        """Return status of all engines."""
        with self._lock:
            return {
                "running": self._running,
                "engines": {k: v.to_dict() for k, v in self._status.items()},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def is_running(self) -> bool:
        return self._running

    def record_user_message(self) -> None:
        """Reset idle timers on all engines."""
        try:
            from thomas.core.initiative import get_initiative_engine
            get_initiative_engine().record_user_message()
        except Exception:
            pass
        try:
            from thomas.core.testing_suite import get_testing_suite
            get_testing_suite().record_user_message()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Engine startup helpers
    # ------------------------------------------------------------------

    def _start_persistence(self) -> bool:
        """Start persistence engine."""
        name = "persistence"
        try:
            from thomas.core.persistence import get_persistence
            pe = get_persistence()
            pe.load()
            self._engines[name] = pe
            self._status[name] = EngineStatus(
                name=name,
                running=True,
                started_at=datetime.now(timezone.utc).isoformat(),
            )
            log.info("PersistenceEngine: started (%d turns, %d goals)",
                     len(pe.turn_history), len(pe.goals))
            return True
        except Exception as e:
            log.error("PersistenceEngine: failed to start: %s", e)
            self._status[name] = EngineStatus(name=name, error=str(e))
            return False

    def _start_tool_factory(self) -> bool:
        """Start tool factory."""
        name = "tool_factory"
        try:
            from thomas.core.tool_factory import get_tool_factory
            tf = get_tool_factory()
            count = tf.load()
            self._engines[name] = tf
            self._status[name] = EngineStatus(
                name=name,
                running=True,
                started_at=datetime.now(timezone.utc).isoformat(),
                cycles_completed=count,
            )
            log.info("ToolFactory: started (%d tools loaded)", count)
            return True
        except Exception as e:
            log.error("ToolFactory: failed to start: %s", e)
            self._status[name] = EngineStatus(name=name, error=str(e))
            return False

    def _start_initiative(
        self,
        executor_fn: Optional[Callable],
        notify_fn: Optional[Callable[[str], None]],
    ) -> bool:
        """Start initiative engine (autonomous work when idle)."""
        name = "initiative"
        try:
            from thomas.core.initiative import get_initiative_engine
            ie = get_initiative_engine()
            ie.start(executor_fn=executor_fn, notify_fn=notify_fn)
            self._engines[name] = ie
            self._status[name] = EngineStatus(
                name=name,
                running=True,
                started_at=datetime.now(timezone.utc).isoformat(),
            )
            log.info("InitiativeEngine: started (idle threshold: 30min)")
            return True
        except Exception as e:
            log.error("InitiativeEngine: failed to start: %s", e)
            self._status[name] = EngineStatus(name=name, error=str(e))
            return False

    def _start_testing_suite(
        self,
        executor_fn: Optional[Callable],
        notify_fn: Optional[Callable[[str], None]],
    ) -> bool:
        """Start testing suite (background quality testing)."""
        name = "testing_suite"
        try:
            from thomas.core.testing_suite import get_testing_suite
            ts = get_testing_suite()
            ts.start(executor_fn=executor_fn, notify_fn=notify_fn)
            self._engines[name] = ts
            self._status[name] = EngineStatus(
                name=name,
                running=True,
                started_at=datetime.now(timezone.utc).isoformat(),
            )
            log.info("TestingSuite: started (cycle interval: 15min)")
            return True
        except Exception as e:
            log.error("TestingSuite: failed to start: %s", e)
            self._status[name] = EngineStatus(name=name, error=str(e))
            return False

    # ------------------------------------------------------------------
    # Summary for UI
    # ------------------------------------------------------------------

    def summary_text(self) -> str:
        """Human-readable summary for UI/tray."""
        lines = ["## Thomas Engine Status"]
        for name, st in self._status.items():
            status = "✅" if st.running else "❌"
            lines.append(f"- {status} **{name}**: {'running' if st.running else st.error or 'stopped'}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_manager: Optional[EngineManager] = None
_manager_lock = threading.Lock()


def get_engine_manager() -> EngineManager:
    """Return the process-level EngineManager singleton."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = EngineManager()
    return _manager
