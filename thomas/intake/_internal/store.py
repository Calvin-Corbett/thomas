from __future__ import annotations

import json
import sqlite3
import time
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .config import IntakeStorageConfig


@dataclass(frozen=True)
class StoredIntake:
    item_id: str
    created_at: float
    source: str
    content_type: str
    text: Optional[str]
    blob_path: Optional[str]
    blob_bytes: int
    ocr_text: Optional[str]
    meta_json: str
    content_hash: str
    idempotency_key: Optional[str]
    chat_id: Optional[str]


class IntakeStore:
    """SQLite-backed persistence for intake events + blobs stored as files.

    Default base dir: ~/.thomas/intake/
      - intake.db
      - blobs/<item_id>.bin
    """

    def __init__(self, cfg: Optional[IntakeStorageConfig] = None):
        self.cfg = cfg or IntakeStorageConfig.from_env()
        self.base_dir = self.cfg.base_dir
        self.db_path = self.base_dir / "intake.db"
        self.blob_dir = self.base_dir / "blobs"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=30.0)
        con.row_factory = sqlite3.Row
        # reasonable concurrency for lightweight service
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        return con

    def _init_db(self) -> None:
        con = self._connect()
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS intake (
                    item_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    source TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    text TEXT,
                    blob_path TEXT,
                    blob_bytes INTEGER NOT NULL,
                    ocr_text TEXT,
                    meta_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    idempotency_key TEXT,
                    chat_id TEXT
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_intake_hash ON intake(content_hash)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_intake_idem ON intake(idempotency_key)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_intake_chat ON intake(chat_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_intake_created ON intake(created_at)")
            con.commit()
        finally:
            con.close()

    @staticmethod
    def compute_hash(content_type: str, text: Optional[str], blob: Optional[bytes], ocr_text: Optional[str]) -> str:
        h = hashlib.sha256()
        h.update(content_type.encode("utf-8"))
        if text:
            h.update(b"\x00txt\x00")
            h.update(text.encode("utf-8", errors="ignore"))
        if blob:
            h.update(b"\x00blob\x00")
            h.update(blob)
        if ocr_text:
            h.update(b"\x00ocr\x00")
            h.update(ocr_text.encode("utf-8", errors="ignore"))
        return h.hexdigest()

    def find_by_idempotency_or_hash(self, idempotency_key: Optional[str], content_hash: str, window_s: float) -> Optional[StoredIntake]:
        con = self._connect()
        try:
            if idempotency_key:
                row = con.execute("SELECT * FROM intake WHERE idempotency_key = ? LIMIT 1", (idempotency_key,)).fetchone()
                if row:
                    return StoredIntake(**dict(row))
            cutoff = time.time() - window_s
            row = con.execute(
                "SELECT * FROM intake WHERE content_hash = ? AND created_at >= ? ORDER BY created_at DESC LIMIT 1",
                (content_hash, cutoff),
            ).fetchone()
            if row:
                return StoredIntake(**dict(row))
            return None
        finally:
            con.close()

    def insert(
        self,
        item_id: str,
        source: str,
        content_type: str,
        text: Optional[str],
        blob: Optional[bytes],
        ocr_text: Optional[str],
        meta: Dict[str, Any],
        content_hash: str,
        idempotency_key: Optional[str],
        chat_id: Optional[str],
    ) -> StoredIntake:
        created_at = time.time()
        blob_path: Optional[str] = None
        blob_bytes = 0
        if blob is not None:
            blob_path = str(self.blob_dir / f"{item_id}.bin")
            Path(blob_path).write_bytes(blob)
            blob_bytes = len(blob)

        meta_json = json.dumps(meta or {}, ensure_ascii=False)

        con = self._connect()
        try:
            con.execute(
                """
                INSERT INTO intake (item_id, created_at, source, content_type, text, blob_path, blob_bytes, ocr_text, meta_json, content_hash, idempotency_key, chat_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (item_id, created_at, source, content_type, text, blob_path, blob_bytes, ocr_text, meta_json, content_hash, idempotency_key, chat_id),
            )
            con.commit()
        finally:
            con.close()

        return StoredIntake(
            item_id=item_id,
            created_at=created_at,
            source=source,
            content_type=content_type,
            text=text,
            blob_path=blob_path,
            blob_bytes=blob_bytes,
            ocr_text=ocr_text,
            meta_json=meta_json,
            content_hash=content_hash,
            idempotency_key=idempotency_key,
            chat_id=chat_id,
        )

    def get(self, item_id: str) -> Optional[StoredIntake]:
        con = self._connect()
        try:
            row = con.execute("SELECT * FROM intake WHERE item_id = ? LIMIT 1", (item_id,)).fetchone()
            return StoredIntake(**dict(row)) if row else None
        finally:
            con.close()

    def list_recent(self, limit: int = 50, chat_id: Optional[str] = None) -> List[StoredIntake]:
        con = self._connect()
        try:
            if chat_id:
                rows = con.execute(
                    "SELECT * FROM intake WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?",
                    (chat_id, int(limit)),
                ).fetchall()
            else:
                rows = con.execute("SELECT * FROM intake ORDER BY created_at DESC LIMIT ?", (int(limit),)).fetchall()
            return [StoredIntake(**dict(r)) for r in rows]
        finally:
            con.close()

    def read_blob(self, item_id: str) -> Optional[bytes]:
        it = self.get(item_id)
        if not it or not it.blob_path:
            return None
        p = Path(it.blob_path)
        if not p.exists():
            return None
        return p.read_bytes()
