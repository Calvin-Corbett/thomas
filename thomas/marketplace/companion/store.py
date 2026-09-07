"""Per-module persistent storage for companion modules.

Every companion module gets one namespaced key/value document under the
kernel's ``data/`` directory. A module can only ever reach its own namespace:
callers address the store by ``module_id`` and the store derives the file path
itself, so a module never supplies a path.

Permission enforcement lives in the route layer, which knows the registry.
This module is deliberately dumb persistence — it validates shape and quota,
nothing else.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .kernel import CompanionKernel

SCHEMA_VERSION = 1

DEFAULT_MAX_BYTES = 1_048_576
DEFAULT_MAX_KEYS = 512
MAX_KEY_LENGTH = 128

_MODULE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,63}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class ModuleStoreError(RuntimeError):
    """Raised when a store operation is rejected."""


class ModuleStoreQuotaError(ModuleStoreError):
    """Raised when a write would push a module past its quota."""


@dataclass(frozen=True)
class StoreQuota:
    """Per-module storage ceiling."""

    max_bytes: int = DEFAULT_MAX_BYTES
    max_keys: int = DEFAULT_MAX_KEYS

    def to_dict(self) -> dict[str, int]:
        return {"max_bytes": int(self.max_bytes), "max_keys": int(self.max_keys)}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def validate_module_id(module_id: str) -> str:
    # Matches contracts._validate_module_id exactly. Do NOT normalise case here:
    # folding "Fit" onto "fit" would let two spellings share one namespace while
    # the contract layer accepts only one of them.
    text = str(module_id or "").strip()
    if not _MODULE_ID_RE.match(text):
        raise ModuleStoreError("module_id must match ^[a-z0-9][a-z0-9_.-]{2,63}$")
    if text in {".", ".."} or "/" in text or "\\" in text:
        raise ModuleStoreError("module_id must not contain path separators")
    return text


def validate_key(key: str) -> str:
    text = str(key or "").strip()
    if not _KEY_RE.match(text):
        raise ModuleStoreError(
            "key must be 1-128 chars of [A-Za-z0-9_.:-] and start alphanumeric"
        )
    return text


def _json_safe(value: Any, *, field: str = "value") -> Any:
    """Reject values json cannot round-trip before they reach disk."""
    try:
        encoded = json.dumps(value, ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ModuleStoreError(f"{field} must be JSON-serializable: {exc}") from exc
    return json.loads(encoded)


class ModuleStore:
    """Namespaced key/value persistence, one document per module."""

    def __init__(self, kernel: CompanionKernel, *, quota: StoreQuota | None = None):
        self.kernel = kernel
        self.quota = quota or StoreQuota()

    # ── paths ────────────────────────────────────────────────────────────

    def _document_path(self, module_id: str) -> Path:
        safe_id = validate_module_id(module_id)
        return self.kernel.paths.data_dir / f"{safe_id}.json"

    def _empty_document(self, module_id: str) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "module_id": module_id,
            "updated_at": _now_iso(),
            "entries": {},
        }

    # ── io ───────────────────────────────────────────────────────────────

    def _read(self, module_id: str) -> dict[str, Any]:
        safe_id = validate_module_id(module_id)
        path = self._document_path(safe_id)
        if not path.exists():
            return self._empty_document(safe_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return self._empty_document(safe_id)
        if not isinstance(payload, dict):
            return self._empty_document(safe_id)
        entries = payload.get("entries")
        if not isinstance(entries, dict):
            payload["entries"] = {}
        return payload

    def _write(self, module_id: str, document: dict[str, Any]) -> None:
        safe_id = validate_module_id(module_id)
        self.kernel.paths.data_dir.mkdir(parents=True, exist_ok=True)
        document["schema_version"] = SCHEMA_VERSION
        document["module_id"] = safe_id
        document["updated_at"] = _now_iso()

        entries = document.get("entries") or {}
        if len(entries) > self.quota.max_keys:
            raise ModuleStoreQuotaError(
                f"module {safe_id} exceeds max_keys ({len(entries)} > {self.quota.max_keys})"
            )
        blob = json.dumps(document, indent=2, ensure_ascii=True) + "\n"
        size = len(blob.encode("utf-8"))
        if size > self.quota.max_bytes:
            raise ModuleStoreQuotaError(
                f"module {safe_id} exceeds max_bytes ({size} > {self.quota.max_bytes})"
            )

        path = self._document_path(safe_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(blob, encoding="utf-8")
        os.replace(tmp, path)

    # ── public api ───────────────────────────────────────────────────────

    def get(self, module_id: str, key: str, default: Any = None) -> Any:
        safe_key = validate_key(key)
        entries = self._read(module_id).get("entries") or {}
        return entries.get(safe_key, default)

    def set(self, module_id: str, key: str, value: Any) -> dict[str, Any]:
        safe_id = validate_module_id(module_id)
        safe_key = validate_key(key)
        safe_value = _json_safe(value)
        document = self._read(safe_id)
        entries = dict(document.get("entries") or {})
        entries[safe_key] = safe_value
        document["entries"] = entries
        self._write(safe_id, document)
        return {"module_id": safe_id, "key": safe_key, "stored": True}

    def delete(self, module_id: str, key: str) -> bool:
        safe_id = validate_module_id(module_id)
        safe_key = validate_key(key)
        document = self._read(safe_id)
        entries = dict(document.get("entries") or {})
        if safe_key not in entries:
            return False
        entries.pop(safe_key)
        document["entries"] = entries
        self._write(safe_id, document)
        return True

    def keys(self, module_id: str) -> list[str]:
        entries = self._read(module_id).get("entries") or {}
        return sorted(str(k) for k in entries)

    def entries(self, module_id: str) -> dict[str, Any]:
        return dict(self._read(module_id).get("entries") or {})

    def clear(self, module_id: str) -> int:
        """Drop a module's whole namespace. Called on uninstall."""
        safe_id = validate_module_id(module_id)
        path = self._document_path(safe_id)
        if not path.exists():
            return 0
        count = len(self._read(safe_id).get("entries") or {})
        path.unlink()
        return count

    def usage(self, module_id: str) -> dict[str, Any]:
        safe_id = validate_module_id(module_id)
        path = self._document_path(safe_id)
        used_bytes = path.stat().st_size if path.exists() else 0
        entries = self._read(safe_id).get("entries") or {}
        return {
            "module_id": safe_id,
            "used_bytes": int(used_bytes),
            "key_count": len(entries),
            "quota": self.quota.to_dict(),
        }
