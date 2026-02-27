from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .runtime_common import _normalize_tags, _now_iso, _safe_int, _safe_string


class AssetStudioJobStore:
    def __init__(self, db_path: str | Path):
        self._path = Path(db_path).expanduser().resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        self._lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS asset_studio_jobs (
                job_id TEXT PRIMARY KEY,
                connector_id TEXT NOT NULL,
                action_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                exit_code INTEGER,
                error_text TEXT,
                command_json TEXT,
                artifact_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_asset_studio_jobs_status
            ON asset_studio_jobs(status);
            CREATE INDEX IF NOT EXISTS idx_asset_studio_jobs_created_at
            ON asset_studio_jobs(created_at DESC);

            CREATE TABLE IF NOT EXISTS asset_studio_job_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                at TEXT NOT NULL,
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                data_json TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES asset_studio_jobs(job_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_asset_studio_job_events_job_seq
            ON asset_studio_job_events(job_id, seq);

            CREATE TABLE IF NOT EXISTS asset_studio_templates (
                template_id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                connector_id TEXT NOT NULL,
                action_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                favorite INTEGER NOT NULL,
                pinned INTEGER NOT NULL,
                pin_index INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_asset_studio_templates_created_at
            ON asset_studio_templates(created_at DESC);

            CREATE TABLE IF NOT EXISTS asset_studio_webhook_configs (
                webhook_key TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                secret TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                timeout_s INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS asset_studio_template_webhook_configs (
                template_id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                secret TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                timeout_s INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(template_id) REFERENCES asset_studio_templates(template_id) ON DELETE CASCADE
            );
            """
        )
        self._ensure_column("asset_studio_jobs", "template_id", "TEXT")
        self._ensure_column("asset_studio_templates", "tags_json", "TEXT")
        self._ensure_column("asset_studio_templates", "favorite", "INTEGER")
        self._ensure_column("asset_studio_templates", "pinned", "INTEGER")
        self._ensure_column("asset_studio_templates", "pin_index", "INTEGER")
        self._conn.execute("UPDATE asset_studio_templates SET tags_json='[]' WHERE tags_json IS NULL")
        self._conn.execute("UPDATE asset_studio_templates SET favorite=0 WHERE favorite IS NULL")
        self._conn.execute("UPDATE asset_studio_templates SET pinned=0 WHERE pinned IS NULL")
        self._conn.execute("UPDATE asset_studio_templates SET pin_index=9999 WHERE pin_index IS NULL")
        self._conn.commit()

    def _has_column(self, table_name: str, column_name: str) -> bool:
        rows = self._conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        for row in rows:
            try:
                name = str(row["name"])
            except (ValueError, TypeError):
                name = str(row[1]) if len(row) > 1 else ""
            if name == column_name:
                return True
        return False

    def _ensure_column(self, table_name: str, column_name: str, column_sql_type: str) -> None:
        if self._has_column(table_name, column_name):
            return
        self._conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql_type}")

    @staticmethod
    def _decode_json(raw: Any, default: Any) -> Any:
        text = _safe_string(raw)
        if not text:
            return default
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return default

    @classmethod
    def _row_to_job(cls, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "job_id": _safe_string(row["job_id"]),
            "template_id": _safe_string(row["template_id"]),
            "connector_id": _safe_string(row["connector_id"]),
            "action_id": _safe_string(row["action_id"]),
            "status": _safe_string(row["status"]),
            "payload": cls._decode_json(row["payload_json"], {}),
            "command": cls._decode_json(row["command_json"], []),
            "artifact": cls._decode_json(row["artifact_json"], {}),
            "created_at": _safe_string(row["created_at"]),
            "started_at": _safe_string(row["started_at"]),
            "completed_at": _safe_string(row["completed_at"]),
            "exit_code": row["exit_code"],
            "error": _safe_string(row["error_text"]),
        }

    @classmethod
    def _row_to_event(cls, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "seq": _safe_int(row["seq"]),
            "job_id": _safe_string(row["job_id"]),
            "at": _safe_string(row["at"]),
            "kind": _safe_string(row["kind"]),
            "message": _safe_string(row["message"]),
            "data": cls._decode_json(row["data_json"], {}),
        }

    @classmethod
    def _row_to_template(cls, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        parsed_tags = cls._decode_json(row["tags_json"], [])
        tags: list[str] = []
        if isinstance(parsed_tags, list):
            for value in parsed_tags:
                label = _safe_string(value)
                if label:
                    tags.append(label)
        return {
            "template_id": _safe_string(row["template_id"]),
            "name": _safe_string(row["name"]),
            "connector_id": _safe_string(row["connector_id"]),
            "action_id": _safe_string(row["action_id"]),
            "payload": cls._decode_json(row["payload_json"], {}),
            "tags": tags,
            "favorite": bool(_safe_int(row["favorite"], 0)),
            "pinned": bool(_safe_int(row["pinned"], 0)),
            "pin_index": max(0, min(9999, _safe_int(row["pin_index"], 9999))),
            "created_at": _safe_string(row["created_at"]),
            "updated_at": _safe_string(row["updated_at"]),
        }

    @classmethod
    def _row_to_webhook_config(cls, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "webhook_key": _safe_string(row["webhook_key"]),
            "url": _safe_string(row["url"]),
            "secret": _safe_string(row["secret"]),
            "enabled": bool(_safe_int(row["enabled"], 0)),
            "timeout_s": max(1, min(30, _safe_int(row["timeout_s"], 5))),
            "created_at": _safe_string(row["created_at"]),
            "updated_at": _safe_string(row["updated_at"]),
        }

    @classmethod
    def _row_to_template_webhook_config(cls, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "template_id": _safe_string(row["template_id"]),
            "url": _safe_string(row["url"]),
            "secret": _safe_string(row["secret"]),
            "enabled": bool(_safe_int(row["enabled"], 0)),
            "timeout_s": max(1, min(30, _safe_int(row["timeout_s"], 5))),
            "created_at": _safe_string(row["created_at"]),
            "updated_at": _safe_string(row["updated_at"]),
        }

    async def create_job(
        self,
        *,
        job_id: str,
        connector_id: str,
        action_id: str,
        payload: Mapping[str, Any],
        template_id: str = "",
    ) -> dict[str, Any]:
        async with self._lock:
            self._conn.execute(
                """
                INSERT INTO asset_studio_jobs (
                    job_id, template_id, connector_id, action_id, payload_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'queued', ?)
                """,
                (
                    job_id,
                    _safe_string(template_id),
                    connector_id,
                    action_id,
                    json.dumps(dict(payload), ensure_ascii=True),
                    _now_iso(),
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM asset_studio_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            return self._row_to_job(row) or {}

    async def set_running(self, job_id: str, *, command: list[str]) -> dict[str, Any] | None:
        async with self._lock:
            self._conn.execute(
                """
                UPDATE asset_studio_jobs
                SET status='running', started_at=?, command_json=?
                WHERE job_id=?
                """,
                (_now_iso(), json.dumps(command, ensure_ascii=True), job_id),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM asset_studio_jobs WHERE job_id = ?", (job_id,)).fetchone()
            return self._row_to_job(row)

    async def set_terminal(
        self,
        job_id: str,
        *,
        status: str,
        exit_code: int | None = None,
        error: str = "",
        artifact: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        async with self._lock:
            self._conn.execute(
                """
                UPDATE asset_studio_jobs
                SET status=?, completed_at=?, exit_code=?, error_text=?, artifact_json=?
                WHERE job_id=?
                """,
                (
                    status,
                    _now_iso(),
                    exit_code,
                    _safe_string(error),
                    json.dumps(dict(artifact or {}), ensure_ascii=True),
                    job_id,
                ),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM asset_studio_jobs WHERE job_id = ?", (job_id,)).fetchone()
            return self._row_to_job(row)

    async def add_event(
        self,
        *,
        job_id: str,
        kind: str,
        message: str,
        data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO asset_studio_job_events (job_id, at, kind, message, data_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    _now_iso(),
                    _safe_string(kind) or "log",
                    _safe_string(message),
                    json.dumps(dict(data or {}), ensure_ascii=True),
                ),
            )
            self._conn.commit()
            seq = int(cursor.lastrowid or 0)
            row = self._conn.execute(
                "SELECT * FROM asset_studio_job_events WHERE seq = ?",
                (seq,),
            ).fetchone()
            return self._row_to_event(row) or {}

    async def get_job(self, job_id: str) -> dict[str, Any] | None:
        async with self._lock:
            row = self._conn.execute(
                "SELECT * FROM asset_studio_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            return self._row_to_job(row)

    async def list_jobs(
        self,
        *,
        limit: int = 100,
        status: str = "",
    ) -> list[dict[str, Any]]:
        max_rows = max(1, min(500, int(limit or 100)))
        async with self._lock:
            if _safe_string(status):
                rows = self._conn.execute(
                    """
                    SELECT * FROM asset_studio_jobs
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (_safe_string(status), max_rows),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT * FROM asset_studio_jobs
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (max_rows,),
                ).fetchall()
            return [item for item in (self._row_to_job(row) for row in rows) if item]

    async def list_events(
        self,
        job_id: str,
        *,
        after_seq: int = 0,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        after = max(0, int(after_seq or 0))
        max_rows = max(1, min(1000, int(limit or 200)))
        async with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM asset_studio_job_events
                WHERE job_id = ? AND seq > ?
                ORDER BY seq ASC
                LIMIT ?
                """,
                (job_id, after, max_rows),
            ).fetchall()
            return [item for item in (self._row_to_event(row) for row in rows) if item]

    async def upsert_template(
        self,
        *,
        name: str,
        connector_id: str,
        action_id: str,
        payload: Mapping[str, Any],
        tags: list[str] | None = None,
        favorite: bool = False,
        pinned: bool = False,
        pin_index: int | None = None,
    ) -> dict[str, Any]:
        now = _now_iso()
        generated_id = f"tpl_{uuid.uuid4().hex[:16]}"
        normalized_tags = _normalize_tags(tags)
        normalized_pin_index = max(0, min(9999, _safe_int(pin_index, 0)))
        effective_pinned = bool(pinned)
        effective_pin_index = normalized_pin_index if effective_pinned else 9999
        async with self._lock:
            self._conn.execute(
                """
                INSERT INTO asset_studio_templates (
                    template_id, name, connector_id, action_id, payload_json, tags_json, favorite, pinned, pin_index, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    connector_id=excluded.connector_id,
                    action_id=excluded.action_id,
                    payload_json=excluded.payload_json,
                    tags_json=excluded.tags_json,
                    favorite=excluded.favorite,
                    pinned=excluded.pinned,
                    pin_index=excluded.pin_index,
                    updated_at=excluded.updated_at
                """,
                (
                    generated_id,
                    _safe_string(name),
                    _safe_string(connector_id),
                    _safe_string(action_id),
                    json.dumps(dict(payload), ensure_ascii=True),
                    json.dumps(normalized_tags, ensure_ascii=True),
                    1 if bool(favorite) else 0,
                    1 if effective_pinned else 0,
                    effective_pin_index,
                    now,
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM asset_studio_templates WHERE name = ?",
                (_safe_string(name),),
            ).fetchone()
            return self._row_to_template(row) or {}

    async def get_template_by_name(self, name: str) -> dict[str, Any] | None:
        async with self._lock:
            row = self._conn.execute(
                "SELECT * FROM asset_studio_templates WHERE name = ?",
                (_safe_string(name),),
            ).fetchone()
            return self._row_to_template(row)

    async def get_template(self, template_id: str) -> dict[str, Any] | None:
        async with self._lock:
            row = self._conn.execute(
                "SELECT * FROM asset_studio_templates WHERE template_id = ?",
                (_safe_string(template_id),),
            ).fetchone()
            return self._row_to_template(row)

    async def list_templates(
        self,
        *,
        limit: int = 100,
        favorites_only: bool = False,
        tag: str = "",
    ) -> list[dict[str, Any]]:
        max_rows = max(1, min(500, int(limit or 100)))
        normalized_tag = _safe_string(tag)
        async with self._lock:
            where_clauses: list[str] = []
            params: list[Any] = []
            if favorites_only:
                where_clauses.append("favorite = 1")
            if normalized_tag:
                where_clauses.append("lower(tags_json) LIKE ?")
                params.append(f'%"{normalized_tag.lower()}"%')
            sql = (
                "SELECT * FROM asset_studio_templates"
                + (f" WHERE {' AND '.join(where_clauses)}" if where_clauses else "")
                + " ORDER BY pinned DESC, pin_index ASC, favorite DESC, updated_at DESC LIMIT ?"
            )
            params.append(max_rows)
            rows = self._conn.execute(sql, tuple(params)).fetchall()
            return [item for item in (self._row_to_template(row) for row in rows) if item]

    async def update_template_metadata(
        self,
        template_id: str,
        *,
        name: str | None = None,
        tags: list[str] | None = None,
        favorite: bool | None = None,
        pinned: bool | None = None,
        pin_index: int | None = None,
    ) -> dict[str, Any] | None:
        tid = _safe_string(template_id)
        assignments: list[str] = []
        values: list[Any] = []
        if name is not None:
            normalized_name = _safe_string(name)
            if not normalized_name:
                raise ValueError("name cannot be empty")
            assignments.append("name = ?")
            values.append(normalized_name)
        if tags is not None:
            assignments.append("tags_json = ?")
            values.append(json.dumps(_normalize_tags(tags), ensure_ascii=True))
        if favorite is not None:
            assignments.append("favorite = ?")
            values.append(1 if bool(favorite) else 0)
        if pinned is not None:
            assignments.append("pinned = ?")
            values.append(1 if bool(pinned) else 0)
            if not bool(pinned):
                assignments.append("pin_index = ?")
                values.append(9999)
        if pin_index is not None:
            assignments.append("pin_index = ?")
            values.append(max(0, min(9999, _safe_int(pin_index, 0))))
            if pinned is None:
                assignments.append("pinned = ?")
                values.append(1)
        if not assignments:
            return await self.get_template(tid)
        assignments.append("updated_at = ?")
        values.append(_now_iso())
        values.append(tid)
        async with self._lock:
            try:
                self._conn.execute(
                    f"UPDATE asset_studio_templates SET {', '.join(assignments)} WHERE template_id = ?",
                    tuple(values),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(str(exc))
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM asset_studio_templates WHERE template_id = ?",
                (tid,),
            ).fetchone()
            return self._row_to_template(row)

    async def delete_template(self, template_id: str) -> bool:
        async with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM asset_studio_templates WHERE template_id = ?",
                (_safe_string(template_id),),
            )
            self._conn.commit()
            return int(cursor.rowcount or 0) > 0

    async def upsert_webhook_config(
        self,
        *,
        webhook_key: str,
        url: str,
        secret: str,
        enabled: bool,
        timeout_s: int,
    ) -> dict[str, Any]:
        now = _now_iso()
        key = _safe_string(webhook_key)
        normalized_timeout = max(1, min(30, _safe_int(timeout_s, 5)))
        async with self._lock:
            existing = self._conn.execute(
                "SELECT secret, created_at FROM asset_studio_webhook_configs WHERE webhook_key = ?",
                (key,),
            ).fetchone()
            existing_secret = _safe_string(existing["secret"]) if existing is not None else ""
            existing_created_at = _safe_string(existing["created_at"]) if existing is not None else now
            candidate_secret = _safe_string(secret)
            final_secret = candidate_secret if candidate_secret else existing_secret
            self._conn.execute(
                """
                INSERT INTO asset_studio_webhook_configs (
                    webhook_key, url, secret, enabled, timeout_s, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(webhook_key) DO UPDATE SET
                    url=excluded.url,
                    secret=excluded.secret,
                    enabled=excluded.enabled,
                    timeout_s=excluded.timeout_s,
                    updated_at=excluded.updated_at
                """,
                (
                    key,
                    _safe_string(url),
                    final_secret,
                    1 if bool(enabled) else 0,
                    normalized_timeout,
                    existing_created_at,
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM asset_studio_webhook_configs WHERE webhook_key = ?",
                (key,),
            ).fetchone()
            return self._row_to_webhook_config(row) or {}

    async def get_webhook_config(self, webhook_key: str) -> dict[str, Any] | None:
        key = _safe_string(webhook_key)
        async with self._lock:
            row = self._conn.execute(
                "SELECT * FROM asset_studio_webhook_configs WHERE webhook_key = ?",
                (key,),
            ).fetchone()
            return self._row_to_webhook_config(row)

    async def delete_webhook_config(self, webhook_key: str) -> bool:
        key = _safe_string(webhook_key)
        async with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM asset_studio_webhook_configs WHERE webhook_key = ?",
                (key,),
            )
            self._conn.commit()
            return int(cursor.rowcount or 0) > 0

    async def upsert_template_webhook_config(
        self,
        *,
        template_id: str,
        url: str,
        secret: str,
        enabled: bool,
        timeout_s: int,
    ) -> dict[str, Any]:
        now = _now_iso()
        tid = _safe_string(template_id)
        normalized_timeout = max(1, min(30, _safe_int(timeout_s, 5)))
        async with self._lock:
            existing = self._conn.execute(
                "SELECT secret, created_at FROM asset_studio_template_webhook_configs WHERE template_id = ?",
                (tid,),
            ).fetchone()
            existing_secret = _safe_string(existing["secret"]) if existing is not None else ""
            existing_created_at = _safe_string(existing["created_at"]) if existing is not None else now
            candidate_secret = _safe_string(secret)
            final_secret = candidate_secret if candidate_secret else existing_secret
            self._conn.execute(
                """
                INSERT INTO asset_studio_template_webhook_configs (
                    template_id, url, secret, enabled, timeout_s, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(template_id) DO UPDATE SET
                    url=excluded.url,
                    secret=excluded.secret,
                    enabled=excluded.enabled,
                    timeout_s=excluded.timeout_s,
                    updated_at=excluded.updated_at
                """,
                (
                    tid,
                    _safe_string(url),
                    final_secret,
                    1 if bool(enabled) else 0,
                    normalized_timeout,
                    existing_created_at,
                    now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM asset_studio_template_webhook_configs WHERE template_id = ?",
                (tid,),
            ).fetchone()
            return self._row_to_template_webhook_config(row) or {}

    async def get_template_webhook_config(self, template_id: str) -> dict[str, Any] | None:
        tid = _safe_string(template_id)
        async with self._lock:
            row = self._conn.execute(
                "SELECT * FROM asset_studio_template_webhook_configs WHERE template_id = ?",
                (tid,),
            ).fetchone()
            return self._row_to_template_webhook_config(row)

    async def delete_template_webhook_config(self, template_id: str) -> bool:
        tid = _safe_string(template_id)
        async with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM asset_studio_template_webhook_configs WHERE template_id = ?",
                (tid,),
            )
            self._conn.commit()
            return int(cursor.rowcount or 0) > 0

    def close(self) -> None:
        self._conn.close()
