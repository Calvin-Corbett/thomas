"""Validation helpers for the canonical Work domain."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlsplit

_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_SECRET_REF = re.compile(r"^secret:[A-Za-z0-9][A-Za-z0-9._:/-]{0,232}$")


class WorkError(RuntimeError):
    """Base class for expected Work-domain failures."""


class WorkValidationError(WorkError):
    """Raised when untrusted Work input is invalid."""


class WorkNotFoundError(WorkError):
    """Raised when a requested Work resource does not exist."""


class WorkConflictError(WorkError):
    """Raised when a Work mutation conflicts with current state."""


class WorkCorruptStateError(WorkError):
    """Raised when durable Work state cannot be trusted."""


class WorkDependencyUnavailableError(WorkError):
    """Raised when Work cannot delegate to an existing runtime dependency."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    safe_prefix = require_safe_id(prefix, field="id prefix")
    return f"{safe_prefix}-{secrets.token_hex(6)}"


def require_safe_id(value: Any, *, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _SAFE_ID.fullmatch(text):
        raise WorkValidationError(
            f"{field} must start with a lowercase letter or digit and contain only lowercase letters, digits, '.', '_' or '-'"
        )
    return text


def legacy_safe_id(value: Any, *, prefix: str) -> str:
    text = re.sub(r"[^a-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-._")
    if not text or not text[0].isalnum():
        text = f"{prefix}-{secrets.token_hex(4)}"
    return text[:80]


def clean_text(
    value: Any,
    *,
    field: str,
    required: bool = False,
    max_length: int = 4_000,
) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise WorkValidationError(f"{field} is required")
    if len(text) > max_length:
        raise WorkValidationError(f"{field} must be at most {max_length} characters")
    return text


def clean_artifact_reference(value: Any) -> str:
    """Return a browser-safe relative path or explicit HTTP(S) artifact URL."""
    reference = clean_text(value, field="reference", required=True, max_length=2_000)
    if any(ord(char) < 32 or ord(char) == 127 for char in reference) or "\\" in reference:
        raise WorkValidationError("reference contains an invalid character")
    if reference.startswith("//"):
        raise WorkValidationError("reference must not use a protocol-relative URL")
    parsed = urlsplit(reference)
    decoded_path = unquote(parsed.path)
    if "\\" in decoded_path or any(ord(char) < 32 or ord(char) == 127 for char in decoded_path):
        raise WorkValidationError("reference contains an invalid encoded character")
    if ".." in decoded_path.split("/"):
        raise WorkValidationError("reference must not traverse parent paths")
    if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
        raise WorkValidationError("reference must be a relative path or an HTTP(S) URL")
    if parsed.scheme and not parsed.netloc:
        raise WorkValidationError("reference HTTP(S) URL must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise WorkValidationError("reference URL must not contain credentials")
    return reference


def clean_credential_ref(value: Any) -> str:
    """Accept only opaque SecretStore identifiers, never credential material."""
    reference = clean_text(value, field="credential_ref", max_length=240)
    if reference and not _SECRET_REF.fullmatch(reference):
        raise WorkValidationError("credential_ref must be an opaque secret:<name> reference")
    return reference


def clean_public_error(value: Any) -> dict[str, Any]:
    """Reduce an untrusted runtime error to a useful, non-sensitive receipt."""
    if not value:
        return {}
    if not isinstance(value, dict):
        return {"code": "mission_failed", "message": "Mission reported a failure."}
    raw_code = value.get("code") or value.get("type") or value.get("kind") or "mission_failed"
    code_text = re.sub(r"[^a-z0-9._-]+", "_", str(raw_code or "").strip().lower()).strip("._-")
    code = code_text[:80] if code_text and code_text[0].isalnum() else "mission_failed"
    receipt: dict[str, Any] = {"code": code, "message": "Mission reported a failure."}
    if isinstance(value.get("retryable"), bool):
        receipt["retryable"] = value["retryable"]
    return receipt


def clean_string_list(value: Any, *, field: str, limit: int = 64) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise WorkValidationError(f"{field} must be an array")
    if len(value) > limit:
        raise WorkValidationError(f"{field} may contain at most {limit} items")
    out: list[str] = []
    for item in value:
        text = clean_text(item, field=field, max_length=240)
        if text and text not in out:
            out.append(text)
    return out


def clean_json_object(value: Any, *, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise WorkValidationError(f"{field} must be an object")
    return dict(value)
