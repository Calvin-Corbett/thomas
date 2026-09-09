"""Bounded original uploads, bound once to a Chat/Build session and copied as inputs."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from thomas.core.config import resolve_thomas_data_dir
from thomas.tools.file_readers import UPLOAD_MAX_BYTES

MAX_STORED_BYTES = 100_000_000
MAX_SESSION_BYTES = 25_000_000
MAX_STORED_FILES = 1_000
UNBOUND_TTL = 3_600
SESSION_TTL = 86_400
_ID = re.compile(r"[a-f0-9]{32}\Z")


class AttachmentError(ValueError):
    """An original attachment cannot be resolved within this session."""


def store_path() -> Path:
    return resolve_thomas_data_dir() / "runtime" / "chat-attachments.sqlite3"


@contextmanager
def _connect():
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA secure_delete=ON")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS originals (id TEXT PRIMARY KEY, session TEXT, "
        "expires REAL NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL, "
        "document TEXT NOT NULL, raw BLOB NOT NULL)"
    )
    connection.execute("CREATE INDEX IF NOT EXISTS originals_session ON originals(session)")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def retain_original(raw: bytes, document: dict[str, Any]) -> dict[str, Any]:
    if not raw or len(raw) > UPLOAD_MAX_BYTES:
        raise AttachmentError("Choose a non-empty attachment no larger than 5 MB.")
    now, token = time.time(), secrets.token_hex(16)
    doc = dict(document, attachment_id=token, sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM originals WHERE expires < ?", (now,))
        size, count = db.execute("SELECT COALESCE(SUM(size),0),COUNT(*) FROM originals").fetchone()
        if size + len(raw) > MAX_STORED_BYTES or count >= MAX_STORED_FILES:
            raise AttachmentError("Attachment storage is full. Try a smaller file or wait for older uploads to expire.")
        db.execute(
            "INSERT INTO originals VALUES(?,?,?,?,?,?,?)",
            (token, None, now + UNBOUND_TTL, len(raw), doc["sha256"], json.dumps(doc), raw),
        )
    return doc


def _ids(docs: Any) -> list[str]:
    refs = []
    for doc in docs if isinstance(docs, list) else []:
        if not isinstance(doc, dict) or "attachment_id" not in doc:
            continue
        token = doc["attachment_id"]
        if not isinstance(token, str) or not _ID.fullmatch(token):
            raise AttachmentError("This attachment reference is invalid. Attach the original file again.")
        if token not in refs:
            refs.append(token)
    return refs


def bind_documents(docs: Any, session_id: str, *, temporary: bool = False) -> list[dict[str, Any]]:
    refs = _ids(docs)
    legacy = (
        [dict(doc) for doc in docs if isinstance(doc, dict) and "attachment_id" not in doc]
        if isinstance(docs, list)
        else []
    )
    if not refs and (temporary or not store_path().is_file()):
        return legacy
    if not session_id or len(session_id) > 256:
        raise AttachmentError("A valid conversation is required for original attachments.")
    now = time.time()
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        selected = []
        for token in refs:
            row = db.execute("SELECT * FROM originals WHERE id=?", (token,)).fetchone()
            if row is None or row["expires"] < now:
                raise AttachmentError("An original attachment expired or is unavailable. Attach it again.")
            if row["session"] not in {None, session_id}:
                raise AttachmentError(
                    "An attachment belongs to another conversation. Attach it again in this conversation."
                )
            selected.append(row)
        existing = list(db.execute("SELECT * FROM originals WHERE session=? AND expires>=?", (session_id, now)))
        combined = {row["id"]: row for row in existing + selected}
        if sum(row["size"] for row in combined.values()) > MAX_SESSION_BYTES:
            raise AttachmentError(
                "This conversation exceeds the 25 MB original-file limit. Use a smaller set of files."
            )
        for token in combined:
            ttl = UNBOUND_TTL if temporary else SESSION_TTL
            db.execute("UPDATE originals SET session=?,expires=? WHERE id=?", (session_id, now + ttl, token))
        return legacy + [json.loads(row["document"]) for row in combined.values()]


def forget_originals(session_id: str) -> int:
    """Delete exact-owner retained originals, zeroing freed SQLite content."""
    if store_path().is_file():
        with _connect() as db:
            return db.execute("DELETE FROM originals WHERE session=?", (session_id,)).rowcount
    return 0


def forget_chat_originals(session_id: str) -> int:
    """Delete a saved Chat session's originals; never touch another surface or inputs."""
    return forget_originals("chat:" + session_id)


def stage_originals(session_id: str, workspace: Path, *, ids: list[str] | None = None) -> list[dict[str, Any]]:
    if not store_path().is_file():
        if ids:
            raise AttachmentError("An original attachment is no longer available. Attach it again.")
        return []
    with _connect() as db:
        rows = list(db.execute("SELECT * FROM originals WHERE session=? AND expires>=?", (session_id, time.time())))
    if ids is not None:
        rows = [row for row in rows if row["id"] in ids]
        if {row["id"] for row in rows} != set(ids):
            raise AttachmentError("An original attachment is no longer available. Attach it again.")
    if sum(row["size"] for row in rows) > MAX_SESSION_BYTES:
        raise AttachmentError("Original task inputs exceed the 25 MB limit.")
    root = workspace.resolve(strict=True)
    staged = []
    for row in rows:
        raw = bytes(row["raw"])
        if len(raw) != row["size"] or len(raw) > UPLOAD_MAX_BYTES or hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise AttachmentError("The retained original failed its integrity check. Attach it again.")
        doc = json.loads(row["document"])
        name = re.sub(r"[^A-Za-z0-9._-]", "_", str(doc["name"]))[:160].strip(".") or "document"
        folder = root / "inputs" / "attachments" / row["id"]
        if not folder.resolve().is_relative_to(root):
            raise AttachmentError("The task attachment folder points outside its workspace.")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        if target.is_symlink() or not target.resolve().is_relative_to(root):
            raise AttachmentError("The task attachment path is unsafe.")
        if target.exists():
            with target.open("rb") as source:
                current = source.read(UPLOAD_MAX_BYTES + 1)
            if current != raw:
                raise AttachmentError(
                    "A task input was changed. Preserve it and use a fresh task to read the original."
                )
        else:
            with target.open("xb") as output:
                output.write(raw)
        staged.append(
            {
                "name": doc["name"],
                "path": target.relative_to(root).as_posix(),
                "sha256": row["sha256"],
                "size_bytes": len(raw),
            }
        )
    return staged
