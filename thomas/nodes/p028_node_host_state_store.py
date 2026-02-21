from __future__ import annotations

"""
Node host state store (P028)

This module provides a tiny, local, file-backed persistence layer for *per-host* state snapshots.

Goals:
- Safe filenames (host_id validation) to avoid path traversal.
- JSON-serializable state payload (dict) stored as an opaque object.
- Deterministic, machine-readable errors for automation.
- Atomic writes (temp file + rename) with best-effort fsync for durability.
"""

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, TypedDict, Final


# -----------------------------
# Contracts
# -----------------------------

HOST_STATE_SCHEMA_V1: Final[str] = "thomas.node_host_state.v1"


class ErrorJson(TypedDict):
    code: str
    message: str
    details: dict[str, Any]


class HostStateRecordJson(TypedDict):
    schema: str
    host_id: str
    updated_at: str
    state: dict[str, Any]


class HostStateWriteResultJson(TypedDict):
    ok: bool
    record: HostStateRecordJson
    path: str


class HostStateReadResultJson(TypedDict):
    ok: bool
    found: bool
    record: Optional[HostStateRecordJson]
    path: Optional[str]


class HostStateDeleteResultJson(TypedDict):
    ok: bool
    deleted: bool
    host_id: str
    path: Optional[str]


class HostStateScanResultJson(TypedDict):
    ok: bool
    store_dir: str
    count: int
    records: list[HostStateRecordJson]
    errors: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class PutHostStateRequest:
    host_id: str
    state: dict[str, Any]
    updated_at: Optional[str] = None


@dataclass(frozen=True, slots=True)
class GetHostStateRequest:
    host_id: str


@dataclass(frozen=True, slots=True)
class DeleteHostStateRequest:
    host_id: str


@dataclass(frozen=True, slots=True)
class HostStateRecord:
    """
    Persisted snapshot of a host's state.

    `state` is JSON-serializable and treated as opaque by the store.
    `updated_at` is an ISO-8601 timestamp with timezone offset, normalized to UTC.
    """

    host_id: str
    updated_at: str
    state: dict[str, Any]
    schema: str = HOST_STATE_SCHEMA_V1

    def to_json(self) -> HostStateRecordJson:
        return {
            "schema": self.schema,
            "host_id": self.host_id,
            "updated_at": self.updated_at,
            "state": self.state,
        }


# -----------------------------
# Deterministic errors
# -----------------------------


class NodeHostStateStoreError(RuntimeError):
    """
    Deterministic, machine-readable store errors.

    `code` is stable across versions to support automation.
    """

    def __init__(self, code: str, message: str, *, details: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def to_json(self) -> ErrorJson:
        return {"code": self.code, "message": str(self), "details": self.details}


class NodeHostStateStoreConfigError(NodeHostStateStoreError):
    pass


class NodeHostStateStoreInvalidInputError(NodeHostStateStoreError):
    pass


class NodeHostStateStoreExternalFailureError(NodeHostStateStoreError):
    pass


# -----------------------------
# Store implementation
# -----------------------------


_ENV_STORE_DIR_KEYS: Final[tuple[str, ...]] = (
    # Preferred explicit config for this feature.
    "THOMAS_NODE_HOST_STATE_DIR",
    # Accept a couple of generic Thomas locations.
    "THOMAS_STATE_DIR",
    "THOMAS_DATA_DIR",
)


_HOST_ID_ALLOWED_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def resolve_host_state_store_dir(
    store_dir: Optional[Path] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
    allow_default: bool = True,
) -> Path:
    """
    Resolve the directory that backs the store.

    Resolution order:
      1) Explicit `store_dir`
      2) Environment variables (THOMAS_NODE_HOST_STATE_DIR, THOMAS_STATE_DIR, THOMAS_DATA_DIR)
      3) Per-user default (only if allow_default=True)

    Raises:
        NodeHostStateStoreConfigError: if no directory can be resolved (and allow_default=False)
    """
    if store_dir is not None:
        return Path(store_dir)

    env_map: Mapping[str, str] = os.environ if env is None else env
    for key in _ENV_STORE_DIR_KEYS:
        value = env_map.get(key)
        if value:
            return Path(value)

    if not allow_default:
        raise NodeHostStateStoreConfigError(
            "missing_store_dir",
            "No node host state store directory configured.",
            details={"expected_env": list(_ENV_STORE_DIR_KEYS)},
        )

    # Default: XDG_STATE_HOME if present, else ~/.local/state
    xdg_state_home = env_map.get("XDG_STATE_HOME")
    base = Path(xdg_state_home) if xdg_state_home else (Path.home() / ".local" / "state")
    return base / "thomas" / "node_host_state"


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_updated_at(updated_at: Optional[str]) -> str:
    if updated_at is None:
        return _now_utc_iso()

    if not isinstance(updated_at, str):
        raise NodeHostStateStoreInvalidInputError(
            "invalid_updated_at",
            "updated_at must be a string.",
            details={"received_type": type(updated_at).__name__},
        )

    value = updated_at.strip()
    if not value:
        raise NodeHostStateStoreInvalidInputError(
            "invalid_updated_at",
            "updated_at must not be empty.",
        )

    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise NodeHostStateStoreInvalidInputError(
            "invalid_updated_at",
            "updated_at must be an ISO-8601 timestamp.",
            details={"value": value, "error": str(exc)},
        ) from exc

    if dt.tzinfo is None:
        raise NodeHostStateStoreInvalidInputError(
            "invalid_updated_at",
            "updated_at must include a timezone offset (e.g., Z or +00:00).",
            details={"value": value},
        )

    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _validate_host_id(host_id: str) -> str:
    if not isinstance(host_id, str):
        raise NodeHostStateStoreInvalidInputError(
            "invalid_host_id",
            "host_id must be a string.",
            details={"received_type": type(host_id).__name__},
        )

    host_id = host_id.strip()
    if not host_id:
        raise NodeHostStateStoreInvalidInputError("invalid_host_id", "host_id must not be empty.")

    if "/" in host_id or "\\" in host_id:
        raise NodeHostStateStoreInvalidInputError(
            "invalid_host_id",
            "host_id must not contain path separators.",
            details={"host_id": host_id},
        )

    if not _HOST_ID_ALLOWED_RE.match(host_id):
        raise NodeHostStateStoreInvalidInputError(
            "invalid_host_id",
            "host_id must match pattern: /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/",
            details={"host_id": host_id},
        )

    return host_id


def _normalize_state(state: Any) -> dict[str, Any]:
    """
    Validate and normalize the state payload.
    - Must be a dict
    - Must be JSON serializable
    - Is deep-copied via JSON round-trip to prevent later caller mutation
    """
    if not isinstance(state, dict):
        raise NodeHostStateStoreInvalidInputError(
            "invalid_state",
            "state must be a JSON-serializable object (dict).",
            details={"received_type": type(state).__name__},
        )

    try:
        encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        decoded = json.loads(encoded)
    except TypeError as exc:
        raise NodeHostStateStoreInvalidInputError(
            "invalid_state",
            "state is not JSON-serializable.",
            details={"error": str(exc)},
        ) from exc
    except json.JSONDecodeError as exc:  # pragma: no cover (shouldn't happen)
        raise NodeHostStateStoreInvalidInputError(
            "invalid_state",
            "state could not be normalized as JSON.",
            details={"error": str(exc)},
        ) from exc

    if not isinstance(decoded, dict):  # pragma: no cover (shouldn't happen)
        raise NodeHostStateStoreInvalidInputError(
            "invalid_state",
            "state must be a JSON object.",
            details={"received_type": type(decoded).__name__},
        )

    return decoded


def _host_state_path(base_dir: Path, host_id: str) -> Path:
    return base_dir / f"{host_id}.json"


def _fsync_dir_best_effort(dir_path: Path) -> None:
    """
    Best-effort directory fsync (helps on POSIX to ensure rename is durable).
    No-op on platforms/filesystems that don't support it.
    """
    try:
        fd = os.open(str(dir_path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


class NodeHostStateStore:
    """
    Simple, file-backed store for node host state.

    Each host has a separate JSON file under `store_dir`:
        <store_dir>/<host_id>.json
    """

    def __init__(self, store_dir: Path, *, create: bool = True):
        self.store_dir = Path(store_dir)

        if self.store_dir.exists() and not self.store_dir.is_dir():
            raise NodeHostStateStoreConfigError(
                "invalid_store_dir",
                "Store directory path exists but is not a directory.",
                details={"store_dir": str(self.store_dir)},
            )

        if create:
            try:
                self.store_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise NodeHostStateStoreExternalFailureError(
                    "store_dir_create_failed",
                    "Failed to create store directory.",
                    details={"store_dir": str(self.store_dir), "error": str(exc)},
                ) from exc

    def path_for(self, host_id: str) -> Path:
        host_id = _validate_host_id(host_id)
        return _host_state_path(self.store_dir, host_id)

    def exists(self, host_id: str) -> bool:
        return self.path_for(host_id).exists()

    def put(
        self,
        host_id: str,
        state: dict[str, Any],
        *,
        updated_at: Optional[str] = None,
    ) -> HostStateRecord:
        host_id = _validate_host_id(host_id)
        state_norm = _normalize_state(state)
        updated_at_norm = _normalize_updated_at(updated_at)

        record = HostStateRecord(host_id=host_id, updated_at=updated_at_norm, state=state_norm)
        path = _host_state_path(self.store_dir, host_id)

        tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        payload = record.to_json()
        try:
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True, ensure_ascii=False)
                f.write("\n")
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    # Some FS/OS combos don't support fsync the way we want; ignore.
                    pass
            tmp_path.replace(path)
            _fsync_dir_best_effort(path.parent)
        except OSError as exc:
            # Best effort cleanup.
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise NodeHostStateStoreExternalFailureError(
                "write_failed",
                "Failed to write host state record.",
                details={"path": str(path), "error": str(exc)},
            ) from exc

        return record

    def get(self, host_id: str) -> Optional[HostStateRecord]:
        host_id = _validate_host_id(host_id)
        path = _host_state_path(self.store_dir, host_id)
        if not path.exists():
            return None

        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except OSError as exc:
            raise NodeHostStateStoreExternalFailureError(
                "read_failed",
                "Failed to read host state record.",
                details={"path": str(path), "error": str(exc)},
            ) from exc
        except json.JSONDecodeError as exc:
            raise NodeHostStateStoreExternalFailureError(
                "corrupt_record",
                "Host state record is not valid JSON.",
                details={"path": str(path), "error": str(exc)},
            ) from exc

        # Validate minimum shape (keep forward-compatible where possible).
        if not isinstance(data, dict):
            raise NodeHostStateStoreExternalFailureError(
                "corrupt_record",
                "Host state record JSON must be an object.",
                details={"path": str(path)},
            )

        schema = data.get("schema")
        rec_host_id = data.get("host_id")
        updated_at = data.get("updated_at")
        state = data.get("state")

        if schema != HOST_STATE_SCHEMA_V1:
            raise NodeHostStateStoreExternalFailureError(
                "unsupported_schema",
                "Unsupported host state schema.",
                details={"path": str(path), "schema": schema},
            )
        if rec_host_id != host_id:
            raise NodeHostStateStoreExternalFailureError(
                "corrupt_record",
                "Host state record host_id does not match filename.",
                details={"path": str(path), "expected_host_id": host_id, "record_host_id": rec_host_id},
            )
        if not isinstance(updated_at, str) or not updated_at:
            raise NodeHostStateStoreExternalFailureError(
                "corrupt_record",
                "Host state record missing/invalid updated_at.",
                details={"path": str(path)},
            )
        if not isinstance(state, dict):
            raise NodeHostStateStoreExternalFailureError(
                "corrupt_record",
                "Host state record 'state' must be an object.",
                details={"path": str(path)},
            )

        # Do not force-normalize on read beyond basic validation; preserve stored value.
        return HostStateRecord(host_id=host_id, updated_at=updated_at, state=state)

    def delete(self, host_id: str) -> bool:
        host_id = _validate_host_id(host_id)
        path = _host_state_path(self.store_dir, host_id)
        if not path.exists():
            return False
        try:
            path.unlink()
            return True
        except OSError as exc:
            raise NodeHostStateStoreExternalFailureError(
                "delete_failed",
                "Failed to delete host state record.",
                details={"path": str(path), "error": str(exc)},
            ) from exc

    def scan(self) -> tuple[list[HostStateRecord], list[dict[str, Any]]]:
        """
        Scan the store directory and return (records, errors).

        - Records are returned in deterministic order by host_id.
        - Per-file errors are captured rather than aborting the scan.
        - Directory access failures raise deterministic errors.
        """
        if not self.store_dir.exists():
            return [], []

        records: list[HostStateRecord] = []
        errors: list[dict[str, Any]] = []

        try:
            for p in sorted(self.store_dir.glob("*.json"), key=lambda x: x.name):
                host_id = p.stem
                if not _HOST_ID_ALLOWED_RE.match(host_id):
                    continue
                try:
                    rec = self.get(host_id)
                    if rec is not None:
                        records.append(rec)
                except NodeHostStateStoreError as exc:
                    errors.append({"path": str(p), "error": exc.to_json()})
        except OSError as exc:
            raise NodeHostStateStoreExternalFailureError(
                "list_failed",
                "Failed to scan host state records.",
                details={"store_dir": str(self.store_dir), "error": str(exc)},
            ) from exc

        records.sort(key=lambda r: r.host_id)
        return records, errors

    def list(self) -> list[HostStateRecord]:
        """
        Return records only; skips unreadable/corrupt records.
        """
        records, _errors = self.scan()
        return records


# -----------------------------
# Convenience JSON helpers
# -----------------------------


def put_host_state_json(
    store: NodeHostStateStore,
    host_id: str,
    state: dict[str, Any],
    *,
    updated_at: Optional[str] = None,
) -> HostStateWriteResultJson:
    record = store.put(host_id, state, updated_at=updated_at)
    path = str(store.path_for(record.host_id))
    return {"ok": True, "record": record.to_json(), "path": path}


def get_host_state_json(store: NodeHostStateStore, host_id: str) -> HostStateReadResultJson:
    record = store.get(host_id)
    if record is None:
        return {"ok": True, "found": False, "record": None, "path": None}
    path = str(store.path_for(record.host_id))
    return {"ok": True, "found": True, "record": record.to_json(), "path": path}


def delete_host_state_json(store: NodeHostStateStore, host_id: str) -> HostStateDeleteResultJson:
    host_id_valid = _validate_host_id(host_id)
    deleted = store.delete(host_id_valid)
    path = str(store.path_for(host_id_valid)) if deleted else None
    return {"ok": True, "deleted": deleted, "host_id": host_id_valid, "path": path}


def scan_host_states_json(store: NodeHostStateStore) -> HostStateScanResultJson:
    records, errors = store.scan()
    recs = [r.to_json() for r in records]
    return {
        "ok": True,
        "store_dir": str(store.store_dir),
        "count": len(recs),
        "records": recs,
        "errors": errors,
    }


__all__ = [
    "HOST_STATE_SCHEMA_V1",
    "ErrorJson",
    "HostStateRecordJson",
    "HostStateWriteResultJson",
    "HostStateReadResultJson",
    "HostStateDeleteResultJson",
    "HostStateScanResultJson",
    "PutHostStateRequest",
    "GetHostStateRequest",
    "DeleteHostStateRequest",
    "HostStateRecord",
    "NodeHostStateStore",
    "NodeHostStateStoreError",
    "NodeHostStateStoreConfigError",
    "NodeHostStateStoreInvalidInputError",
    "NodeHostStateStoreExternalFailureError",
    "resolve_host_state_store_dir",
    "put_host_state_json",
    "get_host_state_json",
    "delete_host_state_json",
    "scan_host_states_json",
]
