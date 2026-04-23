"""Runtime schema migrator for workspace.rbac_multi_tenant.

This is included so you can get a production-grade migration even if your repo's Alembic
graph can't be authored here (because we can't see your current down_revision).

Usage (from repo root):
  python -m server.workspace.migrate_schema

What it does:
  - Creates tables: workspaces, workspace_memberships, workspace_invites (if missing)
  - Adds workspace_id columns + indexes to known tables if they exist and lack the column
  - Creates a default workspace for existing single-workspace installs
  - Backfills workspace_id on existing rows

You can later wrap this logic inside an Alembic migration once you know your down_revision.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.engine import Engine


DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_MEMBERSHIP_ID = "00000000-0000-0000-0000-000000000002"


CANDIDATE_TABLES = [
    # sessions
    "sessions", "user_sessions", "auth_sessions",
    # chat
    "chats", "chat_sessions", "chat_threads", "chat_messages",
    # memory
    "memories", "memory_items", "memory_entries",
    # autonomy jobs
    "autonomy_jobs", "jobs", "task_runs",
    # api tokens
    "api_tokens", "tokens",
]


def _utcnow() -> datetime:
    return datetime.utcnow()


def _import_engine() -> Engine:
    candidates = [
        ("server.db.session", "engine"),
        ("server.db.session", "get_engine"),
        ("server.db", "engine"),
        ("server.database", "engine"),
    ]
    last = None
    for mod, sym in candidates:
        try:
            m = __import__(mod, fromlist=[sym])
            obj = getattr(m, sym)
            if callable(obj):
                eng = obj()
            else:
                eng = obj
            if isinstance(eng, sa.engine.Engine):
                return eng
        except Exception as e:
            last = e
    raise RuntimeError(
        "Could not locate SQLAlchemy Engine. "
        "Update server/workspace/migrate_schema.py::_import_engine() for your repo."
    ) from last


def _table_exists(insp, name: str) -> bool:
    return name in insp.get_table_names()


def _has_column(insp, table: str, col: str) -> bool:
    return any(c["name"] == col for c in insp.get_columns(table))


def _add_index(conn, table: str, col: str) -> None:
    idx = f"ix_{table}_{col}"
    insp = inspect(conn)
    existing = {i["name"] for i in insp.get_indexes(table)}
    if idx in existing:
        return
    conn.execute(sa.text(f"CREATE INDEX {idx} ON {table} ({col})"))


def _create_tables(conn) -> None:
    insp = inspect(conn)

    if not _table_exists(insp, "workspaces"):
        conn.execute(sa.text(
            "CREATE TABLE workspaces ("
            "workspace_id VARCHAR(36) PRIMARY KEY,"
            "name VARCHAR(200) NOT NULL,"
            "owner_user_id VARCHAR(64),"
            "created_at DATETIME NOT NULL"
            ")"
        ))
        _add_index(conn, "workspaces", "owner_user_id")

    if not _table_exists(insp, "workspace_memberships"):
        conn.execute(sa.text(
            "CREATE TABLE workspace_memberships ("
            "membership_id VARCHAR(36) PRIMARY KEY,"
            "workspace_id VARCHAR(36) NOT NULL,"
            "user_id VARCHAR(64) NOT NULL,"
            "role VARCHAR(20) NOT NULL DEFAULT 'member',"
            "created_at DATETIME NOT NULL,"
            "is_active BOOLEAN NOT NULL DEFAULT 1,"
            "CONSTRAINT uq_workspace_memberships_workspace_user UNIQUE (workspace_id, user_id)"
            ")"
        ))
        _add_index(conn, "workspace_memberships", "workspace_id")
        _add_index(conn, "workspace_memberships", "user_id")
        # composite index best-effort
        try:
            conn.execute(sa.text("CREATE INDEX ix_workspace_memberships_workspace_role ON workspace_memberships (workspace_id, role)"))
        except Exception:
            pass

    if not _table_exists(insp, "workspace_invites"):
        conn.execute(sa.text(
            "CREATE TABLE workspace_invites ("
            "invite_id VARCHAR(36) PRIMARY KEY,"
            "workspace_id VARCHAR(36) NOT NULL,"
            "email VARCHAR(320) NOT NULL,"
            "role VARCHAR(20) NOT NULL DEFAULT 'member',"
            "token_hash VARCHAR(64) NOT NULL UNIQUE,"
            "created_by_user_id VARCHAR(64),"
            "created_at DATETIME NOT NULL,"
            "expires_at DATETIME NOT NULL,"
            "accepted_at DATETIME,"
            "revoked_at DATETIME,"
            "note TEXT"
            ")"
        ))
        _add_index(conn, "workspace_invites", "workspace_id")
        _add_index(conn, "workspace_invites", "email")
        _add_index(conn, "workspace_invites", "token_hash")
        try:
            conn.execute(sa.text("CREATE INDEX ix_workspace_invites_workspace_status ON workspace_invites (workspace_id, revoked_at, accepted_at)"))
        except Exception:
            pass


def _best_effort_owner_user_id(conn) -> Optional[str]:
    insp = inspect(conn)
    for t in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns(t)}
        if "id" in cols and ("email" in cols or "username" in cols) and "user" in t.lower():
            try:
                row = conn.execute(sa.text(f"SELECT id FROM {t} ORDER BY id ASC LIMIT 1")).fetchone()
                if row:
                    return str(row[0])
            except Exception:
                continue
    return None


def _ensure_default_workspace(conn) -> None:
    owner_id = _best_effort_owner_user_id(conn)
    now = _utcnow().isoformat(sep=" ", timespec="seconds")

    row = conn.execute(sa.text("SELECT workspace_id FROM workspaces WHERE workspace_id = :ws"), {"ws": DEFAULT_WORKSPACE_ID}).fetchone()
    if not row:
        conn.execute(
            sa.text("INSERT INTO workspaces (workspace_id, name, owner_user_id, created_at) VALUES (:ws, :name, :owner, :created_at)"),
            {"ws": DEFAULT_WORKSPACE_ID, "name": "Personal", "owner": owner_id, "created_at": now},
        )

    if owner_id:
        row2 = conn.execute(sa.text(
            "SELECT membership_id FROM workspace_memberships WHERE workspace_id = :ws AND user_id = :u"
        ), {"ws": DEFAULT_WORKSPACE_ID, "u": owner_id}).fetchone()
        if not row2:
            conn.execute(
                sa.text(
                    "INSERT INTO workspace_memberships "
                    "(membership_id, workspace_id, user_id, role, created_at, is_active) "
                    "VALUES (:mid, :ws, :u, 'owner', :created_at, 1)"
                ),
                {"mid": DEFAULT_MEMBERSHIP_ID, "ws": DEFAULT_WORKSPACE_ID, "u": owner_id, "created_at": now},
            )


def _add_workspace_column(conn, table: str) -> bool:
    insp = inspect(conn)
    if not _table_exists(insp, table):
        return False
    if _has_column(insp, table, "workspace_id"):
        return False
    try:
        conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN workspace_id VARCHAR(36)"))
        _add_index(conn, table, "workspace_id")
        return True
    except Exception:
        return False


def _backfill_workspace_column(conn, table: str) -> None:
    try:
        conn.execute(sa.text(f"UPDATE {table} SET workspace_id = :ws WHERE workspace_id IS NULL"), {"ws": DEFAULT_WORKSPACE_ID})
    except Exception:
        pass


def migrate(engine: Engine, extra_tables: Iterable[str] = ()) -> None:
    with engine.begin() as conn:
        _create_tables(conn)
        _ensure_default_workspace(conn)

        tables = list(dict.fromkeys(list(CANDIDATE_TABLES) + list(extra_tables)))
        changed = []
        for t in tables:
            if _add_workspace_column(conn, t):
                changed.append(t)
            _backfill_workspace_column(conn, t)

        print("workspace.rbac_multi_tenant schema migration complete.")
        if changed:
            print("Added workspace_id column to:", ", ".join(changed))
        else:
            print("No workspace_id columns added (either already present or tables not found).")


def main() -> None:
    engine = _import_engine()
    migrate(engine)


if __name__ == "__main__":
    main()
