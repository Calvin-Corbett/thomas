"""Durable per-session task state ledger.

This module stores a compact task state snapshot per session and keeps a
history stream that can be consumed by API/inspector UIs.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core.config import resolve_thomas_data_dir

ENV_TASK_LEDGER_DB_PATH = "THOMAS_TASK_LEDGER_DB_PATH"
_VALID_STATUSES = {"in_progress", "blocked", "complete"}
_MAX_ACTIVE_GOAL_LEN = 320
_MAX_PROGRESS_LEN = 1200
_MAX_MISSING_INPUTS = 10
_MAX_MISSING_ITEM_LEN = 180
_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_ledger (
  session_id TEXT PRIMARY KEY,
  active_goal TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'in_progress',
  missing_inputs_json TEXT NOT NULL DEFAULT '[]',
  last_progress TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_ledger_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  active_goal TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'in_progress',
  missing_inputs_json TEXT NOT NULL DEFAULT '[]',
  last_progress TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_ledger_events_session
ON task_ledger_events(session_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_task_ledger_updated
ON task_ledger(updated_at DESC);
"""


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact_ws(text: Any) -> str:
    raw = str(text or "")
    return " ".join(raw.split())


def _normalize_status(value: Any, *, fallback: str = "in_progress") -> str:
    status = str(value or "").strip().lower()
    if status not in _VALID_STATUSES:
        return fallback
    return status


def _normalize_goal(value: Any) -> str:
    goal = _compact_ws(value)
    if not goal:
        return ""
    return goal[:_MAX_ACTIVE_GOAL_LEN]


def _normalize_progress(value: Any) -> str:
    progress = _compact_ws(value)
    if not progress:
        return ""
    return progress[:_MAX_PROGRESS_LEN]


def _normalize_missing_inputs(values: Iterable[Any] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        item = _compact_ws(value)
        if not item:
            continue
        item = item.lstrip("-* ").strip()
        if not item:
            continue
        item = item[:_MAX_MISSING_ITEM_LEN]
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= _MAX_MISSING_INPUTS:
            break
    return out


def resolve_task_ledger_db_path(default_root: Path | None = None) -> Path:
    env = str(os.getenv(ENV_TASK_LEDGER_DB_PATH, "")).strip()
    if env:
        return Path(env)
    if default_root is not None:
        return Path(default_root) / ".thomas" / "task_ledger.sqlite3"
    return resolve_thomas_data_dir() / ".thomas" / "task_ledger.sqlite3"


@dataclass(frozen=True)
class TaskLedgerSnapshot:
    session_id: str
    active_goal: str
    status: str
    missing_inputs: list[str]
    last_progress: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "active_goal": self.active_goal,
            "status": self.status,
            "missing_inputs": list(self.missing_inputs),
            "last_progress": self.last_progress,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def derive_active_goal(
    user_text: Any,
    *,
    current_goal: str = "",
    route_input_source: str = "",
) -> str:
    text = _normalize_goal(user_text)
    if not text:
        return _normalize_goal(current_goal)

    # Retained for compatibility only. Prompt wording never decides whether a
    # turn is an acknowledgement or a follow-up.
    _ = route_input_source

    # Title the task with a real, human-readable name instead of the raw user
    # text ("hey thomas can you please build me a pac-man game" -> "Build a
    # pac-man game"). This is the task-card title Calvin flagged as too generic.
    # Function-local import keeps this leaf util off the module load path.
    from thomas.core.task_titling import derive_task_title

    return _normalize_goal(derive_task_title(user_text)) or text


def _snapshot_from_row(row: sqlite3.Row) -> TaskLedgerSnapshot:
    raw_missing = str(row["missing_inputs_json"] or "[]")
    try:
        parsed = json.loads(raw_missing)
    except json.JSONDecodeError:
        parsed = []
    missing_inputs = _normalize_missing_inputs(parsed if isinstance(parsed, list) else [])
    return TaskLedgerSnapshot(
        session_id=str(row["session_id"] or ""),
        active_goal=_normalize_goal(row["active_goal"]),
        status=_normalize_status(row["status"]),
        missing_inputs=missing_inputs,
        last_progress=_normalize_progress(row["last_progress"]),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
    )


class TaskLedgerStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self.ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self.db_path))
        con.row_factory = sqlite3.Row
        return con

    def ensure_schema(self) -> None:
        with self._lock:
            con = self._connect()
            try:
                con.executescript(_SCHEMA)
                con.commit()
            finally:
                con.close()

    def get_current(self, session_id: str) -> TaskLedgerSnapshot | None:
        sid = str(session_id or "").strip()
        if not sid:
            return None
        con = self._connect()
        try:
            row = con.execute(
                """
                SELECT session_id, active_goal, status, missing_inputs_json, last_progress, created_at, updated_at
                FROM task_ledger
                WHERE session_id = ?
                """,
                (sid,),
            ).fetchone()
        finally:
            con.close()
        if row is None:
            return None
        return _snapshot_from_row(row)

    def get_latest(self) -> TaskLedgerSnapshot | None:
        con = self._connect()
        try:
            row = con.execute(
                """
                SELECT session_id, active_goal, status, missing_inputs_json, last_progress, created_at, updated_at
                FROM task_ledger
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ).fetchone()
        finally:
            con.close()
        if row is None:
            return None
        return _snapshot_from_row(row)

    def get_history(self, session_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        sid = str(session_id or "").strip()
        if not sid:
            return []
        row_limit = max(1, min(int(limit), 200))
        con = self._connect()
        try:
            rows = con.execute(
                """
                SELECT id, session_id, active_goal, status, missing_inputs_json, last_progress, source, created_at
                FROM task_ledger_events
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (sid, row_limit),
            ).fetchall()
        finally:
            con.close()

        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                parsed_missing = json.loads(str(row["missing_inputs_json"] or "[]"))
            except json.JSONDecodeError:
                parsed_missing = []
            events.append(
                {
                    "id": int(row["id"]),
                    "session_id": str(row["session_id"] or ""),
                    "active_goal": _normalize_goal(row["active_goal"]),
                    "status": _normalize_status(row["status"]),
                    "missing_inputs": _normalize_missing_inputs(parsed_missing),
                    "last_progress": _normalize_progress(row["last_progress"]),
                    "source": str(row["source"] or ""),
                    "created_at": str(row["created_at"] or ""),
                }
            )
        return events

    def update(
        self,
        session_id: str,
        *,
        active_goal: Any = None,
        status: Any = None,
        missing_inputs: Iterable[Any] | None = None,
        last_progress: Any = None,
        source: str = "",
        force_event: bool = False,
    ) -> TaskLedgerSnapshot:
        sid = str(session_id or "").strip()
        if not sid:
            raise ValueError("session_id is required")

        with self._lock:
            con = self._connect()
            try:
                con.execute("BEGIN IMMEDIATE")
                row = con.execute(
                    """
                    SELECT session_id, active_goal, status, missing_inputs_json, last_progress, created_at, updated_at
                    FROM task_ledger
                    WHERE session_id = ?
                    """,
                    (sid,),
                ).fetchone()

                now_iso = _now_iso_utc()
                if row is None:
                    current = TaskLedgerSnapshot(
                        session_id=sid,
                        active_goal="",
                        status="in_progress",
                        missing_inputs=[],
                        last_progress="",
                        created_at=now_iso,
                        updated_at=now_iso,
                    )
                else:
                    current = _snapshot_from_row(row)

                next_active_goal = current.active_goal if active_goal is None else _normalize_goal(active_goal)
                next_status = current.status if status is None else _normalize_status(status, fallback=current.status)
                next_missing_inputs = (
                    current.missing_inputs if missing_inputs is None else _normalize_missing_inputs(missing_inputs)
                )
                next_last_progress = (
                    current.last_progress if last_progress is None else _normalize_progress(last_progress)
                )
                changed = (
                    row is None
                    or next_active_goal != current.active_goal
                    or next_status != current.status
                    or next_missing_inputs != current.missing_inputs
                    or next_last_progress != current.last_progress
                )

                created_at = current.created_at if row is not None else now_iso
                updated_at = now_iso if changed else current.updated_at
                missing_json = json.dumps(next_missing_inputs, ensure_ascii=False)

                con.execute(
                    """
                    INSERT INTO task_ledger(
                        session_id, active_goal, status, missing_inputs_json, last_progress, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        active_goal=excluded.active_goal,
                        status=excluded.status,
                        missing_inputs_json=excluded.missing_inputs_json,
                        last_progress=excluded.last_progress,
                        updated_at=excluded.updated_at
                    """,
                    (
                        sid,
                        next_active_goal,
                        next_status,
                        missing_json,
                        next_last_progress,
                        created_at,
                        updated_at,
                    ),
                )

                if changed or force_event:
                    con.execute(
                        """
                        INSERT INTO task_ledger_events(
                            session_id, active_goal, status, missing_inputs_json, last_progress, source, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            sid,
                            next_active_goal,
                            next_status,
                            missing_json,
                            next_last_progress,
                            str(source or ""),
                            now_iso,
                        ),
                    )

                con.commit()
            finally:
                con.close()

        return TaskLedgerSnapshot(
            session_id=sid,
            active_goal=next_active_goal,
            status=next_status,
            missing_inputs=next_missing_inputs,
            last_progress=next_last_progress,
            created_at=created_at,
            updated_at=updated_at,
        )
