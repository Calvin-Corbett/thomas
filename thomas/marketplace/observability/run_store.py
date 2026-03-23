"""Thomas Observability: persistent run store for time-travel debugging.

Design goals:
- stdlib-only (no new deps)
- Windows safe (paths, sqlite, threads)
- durable: persist every streamed /api/chat event
- replayable: NDJSON iterator that matches live stream shapes
- scalable enough: supports batched inserts via a single-writer thread

Public API:
- init_db(path)
- create_run(metadata) -> run_id
- append_event(run_id, event_type, payload, t_ms, seq)
- finalize_run(run_id, ok, error, iterations, tool_calls, usage)
- list_runs(limit, offset, filters)
- get_run(run_id) -> metadata + ordered events
- stream_replay(run_id) -> iterator of NDJSON-ready dicts

Recommended for production streaming:
- ThreadedRunWriter: queues events and writes in batches on a single sqlite connection.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import logging
import os
import queue
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

MAX_RUNS: int = 500
MAX_DB_BYTES: int = 200 * 1024 * 1024  # ~200MB
BUSY_TIMEOUT_MS: int = 8000
ENABLE_FTS5: bool = True

_DB_PATH: Path | None = None
_LOCK = threading.Lock()
_ACTIVE_WRITERS: set[ThreadedRunWriter] = set()
_ACTIVE_WRITERS_LOCK = threading.Lock()
log = logging.getLogger(__name__)


def init_db(path: str | os.PathLike[str]) -> Path:
    global _DB_PATH
    db_path = Path(path).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        _create_schema(conn)
        _migrate_schema(conn)
    _DB_PATH = db_path
    return db_path


def shutdown(*, close_timeout: float = 5.0, reset_db_path: bool = False) -> None:
    """Best-effort shutdown for run-store resources.

    Closes active threaded writers so Windows can release DB file handles.
    """
    global _DB_PATH
    with _ACTIVE_WRITERS_LOCK:
        active = list(_ACTIVE_WRITERS)
    for writer in active:
        try:
            writer.close(timeout=close_timeout)
        except Exception as e:
            log.debug("Run store shutdown: writer close failed for %s: %s", writer.run_id[:8], e)
    if reset_db_path:
        _DB_PATH = None


def _register_writer(writer: ThreadedRunWriter) -> None:
    with _ACTIVE_WRITERS_LOCK:
        _ACTIVE_WRITERS.add(writer)


def _unregister_writer(writer: ThreadedRunWriter) -> None:
    with _ACTIVE_WRITERS_LOCK:
        _ACTIVE_WRITERS.discard(writer)


def create_run(metadata: dict[str, Any]) -> str:
    db = _require_db()
    run_id = metadata.get("run_id") or uuid.uuid4().hex
    started_at = metadata.get("started_at") or _utcnow_iso()
    row = {
        "run_id": run_id,
        "session_id": metadata.get("session_id"),
        "started_at": started_at,
        "ended_at": metadata.get("ended_at"),
        "profile": metadata.get("profile"),
        "model_id": metadata.get("model_id"),
        "mode": metadata.get("mode"),
        "ok": metadata.get("ok"),
        "error": metadata.get("error"),
        "iterations": metadata.get("iterations"),
        "tool_calls": metadata.get("tool_calls"),
        "usage_json": _json_dumps(metadata.get("usage_json")) if metadata.get("usage_json") is not None else None,
        "thomas_version": metadata.get("thomas_version"),
    }
    with _connect(db) as conn:
        conn.execute(
            """
            INSERT INTO runs
            (run_id, session_id, started_at, ended_at, profile, model_id, mode, ok, error, iterations, tool_calls, usage_json, thomas_version)
            VALUES
            (:run_id, :session_id, :started_at, :ended_at, :profile, :model_id, :mode, :ok, :error, :iterations, :tool_calls, :usage_json, :thomas_version)
            """,
            row,
        )
        _enforce_retention(conn)
    return run_id


def append_event(run_id: str, event_type: str, payload: dict[str, Any], t_ms: int, seq: int) -> None:
    db = _require_db()
    payload_json = _json_dumps(payload)
    search_text = _extract_search_text(payload)
    with _connect(db) as conn:
        _append_event_row(
            conn,
            run_id,
            int(t_ms),
            int(seq),
            str(event_type),
            payload_json,
            search_text,
        )


def finalize_run(
    run_id: str,
    ok: bool,
    error: str | None,
    iterations: int | None,
    tool_calls: int | None,
    usage: dict[str, Any] | None,
) -> None:
    db = _require_db()
    ended_at = _utcnow_iso()
    with _connect(db) as conn:
        conn.execute(
            """
            UPDATE runs
            SET ended_at = ?, ok = ?, error = ?, iterations = ?, tool_calls = ?, usage_json = ?
            WHERE run_id = ?
            """,
            (
                ended_at,
                1 if ok else 0,
                error,
                iterations,
                tool_calls,
                _json_dumps(usage) if usage is not None else None,
                run_id,
            ),
        )
        _enforce_retention(conn)


def list_runs(limit: int = 50, offset: int = 0, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    db = _require_db()
    filters = filters or {}
    session_id = str(filters["session_id"]) if filters.get("session_id") not in (None, "") else None
    profile = str(filters["profile"]) if filters.get("profile") not in (None, "") else None
    mode = str(filters["mode"]) if filters.get("mode") not in (None, "") else None
    ok_val = _normalize_ok_filter(filters.get("ok"))
    query = _normalize_query_filter(filters.get("q"))

    with _connect(db) as conn:
        if _fts_enabled(conn):
            q_fts = _fts_query(query) if query is not None else None
            rows = conn.execute(
                """
                SELECT run_id, session_id, started_at, ended_at, profile, model_id, mode, ok, error,
                       iterations, tool_calls, usage_json, thomas_version
                FROM runs r
                WHERE (? IS NULL OR r.session_id = ?)
                  AND (? IS NULL OR r.profile = ?)
                  AND (? IS NULL OR r.mode = ?)
                  AND (? IS NULL OR r.ok = ?)
                  AND (
                    ? IS NULL OR EXISTS (
                        SELECT 1
                        FROM events_fts f
                        WHERE f.run_id = r.run_id AND f.search_text MATCH ?
                    )
                  )
                ORDER BY started_at DESC
                LIMIT ? OFFSET ?
                """,
                (
                    session_id,
                    session_id,
                    profile,
                    profile,
                    mode,
                    mode,
                    ok_val,
                    ok_val,
                    q_fts,
                    q_fts,
                    int(limit),
                    int(offset),
                ),
            ).fetchall()
        else:
            q_like = f"%{query}%" if query is not None else None
            rows = conn.execute(
                """
                SELECT run_id, session_id, started_at, ended_at, profile, model_id, mode, ok, error,
                       iterations, tool_calls, usage_json, thomas_version
                FROM runs r
                WHERE (? IS NULL OR r.session_id = ?)
                  AND (? IS NULL OR r.profile = ?)
                  AND (? IS NULL OR r.mode = ?)
                  AND (? IS NULL OR r.ok = ?)
                  AND (
                    ? IS NULL OR EXISTS (
                        SELECT 1
                        FROM events e
                        WHERE e.run_id = r.run_id AND e.search_text LIKE ?
                    )
                  )
                ORDER BY started_at DESC
                LIMIT ? OFFSET ?
                """,
                (
                    session_id,
                    session_id,
                    profile,
                    profile,
                    mode,
                    mode,
                    ok_val,
                    ok_val,
                    q_like,
                    q_like,
                    int(limit),
                    int(offset),
                ),
            ).fetchall()
    return [_row_to_run_dict(r) for r in rows]


def get_run(run_id: str) -> dict[str, Any]:
    db = _require_db()
    with _connect(db) as conn:
        run_row = conn.execute(
            """
            SELECT run_id, session_id, started_at, ended_at, profile, model_id, mode, ok, error,
                   iterations, tool_calls, usage_json, thomas_version
            FROM runs WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if run_row is None:
            raise KeyError(f"run_id not found: {run_id}")
        event_rows = conn.execute(
            """
            SELECT id, run_id, t_ms, seq, event_type, payload_json
            FROM events
            WHERE run_id = ?
            ORDER BY seq ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
    run = _row_to_run_dict(run_row)
    events: list[dict[str, Any]] = []
    for er in event_rows:
        payload = _json_loads(er["payload_json"])
        events.append(
            {
                "id": er["id"],
                "run_id": er["run_id"],
                "t_ms": er["t_ms"],
                "seq": er["seq"],
                "event_type": er["event_type"],
                "payload": payload,
            }
        )
    return {"run": run, "events": events}


def stream_replay(run_id: str) -> Iterator[dict[str, Any]]:
    db = _require_db()
    with _connect(db) as conn:
        cur = conn.execute(
            """
            SELECT t_ms, seq, event_type, payload_json
            FROM events
            WHERE run_id = ?
            ORDER BY seq ASC, id ASC
            """,
            (run_id,),
        )
        for row in cur:
            payload = _json_loads(row["payload_json"])
            replay_event: dict[str, Any]
            if isinstance(payload, dict):
                replay_event = dict(payload)
            else:
                replay_event = {"payload": payload}
            if "type" not in replay_event:
                replay_event["type"] = row["event_type"]
            replay_event["run_id"] = run_id
            replay_event.setdefault("t_ms", row["t_ms"])
            replay_event.setdefault("seq", row["seq"])
            yield replay_event


class ThreadedRunWriter:
    """Single-writer thread that batches event inserts for streaming performance."""

    def __init__(self, run_id: str, *, flush_every: int = 50, flush_interval_s: float = 0.05) -> None:
        self.run_id = run_id
        self.flush_every = max(1, int(flush_every))
        self.flush_interval_s = float(flush_interval_s)
        self._t0_ns = time.perf_counter_ns()
        self._seq = 0
        self._q: queue.Queue[tuple[int, int, str, str, str] | None] = queue.Queue()
        self._thr = threading.Thread(target=self._worker, name=f"RunWriter-{run_id[:8]}", daemon=True)
        self._started = False
        self._closed = False
        self._exc: BaseException | None = None
        self._fallback_events = 0
        self._dropped_events = 0
        self._warned_fallback = False
        self._meta_lock = threading.Lock()

    def start(self) -> None:
        if self._closed:
            raise RuntimeError("RunWriter is closed")
        if self._started:
            return
        self._started = True
        _register_writer(self)
        self._thr.start()

    def record(self, obj: dict[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("RunWriter is closed")
        if not self._started:
            self.start()
        event_type = str(obj.get("type", "unknown"))
        t_ms = int((time.perf_counter_ns() - self._t0_ns) / 1_000_000)
        payload_json = _json_dumps(obj)
        search_text = _extract_search_text(obj)
        seq = self._seq
        self._seq += 1
        item = (t_ms, seq, event_type, payload_json, search_text)
        # If worker has failed, degrade to direct append instead of dropping events.
        if self._exc is not None or (self._started and not self._thr.is_alive()):
            self._record_direct(item, reason="worker_unavailable")
            return
        self._q.put(item)

    @property
    def seq(self) -> int:
        return self._seq

    def close(self, timeout: float = 5.0, *, strict: bool = False) -> None:
        self._closed = True
        if not self._started:
            _unregister_writer(self)
            return
        with contextlib.suppress(Exception):
            self._q.put(None)
        self._thr.join(timeout=timeout)
        if self._thr.is_alive():
            raise TimeoutError("RunWriter did not shut down cleanly")
        pending = self._drain_pending()
        if pending:
            self._write_direct_batch(pending, reason="close_drain")
        if strict and self._exc:
            raise RuntimeError("RunWriter worker failed") from self._exc
        _unregister_writer(self)

    def _worker(self) -> None:
        db = _require_db()
        try:
            with _connect(db) as conn:
                fts = _fts_enabled(conn)
                batch: list[tuple[int, int, str, str, str]] = []
                last_flush = time.monotonic()

                def flush() -> bool:
                    nonlocal batch, last_flush
                    if not batch:
                        return True
                    try:
                        conn.execute("BEGIN;")
                        conn.executemany(
                            "INSERT INTO events (run_id, t_ms, seq, event_type, payload_json, search_text) VALUES (?,?,?,?,?,?)",
                            [(self.run_id, tms, sq, et, pj, st) for (tms, sq, et, pj, st) in batch],
                        )
                        if fts:
                            conn.executemany(
                                "INSERT INTO events_fts (run_id, seq, search_text) VALUES (?,?,?)",
                                [(self.run_id, sq, st) for (_tms, sq, _et, _pj, st) in batch],
                            )
                        conn.execute("COMMIT;")
                    except Exception as e:
                        with contextlib.suppress(Exception):
                            conn.execute("ROLLBACK;")
                        failed_batch = list(batch)
                        batch = []
                        last_flush = time.monotonic()
                        if self._exc is None:
                            self._exc = e
                        self._write_direct_batch(failed_batch, reason="worker_flush_error")
                        return False
                    batch = []
                    last_flush = time.monotonic()
                    return True

                while True:
                    timeout = max(0.01, self.flush_interval_s)
                    try:
                        item = self._q.get(timeout=timeout)
                    except queue.Empty:
                        item = "__tick__"
                    now = time.monotonic()
                    if item is None:
                        flush()
                        return
                    if item == "__tick__":
                        if batch and (now - last_flush) >= self.flush_interval_s:
                            if not flush():
                                return
                        continue
                    t_ms, seq, event_type, payload_json, search_text = item
                    batch.append((int(t_ms), int(seq), str(event_type), payload_json, search_text))
                    if len(batch) >= self.flush_every:
                        if not flush():
                            return
        except BaseException as e:
            if self._exc is None:
                self._exc = e
        finally:
            _unregister_writer(self)

    def _record_direct(
        self,
        item: tuple[int, int, str, str, str],
        *,
        reason: str,
        track_stats: bool = True,
    ) -> None:
        t_ms, seq, event_type, payload_json, search_text = item
        db = _require_db()
        try:
            with _connect(db) as conn:
                _append_event_row(
                    conn,
                    self.run_id,
                    int(t_ms),
                    int(seq),
                    str(event_type),
                    payload_json,
                    search_text,
                )
            if track_stats:
                self._note_fallback(added=1, dropped=0, reason=reason)
        except (ValueError, TypeError):
            if track_stats:
                self._note_fallback(added=0, dropped=1, reason=reason)
            raise

    def _write_direct_batch(self, items: list[tuple[int, int, str, str, str]], *, reason: str) -> None:
        if not items:
            return
        added = 0
        dropped = 0
        for item in items:
            try:
                self._record_direct(item, reason=reason, track_stats=False)
                added += 1
            except (ValueError, TypeError):
                dropped += 1
        if added or dropped:
            self._note_fallback(added=added, dropped=dropped, reason=reason)

    def _note_fallback(self, *, added: int, dropped: int, reason: str) -> None:
        with self._meta_lock:
            if added:
                self._fallback_events += int(added)
            if dropped:
                self._dropped_events += int(dropped)
            should_warn = not self._warned_fallback
            if should_warn:
                self._warned_fallback = True
            total_fallback = self._fallback_events
            total_dropped = self._dropped_events
        if should_warn:
            log.warning(
                "RunWriter for %s switched to direct fallback (%s). fallback=%d dropped=%d",
                self.run_id[:8],
                reason,
                total_fallback,
                total_dropped,
            )
        elif dropped:
            log.warning(
                "RunWriter fallback dropped events for %s (%s). fallback=%d dropped=%d",
                self.run_id[:8],
                reason,
                total_fallback,
                total_dropped,
            )

    def _drain_pending(self) -> list[tuple[int, int, str, str, str]]:
        out: list[tuple[int, int, str, str, str]] = []
        while True:
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            if item is None:
                continue
            out.append(item)
        return out


def _append_event_row(
    conn: sqlite3.Connection,
    run_id: str,
    t_ms: int,
    seq: int,
    event_type: str,
    payload_json: str,
    search_text: str,
) -> None:
    # Retention may evict a run row between create_run() and first event write
    # under very small MAX_DB_BYTES settings. Ensure the parent run exists.
    _ensure_parent_run(conn, run_id)
    conn.execute(
        "INSERT INTO events (run_id, t_ms, seq, event_type, payload_json, search_text) VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, int(t_ms), int(seq), str(event_type), payload_json, search_text),
    )
    if _fts_enabled(conn):
        conn.execute(
            "INSERT INTO events_fts (run_id, seq, search_text) VALUES (?, ?, ?)",
            (run_id, int(seq), search_text),
        )


def _ensure_parent_run(conn: sqlite3.Connection, run_id: str) -> None:
    exists = conn.execute("SELECT 1 FROM runs WHERE run_id = ? LIMIT 1", (run_id,)).fetchone()
    if not exists:
        conn.execute(
            """
            INSERT INTO runs (run_id, started_at)
            VALUES (?, ?)
            """,
            (run_id, _utcnow_iso()),
        )


def _require_db() -> Path:
    if _DB_PATH is None:
        raise RuntimeError("run_store.init_db(path) must be called before using the run store.")
    return _DB_PATH


@contextlib.contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(
        str(db_path),
        timeout=max(1, BUSY_TIMEOUT_MS // 1000),
        isolation_level=None,
        check_same_thread=False,
    )
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS};")
        yield conn
    finally:
        with contextlib.suppress(Exception):
            conn.close()


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            session_id TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            profile TEXT,
            model_id TEXT,
            mode TEXT,
            ok INTEGER,
            error TEXT,
            iterations INTEGER,
            tool_calls INTEGER,
            usage_json TEXT,
            thomas_version TEXT
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            t_ms INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            search_text TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at);
        CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, seq);
        CREATE INDEX IF NOT EXISTS idx_events_run_type ON events(run_id, event_type);
        """
    )
    if ENABLE_FTS5 and _fts5_available(conn):
        with contextlib.suppress(Exception):
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(run_id, seq, search_text);")


def _migrate_schema(conn: sqlite3.Connection) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(events);").fetchall()}
    if "search_text" not in cols:
        conn.execute("ALTER TABLE events ADD COLUMN search_text TEXT NOT NULL DEFAULT '';")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, seq);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_run_type ON events(run_id, event_type);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at);")
    # Create FTS table post-migration if possible
    if ENABLE_FTS5 and _fts5_available(conn):
        with contextlib.suppress(Exception):
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(run_id, seq, search_text);")


def _enforce_retention(conn: sqlite3.Connection) -> None:
    with _LOCK:
        if MAX_RUNS and MAX_RUNS > 0:
            total = conn.execute("SELECT COUNT(*) AS c FROM runs;").fetchone()["c"]
            if total > MAX_RUNS:
                _delete_oldest_runs(conn, total - MAX_RUNS)
        if MAX_DB_BYTES and MAX_DB_BYTES > 0:
            db_path = _require_db()
            try:
                size = db_path.stat().st_size
            except FileNotFoundError:
                return
            if size <= MAX_DB_BYTES:
                return
            while True:
                try:
                    if db_path.stat().st_size <= MAX_DB_BYTES:
                        break
                except FileNotFoundError:
                    break
                oldest = conn.execute("SELECT run_id FROM runs ORDER BY started_at ASC LIMIT 10;").fetchall()
                if not oldest:
                    break
                run_ids = [r["run_id"] for r in oldest]
                _delete_runs_by_id(conn, run_ids)
                remaining = conn.execute("SELECT COUNT(*) AS c FROM runs;").fetchone()["c"]
                if remaining == 0:
                    break


def _delete_oldest_runs(conn: sqlite3.Connection, n: int) -> None:
    if n <= 0:
        return
    rows = conn.execute("SELECT run_id FROM runs ORDER BY started_at ASC LIMIT ?;", (int(n),)).fetchall()
    run_ids = [r["run_id"] for r in rows]
    _delete_runs_by_id(conn, run_ids)


def _delete_runs_by_id(conn: sqlite3.Connection, run_ids: list[str]) -> None:
    if not run_ids:
        return
    if _fts_enabled(conn):
        conn.executemany("DELETE FROM events_fts WHERE run_id = ?;", [(rid,) for rid in run_ids])
    conn.executemany("DELETE FROM runs WHERE run_id = ?;", [(rid,) for rid in run_ids])


def _normalize_ok_filter(value: Any) -> int | None:
    if value in (None, ""):
        return None
    ok_val = value
    if isinstance(ok_val, str):
        x = ok_val.strip().lower()
        if x in ("1", "true", "yes", "ok"):
            ok_val = 1
        elif x in ("0", "false", "no", "fail"):
            ok_val = 0
    return int(ok_val)


def _normalize_query_filter(value: Any) -> str | None:
    if value in (None, ""):
        return None
    q = str(value).strip()
    return q or None


def _row_to_run_dict(row: sqlite3.Row) -> dict[str, Any]:
    usage = _json_loads(row["usage_json"]) if row["usage_json"] else None
    return {
        "run_id": row["run_id"],
        "session_id": row["session_id"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "profile": row["profile"],
        "model_id": row["model_id"],
        "mode": row["mode"],
        "ok": None if row["ok"] is None else bool(row["ok"]),
        "error": row["error"],
        "iterations": row["iterations"],
        "tool_calls": row["tool_calls"],
        "usage": usage,
        "thomas_version": row["thomas_version"],
    }


def _utcnow_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="seconds")


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _json_loads(s: str) -> Any:
    return json.loads(s)


_TEXT_KEYS = ("text", "content", "message", "error", "name", "tool", "tool_name", "tool_call_id", "arguments")


def _extract_search_text(payload: Any) -> str:
    parts: list[str] = []

    def walk(x: Any, depth: int = 0) -> None:
        if depth > 4:
            return
        if x is None:
            return
        if isinstance(x, str):
            s = x.strip()
            if s:
                parts.append(s)
            return
        if isinstance(x, (int, float, bool)):
            parts.append(str(x))
            return
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(k, str) and k in _TEXT_KEYS:
                    walk(v, depth + 1)
                if isinstance(k, str) and k in ("type", "role"):
                    parts.append(str(v))
            return
        if isinstance(x, list):
            for it in x[:20]:
                walk(it, depth + 1)

    walk(payload)
    out = " ".join(parts)
    out = re.sub(r"\s+", " ", out).strip()
    return out[:4000]


def _fts5_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS __fts5_probe USING fts5(x);")
        conn.execute("DROP TABLE IF EXISTS __fts5_probe;")
        return True
    except (ValueError, TypeError):
        return False


def _fts_enabled(conn: sqlite3.Connection) -> bool:
    if not ENABLE_FTS5:
        return False
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events_fts';").fetchone()
    return row is not None


def _fts_query(q: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_]+", q)
    if not tokens:
        return q
    return " AND ".join(tokens)
