# thomas/observability/run_db.py
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ENV_DB_PATH = "THOMAS_RUNS_DB_PATH"

BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  started_at TEXT,
  ended_at TEXT,
  ok INTEGER,
  error TEXT,
  meta_json TEXT,
  last_seq INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  t_ms INTEGER,
  seq INTEGER,
  event_type TEXT,
  payload_json TEXT,
  FOREIGN KEY(run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, seq, id);
"""


def resolve_runs_db_path() -> Path:
    env = os.getenv(ENV_DB_PATH, "").strip()
    if env:
        return Path(env)

    # Try to reuse an existing run_store if present in repo.
    try:
        from thomas.observability import run_store  # type: ignore

        for attr in ("RUNS_DB_PATH", "DB_PATH", "db_path"):
            p = getattr(run_store, attr, None)
            if p:
                return Path(p)
        if hasattr(run_store, "get_db_path"):
            return Path(run_store.get_db_path())  # type: ignore
    except ImportError:
        pass

    return Path.home() / ".thomas" / "runs.sqlite3"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    return con


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    cur = con.execute(f"PRAGMA table_info({table})")
    return {str(r["name"]) for r in cur.fetchall()}


def _add_column(con: sqlite3.Connection, table: str, col: str, ddl: str) -> None:
    cols = _table_columns(con, table)
    if col in cols:
        return
    con.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def ensure_schema(db_path: Path) -> None:
    con = connect(db_path)
    try:
        con.executescript(BASE_SCHEMA)
        # If tables pre-existed, ensure critical columns exist.
        if "runs" in {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
            _add_column(con, "runs", "meta_json", "meta_json TEXT")
            _add_column(con, "runs", "last_seq", "last_seq INTEGER DEFAULT 0")
            _add_column(con, "runs", "ok", "ok INTEGER")
            _add_column(con, "runs", "error", "error TEXT")
            _add_column(con, "runs", "started_at", "started_at TEXT")
            _add_column(con, "runs", "ended_at", "ended_at TEXT")
        if "events" in {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
            _add_column(con, "events", "t_ms", "t_ms INTEGER")
            _add_column(con, "events", "seq", "seq INTEGER")
            _add_column(con, "events", "event_type", "event_type TEXT")
            _add_column(con, "events", "payload_json", "payload_json TEXT")

        con.commit()
    finally:
        con.close()
