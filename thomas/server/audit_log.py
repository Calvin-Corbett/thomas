from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from thomas.policy.redact import Redactor


@dataclass
class AuditLog:
    path: Path
    redactor: Redactor

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path), check_same_thread=False)
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        return con

    def _init_db(self) -> None:
        con = self._connect()
        try:
            con.execute(
                """CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    kind TEXT NOT NULL,
                    run_id TEXT,
                    session_id TEXT,
                    tool_call_id TEXT,
                    tool_name TEXT,
                    decision TEXT,
                    reason TEXT,
                    payload_json TEXT
                );"""
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_events(run_id, ts);")
            con.execute("CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_events(session_id, ts);")
            con.commit()
        finally:
            con.close()

    def log(
        self,
        *,
        kind: str,
        run_id: str = "",
        session_id: str = "",
        tool_call_id: str = "",
        tool_name: str = "",
        decision: str = "",
        reason: str = "",
        payload: Any = None,
    ) -> None:
        red_payload = self.redactor.redact_obj(payload)
        red_reason = self.redactor.redact_text(reason or "")
        payload_json = json.dumps(red_payload, ensure_ascii=False)
        con = self._connect()
        try:
            con.execute(
                """INSERT INTO audit_events (ts, kind, run_id, session_id, tool_call_id, tool_name, decision, reason, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (time.time(), kind, run_id, session_id, tool_call_id, tool_name, decision, red_reason, payload_json),
            )
            con.commit()
        finally:
            con.close()

    async def log_async(self, **kwargs: Any) -> None:
        await asyncio.to_thread(self.log, **kwargs)
