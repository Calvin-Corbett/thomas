"""
Notification Store (SQLite)

Goals:
- Durable notifications with filters + unread count
- Safe concurrency for FastAPI
- Minimal assumptions about the rest of Thomas
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    from pydantic import BaseModel, Field
except Exception:  # pragma: no cover
    BaseModel = object  # type: ignore
    Field = lambda *a, **k: None  # type: ignore


# -----------------------------
# Models
# -----------------------------

SEVERITIES = ("info", "warn", "error")


class NotificationCreate(BaseModel):
    type: str = Field(..., description="Event type, e.g. task.complete")
    title: str = Field(..., description="Short title")
    body: str = Field(..., description="Human readable description")
    severity: str = Field("info", description="info|warn|error")
    action_url: Optional[str] = Field(None, description="Optional deep link URL")

    def normalized(self) -> "NotificationCreate":
        sev = (self.severity or "info").lower()
        if sev not in SEVERITIES:
            sev = "info"
        self.severity = sev
        self.type = (self.type or "").strip()
        self.title = (self.title or "").strip()
        self.body = (self.body or "").strip()
        return self


class Notification(BaseModel):
    id: str
    type: str
    title: str
    body: str
    severity: str
    read: bool
    timestamp: int  # epoch ms (UTC)
    action_url: Optional[str] = None


class PushSubscription(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
    expiration_time: Optional[int] = None
    user_agent: Optional[str] = None
    created_at: int


# -----------------------------
# Store
# -----------------------------

MIGRATION_STATEMENTS: Tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS notifications (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        severity TEXT NOT NULL,
        read INTEGER NOT NULL DEFAULT 0,
        timestamp INTEGER NOT NULL,
        action_url TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_notifications_timestamp ON notifications(timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read, timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_notifications_type ON notifications(type, timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_notifications_severity ON notifications(severity, timestamp DESC);",
    """
    CREATE TABLE IF NOT EXISTS push_subscriptions (
        endpoint TEXT PRIMARY KEY,
        p256dh TEXT NOT NULL,
        auth TEXT NOT NULL,
        expiration_time INTEGER,
        user_agent TEXT,
        created_at INTEGER NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_push_created_at ON push_subscriptions(created_at DESC);",
)


def now_ms() -> int:
    return int(time.time() * 1000)


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


class NotificationStore:
    """
    SQLite store. Thread-safe via a single lock and short-lived connections.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        ensure_parent_dir(db_path)
        self._lock = threading.Lock()
        self.migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Pragmas for concurrency + durability
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def migrate(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                for stmt in MIGRATION_STATEMENTS:
                    conn.execute(stmt)
                conn.commit()
            finally:
                conn.close()

    # -----------------------------
    # Notifications
    # -----------------------------

    def add(self, notif_id: str, payload: NotificationCreate, timestamp_ms: Optional[int] = None) -> Notification:
        payload = payload.normalized()
        ts = timestamp_ms or now_ms()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO notifications (id, type, title, body, severity, read, timestamp, action_url)
                    VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (notif_id, payload.type, payload.title, payload.body, payload.severity, ts, payload.action_url),
                )
                conn.commit()
            finally:
                conn.close()
        return Notification(
            id=notif_id,
            type=payload.type,
            title=payload.title,
            body=payload.body,
            severity=payload.severity,
            read=False,
            timestamp=ts,
            action_url=payload.action_url,
        )

    def get(self, notif_id: str) -> Optional[Notification]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT * FROM notifications WHERE id = ?", (notif_id,)).fetchone()
                if not row:
                    return None
                return self._row_to_notification(row)
            finally:
                conn.close()

    def mark_read(self, notif_id: str) -> Optional[Notification]:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("UPDATE notifications SET read = 1 WHERE id = ?", (notif_id,))
                conn.commit()
                row = conn.execute("SELECT * FROM notifications WHERE id = ?", (notif_id,)).fetchone()
                if not row:
                    return None
                return self._row_to_notification(row)
            finally:
                conn.close()

    def clear(self, mode: str = "all") -> int:
        """
        mode:
          - all: delete all notifications
          - read: delete only read notifications
        """
        mode = (mode or "all").lower()
        with self._lock:
            conn = self._connect()
            try:
                if mode == "read":
                    cur = conn.execute("DELETE FROM notifications WHERE read = 1")
                else:
                    cur = conn.execute("DELETE FROM notifications")
                conn.commit()
                return cur.rowcount or 0
            finally:
                conn.close()

    def unread_count(self, type_: Optional[str] = None, severity: Optional[str] = None) -> int:
        where, params = self._build_where(type_=type_, severity=severity, unread_only=True)
        sql = "SELECT COUNT(*) AS c FROM notifications" + where
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(sql, params).fetchone()
                return int(row["c"]) if row else 0
            finally:
                conn.close()

    def list(
        self,
        limit: int = 50,
        offset: int = 0,
        type_: Optional[str] = None,
        severity: Optional[str] = None,
        unread_only: bool = False,
    ) -> List[Notification]:
        limit = max(1, min(int(limit or 50), 200))
        offset = max(0, int(offset or 0))
        where, params = self._build_where(type_=type_, severity=severity, unread_only=unread_only)
        sql = (
            "SELECT * FROM notifications"
            + where
            + " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        )
        params = list(params) + [limit, offset]
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
                return [self._row_to_notification(r) for r in rows]
            finally:
                conn.close()

    def _build_where(
        self,
        type_: Optional[str],
        severity: Optional[str],
        unread_only: bool,
    ) -> Tuple[str, List[Any]]:
        clauses: List[str] = []
        params: List[Any] = []

        if type_:
            clauses.append("type = ?")
            params.append(type_)
        if severity:
            sev = severity.lower()
            if sev in SEVERITIES:
                clauses.append("severity = ?")
                params.append(sev)
        if unread_only:
            clauses.append("read = 0")

        if clauses:
            return " WHERE " + " AND ".join(clauses), params
        return "", params

    def _row_to_notification(self, row: sqlite3.Row) -> Notification:
        return Notification(
            id=row["id"],
            type=row["type"],
            title=row["title"],
            body=row["body"],
            severity=row["severity"],
            read=bool(row["read"]),
            timestamp=int(row["timestamp"]),
            action_url=row["action_url"],
        )

    # -----------------------------
    # Push subscriptions
    # -----------------------------

    def upsert_subscription(
        self,
        endpoint: str,
        p256dh: str,
        auth: str,
        expiration_time: Optional[int] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        created = now_ms()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO push_subscriptions (endpoint, p256dh, auth, expiration_time, user_agent, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(endpoint) DO UPDATE SET
                      p256dh=excluded.p256dh,
                      auth=excluded.auth,
                      expiration_time=excluded.expiration_time,
                      user_agent=excluded.user_agent
                    """,
                    (endpoint, p256dh, auth, expiration_time, user_agent, created),
                )
                conn.commit()
            finally:
                conn.close()

    def delete_subscription(self, endpoint: str) -> int:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
                conn.commit()
                return cur.rowcount or 0
            finally:
                conn.close()

    def list_subscriptions(self) -> List[PushSubscription]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute("SELECT * FROM push_subscriptions ORDER BY created_at DESC").fetchall()
                out: List[PushSubscription] = []
                for r in rows:
                    out.append(
                        PushSubscription(
                            endpoint=r["endpoint"],
                            p256dh=r["p256dh"],
                            auth=r["auth"],
                            expiration_time=r["expiration_time"],
                            user_agent=r["user_agent"],
                            created_at=int(r["created_at"]),
                        )
                    )
                return out
            finally:
                conn.close()
