"""
Nodes pairing handshake (P049)

This module implements a Thomas-native node pairing handshake. The handshake
creates (or reuses) a short-lived *pending pairing request* stored in the Thomas
state directory.

Design goals:
- Deterministic errors with stable machine-readable codes.
- Idempotent per node_id while a pending request is unexpired.
- Minimal assumptions about surrounding CLI / HTTP registries.

This prompt intentionally does *not* reuse OpenClaw naming.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Literal, Optional, TypedDict


DEFAULT_PENDING_TTL_MS: int = 5 * 60 * 1000  # 5 minutes
DEFAULT_LOCK_TIMEOUT_MS: int = 1500
DEFAULT_LOCK_STALE_MS: int = 15_000


class NodesPairingHandshakeError(RuntimeError):
    """
    Deterministic error for pairing handshake failures.

    `code` is intended to be stable for machine handling.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": self.message}}


@dataclass(frozen=True)
class NodesPairingHandshakeInput:
    """
    Input contract.

    Args:
        node_id: Stable identifier for the node (provided by the node).
        display_name: Human-friendly node name.
        silent: Hint for higher layers (does not change security behavior).
    """

    node_id: str
    display_name: Optional[str] = None
    silent: bool = False


@dataclass(frozen=True)
class NodesPairingHandshakeOutput:
    """
    Output contract for a successful handshake.

    created=True iff a new pending request was created (rather than reused).
    """

    ok: Literal[True]
    request_id: str
    node_id: str
    display_name: Optional[str]
    expires_at_ms: int
    created: bool

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("ok", None)
        return {"ok": True, "payload": payload}


class _PendingRecord(TypedDict):
    request_id: str
    node_id: str
    display_name: Optional[str]
    created_at_ms: int
    expires_at_ms: int
    silent: bool


# node_id: reasonably strict; stable identifiers should not be whitespacey or huge.
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _maybe_resolve_state_dir_from_parity_compat() -> Optional[Path]:
    """
    Best-effort integration point:

    If thomas.cli.parity_compat provides a canonical state-dir resolver, use it.
    This avoids hard coupling to internal helper names.
    """
    try:
        from thomas.cli import parity_compat as _pc  # type: ignore
    except Exception:
        return None

    candidates = (
        "resolve_state_dir",
        "get_state_dir",
        "state_dir",
        "state_dir_path",
        "get_state_path",
        "default_state_dir",
    )

    for attr in candidates:
        fn = getattr(_pc, attr, None)
        if not callable(fn):
            continue
        try:
            value = fn()
        except TypeError:
            # helper might require args
            continue
        except Exception:
            continue
        if isinstance(value, (str, os.PathLike)):
            return Path(value)
    return None


def resolve_state_dir(state_dir: Optional[Path] = None) -> Path:
    """
    Resolve the Thomas state directory.

    Order:
    1) explicit argument
    2) thomas.cli.parity_compat helper (if present)
    3) THOMAS_STATE_DIR env var
    4) ~/.thomas
    """
    if state_dir is not None:
        return Path(state_dir)

    resolved = _maybe_resolve_state_dir_from_parity_compat()
    if resolved is not None:
        return resolved

    env = os.environ.get("THOMAS_STATE_DIR")
    if env:
        return Path(env)

    return Path.home() / ".thomas"


def _ensure_dir(path: Path) -> None:
    if path.exists() and not path.is_dir():
        raise NodesPairingHandshakeError(
            "missing_config",
            f"Expected directory but found file: {path}",
        )
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise NodesPairingHandshakeError("external_failure", f"Could not create directory {path}: {e}") from e


def _load_json_dict(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise NodesPairingHandshakeError("storage_error", f"Invalid JSON in {path}") from e
    except Exception as e:
        raise NodesPairingHandshakeError("external_failure", f"Could not read {path}: {e}") from e

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise NodesPairingHandshakeError("storage_error", f"Unsupported JSON format in {path} (expected object)")
    return data


def _atomic_write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        tmp.replace(path)
    except Exception as e:
        raise NodesPairingHandshakeError("external_failure", f"Could not write {path}: {e}") from e


class _Lock:
    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self._fd: Optional[int] = None

    def acquire(self, *, timeout_ms: int, stale_ms: int, now_ms: Callable[[], int]) -> None:
        start = now_ms()
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        while True:
            try:
                # Atomic create works cross-platform; fails if file already exists.
                self._fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, f"pid={os.getpid()} created_at_ms={now_ms()}\n".encode("utf-8"))
                return
            except FileExistsError:
                # If the lock is stale, best-effort break it.
                try:
                    mtime_ms = int(self.lock_path.stat().st_mtime * 1000)
                except Exception:
                    mtime_ms = 0
                if mtime_ms and (now_ms() - mtime_ms) > stale_ms:
                    try:
                        self.lock_path.unlink(missing_ok=True)  # py3.8+: missing_ok; ok in 3.11
                    except Exception:
                        # If we cannot remove it, fall through to timeout handling.
                        pass
                if (now_ms() - start) >= timeout_ms:
                    raise NodesPairingHandshakeError(
                        "storage_error",
                        f"Pending store is locked: {self.lock_path}",
                    )
                time.sleep(0.02)
            except Exception as e:
                raise NodesPairingHandshakeError("external_failure", f"Could not acquire lock {self.lock_path}: {e}") from e

    def release(self) -> None:
        try:
            if self._fd is not None:
                try:
                    os.close(self._fd)
                finally:
                    self._fd = None
            try:
                self.lock_path.unlink(missing_ok=True)
            except Exception:
                # Best effort: don't crash release.
                pass
        except Exception:
            pass

    def __enter__(self) -> "_Lock":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.release()


def _nodes_store_paths(state_dir: Path) -> tuple[Path, Path, Path]:
    nodes_dir = state_dir / "nodes"
    pending_path = nodes_dir / "pending.json"
    lock_path = nodes_dir / "pending.lock"
    paired_path = nodes_dir / "paired.json"
    return pending_path, lock_path, paired_path


def _validate_input(data: NodesPairingHandshakeInput) -> tuple[str, Optional[str], bool]:
    node_id = data.node_id
    if not isinstance(node_id, str):
        node_id = str(node_id)

    if not node_id:
        raise NodesPairingHandshakeError("invalid_input", "node_id is required")
    if node_id.strip() != node_id:
        raise NodesPairingHandshakeError("invalid_input", "node_id must not have leading/trailing whitespace")
    if not _NODE_ID_RE.match(node_id):
        raise NodesPairingHandshakeError(
            "invalid_input",
            "node_id must match /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/",
        )

    display_name = data.display_name
    if display_name is not None and not isinstance(display_name, str):
        display_name = str(display_name)
    if isinstance(display_name, str):
        display_name = display_name.strip()
        if display_name == "":
            display_name = None
        elif len(display_name) > 120:
            raise NodesPairingHandshakeError("invalid_input", "display_name is too long (max 120 chars)")

    return node_id, display_name, bool(data.silent)


def nodes_pairing_handshake(
    data: NodesPairingHandshakeInput,
    *,
    state_dir: Optional[Path] = None,
    now_ms: Callable[[], int] = _now_ms,
    ttl_ms: int = DEFAULT_PENDING_TTL_MS,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    lock_stale_ms: int = DEFAULT_LOCK_STALE_MS,
) -> NodesPairingHandshakeOutput:
    """
    Create (or reuse) a pending pairing request.

    Idempotency rule:
        If an unexpired pending request already exists for node_id, it is reused.

    Raises:
        NodesPairingHandshakeError for invalid input, missing config, or I/O errors.
    """
    if ttl_ms <= 0:
        raise NodesPairingHandshakeError("invalid_input", "ttl_ms must be > 0")

    node_id, display_name, silent = _validate_input(data)

    resolved_state_dir = resolve_state_dir(state_dir)
    _ensure_dir(resolved_state_dir)

    pending_path, lock_path, _paired_path = _nodes_store_paths(resolved_state_dir)
    _ensure_dir(pending_path.parent)

    now = int(now_ms())
    expires_at = now + int(ttl_ms)

    with _Lock(lock_path) as lk:
        lk.acquire(timeout_ms=lock_timeout_ms, stale_ms=lock_stale_ms, now_ms=now_ms)

        pending_raw = _load_json_dict(pending_path)
        pending: Dict[str, _PendingRecord] = {}

        # Normalize records and drop obviously invalid ones.
        for req_id, rec in pending_raw.items():
            if not isinstance(req_id, str) or not req_id:
                continue
            if not isinstance(rec, dict):
                continue
            try:
                exp = int(rec.get("expires_at_ms", 0))
            except Exception:
                exp = 0
            if exp and exp <= now:
                continue
            # Best effort type normalization; keep only keys we care about.
            pending[req_id] = {
                "request_id": str(rec.get("request_id") or req_id),
                "node_id": str(rec.get("node_id") or ""),
                "display_name": rec.get("display_name") if isinstance(rec.get("display_name"), (str, type(None))) else None,
                "created_at_ms": int(rec.get("created_at_ms") or now),
                "expires_at_ms": int(exp or (now + ttl_ms)),
                "silent": bool(rec.get("silent", False)),
            }

        # Reuse if present (idempotent per node_id).
        for req_id, rec in pending.items():
            if rec.get("node_id") != node_id:
                continue

            updated = False

            # If the caller provides a display name, prefer the latest non-empty one.
            if display_name is not None and rec.get("display_name") != display_name:
                rec["display_name"] = display_name
                updated = True

            # If the caller set silent, retain it (monotonic True).
            if silent and not rec.get("silent", False):
                rec["silent"] = True
                updated = True

            # Keep the original expiry (do not extend) for predictability.
            if updated:
                pending[req_id] = rec
                _atomic_write_json(pending_path, pending)

            return NodesPairingHandshakeOutput(
                ok=True,
                request_id=rec["request_id"],
                node_id=node_id,
                display_name=rec.get("display_name"),
                expires_at_ms=int(rec.get("expires_at_ms") or expires_at),
                created=False,
            )

        # Create new pending request.
        request_id = uuid.uuid4().hex
        record: _PendingRecord = {
            "request_id": request_id,
            "node_id": node_id,
            "display_name": display_name,
            "created_at_ms": now,
            "expires_at_ms": expires_at,
            "silent": silent,
        }
        pending[request_id] = record
        _atomic_write_json(pending_path, pending)

    return NodesPairingHandshakeOutput(
        ok=True,
        request_id=request_id,
        node_id=node_id,
        display_name=display_name,
        expires_at_ms=expires_at,
        created=True,
    )


# ---------------------------------------------------------------------------
# JSON schema (machine readable contracts)
# ---------------------------------------------------------------------------

INPUT_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["node_id"],
    "properties": {
        "node_id": {"type": "string", "minLength": 1, "maxLength": 64},
        "display_name": {"type": ["string", "null"], "maxLength": 120},
        "silent": {"type": "boolean"},
    },
    "additionalProperties": False,
}

OUTPUT_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["ok"],
    "properties": {
        "ok": {"type": "boolean"},
        "payload": {"type": "object"},
        "error": {"type": "object"},
    },
    "additionalProperties": True,
}


def run(payload: Dict[str, Any], *, state_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Execute the handshake from a plain dict payload.

    Returns a dict shaped like OUTPUT_JSON_SCHEMA.
    """
    try:
        out = nodes_pairing_handshake(
            NodesPairingHandshakeInput(
                node_id=str(payload.get("node_id") or ""),
                display_name=payload.get("display_name"),
                silent=bool(payload.get("silent", False)),
            ),
            state_dir=state_dir,
        )
        return out.to_dict()
    except NodesPairingHandshakeError as e:
        return e.to_dict()


# ---------------------------------------------------------------------------
# Aiohttp integration point (optional)
# ---------------------------------------------------------------------------

async def handle(request: Any) -> Any:
    """
    Aiohttp handler for the pairing handshake.

    Request JSON:
        { "node_id": "...", "display_name": "...", "silent": false }

    Response JSON:
        { "ok": true, "payload": { ... } }
    """
    try:
        from aiohttp import web  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("aiohttp is required to use this route") from e

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"ok": False, "error": {"code": "invalid_input", "message": "Request body must be JSON"}},
            status=400,
        )

    if not isinstance(body, dict):
        return web.json_response(
            {"ok": False, "error": {"code": "invalid_input", "message": "Request JSON must be an object"}},
            status=400,
        )

    try:
        out = nodes_pairing_handshake(
            NodesPairingHandshakeInput(
                node_id=str(body.get("node_id") or ""),
                display_name=body.get("display_name"),
                silent=bool(body.get("silent", False)),
            )
        )
        return web.json_response(out.to_dict())
    except NodesPairingHandshakeError as e:
        status = 400 if e.code in {"invalid_input", "missing_config"} else 500
        return web.json_response(e.to_dict(), status=status)
    except Exception as e:  # pragma: no cover
        return web.json_response(
            {"ok": False, "error": {"code": "external_failure", "message": str(e)}},
            status=500,
        )
