from __future__ import annotations

import contextlib
import os
import sqlite3
import threading
import time
from typing import Any, Iterable, Iterator, Optional, Sequence, Tuple

class _LockedCursor:
    """Wrap a sqlite3.Cursor so fetch operations are serialized."""
    def __init__(self, cursor: sqlite3.Cursor, lock: threading.RLock):
        self._cursor = cursor
        self._lock = lock

    @property
    def lastrowid(self) -> int:
        return self._cursor.lastrowid

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def fetchone(self):
        with self._lock:
            return self._cursor.fetchone()

    def fetchall(self):
        with self._lock:
            return self._cursor.fetchall()

    def __iter__(self):
        # safest: materialize under lock
        with self._lock:
            return iter(self._cursor.fetchall())

class SqliteDB:
    """SQLite helper with conservative thread-safety.

    Aiohttp handlers may run concurrently; sqlite3 connections are not safe for concurrent use unless access
    is serialized. This wrapper ensures:
      - every execute + fetch is protected by an RLock
      - transactions (via transact()) are also protected
    """

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_pragmas()

    def _init_pragmas(self) -> None:
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA temp_store=MEMORY;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
            # reduce spurious 'database is locked' under concurrency
            self._conn.execute("PRAGMA busy_timeout=5000;")

    @contextlib.contextmanager
    def transact(self) -> Iterator[sqlite3.Connection]:
        """Transaction context that also serializes access."""
        with self._lock:
            with self._conn:
                yield self._conn

    def execute(self, sql: str, args: Tuple[Any, ...] = ()) -> _LockedCursor:
        with self._lock:
            cur = self._conn.execute(sql, args)
            return _LockedCursor(cur, self._lock)

    def executemany(self, sql: str, seq: Iterable[Tuple[Any, ...]]) -> None:
        with self._lock:
            self._conn.executemany(sql, seq)

    def executescript(self, sql: str) -> None:
        with self._lock:
            self._conn.executescript(sql)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def now_ms(self) -> int:
        return int(time.time() * 1000)

    def size_bytes(self) -> int:
        try:
            return os.path.getsize(self.path)
        except FileNotFoundError:
            return 0
