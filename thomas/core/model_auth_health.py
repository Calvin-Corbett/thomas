"""Model-credential health -- so Thomas can say when he is actually broken.

The health endpoint reported ``degraded: []`` -- "everything is fine" -- while
every single chat turn was failing with ``Token refresh failed with HTTP 401``.
Health was computed purely from boot-time feature flags, so a credential that
died *after* startup was invisible. The person using Thomas found out by sending
a message and being told to "choose another model", which could never have
helped: an expired sign-in takes out every model at once.

This closes that gap from two directions:

* **Passive** -- the chat path reports an auth failure here, so the very first
  401 is remembered and surfaced instead of being rediscovered per message.
* **Local** -- the stored credential is inspected without any network call, so
  a missing or malformed credential is reported before a turn is even attempted.

Deliberately no network probe on the health path: health must stay cheap and
must never hang on the provider being slow.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

APP_MODEL_AUTH_STATE = "model_auth_state"

# Substrings that mean "the credential was rejected", not "the model misbehaved".
_AUTH_FAILURE_MARKERS = (
    "token refresh failed",
    "invalid_grant",
    "http 401",
    "status 401",
    "unauthorized",
)

_PROBE_FAULTS = (OSError, ValueError, TypeError, KeyError, AttributeError)

SIGN_IN_REMEDY = "Run `codex login` in a terminal to sign in again."


def looks_like_auth_failure(detail: str | None) -> bool:
    """True when an error message indicates a rejected credential."""
    text = str(detail or "").strip().lower()
    return any(marker in text for marker in _AUTH_FAILURE_MARKERS)


# Process-level fallback. The code that first sees a rejected credential (the
# orchestrator brain) has no handle on the aiohttp app, so it records here and
# the health endpoint reads it back.
_LAST_AUTH_FAILURE: dict[str, Any] | None = None


def record_auth_failure(app: Any = None, detail: str = "") -> None:
    """Remember that the provider rejected our credential."""
    global _LAST_AUTH_FAILURE
    state = {"ok": False, "detail": str(detail)[:300], "remedy": SIGN_IN_REMEDY}
    _LAST_AUTH_FAILURE = state
    if app is None:
        return
    try:
        app[APP_MODEL_AUTH_STATE] = state
    except _PROBE_FAULTS as exc:  # pragma: no cover - defensive
        log.debug("could not record model auth failure: %s", exc)


def record_auth_success(app: Any = None) -> None:
    """Clear a previously recorded failure after a successful call."""
    global _LAST_AUTH_FAILURE
    _LAST_AUTH_FAILURE = None
    if app is None:
        return
    try:
        app[APP_MODEL_AUTH_STATE] = {"ok": True}
    except _PROBE_FAULTS as exc:  # pragma: no cover - defensive
        log.debug("could not record model auth success: %s", exc)


def _credential_path() -> Path:
    configured = str(os.environ.get("CODEX_HOME", "") or "").strip()
    root = Path(configured).expanduser() if configured else Path.home() / ".codex"
    return root / "auth.json"


def inspect_stored_credential() -> dict[str, Any]:
    """Inspect the stored credential locally. Never makes a network call."""
    import json

    path = _credential_path()
    try:
        if not path.exists():
            return {"present": False, "reason": "no stored sign-in"}
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (*_PROBE_FAULTS, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"present": False, "reason": f"stored sign-in unreadable: {exc}"}

    tokens = raw.get("tokens") if isinstance(raw.get("tokens"), dict) else {}
    has_refresh = bool(raw.get("refresh_token") or tokens.get("refresh_token"))
    has_access = bool(raw.get("access_token") or tokens.get("access_token"))
    has_api_key = bool(raw.get("OPENAI_API_KEY"))

    return {
        "present": bool(has_refresh or has_access or has_api_key),
        "auth_mode": str(raw.get("auth_mode") or ""),
        "has_refresh_token": has_refresh,
        "has_api_key_fallback": has_api_key,
        "last_refresh": str(raw.get("last_refresh") or ""),
    }


def model_auth_health(app: Any) -> dict[str, Any]:
    """Health summary for the model credential.

    ``ok=False`` means chat is known to be broken and the message says why, in
    words someone who does not read logs can act on.
    """
    stored = inspect_stored_credential()

    observed: dict[str, Any] = {}
    try:
        observed = (app.get(APP_MODEL_AUTH_STATE) if app is not None else None) or {}
    except _PROBE_FAULTS:  # pragma: no cover - defensive
        observed = {}
    if not observed and _LAST_AUTH_FAILURE is not None:
        observed = _LAST_AUTH_FAILURE

    if observed.get("ok") is False:
        return {
            "ok": False,
            "reason": "Your ChatGPT sign-in was rejected, so no model can be reached.",
            "remedy": SIGN_IN_REMEDY,
            "stored_credential": stored,
        }

    if not stored.get("present"):
        return {
            "ok": False,
            "reason": f"No usable model sign-in found ({stored.get('reason') or 'missing'}).",
            "remedy": SIGN_IN_REMEDY,
            "stored_credential": stored,
        }

    if not stored.get("has_refresh_token") and not stored.get("has_api_key_fallback"):
        return {
            "ok": False,
            "reason": "The stored sign-in cannot be refreshed and there is no API key fallback.",
            "remedy": SIGN_IN_REMEDY,
            "stored_credential": stored,
        }

    return {"ok": True, "stored_credential": stored}
