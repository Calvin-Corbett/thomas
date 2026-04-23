# tests/_replay_test_db.py
from __future__ import annotations
import sqlite3
from pathlib import Path

SCHEMA_SQL = """
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

def init_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    try:
        con.executescript(SCHEMA_SQL)
        con.commit()
    finally:
        con.close()

def seed_run(path: Path, run_id: str = "run_test_1") -> None:
    con = sqlite3.connect(str(path))
    try:
        con.execute(
            "INSERT INTO runs(run_id, ok, last_seq) VALUES (?, ?, ?)",
            (run_id, 0, 0),
        )
        events = [
            (run_id, 0, 2, "prompt", '{"text":"hello"}'),
            (run_id, 5, 1, "tool.call", '{"name":"secret_tool","authorization":"Bearer abcdef"}'),
            (run_id, 8, 3, "tool.output", '{"result":"ok","api_key":"sk-THIS_SHOULD_NOT_LEAK"}'),
        ]
        con.executemany(
            "INSERT INTO events(run_id, t_ms, seq, event_type, payload_json) VALUES (?, ?, ?, ?, ?)",
            events,
        )
        con.execute("UPDATE runs SET last_seq = 3 WHERE run_id = ?", (run_id,))
        con.commit()
    finally:
        con.close()
