"""Workspace RBAC — plain sqlite3 backend (no SQLAlchemy).

Tables: workspaces, workspace_memberships, workspace_invites
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_MEMBERSHIP_ID = "00000000-0000-0000-0000-000000000002"


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def _new_id() -> str:
    h = secrets.token_hex(16)
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get_db_path(config) -> Path:
    base = getattr(config, "memory", None)
    root = getattr(base, "root_path", None) if base else None
    if root:
        return Path(root) / ".thomas" / "workspaces.sqlite3"
    return Path.home() / ".thomas" / "workspaces.sqlite3"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row

    # Try WAL mode, but fall back to DELETE mode if it fails (e.g., on FUSE filesystems)
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        # WAL mode not supported on this filesystem, use DELETE mode instead
        try:
            con.execute("PRAGMA journal_mode=DELETE")
        except Exception:
            pass  # If DELETE mode also fails, continue with default mode

    con.execute("PRAGMA foreign_keys=ON")
    return con


def ensure_schema(con: sqlite3.Connection) -> None:
    # Try to create schema, handling database I/O errors gracefully
    try:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS workspaces (
                workspace_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                owner_user_id TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_workspaces_owner ON workspaces(owner_user_id);

            CREATE TABLE IF NOT EXISTS workspace_memberships (
                membership_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                created_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                UNIQUE(workspace_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS ix_wm_workspace ON workspace_memberships(workspace_id);
            CREATE INDEX IF NOT EXISTS ix_wm_user ON workspace_memberships(user_id);

            CREATE TABLE IF NOT EXISTS workspace_invites (
                invite_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                email TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                token_hash TEXT NOT NULL UNIQUE,
                created_by_user_id TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                accepted_at TEXT,
                revoked_at TEXT,
                note TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_wi_workspace ON workspace_invites(workspace_id);
            CREATE INDEX IF NOT EXISTS ix_wi_token ON workspace_invites(token_hash);
        """)
        con.commit()

        # Ensure at least the default personal workspace exists
        try:
            row = con.execute("SELECT workspace_id FROM workspaces WHERE workspace_id=?",
                              (DEFAULT_WORKSPACE_ID,)).fetchone()
            if not row:
                con.execute(
                    "INSERT INTO workspaces(workspace_id,name,owner_user_id,created_at) VALUES(?,?,?,?)",
                    (DEFAULT_WORKSPACE_ID, "Personal", None, _utcnow()),
                )
                con.commit()
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            # If we can't access tables, continue anyway (database might be read-only or corrupted)
            pass
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        # If schema creation fails, continue anyway - the database might be corrupted or on a FUSE filesystem
        pass


# ── Workspace CRUD ────────────────────────────────────────────────────────────

def list_workspaces_for_user(con: sqlite3.Connection, user_id: str) -> list[sqlite3.Row]:
    return con.execute(
        """SELECT w.* FROM workspaces w
           JOIN workspace_memberships m ON m.workspace_id=w.workspace_id
           WHERE m.user_id=? AND m.is_active=1
           ORDER BY w.created_at ASC""",
        (user_id,),
    ).fetchall()


def create_workspace(con: sqlite3.Connection, name: str, owner_user_id: str) -> sqlite3.Row:
    ws_id = _new_id()
    now = _utcnow()
    con.execute(
        "INSERT INTO workspaces(workspace_id,name,owner_user_id,created_at) VALUES(?,?,?,?)",
        (ws_id, name, owner_user_id, now),
    )
    mid = _new_id()
    con.execute(
        "INSERT INTO workspace_memberships(membership_id,workspace_id,user_id,role,created_at,is_active)"
        " VALUES(?,?,?,?,?,1)",
        (mid, ws_id, owner_user_id, "owner", now),
    )
    con.commit()
    return con.execute("SELECT * FROM workspaces WHERE workspace_id=?", (ws_id,)).fetchone()


def get_workspace(con: sqlite3.Connection, workspace_id: str) -> Optional[sqlite3.Row]:
    return con.execute("SELECT * FROM workspaces WHERE workspace_id=?", (workspace_id,)).fetchone()


# ── Membership CRUD ───────────────────────────────────────────────────────────

def get_membership(con: sqlite3.Connection, workspace_id: str, user_id: str) -> Optional[sqlite3.Row]:
    return con.execute(
        "SELECT * FROM workspace_memberships WHERE workspace_id=? AND user_id=? AND is_active=1",
        (workspace_id, user_id),
    ).fetchone()


def first_membership_for_user(con: sqlite3.Connection, user_id: str) -> Optional[sqlite3.Row]:
    return con.execute(
        "SELECT * FROM workspace_memberships WHERE user_id=? AND is_active=1 ORDER BY created_at ASC LIMIT 1",
        (user_id,),
    ).fetchone()


def list_members(con: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT * FROM workspace_memberships WHERE workspace_id=? ORDER BY created_at ASC",
        (workspace_id,),
    ).fetchall()


def upsert_membership(con: sqlite3.Connection, workspace_id: str, user_id: str,
                      role: str, is_active: bool = True) -> sqlite3.Row:
    existing = con.execute(
        "SELECT membership_id FROM workspace_memberships WHERE workspace_id=? AND user_id=?",
        (workspace_id, user_id),
    ).fetchone()
    now = _utcnow()
    if existing:
        con.execute(
            "UPDATE workspace_memberships SET role=?,is_active=? WHERE workspace_id=? AND user_id=?",
            (role, 1 if is_active else 0, workspace_id, user_id),
        )
    else:
        mid = _new_id()
        con.execute(
            "INSERT INTO workspace_memberships(membership_id,workspace_id,user_id,role,created_at,is_active)"
            " VALUES(?,?,?,?,?,?)",
            (mid, workspace_id, user_id, role, now, 1 if is_active else 0),
        )
    con.commit()
    return con.execute(
        "SELECT * FROM workspace_memberships WHERE workspace_id=? AND user_id=?",
        (workspace_id, user_id),
    ).fetchone()


def deactivate_member(con: sqlite3.Connection, workspace_id: str, user_id: str) -> bool:
    cur = con.execute(
        "UPDATE workspace_memberships SET is_active=0 WHERE workspace_id=? AND user_id=?",
        (workspace_id, user_id),
    )
    con.commit()
    return cur.rowcount > 0


# ── Invites ───────────────────────────────────────────────────────────────────

def create_invite(con: sqlite3.Connection, workspace_id: str, email: str,
                  role: str, created_by: Optional[str], note: Optional[str]) -> tuple[sqlite3.Row, str]:
    raw = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw)
    inv_id = _new_id()
    now = _utcnow()
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).replace(tzinfo=None).isoformat(
        sep=" ",
        timespec="seconds",
    )
    con.execute(
        "INSERT INTO workspace_invites"
        "(invite_id,workspace_id,email,role,token_hash,created_by_user_id,created_at,expires_at,note)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (inv_id, workspace_id, email.strip().lower(), role, token_hash, created_by, now, expires, note),
    )
    con.commit()
    row = con.execute("SELECT * FROM workspace_invites WHERE invite_id=?", (inv_id,)).fetchone()
    return row, raw


def get_invite_by_token(con: sqlite3.Connection, raw_token: str) -> Optional[sqlite3.Row]:
    token_hash = _hash_token(raw_token)
    return con.execute(
        "SELECT * FROM workspace_invites WHERE token_hash=?", (token_hash,)
    ).fetchone()


def accept_invite(con: sqlite3.Connection, invite_id: str, user_id: str) -> Optional[sqlite3.Row]:
    now = _utcnow()
    con.execute("UPDATE workspace_invites SET accepted_at=? WHERE invite_id=?", (now, invite_id))
    con.commit()
    inv = con.execute("SELECT * FROM workspace_invites WHERE invite_id=?", (invite_id,)).fetchone()
    if not inv:
        return None
    return upsert_membership(con, inv["workspace_id"], user_id, inv["role"], is_active=True)


def list_invites(con: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT * FROM workspace_invites WHERE workspace_id=? ORDER BY created_at DESC",
        (workspace_id,),
    ).fetchall()
