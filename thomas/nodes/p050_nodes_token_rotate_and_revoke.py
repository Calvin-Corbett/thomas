from __future__ import annotations

"""P050 — Nodes token rotate and revoke

Thomas-native support for managing per-node access tokens.

Key behavior
- Rotate: revoke any currently-active token for a node and issue a new token.
- Revoke: revoke the currently-active token for a node (idempotent).

Design
- The persistent store keeps only a salted hash of the token.
- The plaintext token is returned only at rotation time.
- Store writes are atomic (tempfile + replace).

Storage schema (version 1)
{
  "version": 1,
  "nodes": {
    "<node_id>": {
      "tokens": [
        {
          "hash": "...",
          "salt": "...",
          "created_at": "2026-01-01T00:00:00Z",
          "revoked_at": null,
          "revoked_reason": "rotated|revoked"  // optional
        }
      ]
    }
  }
}
"""

import hashlib
import json
import os
import re
import secrets
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

TokenAction = Literal["rotate", "revoke"]

# Environment variable for overriding the default store path.
ENV_STORE_PATH = "THOMAS_NODES_TOKENS_PATH"

# Conservative node-id validation: filesystem safe, URL safe, human readable.
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class NodesTokenError(Exception):
    """Deterministic, machine-readable error for node token operations."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}

    @property
    def http_status(self) -> int:
        """Best-effort mapping for HTTP servers."""
        if self.code in {"invalid_node_id", "invalid_request"}:
            return 400
        if self.code in {"missing_config"}:
            return 404
        return 500

    @property
    def status_code(self) -> int:  # pragma: no cover
        return self.http_status


@dataclass(frozen=True)
class NodesTokenRotateAndRevokeRequest:
    """Input contract."""

    action: TokenAction
    node_id: str
    store_path: Path | None = None


@dataclass(frozen=True)
class NodesTokenRotateAndRevokeResult:
    """Output contract."""

    ok: bool
    action: TokenAction
    node_id: str
    status: Literal["rotated", "revoked", "no_active_token", "error"]
    token: str | None = None
    token_fingerprint: str | None = None
    message: str | None = None
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "action": self.action,
            "node_id": self.node_id,
            "status": self.status,
        }
        if self.token is not None:
            payload["token"] = self.token
        if self.token_fingerprint is not None:
            payload["token_fingerprint"] = self.token_fingerprint
        if self.message is not None:
            payload["message"] = self.message
        if self.error is not None:
            payload["error"] = self.error
        return payload


REQUEST_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["action", "node_id"],
    "properties": {
        "action": {"type": "string", "enum": ["rotate", "revoke"]},
        "node_id": {"type": "string"},
    },
    "additionalProperties": True,
}

RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["ok", "action", "node_id", "status"],
    "properties": {
        "ok": {"type": "boolean"},
        "action": {"type": "string", "enum": ["rotate", "revoke"]},
        "node_id": {"type": "string"},
        "status": {"type": "string"},
        "token": {"type": "string"},
        "token_fingerprint": {"type": "string"},
        "message": {"type": "string"},
        "error": {"type": "object"},
    },
    "additionalProperties": True,
}


def _now_iso(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_node_id(node_id: str) -> None:
    if not isinstance(node_id, str) or not node_id:
        raise NodesTokenError("invalid_node_id", "node_id must be a non-empty string")
    if not _NODE_ID_RE.match(node_id):
        raise NodesTokenError(
            "invalid_node_id",
            "node_id must match ^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$",
            details={"node_id": node_id},
        )


def default_store_path() -> Path:
    env = os.environ.get(ENV_STORE_PATH)
    if env:
        return Path(env).expanduser()
    return Path.home() / ".thomas" / "nodes_tokens.json"


def _hash_token(token: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    return hashlib.sha256(salt + token.encode("utf-8")).hexdigest()


def _fingerprint(digest_hex: str) -> str:
    # Short, non-secret identifier for logs.
    return digest_hex[:12]


class NodesTokenStore:
    """Tiny JSON-backed store for node tokens (schema version 1)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, *, create: bool) -> dict[str, Any]:
        if self.path.exists():
            if self.path.is_dir():
                raise NodesTokenError(
                    "invalid_config",
                    "token store path points to a directory",
                    details={"path": str(self.path)},
                )
            try:
                raw = self.path.read_text(encoding="utf-8")
            except OSError as e:
                raise NodesTokenError(
                    "storage_error",
                    "failed to read token store",
                    details={"path": str(self.path), "os_error": str(e)},
                )
            try:
                data = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError as e:
                raise NodesTokenError(
                    "invalid_config",
                    "token store is not valid JSON",
                    details={"path": str(self.path), "error": str(e)},
                )
        else:
            if not create:
                raise NodesTokenError(
                    "missing_config",
                    "token store does not exist",
                    details={"path": str(self.path)},
                )
            data = {}

        if not isinstance(data, dict):
            raise NodesTokenError(
                "invalid_config",
                "token store root must be a JSON object",
                details={"path": str(self.path)},
            )

        version = data.get("version", 1)
        if version != 1:
            raise NodesTokenError(
                "invalid_config",
                "unsupported token store version",
                details={"path": str(self.path), "version": version},
            )

        nodes = data.get("nodes")
        if nodes is None:
            data["nodes"] = {}
        elif not isinstance(nodes, dict):
            raise NodesTokenError(
                "invalid_config",
                "'nodes' must be a JSON object",
                details={"path": str(self.path)},
            )

        data.setdefault("version", 1)
        return data

    def save(self, data: Mapping[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise NodesTokenError(
                "storage_error",
                "failed to create token store directory",
                details={"path": str(self.path.parent), "os_error": str(e)},
            )

        tmp_dir = self.path.parent if self.path.parent.exists() else Path(tempfile.gettempdir())
        tmp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(tmp_dir), delete=False) as f:
                json.dump(dict(data), f, indent=2, sort_keys=True)
                f.write("\n")
                tmp_name = f.name
            os.replace(tmp_name, self.path)
        except OSError as e:
            if tmp_name:
                try:
                    if os.path.exists(tmp_name):
                        os.unlink(tmp_name)
                except OSError:
                    pass
            raise NodesTokenError(
                "storage_error",
                "failed to write token store",
                details={"path": str(self.path), "os_error": str(e)},
            )


def rotate_node_token(
    node_id: str,
    *,
    store_path: Path | None = None,
    now: datetime | None = None,
) -> NodesTokenRotateAndRevokeResult:
    """Rotate a node token: revoke any active token and create a new one."""

    _validate_node_id(node_id)

    path = store_path or default_store_path()
    store = NodesTokenStore(path)
    state = store.load(create=True)

    nodes: dict[str, Any] = state.setdefault("nodes", {})
    node: dict[str, Any] = nodes.setdefault(node_id, {})
    tokens = node.setdefault("tokens", [])

    if not isinstance(tokens, list):
        raise NodesTokenError(
            "invalid_config",
            "node token list must be a list",
            details={"node_id": node_id},
        )

    ts = _now_iso(now)

    revoked_any = False
    for entry in tokens:
        if isinstance(entry, dict) and entry.get("revoked_at") is None:
            entry["revoked_at"] = ts
            entry["revoked_reason"] = "rotated"
            revoked_any = True

    token = secrets.token_urlsafe(32)
    salt_hex = secrets.token_bytes(16).hex()
    digest = _hash_token(token, salt_hex)

    tokens.append(
        {
            "hash": digest,
            "salt": salt_hex,
            "created_at": ts,
            "revoked_at": None,
        }
    )

    state["version"] = 1
    store.save(state)

    msg = "token rotated" + (" (previous token revoked)" if revoked_any else "")

    return NodesTokenRotateAndRevokeResult(
        ok=True,
        action="rotate",
        node_id=node_id,
        status="rotated",
        token=token,
        token_fingerprint=_fingerprint(digest),
        message=msg,
    )


def revoke_node_token(
    node_id: str,
    *,
    store_path: Path | None = None,
    now: datetime | None = None,
) -> NodesTokenRotateAndRevokeResult:
    """Revoke the active token for a node.

    Idempotent:
    - If there is no store yet, no node entry, or no active token, returns `no_active_token`.
    - Otherwise revokes the active token and persists.
    """

    _validate_node_id(node_id)

    path = store_path or default_store_path()

    # If the store isn't present, there is nothing to revoke.
    if not path.exists():
        return NodesTokenRotateAndRevokeResult(
            ok=True,
            action="revoke",
            node_id=node_id,
            status="no_active_token",
            message="no token store; nothing to revoke",
        )

    store = NodesTokenStore(path)
    state = store.load(create=False)

    nodes = state.get("nodes", {})
    if not isinstance(nodes, dict):
        raise NodesTokenError(
            "invalid_config",
            "'nodes' must be a JSON object",
            details={"path": str(path)},
        )

    node = nodes.get(node_id)
    if node is None:
        return NodesTokenRotateAndRevokeResult(
            ok=True,
            action="revoke",
            node_id=node_id,
            status="no_active_token",
            message="node has no active token",
        )

    if not isinstance(node, dict):
        raise NodesTokenError(
            "invalid_config",
            "node entry must be a JSON object",
            details={"node_id": node_id},
        )

    tokens = node.get("tokens", [])
    if not isinstance(tokens, list):
        raise NodesTokenError(
            "invalid_config",
            "node token list must be a list",
            details={"node_id": node_id},
        )

    active = None
    for entry in tokens:
        if isinstance(entry, dict) and entry.get("revoked_at") is None:
            active = entry
            break

    if active is None:
        return NodesTokenRotateAndRevokeResult(
            ok=True,
            action="revoke",
            node_id=node_id,
            status="no_active_token",
            message="no active token to revoke",
        )

    ts = _now_iso(now)
    active["revoked_at"] = ts
    active["revoked_reason"] = "revoked"

    state["version"] = 1
    store.save(state)

    return NodesTokenRotateAndRevokeResult(
        ok=True,
        action="revoke",
        node_id=node_id,
        status="revoked",
        message="token revoked",
    )


def execute(
    request: NodesTokenRotateAndRevokeRequest | Mapping[str, Any],
    *,
    store_path: Path | None = None,
    now: datetime | None = None,
) -> NodesTokenRotateAndRevokeResult:
    """Dispatch helper used by servers/CLIs.

    Accepts either a strongly-typed request or a plain mapping (e.g. decoded JSON).
    """

    if isinstance(request, Mapping):
        action = request.get("action")
        node_id = request.get("node_id")

        if action not in ("rotate", "revoke") or not isinstance(node_id, str):
            raise NodesTokenError("invalid_request", "request must include 'action' and 'node_id'")

        typed = NodesTokenRotateAndRevokeRequest(action=action, node_id=node_id, store_path=None)
    else:
        typed = request

    path = store_path or typed.store_path

    if typed.action == "rotate":
        return rotate_node_token(typed.node_id, store_path=path, now=now)
    return revoke_node_token(typed.node_id, store_path=path, now=now)


def run(payload: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Legacy-friendly wrapper that returns JSON-safe types.

    This wrapper never raises NodesTokenError; it converts it to a structured error payload.
    """

    action = payload.get("action")
    node_id = payload.get("node_id")

    # Best-effort coercion for error payload.
    action_str: TokenAction = action if action in ("rotate", "revoke") else "rotate"
    node_id_str = node_id if isinstance(node_id, str) else ""

    try:
        return execute(payload, **kwargs).to_dict()
    except NodesTokenError as e:
        return NodesTokenRotateAndRevokeResult(
            ok=False,
            action=action_str,
            node_id=node_id_str,
            status="error",
            message=e.message,
            error=e.to_dict(),
        ).to_dict()


async def aiohttp_handler(request: Any) -> Any:
    """Optional aiohttp handler.

    This is intentionally tiny:
    - parse JSON
    - dispatch via execute()
    - return JSON response
    """

    from aiohttp import web

    try:
        payload = await request.json()
    except (json.JSONDecodeError, ValueError, KeyError) as e:  # noqa: BLE001
        err = NodesTokenError("invalid_request", "request body must be JSON", details={"error": str(e)})
        return web.json_response({"ok": False, "error": err.to_dict()}, status=err.http_status)

    # Best-effort: allow a server to inject a store path via app state.
    store_path = None
    try:
        app = getattr(request, "app", None)
        if isinstance(app, dict):
            candidate = app.get("nodes_tokens_path") or app.get(ENV_STORE_PATH)
            if isinstance(candidate, (str, Path)):
                store_path = Path(candidate)
    except (json.JSONDecodeError, ValueError, KeyError):
        store_path = None

    try:
        result = execute(payload, store_path=store_path)
        return web.json_response(result.to_dict(), status=200)
    except NodesTokenError as e:
        return web.json_response({"ok": False, "error": e.to_dict()}, status=e.http_status)


def __getattr__(name: str) -> Any:
    """Compatibility shims for dynamic importers."""

    if name in {"handler", "handle", "main"}:
        return execute
    if name in {"aiohttp", "handle_aiohttp", "route"}:
        return aiohttp_handler
    raise AttributeError(name)
