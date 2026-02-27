# thomas/observability/event_recorder.py
from __future__ import annotations

import contextlib
import contextvars
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from thomas.observability.redaction import redact_obj
from thomas.observability.run_db import connect, ensure_schema, resolve_runs_db_path

_current_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("thomas_run_id", default=None)
_run_start_perf: contextvars.ContextVar[float | None] = contextvars.ContextVar("thomas_run_start_perf", default=None)
_seq_counter: contextvars.ContextVar[int] = contextvars.ContextVar("thomas_run_seq", default=0)

ENV_REDACT_WRITE = "THOMAS_REDACT_AT_WRITE"  # "1" to enable


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _t_ms() -> int | None:
    start = _run_start_perf.get()
    if start is None:
        return None
    return int((time.perf_counter() - start) * 1000.0)


def get_current_run_id() -> str | None:
    return _current_run_id.get()


def attach_run(run_id: str) -> None:
    _current_run_id.set(run_id)
    if _run_start_perf.get() is None:
        _run_start_perf.set(time.perf_counter())


def _ensure_run_row(run_id: str, meta: dict[str, Any] | None = None) -> None:
    db = resolve_runs_db_path()
    ensure_schema(db)
    con = connect(db)
    try:
        cur = con.execute("SELECT run_id, last_seq FROM runs WHERE run_id = ? LIMIT 1", (run_id,))
        row = cur.fetchone()
        if row is None:
            con.execute(
                "INSERT INTO runs(run_id, started_at, ok, meta_json, last_seq) VALUES (?, ?, ?, ?, ?)",
                (run_id, _now_iso(), None, json.dumps(meta or {}, separators=(",", ":")), 0),
            )
            con.commit()
            _seq_counter.set(0)
        else:
            try:
                last = int(row["last_seq"] or 0)
            except json.JSONDecodeError:
                last = 0
            _seq_counter.set(last)
    finally:
        con.close()


def start_run(meta: dict[str, Any] | None = None, run_id: str | None = None) -> str:
    rid = run_id or f"run_{uuid.uuid4().hex}"
    attach_run(rid)
    _ensure_run_row(rid, meta=meta)
    return rid


def end_run(ok: bool | None = None, error: str | None = None) -> None:
    rid = get_current_run_id()
    if not rid:
        return
    db = resolve_runs_db_path()
    ensure_schema(db)
    con = connect(db)
    try:
        con.execute(
            "UPDATE runs SET ended_at = ?, ok = COALESCE(?, ok), error = COALESCE(?, error), last_seq = ? WHERE run_id = ?",
            (_now_iso(), None if ok is None else (1 if ok else 0), error, _seq_counter.get(), rid),
        )
        con.commit()
    finally:
        con.close()


def _next_seq() -> int:
    nxt = _seq_counter.get() + 1
    _seq_counter.set(nxt)
    return nxt


def record_event(event_type: str, payload: Any, *, t_ms: int | None = None, run_id: str | None = None) -> None:
    """
    Persist an event for the current run.
    Secrets are enforced at read/export time; optional write-time redaction is available.
    """
    rid = run_id or get_current_run_id()
    if not rid:
        return

    # Prefer existing repo's run_store if it has an event writer.
    try:
        from thomas.observability import run_store  # type: ignore

        for fn_name in ("record_event", "append_event", "log_event", "add_event"):
            fn = getattr(run_store, fn_name, None)
            if callable(fn):
                fn(rid, event_type, payload, t_ms=t_ms)  # type: ignore
                return
    except ImportError:
        pass

    db = resolve_runs_db_path()
    ensure_schema(db)

    t = t_ms if t_ms is not None else _t_ms()
    seq = _next_seq()

    do_redact = os.getenv(ENV_REDACT_WRITE, "0").strip() == "1"
    safe_payload = redact_obj(payload) if do_redact else payload

    con = connect(db)
    try:
        con.execute(
            "INSERT INTO events(run_id, t_ms, seq, event_type, payload_json) VALUES (?, ?, ?, ?, ?)",
            (rid, t, seq, event_type, json.dumps(safe_payload, separators=(",", ":"), ensure_ascii=False)),
        )
        con.execute("UPDATE runs SET last_seq = ? WHERE run_id = ?", (seq, rid))
        con.commit()
    finally:
        con.close()


@dataclass(frozen=True)
class RunContext:
    run_id: str

    def __enter__(self) -> RunContext:
        attach_run(self.run_id)
        _ensure_run_row(self.run_id, meta={})
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is None:
            end_run(ok=True)
        else:
            end_run(ok=False, error=str(exc))


@contextlib.contextmanager
def run_context(meta: dict[str, Any] | None = None, run_id: str | None = None):
    rid = start_run(meta=meta, run_id=run_id)
    try:
        yield rid
        end_run(ok=True)
    except Exception as e:
        end_run(ok=False, error=str(e))
        raise
