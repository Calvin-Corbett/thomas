from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from collections.abc import Iterable

DERIVED_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

-- Vectors: store sparse vector as compressed JSON of {i: v}
CREATE TABLE IF NOT EXISTS vec (
    event_id INTEGER PRIMARY KEY,
    thread TEXT NOT NULL,
    ts_utc INTEGER NOT NULL,
    etype TEXT NOT NULL,
    vec_json TEXT NOT NULL,
    norm REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vec_thread_ts ON vec(thread, ts_utc DESC);

-- Graph: strict schema (types, nodes, edges)
CREATE TABLE IF NOT EXISTS schema_types (
    type_name TEXT PRIMARY KEY,
    created_ts_utc INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS g_nodes (
    node_id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_name TEXT NOT NULL,
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    created_ts_utc INTEGER NOT NULL,
    user_asserted INTEGER NOT NULL DEFAULT 0,
    tombstoned INTEGER NOT NULL DEFAULT 0,
    UNIQUE(type_name, key)
);

CREATE TABLE IF NOT EXISTS g_edges (
    edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
    src_node INTEGER NOT NULL,
    rel TEXT NOT NULL,
    dst_node INTEGER NOT NULL,
    created_ts_utc INTEGER NOT NULL,
    valid_from_ts_utc INTEGER,
    valid_to_ts_utc INTEGER,
    confidence REAL NOT NULL DEFAULT 0.5,
    user_asserted INTEGER NOT NULL DEFAULT 0,
    tombstoned INTEGER NOT NULL DEFAULT 0,
    receipts_json TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_edges_src ON g_edges(src_node);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON g_edges(dst_node);
CREATE INDEX IF NOT EXISTS idx_edges_rel ON g_edges(rel);

-- Summaries / rollups
CREATE TABLE IF NOT EXISTS rollups (
    key TEXT PRIMARY KEY,
    created_ts_utc INTEGER NOT NULL,
    text TEXT NOT NULL,
    meta_json TEXT NOT NULL DEFAULT '{}'
);

-- Tombstones for deleted edges/nodes (cold storage)
CREATE TABLE IF NOT EXISTS tombstones (
    kind TEXT NOT NULL, -- 'node' or 'edge'
    id INTEGER NOT NULL,
    ts_utc INTEGER NOT NULL,
    reason TEXT,
    payload_json TEXT NOT NULL,
    PRIMARY KEY(kind, id)
);
"""

class DerivedDB:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.executescript(DERIVED_SCHEMA)
        self.conn.commit()
        self._bootstrap_schema()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def _bootstrap_schema(self):
        now = int(time.time())
        for t in ["User", "Project", "Task", "Concept", "Preference", "Artifact", "Fact", "Thread", "Mode"]:
            self.conn.execute("INSERT OR IGNORE INTO schema_types(type_name, created_ts_utc) VALUES (?,?)", (t, now))
        self.conn.commit()

    # ---- vectors ----
    def vec_upsert(self, event_id: int, thread: str, ts_utc: int, etype: str, vec: dict[str, float]) -> None:
        norm = sum(v*v for v in vec.values()) ** 0.5
        if norm > 0:
            vec = {k: v / norm for k, v in vec.items()}
            norm = 1.0
        self.conn.execute(
            "INSERT INTO vec(event_id, thread, ts_utc, etype, vec_json, norm) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(event_id) DO UPDATE SET thread=excluded.thread, ts_utc=excluded.ts_utc, etype=excluded.etype, vec_json=excluded.vec_json, norm=excluded.norm",
            (event_id, thread, ts_utc, etype, json.dumps(vec, ensure_ascii=False), float(norm))
        )

    def vec_get(self, event_id: int) -> dict[str, float] | None:
        cur = self.conn.execute("SELECT vec_json FROM vec WHERE event_id=?", (event_id,))
        r = cur.fetchone()
        if not r:
            return None
        return json.loads(r[0])

    def vec_candidates_by_thread(self, thread: str, limit: int = 2000) -> list[int]:
        cur = self.conn.execute("SELECT event_id FROM vec WHERE thread=? ORDER BY ts_utc DESC LIMIT ?", (thread, limit))
        return [int(r[0]) for r in cur.fetchall()]

    def vec_candidates_recent_global(self, limit: int = 2000) -> list[int]:
        cur = self.conn.execute("SELECT event_id FROM vec ORDER BY ts_utc DESC LIMIT ?", (limit,))
        return [int(r[0]) for r in cur.fetchall()]

    def vec_similarity(self, qvec: dict[str, float], event_ids: list[int]) -> dict[int, float]:
        # cosine for sparse dicts
        q = qvec
        out: dict[int, float] = {}
        if not q:
            return out
        placeholders = ",".join("?" for _ in event_ids) if event_ids else "NULL"
        cur = self.conn.execute(f"SELECT event_id, vec_json FROM vec WHERE event_id IN ({placeholders})", tuple(event_ids))
        for eid, vj in cur.fetchall():
            v = json.loads(vj)
            # dot product
            if len(v) < len(q):
                dot = sum(v.get(k, 0.0) * qv for k, qv in q.items())
            else:
                dot = sum(q.get(k, 0.0) * vv for k, vv in v.items())
            out[int(eid)] = float(dot)
        return out

    # ---- graph ----
    def schema_add_type(self, type_name: str) -> None:
        self.conn.execute("INSERT OR IGNORE INTO schema_types(type_name, created_ts_utc) VALUES (?,?)", (type_name, int(time.time())))

    def node_upsert(self, type_name: str, key: str, label: str, user_asserted: bool = False) -> int:
        now = int(time.time())
        self.schema_add_type(type_name)
        self.conn.execute(
            "INSERT OR IGNORE INTO g_nodes(type_name, key, label, created_ts_utc, user_asserted) VALUES (?,?,?,?,?)",
            (type_name, key, label, now, 1 if user_asserted else 0)
        )
        cur = self.conn.execute("SELECT node_id FROM g_nodes WHERE type_name=? AND key=?", (type_name, key))
        return int(cur.fetchone()[0])

    def edge_add(self, src_node: int, rel: str, dst_node: int, confidence: float = 0.5, user_asserted: bool = False, receipts: list[dict[str, Any]] | None = None,
                 valid_from_ts_utc: int | None = None, valid_to_ts_utc: int | None = None) -> int:
        now = int(time.time())
        self.conn.execute(
            "INSERT INTO g_edges(src_node, rel, dst_node, created_ts_utc, valid_from_ts_utc, valid_to_ts_utc, confidence, user_asserted, receipts_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (src_node, rel, dst_node, now, valid_from_ts_utc, valid_to_ts_utc, float(confidence), 1 if user_asserted else 0, json.dumps(receipts or [], ensure_ascii=False))
        )
        cur = self.conn.execute("SELECT last_insert_rowid()")
        return int(cur.fetchone()[0])

    def edges_from(self, src_node: int, rel: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if rel:
            cur = self.conn.execute(
                "SELECT edge_id, src_node, rel, dst_node, created_ts_utc, valid_from_ts_utc, valid_to_ts_utc, confidence, user_asserted, tombstoned, receipts_json "
                "FROM g_edges WHERE src_node=? AND rel=? AND tombstoned=0 ORDER BY confidence DESC, created_ts_utc DESC LIMIT ?",
                (src_node, rel, limit)
            )
        else:
            cur = self.conn.execute(
                "SELECT edge_id, src_node, rel, dst_node, created_ts_utc, valid_from_ts_utc, valid_to_ts_utc, confidence, user_asserted, tombstoned, receipts_json "
                "FROM g_edges WHERE src_node=? AND tombstoned=0 ORDER BY confidence DESC, created_ts_utc DESC LIMIT ?",
                (src_node, limit)
            )
        out = []
        for r in cur.fetchall():
            out.append({
                "edge_id": int(r[0]),
                "src_node": int(r[1]),
                "rel": r[2],
                "dst_node": int(r[3]),
                "created_ts_utc": int(r[4]),
                "valid_from_ts_utc": r[5],
                "valid_to_ts_utc": r[6],
                "confidence": float(r[7]),
                "user_asserted": bool(r[8]),
                "tombstoned": bool(r[9]),
                "receipts": json.loads(r[10] or "[]"),
            })
        return out

    def node_get(self, node_id: int) -> dict[str, Any] | None:
        cur = self.conn.execute("SELECT node_id, type_name, key, label, created_ts_utc, user_asserted, tombstoned FROM g_nodes WHERE node_id=?", (node_id,))
        r = cur.fetchone()
        if not r:
            return None
        return {
            "node_id": int(r[0]),
            "type_name": r[1],
            "key": r[2],
            "label": r[3],
            "created_ts_utc": int(r[4]),
            "user_asserted": bool(r[5]),
            "tombstoned": bool(r[6]),
        }

    def nodes_search_label(self, like: str, limit: int = 50) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT node_id, type_name, key, label, created_ts_utc, user_asserted, tombstoned FROM g_nodes WHERE tombstoned=0 AND label LIKE ? LIMIT ?",
            (f"%{like}%", limit)
        )
        out = []
        for r in cur.fetchall():
            out.append({
                "node_id": int(r[0]),
                "type_name": r[1],
                "key": r[2],
                "label": r[3],
                "created_ts_utc": int(r[4]),
                "user_asserted": bool(r[5]),
                "tombstoned": bool(r[6]),
            })
        return out

    def tombstone_edge(self, edge_id: int, reason: str = "") -> None:
        cur = self.conn.execute(
            "SELECT edge_id, src_node, rel, dst_node, created_ts_utc, valid_from_ts_utc, valid_to_ts_utc, confidence, user_asserted, receipts_json FROM g_edges WHERE edge_id=?",
            (edge_id,)
        )
        r = cur.fetchone()
        if not r:
            return
        payload = {
            "edge_id": int(r[0]),
            "src_node": int(r[1]),
            "rel": r[2],
            "dst_node": int(r[3]),
            "created_ts_utc": int(r[4]),
            "valid_from_ts_utc": r[5],
            "valid_to_ts_utc": r[6],
            "confidence": float(r[7]),
            "user_asserted": bool(r[8]),
            "receipts": json.loads(r[9] or "[]"),
        }
        self.conn.execute("UPDATE g_edges SET tombstoned=1 WHERE edge_id=?", (edge_id,))
        self.conn.execute(
            "INSERT OR REPLACE INTO tombstones(kind, id, ts_utc, reason, payload_json) VALUES ('edge', ?, ?, ?, ?)",
            (edge_id, int(time.time()), reason, json.dumps(payload, ensure_ascii=False))
        )

    # ---- rollups ----
    def rollup_set(self, key: str, text: str, meta: dict[str, Any] | None = None):
        self.conn.execute(
            "INSERT INTO rollups(key, created_ts_utc, text, meta_json) VALUES (?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET created_ts_utc=excluded.created_ts_utc, text=excluded.text, meta_json=excluded.meta_json",
            (key, int(time.time()), text, json.dumps(meta or {}, ensure_ascii=False))
        )

    def rollup_get(self, key: str) -> str | None:
        cur = self.conn.execute("SELECT text FROM rollups WHERE key=?", (key,))
        r = cur.fetchone()
        return r[0] if r else None

    def commit(self):
        self.conn.commit()
