from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from croniter import croniter

logger = logging.getLogger(__name__)


# ============================================================
# Time + serialization helpers
# ============================================================

def _now_local() -> datetime:
    """Local tz-aware time. Cron is interpreted in local time by default."""
    return datetime.now().astimezone()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _from_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            # If naive, assume local time.
            return dt.astimezone()
        return dt
    except Exception:
        return None


def _atomic_write_json(path: Path, payload: Any) -> None:
    """
    Atomic JSON write:
      - write to tmp file
      - fsync
      - replace
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ============================================================
# Cross-platform instance lock (prevents double-firing if Thomas runs twice)
# ============================================================

class _InstanceLock:
    """
    Best-effort single-process-instance lock using an OS-level file lock.
    If lock can't be acquired, scheduler will not start its polling loop.
    """

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._fh = None
        self.acquired = False

    def acquire(self) -> bool:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._lock_path, "a+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt  # type: ignore

                # lock 1 byte, non-blocking
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl  # type: ignore

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.acquired = True
            return True
        except Exception:
            self.acquired = False
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None
            return False

    def release(self) -> None:
        if not self._fh:
            return
        try:
            if os.name == "nt":
                import msvcrt  # type: ignore
                try:
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
            else:
                import fcntl  # type: ignore
                try:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
        finally:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None
            self.acquired = False


# ============================================================
# Best-effort integrations (events + persistence)
# ============================================================

def _best_effort_emit(event_name: str, payload: dict) -> None:
    """
    Optional integration with thomas/core/events.py.
    If an EventType member matches, use it; otherwise emit by name.
    Never raises.
    """
    try:
        from thomas.core import events as ev  # type: ignore

        emitter = None
        for fn in ("emit", "publish", "dispatch", "push"):
            if hasattr(ev, fn):
                emitter = getattr(ev, fn)
                break
        if emitter is None:
            return

        et = None
        if hasattr(ev, "EventType"):
            EventType = ev.EventType
            for candidate in (
                event_name,
                event_name.upper(),
                f"SCHEDULER_{event_name.upper()}",
                f"SCHEDULE_{event_name.upper()}",
            ):
                if hasattr(EventType, candidate):
                    et = getattr(EventType, candidate)
                    break

        if et is not None:
            emitter(et, payload)
        else:
            emitter(event_name, payload)
    except Exception:
        return


def _best_effort_pe_set(key: str, value: Any) -> None:
    """Optional integration with thomas.core.persistence.get_persistence().set_fact."""
    try:
        from thomas.core.persistence import get_persistence  # type: ignore

        pe = get_persistence()
        pe.set_fact(key, value)
    except Exception:
        return


# ============================================================
# Cron parsing (STRICT 5-field, plus user-friendly shorthands)
# ============================================================

_SHORTHANDS: dict[str, str] = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}


_EVERY_MIN_RE = re.compile(r"^\s*every\s+(\d+)\s+minutes?\s*$", re.IGNORECASE)
_EVERY_HOUR_RE = re.compile(r"^\s*every\s+hour\s*$", re.IGNORECASE)
_EVERY_DAY_RE = re.compile(r"^\s*every\s+day\s*$", re.IGNORECASE)


def _normalize_cron(expr: str) -> str:
    """
    Consumer-friendly cron input:
    - Accepts strict 5-field cron: "0 9 * * 1-5"
    - Accepts common shorthands: "@daily", "@hourly", "@weekly"...
    - Accepts tiny natural language:
        "every 15 minutes" -> "*/15 * * * *"
        "every hour"       -> "0 * * * *"
        "every day"        -> "0 0 * * *"
    Stores canonical 5-field cron.
    """
    expr = (expr or "").strip()
    if not expr:
        raise ValueError("Cron cannot be empty.")

    low = expr.lower()
    if low in _SHORTHANDS:
        expr = _SHORTHANDS[low]

    m = _EVERY_MIN_RE.match(expr)
    if m:
        n = int(m.group(1))
        if n <= 0 or n > 60:
            raise ValueError("For 'every N minutes', N must be between 1 and 60.")
        expr = f"*/{n} * * * *"
    elif _EVERY_HOUR_RE.match(expr):
        expr = "0 * * * *"
    elif _EVERY_DAY_RE.match(expr):
        expr = "0 0 * * *"

    # STRICT 5-field check
    parts = [p for p in expr.split() if p.strip()]
    if len(parts) != 5:
        raise ValueError(
            f"Cron must be standard 5-field format: 'min hour day month weekday'. "
            f"Got {len(parts)} fields: {expr}"
        )
    if not croniter.is_valid(expr):
        raise ValueError(f"Invalid cron expression: {expr}")
    return expr


def _cron_human_hint(expr: str) -> str:
    """
    Tiny humanization for common crons.
    (Not exhaustive; no extra dependencies.)
    """
    try:
        parts = expr.split()
        if parts == ["0", "*", "*", "*", "*"]:
            return "hourly"
        if parts == ["0", "0", "*", "*", "*"]:
            return "daily at midnight"
        if parts[0].startswith("*/") and parts[1:] == ["*", "*", "*", "*"]:
            return f"every {parts[0][2:]} minutes"
        if parts[0] == "0" and parts[2:] == ["*", "*", "1-5"]:
            return f"weekdays at {parts[1]}:00"
    except Exception:
        pass
    return ""


# ============================================================
# Data model (with consumer-friendly extras)
# ============================================================

@dataclass
class ScheduledTask:
    id: str
    cron_expr: str
    goal_text: str
    channel: str = "default"

    paused: bool = False

    # Misfire policy: what to do if Thomas was down and a run is "stale"
    # - "catch_up": fire up to catch_up_limit occurrences per poll tick (default)
    # - "skip": skip occurrences older than misfire_grace_s
    misfire_policy: str = "catch_up"
    misfire_grace_s: int = 3600  # 1 hour

    # Jitter: random delay [0, jitter_s] before executing to avoid herd-at-the-top
    jitter_s: int = 0

    created_at: str = field(default_factory=lambda: _iso(_now_local()) or "")
    updated_at: str = field(default_factory=lambda: _iso(_now_local()) or "")

    # Execution bookkeeping
    last_fire_at: str | None = None
    last_scheduled_for: str | None = None
    next_run_at: str | None = None

    last_error: str | None = None

    # Bounded run history (kept small, great for UX)
    run_history: list[dict] = field(default_factory=list)

    def status(self) -> str:
        return "paused" if self.paused else "active"

    def next_run_dt(self) -> datetime | None:
        return _from_iso(self.next_run_at)


# ============================================================
# TaskScheduler
# ============================================================

class TaskScheduler:
    """
    Persistent scheduled task system (cron, strict 5-field).

    "Consumer delight" features:
    - Friendly cron shorthands + tiny natural language parsing
    - Instance lock prevents duplicate firing if Thomas runs twice
    - Bounded concurrency (thread pool)
    - Misfire policy (catch_up vs skip stale)
    - Optional jitter to reduce thundering herd
    - Bounded per-task run history for visibility
    """

    def __init__(
        self,
        execute_fn: Callable[[str, str], None],
        schedule_path: str | Path = "./thomas_schedules.json",
        poll_interval_s: int = 30,
        catch_up_limit: int = 1,
        max_workers: int = 4,
        now_fn: Callable[[], datetime] = _now_local,
        auto_start: bool = True,
    ) -> None:
        if execute_fn is None:
            raise ValueError("TaskScheduler requires execute_fn(goal_text, channel).")

        self._execute_fn = execute_fn
        self._path = Path(schedule_path)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")

        self._poll_interval_s = int(poll_interval_s)
        self._catch_up_limit = max(1, int(catch_up_limit))
        self._now = now_fn

        self._lock = threading.RLock()
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None

        self._instance_lock = _InstanceLock(self._lock_path)
        self._instance_lock_acquired = False

        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)),
            thread_name_prefix="TaskExec",
        )

        self._tasks: dict[str, ScheduledTask] = {}

        self._load()
        self._repair_next_runs()

        if auto_start:
            self.start()

    # --------------------------
    # Lifecycle
    # --------------------------

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            # Acquire instance lock; if not, do not start polling thread.
            self._instance_lock_acquired = self._instance_lock.acquire()
            if not self._instance_lock_acquired:
                logger.warning(
                    "TaskScheduler did not start polling because instance lock is held by another process: %s",
                    self._lock_path,
                )
                return

            self._stop_evt.clear()
            self._thread = threading.Thread(target=self._run_loop, name="TaskScheduler", daemon=True)
            self._thread.start()

        logger.info(
            "TaskScheduler started (poll=%ss catch_up_limit=%s workers=%s)",
            self._poll_interval_s,
            self._catch_up_limit,
            getattr(self._executor, "_max_workers", "?"),
        )

    def stop(self) -> None:
        self._stop_evt.set()
        t = None
        with self._lock:
            t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.0)

        self._executor.shutdown(wait=False, cancel_futures=False)

        if self._instance_lock_acquired:
            self._instance_lock.release()
            self._instance_lock_acquired = False

    def set_execute_fn(self, execute_fn: Callable[[str, str], None], start_if_needed: bool = True) -> None:
        if execute_fn is None:
            raise ValueError("execute_fn cannot be None")
        with self._lock:
            self._execute_fn = execute_fn
            if start_if_needed and not (self._thread and self._thread.is_alive()):
                self.start()

    def health(self) -> dict:
        with self._lock:
            return {
                "running": bool(self._thread and self._thread.is_alive()),
                "instance_lock": bool(self._instance_lock_acquired),
                "tasks": len(self._tasks),
                "poll_interval_s": self._poll_interval_s,
                "catch_up_limit": self._catch_up_limit,
                "max_workers": getattr(self._executor, "_max_workers", None),
            }

    # --------------------------
    # Required API
    # --------------------------

    def add_task(self, id: str, cron_expr: str, goal_text: str, channel: str = "default") -> None:
        """
        Adds (or updates) a scheduled task.
        Upsert behavior is intentionally consumer-friendly: same id replaces definition.
        """
        task_id = (id or "").strip()
        if not task_id:
            raise ValueError("Task id cannot be empty.")

        cron_expr = _normalize_cron(cron_expr)
        now = self._now()

        with self._lock:
            existing = self._tasks.get(task_id)
            if existing:
                existing.cron_expr = cron_expr
                existing.goal_text = goal_text
                existing.channel = channel or "default"
                existing.paused = False
                existing.next_run_at = _iso(self._next_after(cron_expr, base=now))
                existing.updated_at = _iso(now) or existing.updated_at
                existing.last_error = None
            else:
                t = ScheduledTask(
                    id=task_id,
                    cron_expr=cron_expr,
                    goal_text=goal_text,
                    channel=(channel or "default"),
                )
                t.next_run_at = _iso(self._next_after(cron_expr, base=now))
                t.updated_at = _iso(now) or t.updated_at
                self._tasks[task_id] = t

            self._persist_locked()

        _best_effort_emit("task_added", {"id": task_id, "cron": cron_expr, "channel": channel or "default"})
        _best_effort_pe_set(f"scheduler.task.{task_id}", {"cron": cron_expr, "channel": channel or "default", "task": goal_text})

    def remove_task(self, id: str) -> None:
        task_id = (id or "").strip()
        with self._lock:
            existed = task_id in self._tasks
            if existed:
                del self._tasks[task_id]
                self._persist_locked()
        if existed:
            _best_effort_emit("task_removed", {"id": task_id})
            _best_effort_pe_set(f"scheduler.task.{task_id}", None)

    def list_tasks(self) -> list[dict]:
        with self._lock:
            tasks = list(self._tasks.values())
        tasks.sort(key=lambda x: x.id.lower())
        return [
            {
                "id": t.id,
                "cron": t.cron_expr,
                "cron_hint": _cron_human_hint(t.cron_expr),
                "next_run": t.next_run_at,
                "task": t.goal_text,
                "status": t.status(),
                "channel": t.channel,
                "last_fire": t.last_fire_at,
                "last_scheduled_for": t.last_scheduled_for,
                "last_error": t.last_error,
                "misfire_policy": t.misfire_policy,
                "misfire_grace_s": t.misfire_grace_s,
                "jitter_s": t.jitter_s,
                "run_history": list(t.run_history),
            }
            for t in tasks
        ]

    def pause_task(self, id: str) -> None:
        task_id = (id or "").strip()
        now = self._now()
        with self._lock:
            t = self._require(task_id)
            t.paused = True
            t.next_run_at = None
            t.updated_at = _iso(now) or t.updated_at
            self._persist_locked()
        _best_effort_emit("task_paused", {"id": task_id})

    def resume_task(self, id: str) -> None:
        task_id = (id or "").strip()
        now = self._now()
        with self._lock:
            t = self._require(task_id)
            t.cron_expr = _normalize_cron(t.cron_expr)
            t.paused = False
            t.next_run_at = _iso(self._next_after(t.cron_expr, base=now))
            t.updated_at = _iso(now) or t.updated_at
            self._persist_locked()
        _best_effort_emit("task_resumed", {"id": task_id})

    # --------------------------
    # Tool support
    # --------------------------

    def run_now(self, id: str, ignore_paused: bool = True) -> None:
        task_id = (id or "").strip()
        now = self._now()

        with self._lock:
            t = self._require(task_id)
            if t.paused and not ignore_paused:
                raise ValueError(f"Task '{task_id}' is paused.")

            # Persist-before-execute
            t.last_fire_at = _iso(now)
            t.last_scheduled_for = _iso(now)
            t.last_error = None
            t.next_run_at = _iso(self._next_after(t.cron_expr, base=now))
            t.updated_at = _iso(now) or t.updated_at
            self._persist_locked()

        _best_effort_emit("task_run_now", {"id": task_id, "at": _iso(now)})
        self._submit_execution(t, scheduled_for=now)

    def preview_next(self, id: str, count: int = 5) -> list[str]:
        task_id = (id or "").strip()
        with self._lock:
            t = self._require(task_id)
            cron_expr = _normalize_cron(t.cron_expr)
            base = self._now()
        it = croniter(cron_expr, base)
        out = []
        for _ in range(max(0, min(50, int(count)))):
            nxt = it.get_next(datetime)
            if nxt.tzinfo is None:
                nxt = nxt.replace(tzinfo=base.tzinfo)
            out.append(nxt.isoformat())
        return out

    def update_task(self, id: str, cron: str | None = None, task: str | None = None,
                    channel: str | None = None, misfire_policy: str | None = None,
                    misfire_grace_s: int | None = None, jitter_s: int | None = None) -> None:
        """
        Consumer-friendly update without removing/re-adding.
        """
        task_id = (id or "").strip()
        now = self._now()
        with self._lock:
            t = self._require(task_id)

            if cron is not None:
                t.cron_expr = _normalize_cron(cron)
            if task is not None:
                t.goal_text = task
            if channel is not None:
                t.channel = channel or "default"
            if misfire_policy is not None:
                mp = (misfire_policy or "").strip().lower()
                if mp not in ("catch_up", "skip"):
                    raise ValueError("misfire_policy must be 'catch_up' or 'skip'")
                t.misfire_policy = mp
            if misfire_grace_s is not None:
                t.misfire_grace_s = max(0, int(misfire_grace_s))
            if jitter_s is not None:
                t.jitter_s = max(0, int(jitter_s))

            if not t.paused:
                t.next_run_at = _iso(self._next_after(t.cron_expr, base=now))
            t.updated_at = _iso(now) or t.updated_at
            self._persist_locked()

        _best_effort_emit("task_updated", {"id": task_id})

    # ============================================================
    # Internals
    # ============================================================

    def _require(self, task_id: str) -> ScheduledTask:
        t = self._tasks.get(task_id)
        if not t:
            raise KeyError(f"Unknown task id: {task_id}")
        return t

    def _next_after(self, cron_expr: str, base: datetime) -> datetime:
        """
        Next scheduled time strictly after `base`.
        """
        it = croniter(cron_expr, base)
        nxt = it.get_next(datetime)
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=base.tzinfo)
        return nxt

    def _load(self) -> None:
        if not self._path.exists():
            self._tasks = {}
            return

        try:
            with open(self._path, encoding="utf-8") as f:
                raw = json.load(f)

            items = raw.get("tasks", [])
            tasks: dict[str, ScheduledTask] = {}

            for item in items:
                try:
                    t = ScheduledTask(
                        id=item["id"],
                        cron_expr=item["cron_expr"],
                        goal_text=item.get("goal_text", ""),
                        channel=item.get("channel", "default"),
                        paused=bool(item.get("paused", False)),
                        misfire_policy=item.get("misfire_policy", "catch_up"),
                        misfire_grace_s=int(item.get("misfire_grace_s", 3600) or 3600),
                        jitter_s=int(item.get("jitter_s", 0) or 0),
                        created_at=item.get("created_at") or (_iso(self._now()) or ""),
                        updated_at=item.get("updated_at") or (_iso(self._now()) or ""),
                        last_fire_at=item.get("last_fire_at"),
                        last_scheduled_for=item.get("last_scheduled_for"),
                        next_run_at=item.get("next_run_at"),
                        last_error=item.get("last_error"),
                        run_history=list(item.get("run_history", []) or []),
                    )

                    # Normalize/validate cron; if invalid, pause to avoid poison-pill behavior.
                    try:
                        t.cron_expr = _normalize_cron(t.cron_expr)
                    except Exception as e:
                        t.paused = True
                        t.last_error = f"Invalid cron on load (paused): {e}"
                        t.next_run_at = None

                    # Clamp run_history size
                    if len(t.run_history) > 30:
                        t.run_history = t.run_history[-30:]

                    tasks[t.id] = t
                except Exception:
                    continue

            self._tasks = tasks
            logger.info("Loaded %d scheduled tasks from %s", len(self._tasks), self._path)
        except Exception as e:
            logger.exception("Failed to load schedules from %s: %s", self._path, e)
            self._tasks = {}

    def _persist_locked(self) -> None:
        payload = {
            "version": 4,
            "updated_at": _iso(self._now()),
            "tasks": [asdict(t) for t in self._tasks.values()],
        }
        _atomic_write_json(self._path, payload)

    def _repair_next_runs(self) -> None:
        """
        Ensure all active tasks have a next_run computed.
        """
        now = self._now()
        changed = False

        with self._lock:
            for t in self._tasks.values():
                if t.paused:
                    continue
                try:
                    t.cron_expr = _normalize_cron(t.cron_expr)
                except Exception as e:
                    t.paused = True
                    t.last_error = f"Invalid cron (paused): {e}"
                    t.next_run_at = None
                    changed = True
                    continue

                if t.next_run_dt() is None:
                    t.next_run_at = _iso(self._next_after(t.cron_expr, base=now))
                    t.updated_at = _iso(now) or t.updated_at
                    changed = True

            if changed:
                self._persist_locked()

    def _run_loop(self) -> None:
        while not self._stop_evt.is_set():
            started = time.time()
            try:
                self._poll_once()
            except Exception:
                logger.exception("Scheduler poll error")
            elapsed = time.time() - started
            sleep_for = max(0.0, self._poll_interval_s - elapsed)
            self._stop_evt.wait(sleep_for)

    def _poll_once(self) -> None:
        """
        Find due tasks, advance their schedules, persist, then execute.

        Misfire policy:
        - "catch_up": fire up to catch_up_limit occurrences per poll tick
        - "skip": if occurrence is older than misfire_grace_s, skip it (advance schedule)
        """
        now = self._now()
        fires: list[tuple[str, datetime]] = []

        with self._lock:
            for t in self._tasks.values():
                if t.paused:
                    continue

                try:
                    t.cron_expr = _normalize_cron(t.cron_expr)
                except Exception as e:
                    t.paused = True
                    t.last_error = f"Invalid cron (paused): {e}"
                    t.next_run_at = None
                    t.updated_at = _iso(now) or t.updated_at
                    continue

                nxt = t.next_run_dt()
                if nxt is None:
                    t.next_run_at = _iso(self._next_after(t.cron_expr, base=now))
                    t.updated_at = _iso(now) or t.updated_at
                    continue

                if now < nxt:
                    continue

                due_count = 0
                scheduled_for = nxt

                it = croniter(t.cron_expr, scheduled_for - timedelta(seconds=1))

                # Skip stale runs aggressively when policy is "skip". If we missed
                # beyond the grace window, fast-forward to the next future slot and
                # do not fire in this poll tick.
                if t.misfire_policy == "skip":
                    initial_age_s = (now - scheduled_for).total_seconds()
                    if initial_age_s > float(t.misfire_grace_s):
                        guard = 0
                        while scheduled_for <= now and guard < 500:
                            scheduled_for = it.get_next(datetime)
                            if scheduled_for.tzinfo is None:
                                scheduled_for = scheduled_for.replace(tzinfo=now.tzinfo)
                            guard += 1
                        t.next_run_at = _iso(scheduled_for)
                        t.updated_at = _iso(now) or t.updated_at
                        continue

                while now >= scheduled_for and due_count < self._catch_up_limit:
                    age_s = (now - scheduled_for).total_seconds()
                    if t.misfire_policy == "skip" and age_s > float(t.misfire_grace_s):
                        # stale, skip without firing
                        pass
                    else:
                        fires.append((t.id, scheduled_for))
                        due_count += 1

                    scheduled_for = it.get_next(datetime)
                    if scheduled_for.tzinfo is None:
                        scheduled_for = scheduled_for.replace(tzinfo=now.tzinfo)

                # Ensure next_run is future (guard)
                guard = 0
                while scheduled_for <= now and guard < 50:
                    scheduled_for = it.get_next(datetime)
                    if scheduled_for.tzinfo is None:
                        scheduled_for = scheduled_for.replace(tzinfo=now.tzinfo)
                    guard += 1

                t.next_run_at = _iso(scheduled_for)
                t.updated_at = _iso(now) or t.updated_at

            if fires:
                self._persist_locked()

        for task_id, scheduled_for_dt in fires:
            with self._lock:
                t = self._tasks.get(task_id)
                if not t:
                    continue
                fire_time = self._now()
                t.last_fire_at = _iso(fire_time)
                t.last_scheduled_for = _iso(scheduled_for_dt)
                t.last_error = None
                t.updated_at = _iso(fire_time) or t.updated_at
                self._persist_locked()

            _best_effort_pe_set(f"scheduler.last_fired.{task_id}", t.last_fire_at)
            _best_effort_emit("task_fired", {"id": task_id, "scheduled_for": _iso(scheduled_for_dt)})
            self._submit_execution(t, scheduled_for=scheduled_for_dt)

    def _submit_execution(self, task: ScheduledTask, scheduled_for: datetime) -> None:
        """
        Submit execution to bounded pool.
        Stores run history (cap 30) with duration + error.
        Applies optional jitter.
        """
        task_id = task.id
        goal_text = task.goal_text
        channel = task.channel
        jitter = max(0, int(task.jitter_s or 0))

        started_at = self._now()

        def _run() -> None:
            if jitter > 0:
                time.sleep(random.random() * float(jitter))
            self._execute_fn(goal_text, channel)

        fut: Future = self._executor.submit(_run)

        def _done(f: Future) -> None:
            finished_at = self._now()
            duration_ms = int(max(0.0, (finished_at - started_at).total_seconds()) * 1000.0)
            exc = f.exception()

            entry = {
                "scheduled_for": _iso(scheduled_for),
                "started_at": _iso(started_at),
                "finished_at": _iso(finished_at),
                "duration_ms": duration_ms,
                "ok": exc is None,
                "error": None if exc is None else str(exc),
            }

            with self._lock:
                t = self._tasks.get(task_id)
                if t:
                    t.run_history.append(entry)
                    if len(t.run_history) > 30:
                        t.run_history = t.run_history[-30:]
                    if exc is not None:
                        t.last_error = str(exc)
                    t.updated_at = _iso(self._now()) or t.updated_at
                    self._persist_locked()

            if exc is not None:
                _best_effort_emit("task_failed", {"id": task_id, "error": str(exc), "scheduled_for": _iso(scheduled_for)})

        fut.add_done_callback(_done)


# ============================================================
# Singleton
# ============================================================

_SCHED: TaskScheduler | None = None
_SCHED_LOCK = threading.Lock()


def get_scheduler(execute_fn: Callable[[str, str], None] | None = None) -> TaskScheduler:
    """
    Singleton accessor.

    Best wiring:
      - Call once at app startup with execute_fn.
      - Later calls from tools use get_scheduler() with no args.

    If called first with no execute_fn, we create a scheduler with a placeholder
    executor and do not auto-start until a real executor is set.
    """
    global _SCHED
    with _SCHED_LOCK:
        if _SCHED is None:
            if execute_fn is None:
                def _missing(goal_text: str, channel: str) -> None:
                    raise RuntimeError(
                        "Scheduler execute_fn is not configured. "
                        "Call get_scheduler(execute_fn=...) once at app startup."
                    )
                _SCHED = TaskScheduler(execute_fn=_missing, auto_start=False)
            else:
                _SCHED = TaskScheduler(execute_fn=execute_fn, auto_start=True)
        else:
            if execute_fn is not None:
                _SCHED.set_execute_fn(execute_fn, start_if_needed=True)
        return _SCHED
