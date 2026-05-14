from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS pins (
    key TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    created_ts_utc INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS lexicon (
    phrase TEXT PRIMARY KEY,
    meaning TEXT NOT NULL,
    updated_ts_utc INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc INTEGER NOT NULL,
    thread TEXT NOT NULL,
    mode TEXT NOT NULL,
    query TEXT NOT NULL,
    trace_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_traces_thread ON traces(thread);
"""

class MetaDB:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    # Pins
    def pin_set(self, key: str, text: str):
        ts = int(time.time())
        self.conn.execute(
            "INSERT INTO pins(key, text, created_ts_utc) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET text=excluded.text, created_ts_utc=excluded.created_ts_utc",
            (key, text, ts),
        )
        self.conn.commit()

    def pin_rm(self, key: str):
        self.conn.execute("DELETE FROM pins WHERE key=?", (key,))
        self.conn.commit()

    def pin_list(self) -> list[tuple[str, str, int]]:
        cur = self.conn.execute("SELECT key, text, created_ts_utc FROM pins ORDER BY created_ts_utc DESC")
        return [(r[0], r[1], int(r[2])) for r in cur.fetchall()]

    # Lexicon
    def lex_add(self, phrase: str, meaning: str):
        ts = int(time.time())
        self.conn.execute(
            "INSERT INTO lexicon(phrase, meaning, updated_ts_utc) VALUES (?,?,?) ON CONFLICT(phrase) DO UPDATE SET meaning=excluded.meaning, updated_ts_utc=excluded.updated_ts_utc",
            (phrase, meaning, ts),
        )
        self.conn.commit()

    def lex_list(self) -> list[tuple[str, str, int]]:
        cur = self.conn.execute("SELECT phrase, meaning, updated_ts_utc FROM lexicon ORDER BY updated_ts_utc DESC")
        return [(r[0], r[1], int(r[2])) for r in cur.fetchall()]

    def lex_translate(self, text: str) -> str:
        # simple literal replacement; expand later to fuzzy
        rows = self.lex_list()
        out = text
        for phrase, meaning, _ in rows:
            if phrase and phrase in out:
                out = out.replace(phrase, meaning)
        return out

    # Traces
    def trace_add(self, thread: str, mode: str, query: str, trace: dict[str, Any]):
        ts = int(time.time())
        self.conn.execute(
            "INSERT INTO traces(ts_utc, thread, mode, query, trace_json) VALUES (?,?,?,?,?)",
            (ts, thread, mode, query, json.dumps(trace, ensure_ascii=False)),
        )
        self.conn.commit()

    def trace_iter(self, limit: int = 5000):
        cur = self.conn.execute("SELECT ts_utc, thread, mode, query, trace_json FROM traces ORDER BY id DESC LIMIT ?", (limit,))
        for ts, thread, mode, query, tj in cur.fetchall():
            yield int(ts), thread, mode, query, json.loads(tj)
