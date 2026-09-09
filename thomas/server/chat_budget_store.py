"""Durable SQLite storage primitives for the Chat token budget ledger."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class ChatBudgetError(RuntimeError):
    """Base error for fail-closed budget accounting."""


class ChatBudgetExceeded(ChatBudgetError):
    """Raised when a configured token budget cannot admit a provider call."""


@dataclass(frozen=True)
class ChatBudgetTicket:
    ticket_id: str
    user_id: str
    session_id: str
    reserved_tokens: int
    hard_limit: bool = False


@dataclass(frozen=True)
class ChatBudgetTotals:
    session_tokens: int
    daily_tokens: int


_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_usage (
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    tokens INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, session_id)
);
CREATE TABLE IF NOT EXISTS daily_usage (
    day TEXT NOT NULL,
    user_id TEXT NOT NULL,
    tokens INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, user_id)
);
CREATE TABLE IF NOT EXISTS reservations (
    ticket_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    reserved_tokens INTEGER NOT NULL,
    hard_limit INTEGER NOT NULL DEFAULT 0,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settlements (
    ticket_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    actual_tokens INTEGER NOT NULL,
    overrun_tokens INTEGER NOT NULL DEFAULT 0,
    settled_at REAL NOT NULL
);
"""

_SQLITE_INIT_LOCK = threading.Lock()


class ChatBudgetStore:
    """SQLite-backed ledger with cross-process reservations and atomic settlement."""

    _LEASE_SECONDS = 21_600.0

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migration_lock = threading.Lock()
        self._initialized = False

    @staticmethod
    def _today() -> str:
        return datetime.now().astimezone().date().isoformat()

    def _migrate_legacy_json(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        with self.path.open("rb") as handle:
            if handle.read(16) == b"SQLite format 3\x00":
                return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ChatBudgetError("Token budget ledger is unavailable") from exc
        if not isinstance(payload, dict):
            raise ChatBudgetError("Token budget ledger is unavailable")
        backup = self.path.with_suffix(self.path.suffix + ".legacy-json")
        try:
            os.replace(self.path, backup)
        except OSError as exc:
            raise ChatBudgetError("Token budget ledger could not be migrated") from exc
        conn = self._connect_raw()
        try:
            conn.executescript(_SCHEMA)
            day = str(payload.get("day") or self._today())
            for session_id, tokens in dict(payload.get("sessions") or {}).items():
                conn.execute(
                    "INSERT OR REPLACE INTO session_usage(user_id, session_id, tokens) VALUES(?, ?, ?)",
                    ("default", str(session_id), max(0, int(tokens or 0))),
                )
            for user_id, tokens in dict(payload.get("daily") or {}).items():
                conn.execute(
                    "INSERT OR REPLACE INTO daily_usage(day, user_id, tokens) VALUES(?, ?, ?)",
                    (day, str(user_id), max(0, int(tokens or 0))),
                )
            conn.commit()
        finally:
            conn.close()

    def _connect_raw(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30.0, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _connect(self) -> sqlite3.Connection:
        if not self._initialized:
            with self._migration_lock, _SQLITE_INIT_LOCK:
                if not self._initialized:
                    self._migrate_legacy_json()
                    conn = self._connect_raw()
                    try:
                        conn.executescript(_SCHEMA)
                    finally:
                        conn.close()
                    self._initialized = True
        return self._connect_raw()

    def _connect_checked(self) -> sqlite3.Connection:
        try:
            return self._connect()
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            raise ChatBudgetError("Token budget ledger is unavailable") from exc

    @staticmethod
    def _scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> int:
        row = conn.execute(sql, params).fetchone()
        return max(0, int((row or (0,))[0] or 0))
