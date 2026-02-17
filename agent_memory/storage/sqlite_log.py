from __future__ import annotations
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc INTEGER NOT NULL,
    thread TEXT NOT NULL,
    etype TEXT NOT NULL,
    text TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    blob_id TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    text,
    thread,
    etype,
    content='events',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, text, thread, etype) VALUES (new.id, new.text, new.thread, new.etype);
END;

CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, text, thread, etype) VALUES('delete', old.id, old.text, old.thread, old.etype);
END;

CREATE TRIGGER IF NOT EXISTS events_au AFTER UPDATE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, text, thread, etype) VALUES('delete', old.id, old.text, old.thread, old.etype);
    INSERT INTO events_fts(rowid, text, thread, etype) VALUES (new.id, new.text, new.thread, new.etype);
END;
"""

@dataclass
class EventRow:
    id: int
    ts_utc: int
    thread: str
    etype: str
    text: str
    metadata: Dict[str, Any]
    blob_id: Optional[str]

class ImmortalLog:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def add_event(self, thread: str, etype: str, text: str, metadata: Optional[Dict[str, Any]] = None, blob_id: Optional[str] = None) -> int:
        ts = int(time.time())
        meta = json.dumps(metadata or {}, ensure_ascii=False)
        cur = self.conn.execute(
            "INSERT INTO events(ts_utc, thread, etype, text, metadata_json, blob_id) VALUES (?,?,?,?,?,?)",
            (ts, thread, etype, text, meta, blob_id)
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_event(self, eid: int) -> Optional[EventRow]:
        cur = self.conn.execute("SELECT id, ts_utc, thread, etype, text, metadata_json, blob_id FROM events WHERE id=?", (eid,))
        r = cur.fetchone()
        if not r:
            return None
        return EventRow(id=r[0], ts_utc=r[1], thread=r[2], etype=r[3], text=r[4],
                        metadata=json.loads(r[5] or "{}"), blob_id=r[6])

    def recent_events(self, thread: str, limit: int = 20) -> List[EventRow]:
        cur = self.conn.execute(
            "SELECT id, ts_utc, thread, etype, text, metadata_json, blob_id FROM events WHERE thread=? ORDER BY id DESC LIMIT ?",
            (thread, limit)
        )
        out: List[EventRow] = []
        for r in cur.fetchall():
            out.append(EventRow(id=r[0], ts_utc=r[1], thread=r[2], etype=r[3], text=r[4],
                                metadata=json.loads(r[5] or "{}"), blob_id=r[6]))
        return out

    def search_fts(self, query: str, thread: Optional[str] = None, limit: int = 80) -> List[Tuple[int, float]]:
        where = "events_fts MATCH ?"
        params = [query]
        if thread:
            where += " AND thread=?"
            params.append(thread)
        sql = f"""
        SELECT rowid, bm25(events_fts) AS rank
        FROM events_fts
        WHERE {where}
        ORDER BY rank
        LIMIT ?
        """
        params.append(limit)
        cur = self.conn.execute(sql, tuple(params))
        out: List[Tuple[int, float]] = []
        for rowid, rank in cur.fetchall():
            score = 1.0 / (1.0 + abs(float(rank)))
            out.append((int(rowid), score))
        return out

    def iter_events(self) -> Iterator[EventRow]:
        cur = self.conn.execute("SELECT id, ts_utc, thread, etype, text, metadata_json, blob_id FROM events ORDER BY id ASC")
        for r in cur.fetchall():
            yield EventRow(id=r[0], ts_utc=r[1], thread=r[2], etype=r[3], text=r[4],
                           metadata=json.loads(r[5] or "{}"), blob_id=r[6])

    def count_events(self) -> int:
        cur = self.conn.execute("SELECT COUNT(*) FROM events")
        return int(cur.fetchone()[0])
