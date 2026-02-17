"""Storage layer for Thomas memory: SQLite log, blob store, meta DB, derived DB.

Ported from agent_memory/ with improvements:
- Added get_events_batch() to fix N+1 queries
- Added vec_dense BLOB column for sentence-transformer embeddings
- Added compound index on g_edges(src_node, rel, tombstoned)
- All DBs use WAL mode + NORMAL sync for crash safety + performance
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Cross-platform file lock
# ---------------------------------------------------------------------------

try:
    import msvcrt
    _HAS_MSVCRT = True
except ImportError:
    _HAS_MSVCRT = False

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False


def _ids_json(ids: Iterable[int]) -> str:
    """Serialize integer ids for SQLite json_each(?) membership checks."""
    return json.dumps([int(x) for x in ids], separators=(",", ":"))


@contextmanager
def file_lock(lock_path: str, timeout_s: float = 10.0, poll_s: float = 0.05):
    """Cross-platform advisory file lock (Windows msvcrt / Unix fcntl)."""
    fp = open(lock_path, "a+b")
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            if _HAS_MSVCRT:
                fp.seek(0)
                msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
            elif _HAS_FCNTL:
                fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                break  # No locking available — proceed anyway
            break
        except (OSError, IOError):
            if time.monotonic() >= deadline:
                fp.close()
                raise TimeoutError(f"Could not acquire lock: {lock_path}")
            time.sleep(poll_s)
    try:
        yield
    finally:
        try:
            if _HAS_MSVCRT:
                fp.seek(0)
                msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
            elif _HAS_FCNTL:
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
        except (OSError, IOError):
            pass
        fp.close()


# ---------------------------------------------------------------------------
# Path configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryPaths:
    """All paths derived from a single root directory."""
    root: Path
    data_dir: Path
    blobs_dir: Path
    indices_dir: Path
    builds_dir: Path
    delta_dir: Path

    @staticmethod
    def from_root(root: Path) -> MemoryPaths:
        r = root.resolve()
        indices = r / "indices"
        return MemoryPaths(
            root=r,
            data_dir=r / "data",
            blobs_dir=r / "blobs",
            indices_dir=indices,
            builds_dir=indices / "builds",
            delta_dir=indices / "delta",
        )

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.blobs_dir, self.indices_dir,
                  self.builds_dir, self.delta_dir):
            d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# EventRow
# ---------------------------------------------------------------------------


@dataclass
class EventRow:
    id: int
    ts_utc: int
    thread: str
    etype: str
    text: str
    metadata: Dict[str, Any]
    blob_id: Optional[str] = None


# ---------------------------------------------------------------------------
# FTS5 query sanitization
# ---------------------------------------------------------------------------


def _sanitize_fts5(query: str) -> str:
    """Sanitize a query string for FTS5 MATCH.

    FTS5 uses special syntax (AND, OR, NOT, *, ^, NEAR, etc.)
    and treats dots, colons, and other punctuation as syntax errors.
    This strips them to produce a safe implicit-AND query.
    """
    import re
    # Remove characters that are FTS5 syntax: . : ( ) { } ^ * " ~
    cleaned = re.sub(r'[.:()\[\]{}\^*"~@#$!?/\\<>]', " ", query)
    # Split into tokens, filter FTS5 reserved words used bare
    tokens = []
    reserved = {"AND", "OR", "NOT", "NEAR"}
    for t in cleaned.split():
        if t.upper() in reserved:
            tokens.append(f'"{t}"')  # Quote reserved words
        elif t.strip():
            tokens.append(t)
    return " ".join(tokens)


# ---------------------------------------------------------------------------
# ImmortalLog — append-only event store with FTS5
# ---------------------------------------------------------------------------


class ImmortalLog:
    """Append-only event store backed by SQLite WAL + FTS5."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        c = self._conn
        c.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc INTEGER NOT NULL,
                thread TEXT NOT NULL,
                etype TEXT NOT NULL,
                text TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                blob_id TEXT
            )
        """)
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
                text, thread, etype,
                content='events', content_rowid='id'
            )
        """)
        # FTS sync triggers
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
                INSERT INTO events_fts(rowid, text, thread, etype)
                VALUES (new.id, new.text, new.thread, new.etype);
            END
        """)
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
                INSERT INTO events_fts(events_fts, rowid, text, thread, etype)
                VALUES ('delete', old.id, old.text, old.thread, old.etype);
            END
        """)
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS events_au AFTER UPDATE ON events BEGIN
                INSERT INTO events_fts(events_fts, rowid, text, thread, etype)
                VALUES ('delete', old.id, old.text, old.thread, old.etype);
                INSERT INTO events_fts(rowid, text, thread, etype)
                VALUES (new.id, new.text, new.thread, new.etype);
            END
        """)
        c.commit()

    def add_event(
        self,
        thread: str,
        etype: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        blob_id: Optional[str] = None,
    ) -> int:
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        cur = self._conn.execute(
            "INSERT INTO events (ts_utc, thread, etype, text, metadata_json, blob_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (int(time.time()), thread, etype, text, meta_json, blob_id),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_event(self, eid: int) -> Optional[EventRow]:
        row = self._conn.execute(
            "SELECT id, ts_utc, thread, etype, text, metadata_json, blob_id "
            "FROM events WHERE id = ?", (eid,)
        ).fetchone()
        if row is None:
            return None
        return EventRow(
            id=row[0], ts_utc=row[1], thread=row[2], etype=row[3],
            text=row[4], metadata=json.loads(row[5]), blob_id=row[6],
        )

    def get_events_batch(self, eids: List[int]) -> Dict[int, EventRow]:
        """Batch load events by ID — fixes N+1 query pattern."""
        if not eids:
            return {}
        ids_json = _ids_json(eids)
        try:
            rows = self._conn.execute(
                "SELECT id, ts_utc, thread, etype, text, metadata_json, blob_id "
                "FROM events "
                "WHERE id IN (SELECT CAST(value AS INTEGER) FROM json_each(?))",
                (ids_json,),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
            for eid in eids:
                row = self._conn.execute(
                    "SELECT id, ts_utc, thread, etype, text, metadata_json, blob_id "
                    "FROM events WHERE id = ?",
                    (int(eid),),
                ).fetchone()
                if row is not None:
                    rows.append(row)
        return {
            r[0]: EventRow(
                id=r[0], ts_utc=r[1], thread=r[2], etype=r[3],
                text=r[4], metadata=json.loads(r[5]), blob_id=r[6],
            )
            for r in rows
        }

    def recent_events(self, thread: str, limit: int = 20) -> List[EventRow]:
        rows = self._conn.execute(
            "SELECT id, ts_utc, thread, etype, text, metadata_json, blob_id "
            "FROM events WHERE thread = ? ORDER BY id DESC LIMIT ?",
            (thread, limit),
        ).fetchall()
        return [
            EventRow(r[0], r[1], r[2], r[3], r[4], json.loads(r[5]), r[6])
            for r in reversed(rows)
        ]

    def search_fts(
        self, query: str, thread: Optional[str] = None, limit: int = 80
    ) -> List[Tuple[int, float]]:
        """BM25 full-text search. Returns (event_id, score) pairs."""
        sanitized = _sanitize_fts5(query)
        if not sanitized.strip():
            return []
        if thread:
            rows = self._conn.execute(
                "SELECT rowid, rank FROM events_fts "
                "WHERE events_fts MATCH ? AND thread = ? "
                "ORDER BY rank LIMIT ?",
                (sanitized, thread, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT rowid, rank FROM events_fts "
                "WHERE events_fts MATCH ? ORDER BY rank LIMIT ?",
                (sanitized, limit),
            ).fetchall()
        # Convert rank (negative BM25) to positive score
        return [(int(r[0]), 1.0 / (1.0 + abs(r[1]))) for r in rows]

    def iter_events(self, after_id: int = 0) -> Iterator[EventRow]:
        """Iterate events in ID order, optionally starting after a given ID.

        Args:
            after_id: Only yield events with id > after_id (0 = all events)
        """
        cur = self._conn.execute(
            "SELECT id, ts_utc, thread, etype, text, metadata_json, blob_id "
            "FROM events WHERE id > ? ORDER BY id",
            (after_id,),
        )
        for r in cur:
            yield EventRow(r[0], r[1], r[2], r[3], r[4], json.loads(r[5]), r[6])

    def count_events(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def close(self) -> None:
        if self._conn:
            self._conn.close()


# ---------------------------------------------------------------------------
# BlobStore — SHA256-addressed content store
# ---------------------------------------------------------------------------


class BlobStore:
    """Content-addressable blob store with SHA256 hashing."""

    def __init__(self, root: Path) -> None:
        self._root = root
        root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, data: bytes) -> str:
        h = hashlib.sha256(data).hexdigest()
        dest = self._root / h[:2] / h
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            dest.write_bytes(data)
        return h

    def get_bytes(self, blob_id: str) -> bytes:
        return (self._root / blob_id[:2] / blob_id).read_bytes()

    def put_text(self, text: str, encoding: str = "utf-8") -> str:
        return self.put_bytes(text.encode(encoding))

    def get_text(self, blob_id: str, encoding: str = "utf-8") -> str:
        return self.get_bytes(blob_id).decode(encoding)


# ---------------------------------------------------------------------------
# MetaDB — pins, lexicon, retrieval traces
# ---------------------------------------------------------------------------


class MetaDB:
    """Metadata store: user pins, lexicon expansions, retrieval traces."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        c = self._conn
        c.execute("""
            CREATE TABLE IF NOT EXISTS pins (
                key TEXT PRIMARY KEY, text TEXT NOT NULL, created_ts_utc INTEGER NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS lexicon (
                phrase TEXT PRIMARY KEY, meaning TEXT NOT NULL, updated_ts_utc INTEGER NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS traces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc INTEGER NOT NULL, thread TEXT NOT NULL,
                mode TEXT NOT NULL, query TEXT NOT NULL, trace_json TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_traces_thread ON traces(thread)")
        c.commit()

    def pin_set(self, key: str, text: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO pins VALUES (?, ?, ?)",
            (key, text, int(time.time())),
        )
        self._conn.commit()

    def pin_rm(self, key: str) -> None:
        self._conn.execute("DELETE FROM pins WHERE key = ?", (key,))
        self._conn.commit()

    def pin_list(self) -> List[Tuple[str, str, int]]:
        return self._conn.execute(
            "SELECT key, text, created_ts_utc FROM pins ORDER BY created_ts_utc DESC"
        ).fetchall()

    def lex_add(self, phrase: str, meaning: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO lexicon VALUES (?, ?, ?)",
            (phrase, meaning, int(time.time())),
        )
        self._conn.commit()

    def lex_list(self) -> List[Tuple[str, str, int]]:
        return self._conn.execute("SELECT * FROM lexicon").fetchall()

    def lex_translate(self, text: str) -> str:
        for phrase, meaning, _ in self.lex_list():
            text = text.replace(phrase, meaning)
        return text

    def trace_add(self, thread: str, mode: str, query: str, trace: Dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO traces (ts_utc, thread, mode, query, trace_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (int(time.time()), thread, mode, query, json.dumps(trace)),
        )
        self._conn.commit()

    def trace_recent(self, thread: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        if thread:
            rows = self._conn.execute(
                "SELECT id, ts_utc, thread, mode, query, trace_json "
                "FROM traces WHERE thread = ? ORDER BY id DESC LIMIT ?",
                (thread, int(limit)),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, ts_utc, thread, mode, query, trace_json "
                "FROM traces ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()

        out: List[Dict[str, Any]] = []
        for r in rows:
            try:
                parsed = json.loads(r[5]) if r[5] else {}
            except Exception:
                parsed = {}
            out.append(
                {
                    "id": int(r[0]),
                    "ts_utc": int(r[1]),
                    "thread": str(r[2]),
                    "mode": str(r[3]),
                    "query": str(r[4]),
                    "trace": parsed,
                }
            )
        return out

    def close(self) -> None:
        if self._conn:
            self._conn.close()


# ---------------------------------------------------------------------------
# DerivedDB — vectors + knowledge graph + rollups
# ---------------------------------------------------------------------------


_DEFAULT_TYPES = [
    "User", "Project", "Task", "Concept", "Preference",
    "Artifact", "Fact", "Thread", "Mode",
]


class DerivedDB:
    """Derived index database: vectors, knowledge graph, rollups."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        c = self._conn
        # Vectors — sparse JSON + dense BLOB
        c.execute("""
            CREATE TABLE IF NOT EXISTS vec (
                event_id INTEGER PRIMARY KEY,
                thread TEXT NOT NULL,
                ts_utc INTEGER NOT NULL,
                etype TEXT NOT NULL,
                vec_json TEXT NOT NULL,
                norm REAL NOT NULL,
                vec_dense BLOB
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_vec_thread_ts ON vec(thread, ts_utc DESC)")

        # Graph nodes
        c.execute("""
            CREATE TABLE IF NOT EXISTS schema_types (
                type_name TEXT PRIMARY KEY, created_ts_utc INTEGER
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS g_nodes (
                node_id INTEGER PRIMARY KEY AUTOINCREMENT,
                type_name TEXT NOT NULL, key TEXT NOT NULL,
                label TEXT NOT NULL, created_ts_utc INTEGER,
                user_asserted INTEGER DEFAULT 0,
                tombstoned INTEGER DEFAULT 0,
                UNIQUE(type_name, key)
            )
        """)
        # Graph edges
        c.execute("""
            CREATE TABLE IF NOT EXISTS g_edges (
                edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
                src_node INTEGER NOT NULL, rel TEXT NOT NULL,
                dst_node INTEGER NOT NULL, created_ts_utc INTEGER,
                valid_from_ts_utc INTEGER, valid_to_ts_utc INTEGER,
                confidence REAL DEFAULT 0.5,
                user_asserted INTEGER DEFAULT 0,
                tombstoned INTEGER DEFAULT 0,
                receipts_json TEXT DEFAULT '[]'
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_edges_src ON g_edges(src_node)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_edges_dst ON g_edges(dst_node)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_edges_rel ON g_edges(rel)")
        # NEW: compound index for efficient graph traversal
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_edges_src_rel_live "
            "ON g_edges(src_node, rel, tombstoned)"
        )

        # Rollups
        c.execute("""
            CREATE TABLE IF NOT EXISTS rollups (
                key TEXT PRIMARY KEY, created_ts_utc INTEGER,
                text TEXT, meta_json TEXT DEFAULT '{}'
            )
        """)
        # Tombstones
        c.execute("""
            CREATE TABLE IF NOT EXISTS tombstones (
                kind TEXT NOT NULL, id INTEGER NOT NULL,
                ts_utc INTEGER, reason TEXT, payload_json TEXT,
                PRIMARY KEY(kind, id)
            )
        """)
        c.commit()
        self._bootstrap_types()

    def _bootstrap_types(self) -> None:
        ts = int(time.time())
        for t in _DEFAULT_TYPES:
            self._conn.execute(
                "INSERT OR IGNORE INTO schema_types VALUES (?, ?)", (t, ts)
            )
        self._conn.commit()

    # --- Vector operations ---

    def vec_upsert(
        self,
        event_id: int,
        thread: str,
        ts_utc: int,
        etype: str,
        vec: Dict[str, float],
        vec_dense: Optional[bytes] = None,
    ) -> None:
        """Store sparse vector (and optionally dense) for an event."""
        # L2 normalize sparse
        norm = sum(v * v for v in vec.values()) ** 0.5
        if norm > 0:
            vec = {k: v / norm for k, v in vec.items()}
        self._conn.execute(
            "INSERT OR REPLACE INTO vec "
            "(event_id, thread, ts_utc, etype, vec_json, norm, vec_dense) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, thread, ts_utc, etype, json.dumps(vec), norm, vec_dense),
        )
        self._conn.commit()

    def vec_get_dense(self, event_id: int) -> Optional[bytes]:
        row = self._conn.execute(
            "SELECT vec_dense FROM vec WHERE event_id = ?", (event_id,)
        ).fetchone()
        return row[0] if row and row[0] else None

    def vec_candidates_by_thread(self, thread: str, limit: int = 2000) -> List[int]:
        rows = self._conn.execute(
            "SELECT event_id FROM vec WHERE thread = ? ORDER BY ts_utc DESC LIMIT ?",
            (thread, limit),
        ).fetchall()
        return [r[0] for r in rows]

    def vec_candidates_recent(self, limit: int = 2000) -> List[int]:
        rows = self._conn.execute(
            "SELECT event_id FROM vec ORDER BY ts_utc DESC LIMIT ?", (limit,)
        ).fetchall()
        return [r[0] for r in rows]

    def vec_similarity_sparse(
        self, qvec: Dict[str, float], event_ids: List[int]
    ) -> Dict[int, float]:
        """Compute cosine similarity using sparse vectors."""
        if not event_ids:
            return {}
        ids_json = _ids_json(event_ids)
        try:
            rows = self._conn.execute(
                "SELECT event_id, vec_json FROM vec "
                "WHERE event_id IN (SELECT CAST(value AS INTEGER) FROM json_each(?))",
                (ids_json,),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
            for event_id in event_ids:
                row = self._conn.execute(
                    "SELECT event_id, vec_json FROM vec WHERE event_id = ?",
                    (int(event_id),),
                ).fetchone()
                if row is not None:
                    rows.append(row)
        scores: Dict[int, float] = {}
        for eid, vj in rows:
            doc = json.loads(vj)
            dot = sum(qvec.get(k, 0.0) * v for k, v in doc.items())
            scores[eid] = dot
        return scores

    def vec_get_dense_batch(self, event_ids: List[int]) -> Dict[int, bytes]:
        """Batch load dense vectors."""
        if not event_ids:
            return {}
        ids_json = _ids_json(event_ids)
        try:
            rows = self._conn.execute(
                "SELECT event_id, vec_dense FROM vec "
                "WHERE event_id IN (SELECT CAST(value AS INTEGER) FROM json_each(?)) "
                "AND vec_dense IS NOT NULL",
                (ids_json,),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
            for event_id in event_ids:
                row = self._conn.execute(
                    "SELECT event_id, vec_dense FROM vec "
                    "WHERE event_id = ? AND vec_dense IS NOT NULL",
                    (int(event_id),),
                ).fetchone()
                if row is not None:
                    rows.append(row)
        return {r[0]: r[1] for r in rows}

    # --- Graph operations ---

    def node_upsert(
        self, type_name: str, key: str, label: str, user_asserted: bool = False
    ) -> int:
        ts = int(time.time())
        self._conn.execute(
            "INSERT INTO g_nodes (type_name, key, label, created_ts_utc, user_asserted) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(type_name, key) DO UPDATE SET label=excluded.label",
            (type_name, key, label, ts, int(user_asserted)),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT node_id FROM g_nodes WHERE type_name = ? AND key = ?",
            (type_name, key),
        ).fetchone()
        return row[0]

    def edge_add(
        self,
        src_node: int,
        rel: str,
        dst_node: int,
        confidence: float = 0.5,
        user_asserted: bool = False,
        receipts: Optional[List[int]] = None,
    ) -> int:
        ts = int(time.time())
        cur = self._conn.execute(
            "INSERT INTO g_edges "
            "(src_node, rel, dst_node, created_ts_utc, confidence, user_asserted, receipts_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (src_node, rel, dst_node, ts, confidence, int(user_asserted),
             json.dumps(receipts or [])),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def edges_from(
        self, src_node: int, rel: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        if rel:
            rows = self._conn.execute(
                "SELECT edge_id, src_node, rel, dst_node, confidence, receipts_json "
                "FROM g_edges WHERE src_node = ? AND rel = ? AND tombstoned = 0 LIMIT ?",
                (src_node, rel, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT edge_id, src_node, rel, dst_node, confidence, receipts_json "
                "FROM g_edges WHERE src_node = ? AND tombstoned = 0 LIMIT ?",
                (src_node, limit),
            ).fetchall()
        return [
            {"edge_id": r[0], "src": r[1], "rel": r[2], "dst": r[3],
             "confidence": r[4], "receipts": json.loads(r[5])}
            for r in rows
        ]

    def node_get_by_id(self, node_id: int) -> Optional[Dict[str, Any]]:
        """Look up a single node by its ID."""
        row = self._conn.execute(
            "SELECT node_id, type_name, key, label FROM g_nodes "
            "WHERE node_id = ? AND tombstoned = 0",
            (node_id,),
        ).fetchone()
        if row is None:
            return None
        return {"node_id": row[0], "type": row[1], "key": row[2], "label": row[3]}

    def nodes_get_by_ids(self, node_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """Batch look up nodes by their IDs."""
        if not node_ids:
            return {}
        ids_json = _ids_json(node_ids)
        try:
            rows = self._conn.execute(
                "SELECT node_id, type_name, key, label FROM g_nodes "
                "WHERE node_id IN (SELECT CAST(value AS INTEGER) FROM json_each(?)) "
                "AND tombstoned = 0",
                (ids_json,),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
            for node_id in node_ids:
                row = self._conn.execute(
                    "SELECT node_id, type_name, key, label FROM g_nodes "
                    "WHERE node_id = ? AND tombstoned = 0",
                    (int(node_id),),
                ).fetchone()
                if row is not None:
                    rows.append(row)
        return {
            r[0]: {"node_id": r[0], "type": r[1], "key": r[2], "label": r[3]}
            for r in rows
        }

    def nodes_search_label(self, like: str, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT node_id, type_name, key, label FROM g_nodes "
            "WHERE label LIKE ? AND tombstoned = 0 LIMIT ?",
            (f"%{like}%", limit),
        ).fetchall()
        return [{"node_id": r[0], "type": r[1], "key": r[2], "label": r[3]} for r in rows]

    def tombstone_edge(self, edge_id: int, reason: str = "") -> None:
        ts = int(time.time())
        self._conn.execute(
            "UPDATE g_edges SET tombstoned = 1 WHERE edge_id = ?", (edge_id,)
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO tombstones VALUES ('edge', ?, ?, ?, '{}')",
            (edge_id, ts, reason),
        )
        self._conn.commit()

    # --- Rollups ---

    def rollup_set(self, key: str, text: str, meta: Optional[Dict] = None) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO rollups VALUES (?, ?, ?, ?)",
            (key, int(time.time()), text, json.dumps(meta or {})),
        )
        self._conn.commit()

    def rollup_get(self, key: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT text FROM rollups WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()


# ---------------------------------------------------------------------------
# IndexManager — base/delta swap with file locking
# ---------------------------------------------------------------------------


@dataclass
class ActiveIndex:
    active_build: str
    updated_ts_utc: int


class IndexManager:
    """Manages base/delta index builds with atomic swap."""

    def __init__(self, indices_dir: Path) -> None:
        self._indices = indices_dir
        self._builds = indices_dir / "builds"
        self._active_path = indices_dir / "ACTIVE.json"
        self._lock_path = str(indices_dir / "ACTIVE.lock")
        self._builds.mkdir(parents=True, exist_ok=True)

    def ensure_bootstrap(self) -> None:
        """Create initial bootstrap build if no active index exists."""
        if self._active_path.exists():
            return
        name = "bootstrap"
        bdir = self._builds / name
        bdir.mkdir(parents=True, exist_ok=True)
        # Create empty derived_base.db
        db = DerivedDB(bdir / "derived_base.db")
        db.close()
        self.set_active(name)

    def get_active(self) -> ActiveIndex:
        data = json.loads(self._active_path.read_text(encoding="utf-8"))
        return ActiveIndex(data["active_build"], data["updated_ts_utc"])

    def set_active(self, build_name: str) -> None:
        data = json.dumps({
            "active_build": build_name,
            "updated_ts_utc": int(time.time()),
        })
        tmp = self._active_path.with_suffix(".tmp")
        with file_lock(self._lock_path):
            tmp.write_text(data, encoding="utf-8")
            os.replace(str(tmp), str(self._active_path))

    def new_build_dir(self, name: str) -> Path:
        d = self._builds / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def active_base_path(self) -> Path:
        active = self.get_active()
        return self._builds / active.active_build / "derived_base.db"

    def delta_path(self) -> Path:
        return self._indices / "delta" / "derived_delta.db"
