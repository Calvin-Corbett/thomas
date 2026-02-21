"""Agent file-change audit log.

Records every file write/edit/delete made by any agent run so you can
go back and see exactly what each model did, when, and to which files.

Design:
- Separate SQLite DB from run_store.py (clean separation of concerns)
- Stdlib-only, Windows-safe
- Append-only writes (crash-safe)
- Queryable by run_id, model, path, or time range
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_DB_PATH: Optional[Path] = None
_LOCK = threading.Lock()

# File-write tool name fragments — if a tool name contains any of these,
# we consider it a file-mutating operation.
_WRITE_TOOL_KEYWORDS = frozenset({
    "write", "edit", "create", "delete", "remove", "replace",
    "patch", "append", "rename", "move", "mkdir", "touch",
    "diff.create", "fs.write", "fs.delete", "fs.rename",
})

# Max chars of diff snippet to store
_MAX_DIFF_SNIPPET = 1000


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_audit(path: str | os.PathLike[str]) -> None:
    """Initialise the audit database. Call once at server startup."""
    global _DB_PATH
    with _LOCK:
        _DB_PATH = Path(path)
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = _connect(_DB_PATH)
        try:
            _create_schema(conn)
        finally:
            conn.close()
    log.info("File audit log initialised at %s", _DB_PATH)


def record_file_write(
    *,
    run_id: str,
    model: str,
    tool_name: str,
    path: str,
    action: str = "write",
    content_before: Optional[str] = None,
    content_after: Optional[str] = None,
    args_snippet: Optional[str] = None,
) -> None:
    """Record a file mutation event.

    Args:
        run_id:         Agent run ID.
        model:          Model name/ID that triggered this.
        tool_name:      The tool that was called (e.g. 'fs.write_file').
        path:           Absolute or relative file path that was changed.
        action:         One of 'write', 'append', 'delete', 'rename', 'create'.
        content_before: File content before the change (optional, for diff).
        content_after:  File content after the change (optional, for diff).
        args_snippet:   Short summary of tool arguments for context.
    """
    if _DB_PATH is None:
        return  # Not initialised — silently skip

    size_before = len(content_before.encode()) if content_before else None
    size_after = len(content_after.encode()) if content_after else None
    diff_snippet = _make_diff_snippet(content_before, content_after, path)

    ts = datetime.now(timezone.utc).isoformat()
    row = {
        "run_id": str(run_id or ""),
        "model": str(model or "unknown"),
        "tool_name": str(tool_name or ""),
        "path": str(path or ""),
        "action": str(action or "write"),
        "size_before": size_before,
        "size_after": size_after,
        "diff_snippet": diff_snippet,
        "args_snippet": (args_snippet or "")[:500],
        "ts": ts,
    }

    try:
        with _LOCK:
            conn = _connect(_DB_PATH)
            try:
                conn.execute(
                    """
                    INSERT INTO file_audit
                        (run_id, model, tool_name, path, action,
                         size_before, size_after, diff_snippet, args_snippet, ts)
                    VALUES
                        (:run_id, :model, :tool_name, :path, :action,
                         :size_before, :size_after, :diff_snippet, :args_snippet, :ts)
                    """,
                    row,
                )
                conn.commit()
            finally:
                conn.close()
    except Exception as e:
        log.warning("file_audit: failed to record write for %s: %s", path, e)


def list_file_changes(
    *,
    run_id: Optional[str] = None,
    path_contains: Optional[str] = None,
    model: Optional[str] = None,
    action: Optional[str] = None,
    since_iso: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Query file change records.

    Returns a list of dicts ordered by most recent first.
    """
    if _DB_PATH is None:
        return []
    try:
        with _LOCK:
            conn = _connect(_DB_PATH)
            try:
                clauses = []
                params: List[Any] = []
                if run_id:
                    clauses.append("run_id = ?")
                    params.append(run_id)
                if path_contains:
                    clauses.append("path LIKE ?")
                    params.append(f"%{path_contains}%")
                if model:
                    clauses.append("model = ?")
                    params.append(model)
                if action:
                    clauses.append("action = ?")
                    params.append(action)
                if since_iso:
                    clauses.append("ts >= ?")
                    params.append(since_iso)

                where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
                params += [limit, offset]
                rows = conn.execute(
                    f"""
                    SELECT id, run_id, model, tool_name, path, action,
                           size_before, size_after, diff_snippet, args_snippet, ts
                    FROM file_audit
                    {where}
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?
                    """,
                    params,
                ).fetchall()
                return [_row_to_dict(r) for r in rows]
            finally:
                conn.close()
    except Exception as e:
        log.warning("file_audit: list_file_changes failed: %s", e)
        return []


def get_run_summary(run_id: str) -> Dict[str, Any]:
    """Return aggregate stats for a single run."""
    if _DB_PATH is None:
        return {}
    try:
        with _LOCK:
            conn = _connect(_DB_PATH)
            try:
                row = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS total_changes,
                        COUNT(DISTINCT path) AS unique_files,
                        MIN(ts) AS first_change,
                        MAX(ts) AS last_change,
                        GROUP_CONCAT(DISTINCT action) AS actions
                    FROM file_audit
                    WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchone()
                if not row:
                    return {}
                return {
                    "run_id": run_id,
                    "total_changes": row[0],
                    "unique_files": row[1],
                    "first_change": row[2],
                    "last_change": row[3],
                    "actions": (row[4] or "").split(",") if row[4] else [],
                }
            finally:
                conn.close()
    except Exception as e:
        log.warning("file_audit: get_run_summary failed: %s", e)
        return {}


def is_write_tool(tool_name: str) -> bool:
    """Return True if the tool name looks like a file-mutating operation."""
    name_lower = tool_name.lower()
    return any(kw in name_lower for kw in _WRITE_TOOL_KEYWORDS)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=8.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS file_audit (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id       TEXT    NOT NULL,
            model        TEXT    NOT NULL DEFAULT '',
            tool_name    TEXT    NOT NULL DEFAULT '',
            path         TEXT    NOT NULL,
            action       TEXT    NOT NULL DEFAULT 'write',
            size_before  INTEGER,
            size_after   INTEGER,
            diff_snippet TEXT,
            args_snippet TEXT,
            ts           TEXT    NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fa_run_id ON file_audit(run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fa_path   ON file_audit(path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fa_ts     ON file_audit(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fa_model  ON file_audit(model)")
    conn.commit()


def _make_diff_snippet(
    before: Optional[str],
    after: Optional[str],
    path: str,
) -> Optional[str]:
    """Generate a short unified-diff snippet between before and after."""
    if before is None and after is None:
        return None
    if before is None:
        # New file — show first N chars
        snippet = (after or "")[:_MAX_DIFF_SNIPPET]
        return f"+++ {path} (new file)\n" + "\n".join(f"+ {l}" for l in snippet.splitlines()[:30])
    if after is None:
        return f"--- {path} (deleted)"

    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        before_lines, after_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=2,
    ))
    snippet = "".join(diff)
    if len(snippet) > _MAX_DIFF_SNIPPET:
        snippet = snippet[:_MAX_DIFF_SNIPPET] + "\n... (truncated)"
    return snippet or None


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "model": row["model"],
        "tool_name": row["tool_name"],
        "path": row["path"],
        "action": row["action"],
        "size_before": row["size_before"],
        "size_after": row["size_after"],
        "diff_snippet": row["diff_snippet"],
        "args_snippet": row["args_snippet"],
        "ts": row["ts"],
    }
