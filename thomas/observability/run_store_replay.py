# thomas/observability/run_store_replay.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from thomas.observability.run_db import connect, ensure_schema, resolve_runs_db_path


@dataclass(frozen=True)
class RunEvent:
    index: int
    seq: int
    t_ms: int | None
    event_type: str
    payload: Any


def count_events(run_id: str, db_path: Path | None = None) -> int:
    db_path = db_path or resolve_runs_db_path()
    ensure_schema(db_path)
    con = connect(db_path)
    try:
        cur = con.execute("SELECT COUNT(1) AS n FROM events WHERE run_id = ?", (run_id,))
        row = cur.fetchone()
        return int(row["n"] if row else 0)
    finally:
        con.close()


def list_events(
    run_id: str,
    *,
    start: int = 0,
    limit: int = 500,
    db_path: Path | None = None,
) -> list[RunEvent]:
    if start < 0:
        start = 0
    if limit <= 0:
        return []
    if limit > 5000:
        limit = 5000

    db_path = db_path or resolve_runs_db_path()
    ensure_schema(db_path)
    con = connect(db_path)
    try:
        cur = con.execute(
            """
            SELECT id, seq, t_ms, event_type, payload_json
            FROM events
            WHERE run_id = ?
            ORDER BY seq ASC, id ASC
            LIMIT ? OFFSET ?
            """,
            (run_id, limit, start),
        )
        out: list[RunEvent] = []
        idx = start
        for row in cur.fetchall():
            payload_json = row["payload_json"]
            try:
                payload = json.loads(payload_json) if payload_json else None
            except json.JSONDecodeError:
                payload = {"_parse_error": True, "raw": payload_json}
            out.append(
                RunEvent(
                    index=idx,
                    seq=int(row["seq"]) if row["seq"] is not None else idx,
                    t_ms=int(row["t_ms"]) if row["t_ms"] is not None else None,
                    event_type=str(row["event_type"] or ""),
                    payload=payload,
                )
            )
            idx += 1
        return out
    finally:
        con.close()


def get_event_at_index(run_id: str, index: int, db_path: Path | None = None) -> RunEvent | None:
    if index < 0:
        return None
    events = list_events(run_id, start=index, limit=1, db_path=db_path)
    return events[0] if events else None


def get_run_metadata(run_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    db_path = db_path or resolve_runs_db_path()
    ensure_schema(db_path)
    con = connect(db_path)
    try:
        cur = con.execute("SELECT * FROM runs WHERE run_id = ? LIMIT 1", (run_id,))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        if "meta_json" in d and isinstance(d["meta_json"], str):
            try:
                d["meta_json"] = json.loads(d["meta_json"])
            except json.JSONDecodeError:
                pass
        return d
    finally:
        con.close()
