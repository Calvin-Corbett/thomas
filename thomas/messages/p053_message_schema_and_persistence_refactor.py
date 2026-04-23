"""P053 - Message schema and persistence refactor (Thomas-native).

This module defines:
- A small, **versioned** canonical message schema (v1)
- A normalizer that accepts several common inbound shapes (webhooks/CLI)
- A lightweight **SQLite** persistence layer with deterministic error codes

Design goals:
- Standard-library only (no extra deps)
- Deterministic failures (stable error `code` values)
- Machine-readable contracts (TypedDict/dataclasses + JSON schema dicts)
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

# ---------------------------
# Public schema + contracts
# ---------------------------

MESSAGE_SCHEMA_VERSION: int = 1
DEFAULT_DB_FILENAME: str = "messages.sqlite3"
DEFAULT_TABLE_NAME: str = "messages"


class RawMessagePayload(TypedDict, total=False):
    """Accepted (loose) inbound payload shape.

    The normalizer is intentionally permissive to support multiple upstreams.

    Canonical keys:
      - text (required)
      - channel
      - sender
      - created_at (ISO8601 string or epoch seconds)
      - metadata (object)
      - message_id (for idempotency)

    Common aliases also accepted:
      - content/message -> text
      - room -> channel
      - user/author -> sender
      - timestamp/ts -> created_at
      - id -> message_id
    """

    # Canonical fields
    text: str
    channel: str
    sender: str
    metadata: Mapping[str, Any]
    created_at: Any
    message_id: str
    schema_version: int

    # Common aliases we accept during normalization
    content: str
    message: str
    room: str
    user: str
    author: str
    timestamp: Any
    ts: Any
    id: str
    version: int


@dataclass(frozen=True)
class MessageRecord:
    """Canonical message record (schema v1)."""

    message_id: str
    channel: str
    sender: str
    text: str
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = MESSAGE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "channel": self.channel,
            "sender": self.sender,
            "text": self.text,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class PersistedMessage:
    """Result of persisting a message."""

    record: MessageRecord
    store_path: str
    inserted: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "store_path": self.store_path,
            "inserted": self.inserted,
            "message": self.record.to_dict(),
        }


# Machine-readable request schema for HTTP routes / automation.
MESSAGE_INGEST_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "ThomasMessageIngestRequestV1",
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "channel": {"type": "string"},
        "sender": {"type": "string"},
        "created_at": {"type": ["string", "number", "integer"]},
        "metadata": {"type": "object"},
        "message_id": {"type": "string"},
        "schema_version": {"type": "integer"},
    },
    "required": ["text"],
    "additionalProperties": True,
}

# Optional: response schema (useful for routes/automation)
MESSAGE_INGEST_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "ThomasMessageIngestResponseV1",
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "store_path": {"type": "string"},
        "inserted": {"type": "boolean"},
        "message": {"type": "object"},
        "error": {"type": "object"},
    },
    "required": ["ok"],
    "additionalProperties": True,
}


# ---------------------------
# Deterministic error model
# ---------------------------


class ThomasMessageError(RuntimeError):
    """Base exception for deterministic messaging errors."""

    code: str

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ok": False, "error": {"code": self.code, "message": str(self)}}
        if self.details:
            payload["error"]["details"] = _coerce_jsonable(self.details)
        return payload


class MessageValidationError(ThomasMessageError):
    pass


class MessageConfigError(ThomasMessageError):
    pass


class MessagePersistenceError(ThomasMessageError):
    pass


# ---------------------------
# Normalization
# ---------------------------

_TIMESTAMP_RE = re.compile(r"^\d+(?:\.\d+)?$")
_SQLITE_SAFE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def normalize_message(
    payload: Mapping[str, Any],
    *,
    default_channel: str = "default",
    default_sender: str = "unknown",
) -> MessageRecord:
    """Normalize an inbound payload into a canonical :class:`MessageRecord`.

    Deterministic validation rules:
    - payload must be a mapping/object
    - text (or alias) must be present and non-empty
    - if schema_version is provided it must equal MESSAGE_SCHEMA_VERSION
    - if message_id is provided it must be a non-empty string
    """
    if not isinstance(payload, Mapping):
        raise MessageValidationError("invalid_input", "payload must be a JSON object")

    data: dict[str, Any] = dict(payload)

    # Schema/version guard (accept both keys)
    version_raw = data.pop("schema_version", None)
    if version_raw is None:
        version_raw = data.pop("version", None)
    if version_raw is not None:
        try:
            version_int = int(version_raw)
        except (json.JSONDecodeError, ValueError, KeyError) as e:  # pragma: no cover
            raise MessageValidationError("invalid_input", "schema_version must be an integer") from e
        if version_int != MESSAGE_SCHEMA_VERSION:
            raise MessageValidationError(
                "unsupported_schema_version",
                f"unsupported schema_version {version_int} (expected {MESSAGE_SCHEMA_VERSION})",
                details={"schema_version": version_int, "expected": MESSAGE_SCHEMA_VERSION},
            )

    # metadata: explicit + leftovers (explicit wins)
    metadata: dict[str, Any] = {}
    explicit_meta = data.pop("metadata", None)
    if isinstance(explicit_meta, Mapping):
        metadata.update(explicit_meta)
    elif explicit_meta is not None:
        raise MessageValidationError("invalid_input", "metadata must be an object when provided")

    # message_id (idempotency)
    message_id_raw = data.pop("message_id", None)
    if message_id_raw is None:
        message_id_raw = data.pop("id", None)
    if message_id_raw is None:
        message_id = str(uuid.uuid4())
    else:
        if not isinstance(message_id_raw, str) or not message_id_raw.strip():
            raise MessageValidationError("invalid_input", "message_id must be a non-empty string")
        message_id = message_id_raw.strip()

    # Text
    text = _first_string(data.pop("text", None), data.pop("content", None), data.pop("message", None))
    if not text:
        raise MessageValidationError("invalid_input", "text is required")

    # Channel + sender
    channel = _first_string(data.pop("channel", None), data.pop("room", None)) or default_channel
    sender = _first_string(data.pop("sender", None), data.pop("user", None), data.pop("author", None)) or default_sender

    # Timestamp
    ts_raw = data.pop("created_at", None)
    if ts_raw is None:
        ts_raw = data.pop("timestamp", None)
    if ts_raw is None:
        ts_raw = data.pop("ts", None)

    created_at = _parse_timestamp(ts_raw) if ts_raw is not None else datetime.now(timezone.utc)

    # Remaining unknown fields go into metadata (do not overwrite explicit keys)
    for k, v in data.items():
        metadata.setdefault(str(k), v)

    return MessageRecord(
        message_id=message_id,
        channel=str(channel),
        sender=str(sender),
        text=text,
        created_at=created_at,
        metadata=_coerce_jsonable(metadata),
        schema_version=MESSAGE_SCHEMA_VERSION,
    )


def _first_string(*values: Any) -> str:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _parse_timestamp(value: Any) -> datetime:
    """Parse a timestamp into an aware UTC datetime.

    Supported inputs:
    - datetime (aware/naive)
    - int/float epoch seconds
    - string epoch seconds (e.g. "1712345678.123")
    - ISO 8601 string (with optional trailing Z)
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)

    if isinstance(value, str):
        s = value.strip()
        if not s:
            raise MessageValidationError("invalid_input", "created_at/timestamp must be non-empty when provided")
        if _TIMESTAMP_RE.match(s):
            return datetime.fromtimestamp(float(s), tz=timezone.utc)
        if s.endswith("Z") and "T" in s:
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError as e:
            raise MessageValidationError(
                "invalid_input", "created_at/timestamp must be ISO8601 or epoch seconds"
            ) from e
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    raise MessageValidationError("invalid_input", "created_at/timestamp must be ISO8601, epoch seconds, or datetime")


def _coerce_jsonable(value: Any) -> Any:
    """Best-effort coercion to JSON-compatible types."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _coerce_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_coerce_jsonable(v) for v in value]
    return str(value)


# ---------------------------
# Persistence
# ---------------------------


@dataclass(frozen=True)
class MessageStoreConfig:
    """Configuration for message persistence."""

    db_path: Path
    table_name: str = DEFAULT_TABLE_NAME

    def __post_init__(self) -> None:
        if not _SQLITE_SAFE_NAME_RE.match(self.table_name):
            raise MessageConfigError(
                "invalid_config",
                f"invalid table_name {self.table_name!r} (must match {_SQLITE_SAFE_NAME_RE.pattern})",
            )


class MessageStore:
    """SQLite-backed message store."""

    def __init__(self, config: MessageStoreConfig):
        self._config = config
        self._db_path = config.db_path
        self._table = config.table_name

        if self._db_path.exists() and self._db_path.is_dir():
            raise MessageConfigError("invalid_store_path", f"store path is a directory: {self._db_path}")

        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise MessageConfigError(
                "invalid_store_path",
                f"cannot create store directory: {self._db_path.parent}",
                details={"store_path": str(self._db_path)},
            ) from e

        self._ensure_schema()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def add(self, record: MessageRecord) -> tuple[MessageRecord, bool]:
        """Insert a record.

        Insert behavior is idempotent for the same message_id:
          - if the message_id already exists, insertion is ignored and the stored row is returned.

        Returns (stored_record, inserted_flag).
        """
        if not isinstance(record.message_id, str) or not record.message_id:
            raise MessageValidationError("invalid_input", "record.message_id must be a non-empty string")
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                before = conn.total_changes
                conn.execute(
                    f"""
                    INSERT OR IGNORE INTO {self._table} (
                        message_id, channel, sender, text, created_at, schema_version, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.message_id,
                        record.channel,
                        record.sender,
                        record.text,
                        record.created_at.isoformat(),
                        record.schema_version,
                        json.dumps(record.metadata, separators=(",", ":"), sort_keys=True),
                    ),
                )
                conn.commit()
                inserted = conn.total_changes > before
        except sqlite3.Error as e:
            raise MessagePersistenceError("persistence_failure", "failed to persist message") from e

        if inserted:
            return record, True

        existing = self.get(record.message_id)
        return (existing if existing is not None else record), False

    def get(self, message_id: str) -> MessageRecord | None:
        if not isinstance(message_id, str) or not message_id:
            raise MessageValidationError("invalid_input", "message_id must be a non-empty string")
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                row = conn.execute(
                    f"""
                    SELECT message_id, channel, sender, text, created_at, schema_version, metadata_json
                    FROM {self._table}
                    WHERE message_id = ?
                    """,
                    (message_id,),
                ).fetchone()
        except sqlite3.Error as e:
            raise MessagePersistenceError("persistence_failure", "failed to read message") from e

        if not row:
            return None
        return _row_to_record(row)

    def list(self, *, limit: int = 100, channel: str | None = None) -> list[MessageRecord]:
        limit = int(limit)
        if limit <= 0:
            raise MessageValidationError("invalid_input", "limit must be a positive integer")

        where = ""
        params: list[Any] = []
        if channel is not None:
            where = "WHERE channel = ?"
            params.append(channel)

        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                rows = conn.execute(
                    f"""
                    SELECT message_id, channel, sender, text, created_at, schema_version, metadata_json
                    FROM {self._table}
                    {where}
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (*params, limit),
                ).fetchall()
        except sqlite3.Error as e:
            raise MessagePersistenceError("persistence_failure", "failed to read messages") from e

        return [_row_to_record(r) for r in rows]

    def _ensure_schema(self) -> None:
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self._table} (
                        message_id TEXT PRIMARY KEY,
                        channel TEXT NOT NULL,
                        sender TEXT NOT NULL,
                        text TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        schema_version INTEGER NOT NULL,
                        metadata_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{self._table}_created_at ON {self._table}(created_at)")
                conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{self._table}_channel ON {self._table}(channel)")
                conn.commit()
        except sqlite3.Error as e:
            raise MessagePersistenceError("persistence_failure", "failed to initialize message store") from e


def _row_to_record(row: Sequence[Any]) -> MessageRecord:
    (message_id, channel_v, sender_v, text_v, created_at_v, schema_version_v, metadata_json) = row
    try:
        metadata = json.loads(metadata_json) if metadata_json else {}
    except json.JSONDecodeError:
        metadata = {}
    created_at = _parse_timestamp(created_at_v)
    return MessageRecord(
        message_id=str(message_id),
        channel=str(channel_v),
        sender=str(sender_v),
        text=str(text_v),
        created_at=created_at,
        metadata=_coerce_jsonable(metadata),
        schema_version=int(schema_version_v),
    )


def resolve_store_path(
    *,
    explicit_path: os.PathLike[str] | str | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Resolve message store path from config/env.

    Resolution order:
      1) explicit_path
      2) THOMAS_MESSAGE_STORE / THOMAS_MESSAGES_DB / THOMAS_MESSAGE_DB
      3) THOMAS_DATA_DIR / THOMAS_HOME + DEFAULT_DB_FILENAME

    Raises:
        MessageConfigError(code="missing_config") when no configuration exists.
    """
    if explicit_path:
        return Path(explicit_path).expanduser()

    env_map = dict(env or os.environ)

    for key in ("THOMAS_MESSAGE_STORE", "THOMAS_MESSAGES_DB", "THOMAS_MESSAGE_DB"):
        v = env_map.get(key)
        if v:
            return Path(v).expanduser()

    data_dir = env_map.get("THOMAS_DATA_DIR") or env_map.get("THOMAS_HOME")
    if data_dir:
        return Path(data_dir).expanduser() / DEFAULT_DB_FILENAME

    raise MessageConfigError(
        "missing_config",
        "message store path not configured (set THOMAS_MESSAGE_STORE or THOMAS_DATA_DIR)",
    )


def ingest_and_persist(
    payload: Mapping[str, Any], *, store_path: os.PathLike[str] | str | None = None
) -> PersistedMessage:
    """Normalize and persist an inbound payload."""
    record = normalize_message(payload)
    db_path = resolve_store_path(explicit_path=store_path)
    store = MessageStore(MessageStoreConfig(db_path=db_path))
    stored, inserted = store.add(record)
    return PersistedMessage(record=stored, store_path=str(db_path), inserted=inserted)


def ingest_and_persist_safe(
    payload: Mapping[str, Any], *, store_path: os.PathLike[str] | str | None = None
) -> dict[str, Any]:
    """Safe wrapper that returns a machine-readable dict instead of raising."""
    try:
        return ingest_and_persist(payload, store_path=store_path).to_dict()
    except ThomasMessageError as e:
        return e.to_dict()
    except (json.JSONDecodeError, ValueError, KeyError):
        return {"ok": False, "error": {"code": "internal_error", "message": "unexpected error"}}


# Convenience aliases (Thomas-native naming)
persist_message = ingest_and_persist
persist_message_safe = ingest_and_persist_safe


def list_messages(
    *,
    store_path: os.PathLike[str] | str | None = None,
    limit: int = 100,
    channel: str | None = None,
) -> list[MessageRecord]:
    db_path = resolve_store_path(explicit_path=store_path)
    store = MessageStore(MessageStoreConfig(db_path=db_path))
    return store.list(limit=limit, channel=channel)


def list_messages_safe(
    *,
    store_path: os.PathLike[str] | str | None = None,
    limit: int = 100,
    channel: str | None = None,
) -> dict[str, Any]:
    try:
        records = list_messages(store_path=store_path, limit=limit, channel=channel)
        return {
            "ok": True,
            "store_path": str(resolve_store_path(explicit_path=store_path)),
            "messages": [r.to_dict() for r in records],
        }
    except ThomasMessageError as e:
        return e.to_dict()
    except (KeyError, ValueError, AttributeError):
        return {"ok": False, "error": {"code": "internal_error", "message": "unexpected error"}}
