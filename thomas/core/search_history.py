# thomas/core/search_history.py
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core.persistence import get_persistence
from thomas.core.search_history_shared import (
    Bookmark,
    SavedSearch,
    SearchResult,
    TurnContext,
    _norm_ts,
    _parse_ts,
    _safe_text,
    _scoped_query,
    _turn_fingerprint,
    _turn_id,
)

# Highlight markers produced by FTS snippet() and rendered safely by UI (no innerHTML)
HL_START = "\u0001"
HL_END = "\u0002"


class ConversationSearch:
    """
    SQLite FTS5 conversation search with consumer-friendly features:
    - Accurate highlighting via snippet()
    - Recency-aware ranking (relevance first, but recent wins ties)
    - Scopes (search in user / assistant / tool_calls)
    - Bookmarks + Saved searches (server-side, synced across devices)
    - Incremental indexing + schema versioning
    """

    SCHEMA_VERSION = "4"

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._lock = threading.RLock()
        self._db_path = Path(
            db_path if db_path is not None else os.getenv("THOMAS_SEARCH_DB", "./thomas_search.db")
        ).resolve()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA temp_store=MEMORY;")
        self._conn.execute("PRAGMA foreign_keys=ON;")

        self._ensure_schema()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _ensure_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    val TEXT NOT NULL
                )
                """
            )
            row = self._conn.execute("SELECT val FROM meta WHERE key='schema_version'").fetchone()
            if row is None:
                self._conn.execute("INSERT INTO meta(key,val) VALUES('schema_version', ?)", (self.SCHEMA_VERSION,))
            elif str(row["val"]) != self.SCHEMA_VERSION:
                self._drop_all()
                self._conn.execute("INSERT INTO meta(key,val) VALUES('schema_version', ?)", (self.SCHEMA_VERSION,))

            self._conn.execute("INSERT OR IGNORE INTO meta(key,val) VALUES('last_indexed_pos', '0')")
            self._conn.execute("INSERT OR IGNORE INTO meta(key,val) VALUES('last_optimize_at_pos', '0')")

            try:
                self._conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
                        turn_id UNINDEXED,
                        turn_pos UNINDEXED,
                        ts UNINDEXED,
                        channel UNINDEXED,
                        has_tool_calls UNINDEXED,
                        user_msg,
                        assistant_msg,
                        tool_calls,
                        tokenize='porter'
                    )
                    """
                )
            except sqlite3.OperationalError as e:
                raise RuntimeError(
                    "SQLite in this Python build does not support FTS5. "
                    "Install a Python build with FTS5 enabled (official CPython typically includes it). "
                    f"Original error: {e}"
                )

            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS turn_map (
                    turn_id TEXT PRIMARY KEY,
                    rowid INTEGER NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS turn_index (
                    turn_pos INTEGER PRIMARY KEY,
                    turn_id TEXT NOT NULL UNIQUE,
                    ts TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    rowid INTEGER NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS query_history (
                    q TEXT PRIMARY KEY,
                    last_used_ts TEXT NOT NULL,
                    use_count INTEGER NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bookmarks (
                    turn_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL DEFAULT '',
                    created_ts TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS saved_searches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    query TEXT NOT NULL,
                    filters_json TEXT NOT NULL DEFAULT '{}',
                    created_ts TEXT NOT NULL,
                    last_used_ts TEXT NOT NULL,
                    use_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS turns_vocab USING fts5vocab(turns_fts, 'row')
                """
            )
            self._conn.commit()

    def _drop_all(self) -> None:
        self._conn.execute("DROP TABLE IF EXISTS turn_map")
        self._conn.execute("DROP TABLE IF EXISTS turn_index")
        self._conn.execute("DROP TABLE IF EXISTS query_history")
        self._conn.execute("DROP TABLE IF EXISTS bookmarks")
        self._conn.execute("DROP TABLE IF EXISTS saved_searches")
        self._conn.execute("DROP TABLE IF EXISTS turns_vocab")
        self._conn.execute("DROP TABLE IF EXISTS turns_fts")
        self._conn.execute("DROP TABLE IF EXISTS meta")
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _get_meta_int(self, key: str, default: int = 0) -> int:
        row = self._conn.execute("SELECT val FROM meta WHERE key=?", (key,)).fetchone()
        try:
            return int(row["val"]) if row else default
        except Exception:
            return default

    def _set_meta_int(self, key: str, value: int) -> None:
        self._conn.execute(
            "INSERT INTO meta(key,val) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET val=excluded.val",
            (key, str(int(value))),
        )

    def status(self) -> dict[str, Any]:
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) AS n FROM turns_fts").fetchone()["n"]
            last_pos = self._get_meta_int("last_indexed_pos", 0)
            last_opt = self._get_meta_int("last_optimize_at_pos", 0)
            bms = self._conn.execute("SELECT COUNT(*) AS n FROM bookmarks").fetchone()["n"]
            sss = self._conn.execute("SELECT COUNT(*) AS n FROM saved_searches").fetchone()["n"]
        try:
            size = self._db_path.stat().st_size
        except Exception:
            size = 0
        return {
            "db_path": str(self._db_path),
            "indexed_rows": int(count),
            "last_indexed_pos": int(last_pos),
            "last_optimize_at_pos": int(last_opt),
            "db_size_bytes": int(size),
            "schema_version": self.SCHEMA_VERSION,
            "bookmarks": int(bms),
            "saved_searches": int(sss),
        }

    def record_query(self, q: str) -> None:
        q = (q or "").strip()
        if not q:
            return
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO query_history(q, last_used_ts, use_count)
                VALUES(?, ?, 1)
                ON CONFLICT(q) DO UPDATE SET last_used_ts=excluded.last_used_ts, use_count=use_count+1
                """,
                (q, now),
            )
            self._conn.commit()

    def _maybe_optimize(self) -> None:
        with self._lock:
            last_pos = self._get_meta_int("last_indexed_pos", 0)
            last_opt = self._get_meta_int("last_optimize_at_pos", 0)
            if last_pos - last_opt >= 2000:
                try:
                    self._conn.execute("INSERT INTO turns_fts(turns_fts) VALUES('optimize')")
                    self._set_meta_int("last_optimize_at_pos", last_pos)
                    self._conn.commit()
                except sqlite3.OperationalError:
                    pass

    def index_turn(self, turn: Any, pos: int | None = None) -> str:
        ts = _norm_ts(getattr(turn, "timestamp", ""))
        channel = _safe_text(getattr(turn, "channel", ""))
        user_msg = _safe_text(getattr(turn, "user_msg", ""))
        assistant_msg = _safe_text(getattr(turn, "assistant_msg", ""))
        tool_calls = _safe_text(getattr(turn, "tool_calls", ""))

        fp = _turn_fingerprint(ts, channel, user_msg, assistant_msg, tool_calls)
        tid = _turn_id(fp)
        tpos = int(pos) if pos is not None else -1
        has_tools = 1 if (tool_calls.strip() != "" and tool_calls.strip() != "[]") else 0

        with self._lock:
            existing = self._conn.execute("SELECT rowid FROM turn_map WHERE turn_id=?", (tid,)).fetchone()
            if existing is not None:
                if tpos >= 0:
                    self._conn.execute(
                        """
                        INSERT OR IGNORE INTO turn_index(turn_pos, turn_id, ts, channel, rowid)
                        VALUES(?,?,?,?,?)
                        """,
                        (tpos, tid, ts, channel, int(existing["rowid"])),
                    )
                    self._conn.commit()
                return tid

            cur = self._conn.execute(
                """
                INSERT INTO turns_fts(turn_id, turn_pos, ts, channel, has_tool_calls, user_msg, assistant_msg, tool_calls)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (tid, tpos, ts, channel, has_tools, user_msg, assistant_msg, tool_calls),
            )
            rowid = cur.lastrowid
            self._conn.execute("INSERT INTO turn_map(turn_id,rowid) VALUES(?,?)", (tid, rowid))
            if tpos >= 0:
                self._conn.execute(
                    "INSERT OR REPLACE INTO turn_index(turn_pos, turn_id, ts, channel, rowid) VALUES(?,?,?,?,?)",
                    (tpos, tid, ts, channel, rowid),
                )
            self._conn.commit()
            return tid

    def sync_from_persistence(self, max_new: int = 15000) -> int:
        persistence = get_persistence()
        history = list(getattr(persistence, "turn_history", []) or [])

        with self._lock:
            last_pos = self._get_meta_int("last_indexed_pos", 0)
            if last_pos < 0 or last_pos > len(history):
                self.reindex_all()
                return len(history)

            start = last_pos
            end = min(len(history), start + max_new)

            added = 0
            for i in range(start, end):
                self.index_turn(history[i], pos=i)
                added += 1

            self._set_meta_int("last_indexed_pos", end)
            self._conn.commit()

        self._maybe_optimize()
        return added

    def reindex_all(self) -> None:
        persistence = get_persistence()
        history = list(getattr(persistence, "turn_history", []) or [])

        with self._lock:
            self._conn.execute("DELETE FROM turns_fts")
            self._conn.execute("DELETE FROM turn_map")
            self._conn.execute("DELETE FROM turn_index")
            self._set_meta_int("last_indexed_pos", 0)
            self._conn.commit()

            for i, t in enumerate(history):
                self.index_turn(t, pos=i)

            self._set_meta_int("last_indexed_pos", len(history))
            self._conn.commit()

        with self._lock:
            try:
                self._conn.execute("INSERT INTO turns_fts(turns_fts) VALUES('optimize')")
                self._conn.commit()
            except sqlite3.OperationalError:
                pass

    def list_channels(self) -> list[str]:
        self.sync_from_persistence()
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT channel FROM turns_fts WHERE channel != '' ORDER BY channel ASC"
            ).fetchall()
        return [str(r["channel"]) for r in rows if r and r["channel"]]

    def get_context(self, turn_id: str, window: int = 2) -> list[TurnContext]:
        tid = (turn_id or "").strip()
        if not tid:
            return []

        self.sync_from_persistence()

        w = max(0, min(int(window or 2), 25))

        with self._lock:
            row = self._conn.execute("SELECT turn_pos FROM turn_index WHERE turn_id=?", (tid,)).fetchone()
            if row is None:
                return self._get_turn_by_id(tid)

            center = int(row["turn_pos"])
            start = max(0, center - w)
            end = center + w

            idx_rows = self._conn.execute(
                """
                SELECT turn_id, turn_pos, rowid
                FROM turn_index
                WHERE turn_pos BETWEEN ? AND ?
                ORDER BY turn_pos ASC
                """,
                (start, end),
            ).fetchall()

            out: list[TurnContext] = []
            for ir in idx_rows:
                rid = int(ir["rowid"])
                tr = self._conn.execute(
                    "SELECT turn_id, turn_pos, ts, channel, user_msg, assistant_msg, tool_calls FROM turns_fts WHERE rowid=?",
                    (rid,),
                ).fetchone()
                if tr is None:
                    continue
                out.append(
                    TurnContext(
                        turn_id=str(tr["turn_id"]),
                        turn_pos=int(tr["turn_pos"]) if tr["turn_pos"] is not None else -1,
                        ts=str(tr["ts"] or ""),
                        channel=str(tr["channel"] or ""),
                        user_msg=str(tr["user_msg"] or ""),
                        assistant_msg=str(tr["assistant_msg"] or ""),
                        tool_calls=str(tr["tool_calls"] or ""),
                    )
                )
            return out

    def _get_turn_by_id(self, tid: str) -> list[TurnContext]:
        row = self._conn.execute("SELECT rowid FROM turn_map WHERE turn_id=?", (tid,)).fetchone()
        if row is None:
            return []
        rid = int(row["rowid"])
        tr = self._conn.execute(
            "SELECT turn_id, turn_pos, ts, channel, user_msg, assistant_msg, tool_calls FROM turns_fts WHERE rowid=?",
            (rid,),
        ).fetchone()
        if tr is None:
            return []
        return [
            TurnContext(
                turn_id=str(tr["turn_id"]),
                turn_pos=int(tr["turn_pos"]) if tr["turn_pos"] is not None else -1,
                ts=str(tr["ts"] or ""),
                channel=str(tr["channel"] or ""),
                user_msg=str(tr["user_msg"] or ""),
                assistant_msg=str(tr["assistant_msg"] or ""),
                tool_calls=str(tr["tool_calls"] or ""),
            )
        ]

    # -----------------------
    # Bookmarks (consumer love)
    # -----------------------
    def list_bookmarks(self) -> list[Bookmark]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT turn_id, label, created_ts FROM bookmarks ORDER BY created_ts DESC"
            ).fetchall()
        return [Bookmark(str(r["turn_id"]), str(r["label"] or ""), str(r["created_ts"] or "")) for r in rows]

    def set_bookmark(self, turn_id: str, label: str = "") -> None:
        tid = (turn_id or "").strip()
        if not tid:
            return
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO bookmarks(turn_id, label, created_ts)
                VALUES(?,?,?)
                ON CONFLICT(turn_id) DO UPDATE SET label=excluded.label
                """,
                (tid, (label or "").strip(), now),
            )
            self._conn.commit()

    def remove_bookmark(self, turn_id: str) -> None:
        tid = (turn_id or "").strip()
        if not tid:
            return
        with self._lock:
            self._conn.execute("DELETE FROM bookmarks WHERE turn_id=?", (tid,))
            self._conn.commit()

    def is_bookmarked(self, turn_id: str) -> bool:
        tid = (turn_id or "").strip()
        if not tid:
            return False
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM bookmarks WHERE turn_id=? LIMIT 1", (tid,)).fetchone()
        return row is not None

    # -----------------------
    # Saved searches
    # -----------------------
    def list_saved_searches(self) -> list[SavedSearch]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, name, query, filters_json, created_ts, last_used_ts, use_count
                FROM saved_searches
                ORDER BY use_count DESC, last_used_ts DESC
                LIMIT 50
                """
            ).fetchall()
        out = []
        for r in rows:
            out.append(
                SavedSearch(
                    id=int(r["id"]),
                    name=str(r["name"] or ""),
                    query=str(r["query"] or ""),
                    filters_json=str(r["filters_json"] or "{}"),
                    created_ts=str(r["created_ts"] or ""),
                    last_used_ts=str(r["last_used_ts"] or ""),
                    use_count=int(r["use_count"] or 0),
                )
            )
        return out

    def save_search(self, name: str, query: str, filters: dict[str, Any]) -> int:
        nm = (name or "").strip() or "Saved search"
        q = (query or "").strip()
        if not q:
            raise ValueError("query required")
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
        fj = json.dumps(filters or {}, ensure_ascii=False)
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO saved_searches(name, query, filters_json, created_ts, last_used_ts, use_count)
                VALUES(?,?,?,?,?,0)
                """,
                (nm, q, fj, now, now),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def delete_saved_search(self, sid: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM saved_searches WHERE id=?", (int(sid),))
            self._conn.commit()

    def touch_saved_search(self, sid: int) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
        with self._lock:
            self._conn.execute(
                "UPDATE saved_searches SET last_used_ts=?, use_count=use_count+1 WHERE id=?",
                (now, int(sid)),
            )
            self._conn.commit()

    # -----------------------
    # Search core
    # -----------------------
    def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
        channel: str | None = None,
        since: str | None = None,
        before: str | None = None,
        has_tool_calls: bool | None = None,
        sort: str = "relevance",
        scopes: set[str] | None = None,
    ) -> list[SearchResult]:
        q = (query or "").strip()
        if not q:
            return []

        self.sync_from_persistence()

        scopes = scopes or {"all"}
        cooked = _scoped_query(q, scopes)
        if not cooked:
            return []

        lim = max(1, min(int(limit or 20), 200))
        off = max(0, min(int(offset or 0), 10000))

        where = ["turns_fts MATCH ?"]
        params: list[Any] = [cooked]

        if channel:
            where.append("channel = ?")
            params.append(str(channel))

        if since:
            where.append("ts >= ?")
            params.append(_norm_ts(since))

        if before:
            where.append("ts <= ?")
            params.append(_norm_ts(before))

        if has_tool_calls is True:
            where.append("has_tool_calls = 1")
        elif has_tool_calls is False:
            where.append("has_tool_calls = 0")

        if sort not in ("relevance", "newest"):
            sort = "relevance"

        order_by = "rank ASC, ts DESC" if sort == "relevance" else "ts DESC, rank ASC"

        # snippet column indexes:
        # 5=user_msg, 6=assistant_msg, 7=tool_calls
        sql = f"""
            SELECT
                turn_id,
                turn_pos,
                ts,
                channel,
                user_msg,
                snippet(turns_fts, 5, ?, ?, '…', 20) AS user_snip,
                snippet(turns_fts, 6, ?, ?, '…', 20) AS assistant_snip,
                snippet(turns_fts, 6, '', '', '…', 20) AS assistant_plain,
                bm25(turns_fts) AS rank
            FROM turns_fts
            WHERE {" AND ".join(where)}
            ORDER BY {order_by}
            LIMIT ?
            OFFSET ?
        """

        params2 = [HL_START, HL_END, HL_START, HL_END]
        params2.extend(params)
        params2.append(lim)
        params2.append(off)

        now = datetime.now(timezone.utc)

        out: list[SearchResult] = []
        with self._lock:
            try:
                rows = self._conn.execute(sql, params2).fetchall()
            except sqlite3.OperationalError:
                # fallback: quote terms, no prefix
                cooked2 = " AND ".join([f'"{p}"' for p in q.split() if p.strip()]) or q
                params2[0] = cooked2
                rows = self._conn.execute(sql, params2).fetchall()

            for r in rows:
                rank = float(r["rank"]) if r["rank"] is not None else 0.0
                base_score = 1.0 / (1.0 + abs(rank))

                # soft recency boost (keeps relevance primary):
                # factor in [1.0, 1.35] for recent turns, decays over ~90 days
                ts = str(r["ts"] or "")
                dt = _parse_ts(ts)
                if dt is not None:
                    days = max(0.0, (now - dt).total_seconds() / 86400.0)
                    # exp-ish decay without importing math.exp (avoid perf churn / tiny benefit):
                    # approximate exp(-days/90) via (1/(1+days/90))
                    rec = 1.0 / (1.0 + (days / 90.0))
                    recency_factor = 1.0 + 0.35 * rec
                else:
                    recency_factor = 1.0

                score = base_score * recency_factor

                out.append(
                    SearchResult(
                        turn_id=str(r["turn_id"] or ""),
                        turn_pos=int(r["turn_pos"]) if r["turn_pos"] is not None else -1,
                        ts=ts,
                        channel=str(r["channel"] or ""),
                        user_msg=str(r["user_msg"] or ""),
                        user_snippet=str(r["user_snip"] or ""),
                        assistant_snippet=str(r["assistant_snip"] or ""),
                        assistant_snippet_plain=str(r["assistant_plain"] or "").strip(),
                        rank=float(rank),
                        score=float(score),
                    )
                )
        return out

    def suggest(self, partial: str) -> list[str]:
        """
        Autocomplete consumers actually like:
        - past queries (most-used)
        - saved searches by name + query
        - vocabulary tokens (common terms)
        """
        p = (partial or "").strip()
        if not p:
            return []

        self.sync_from_persistence()

        p_low = p.lower()
        like = p_low + "%"

        with self._lock:
            vocab_rows = self._conn.execute(
                """
                SELECT term
                FROM turns_vocab
                WHERE term LIKE ?
                ORDER BY cnt DESC
                LIMIT 12
                """,
                (like,),
            ).fetchall()

            hist_rows = self._conn.execute(
                """
                SELECT q
                FROM query_history
                WHERE lower(q) LIKE ?
                ORDER BY use_count DESC, last_used_ts DESC
                LIMIT 12
                """,
                (like,),
            ).fetchall()

            saved_rows = self._conn.execute(
                """
                SELECT name, query
                FROM saved_searches
                WHERE lower(name) LIKE ? OR lower(query) LIKE ?
                ORDER BY use_count DESC, last_used_ts DESC
                LIMIT 12
                """,
                (like, like),
            ).fetchall()

        seen = set()
        out: list[str] = []

        for r in hist_rows:
            s = str(r["q"])
            if s and s not in seen:
                seen.add(s)
                out.append(s)

        for r in saved_rows:
            nm = str(r["name"] or "").strip()
            q = str(r["query"] or "").strip()
            if nm and nm not in seen:
                seen.add(nm)
                out.append(nm)
            if q and q not in seen:
                seen.add(q)
                out.append(q)

        for r in vocab_rows:
            s = str(r["term"])
            if s and s not in seen:
                seen.add(s)
                out.append(s)

        return out[:12]


_search_singleton: ConversationSearch | None = None
_search_lock = threading.Lock()


def get_search() -> ConversationSearch:
    global _search_singleton
    if _search_singleton is None:
        with _search_lock:
            if _search_singleton is None:
                _search_singleton = ConversationSearch()
    return _search_singleton
