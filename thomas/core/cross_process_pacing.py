"""SQLite-backed request admission shared by Thomas Chat and Build processes.

Only HTTP attempts occupy leases. A crashed process loses its leases when the
next contender observes that its PID and creation time no longer match.
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:  # optional; the native process checks below need no extra package
    psutil = None

from thomas.core.provider_pacing import parse_retry_after


def _process_started(pid: int) -> float | None:
    if psutil is not None:
        try:
            return psutil.Process(pid).create_time()
        except psutil.Error:
            return None
    if os.name == "nt":
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetProcessTimes.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        )
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            created = wintypes.FILETIME()
            exited = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            if not kernel32.GetProcessTimes(
                handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)
            ):
                return None
            return float((created.dwHighDateTime << 32) | created.dwLowDateTime)
        finally:
            kernel32.CloseHandle(handle)
    proc = Path(f"/proc/{pid}")
    if proc.exists():
        try:
            return proc.stat().st_ctime
        except OSError:
            return None
    try:
        value = subprocess.check_output(["ps", "-o", "lstart=", "-p", str(pid)], timeout=2).decode().strip()
        return time.mktime(time.strptime(value, "%a %b %d %H:%M:%S %Y")) if value else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class CrossProcessProviderPacer:
    def __init__(
        self,
        path: Path,
        *,
        provider: str,
        ceiling: int = 100,
        floor: int = 1,
        increase_every: int = 8,
        reserved_interactive: int = 4,
        poll_s: float = 0.03,
    ) -> None:
        if not provider or not 1 <= floor <= ceiling or not 0 <= reserved_interactive < ceiling:
            raise ValueError("invalid provider pacing configuration")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.provider = provider
        self.ceiling = ceiling
        self.floor = floor
        self.increase_every = increase_every
        self.reserved_interactive = reserved_interactive
        self.poll_s = poll_s
        self.pid = os.getpid()
        self.process_started = _process_started(self.pid)
        if self.process_started is None:
            raise RuntimeError("provider pacing could not identify the current process")
        self._local_lock = threading.Lock()
        self._retry_after: dict[str, float] = {}
        with closing(self._db()) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS provider_state (provider TEXT PRIMARY KEY, cap INTEGER NOT NULL, "
                "clean INTEGER NOT NULL DEFAULT 0, last_decrease REAL NOT NULL DEFAULT 0, "
                "peak INTEGER NOT NULL DEFAULT 0, refusals INTEGER NOT NULL DEFAULT 0)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS provider_waiters (ticket TEXT PRIMARY KEY, provider TEXT NOT NULL, "
                "lane TEXT NOT NULL, pid INTEGER NOT NULL, process_started REAL NOT NULL, created REAL NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS provider_leases (ticket TEXT PRIMARY KEY, provider TEXT NOT NULL, "
                "pid INTEGER NOT NULL, process_started REAL NOT NULL, sent REAL NOT NULL)"
            )
            db.execute("INSERT OR IGNORE INTO provider_state(provider, cap) VALUES (?, ?)", (provider, ceiling))

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.execute("PRAGMA busy_timeout=30000")
        return db

    @staticmethod
    def _alive(pid: int, started: float) -> bool:
        current = _process_started(pid)
        return current is not None and abs(current - started) < 0.01

    def _reap(self, db: sqlite3.Connection) -> None:
        rows = db.execute(
            "SELECT DISTINCT pid, process_started FROM provider_leases WHERE provider=? "
            "UNION SELECT DISTINCT pid, process_started FROM provider_waiters WHERE provider=?",
            (self.provider, self.provider),
        ).fetchall()
        for pid, started in rows:
            if not self._alive(pid, started):
                for table in ("provider_leases", "provider_waiters"):
                    db.execute(
                        f"DELETE FROM {table} WHERE provider=? AND pid=? AND process_started=?",
                        (self.provider, pid, started),
                    )

    def _transaction(self, action):
        db = self._db()
        try:
            db.execute("BEGIN IMMEDIATE")
            result = action(db)
            db.execute("COMMIT")
            return result
        except (sqlite3.Error, OSError, ValueError):
            db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    async def acquire(self, builder: str, *, lane: str = "worker", abort=lambda: False) -> dict[str, Any]:
        if lane not in {"worker", "interactive"}:
            raise ValueError("unknown provider admission lane")
        started = time.monotonic()
        with self._local_lock:
            not_before = self._retry_after.get(builder, 0.0)
        while time.monotonic() < not_before:
            if abort():
                return {"slot": False, "ticket": None}
            await asyncio.sleep(min(self.poll_s, not_before - time.monotonic()))
        ticket = uuid.uuid4().hex
        self._transaction(
            lambda db: db.execute(
                "INSERT INTO provider_waiters VALUES (?, ?, ?, ?, ?, ?)",
                (ticket, self.provider, lane, self.pid, self.process_started, started),
            )
        )
        admitted = False
        try:
            while not abort():

                def try_acquire(db):
                    self._reap(db)
                    head = db.execute(
                        "SELECT ticket FROM provider_waiters WHERE provider=? AND lane=? ORDER BY created, ticket LIMIT 1",
                        (self.provider, lane),
                    ).fetchone()
                    cap, peak = db.execute(
                        "SELECT cap, peak FROM provider_state WHERE provider=?", (self.provider,)
                    ).fetchone()
                    inflight = db.execute(
                        "SELECT COUNT(*) FROM provider_leases WHERE provider=?", (self.provider,)
                    ).fetchone()[0]
                    allowance = cap if lane == "interactive" else max(1, cap - self.reserved_interactive)
                    if head is None or head[0] != ticket or inflight >= allowance:
                        return None
                    sent = time.time()
                    acquired_at = time.monotonic()
                    db.execute("DELETE FROM provider_waiters WHERE ticket=?", (ticket,))
                    db.execute(
                        "INSERT INTO provider_leases VALUES (?, ?, ?, ?, ?)",
                        (ticket, self.provider, self.pid, self.process_started, sent),
                    )
                    db.execute(
                        "UPDATE provider_state SET peak=? WHERE provider=?",
                        (max(peak, inflight + 1), self.provider),
                    )
                    return sent, acquired_at, cap, inflight + 1

                result = self._transaction(try_acquire)
                if result is not None:
                    admitted = True
                    sent, acquired_at, cap, inflight = result
                    with self._local_lock:
                        self._retry_after.pop(builder, None)
                    return {
                        "slot": True,
                        "ticket": ticket,
                        "sent_at": sent,
                        "wait_s": acquired_at - started,
                        "cap_at_acquire": cap,
                        "inflight_after_acquire": inflight,
                    }
                await asyncio.sleep(self.poll_s)
            return {"slot": False, "ticket": ticket}
        finally:
            if not admitted:
                self._transaction(lambda db: db.execute("DELETE FROM provider_waiters WHERE ticket=?", (ticket,)))

    def release(
        self,
        builder: str,
        *,
        ticket: str,
        kind: str,
        sent_mono: float | None = None,
        retry_after_raw: Any = None,
        status: Any = None,
    ) -> dict[str, Any]:
        def settle(db):
            lease = db.execute(
                "SELECT sent FROM provider_leases WHERE ticket=? AND provider=?", (ticket, self.provider)
            ).fetchone()
            if lease is None:
                return self._state(db)
            db.execute("DELETE FROM provider_leases WHERE ticket=?", (ticket,))
            cap, clean, last, peak, refusals = db.execute(
                "SELECT cap, clean, last_decrease, peak, refusals FROM provider_state WHERE provider=?",
                (self.provider,),
            ).fetchone()
            # Use the persisted wall timestamp so manager restarts and process
            # boundaries compare attempts in the same clock domain.
            sent = lease[0]
            if kind == "provider_refusal":
                refusals += 1
                if sent > last:
                    cap, clean, last = max(self.floor, cap // 2), 0, time.time()
            elif kind == "clean" and sent > last:
                clean += 1
                if clean >= self.increase_every and cap < self.ceiling:
                    cap, clean = cap + 1, 0
            db.execute(
                "UPDATE provider_state SET cap=?, clean=?, last_decrease=?, refusals=? WHERE provider=?",
                (cap, clean, last, refusals, self.provider),
            )
            return {"cap": cap, "inflight": self._state(db)["inflight"], "kind": kind}

        result = self._transaction(settle)
        if kind == "provider_refusal":
            parsed = parse_retry_after(retry_after_raw)
            wait = 20.0 if parsed is None else min(parsed, 300.0)
            with self._local_lock:
                self._retry_after[builder] = time.monotonic() + wait
        return result

    def _state(self, db) -> dict[str, Any]:
        cap, peak, refusals = db.execute(
            "SELECT cap, peak, refusals FROM provider_state WHERE provider=?", (self.provider,)
        ).fetchone()
        inflight = db.execute("SELECT COUNT(*) FROM provider_leases WHERE provider=?", (self.provider,)).fetchone()[0]
        waiting = db.execute("SELECT COUNT(*) FROM provider_waiters WHERE provider=?", (self.provider,)).fetchone()[0]
        return {
            "ceiling": self.ceiling,
            "cap_now": cap,
            "inflight": inflight,
            "inflight_now": inflight,
            "peak_inflight": peak,
            "waiting_now": waiting,
            "refusals_total": refusals,
            "reserved_interactive": self.reserved_interactive,
        }

    def report(self) -> dict[str, Any]:
        return self._transaction(lambda db: (self._reap(db), self._state(db))[1])
