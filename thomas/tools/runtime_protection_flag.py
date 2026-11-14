"""Runtime-protection toggle flag: signed disable flag and its break-glass window.

Moved out of ``thomas/tools/filesystem.py`` (which re-exports every name) to keep
that file under the 800-line limit. Behaviour is unchanged: the flag is signed by
``scripts/runtime_protection_toggle.py`` and every failure here keeps protection on.
"""

from __future__ import annotations

import datetime as _dt
import hmac
import json
import logging
import os
from hashlib import sha256
from pathlib import Path

log = logging.getLogger("thomas.tools.filesystem")


# ---------------------------------------------------------------------------
# Runtime-protection toggle flag — signed-content validation.
#
# The flag file is created by ``scripts/runtime_protection_toggle.py`` after
# a successful Windows credential prompt.  The toggle script writes a JSON
# document signed with HMAC-SHA256 using a per-install key that lives in
# ``runtime/.runtime_protection_key`` (also a protected file).  Validation
# is fail-closed: any parse, IO, or signature error means the flag is
# treated as absent and runtime protection stays on.
#
# This is defense-in-depth on top of the path protection above.  Path
# protection alone blocks ``fs.write_file`` / ``diff.create`` /
# ``diff.apply_patch`` from writing either file.  Signature validation
# additionally rejects forged flags that might slip through some other
# future write path (e.g. an enabled ``shell.exec``).
# ---------------------------------------------------------------------------
_RUNTIME_FLAG_REL = "runtime/.runtime_protection_disabled"
_RUNTIME_KEY_REL = "runtime/.runtime_protection_key"
_RUNTIME_FLAG_VERSION = 1
_GREEN_EVOLVE_RUNTIME_WRITES_ENV = "THOMAS_EVOLVE_GREEN_RUNTIME_WRITES"


def _runtime_signing_payload(version: int, issued_at: str, issued_by: str, repo: str) -> bytes:
    """Canonical byte string signed by the toggle script.  Order matters."""
    return f"{int(version)}|{issued_at}|{issued_by}|{repo}".encode()


def _load_runtime_protection_key(sandbox_root: Path) -> bytes | None:
    key_file = sandbox_root / _RUNTIME_KEY_REL
    try:
        raw = key_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        return None
    return key or None


# Break-glass is a window, not a state. A signature proves a human authorised the
# disable; it does not prove they still mean it days later. Found live 2026-09-08:
# a flag issued two days earlier was still switching off fourteen gates, each
# printing "PASS (runtime protection disabled by human)" and exiting 0.
#
# `expires_at` is NOT part of the signed payload, so it may only ever SHORTEN the
# window; the age limit applies regardless. Anything unparseable fails closed,
# which for this module means protection stays ON.
_MAX_DISABLE_HOURS = 8.0


def _within_disable_window(doc: object) -> bool:
    """Whether a signed flag is still inside its break-glass window."""
    if not isinstance(doc, dict):
        return False
    raw_issued = str(doc.get("issued_at") or "").strip()
    if not raw_issued:
        return False
    try:
        issued = _dt.datetime.fromisoformat(raw_issued.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=_dt.UTC)
    now = _dt.datetime.now(_dt.UTC)
    if (now - issued) > _dt.timedelta(hours=_MAX_DISABLE_HOURS):
        return False
    raw_expires = str(doc.get("expires_at") or "").strip()
    if raw_expires:
        try:
            expires = _dt.datetime.fromisoformat(raw_expires.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return False
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=_dt.UTC)
        if now >= expires:
            return False
    return True


def _is_runtime_protection_disabled(sandbox_root: Path) -> bool:
    """Return True iff a *validly signed* disable-flag is present.

    The flag is signed by ``scripts/runtime_protection_toggle.py`` after a
    successful Windows credential prompt.  This function never prompts —
    it only verifies the signature against the per-install HMAC key.

    Fail-closed: any IO error, parse error, missing key, missing/invalid
    signature, or sandbox-root mismatch returns False (protection stays on).
    """
    resolved_root = sandbox_root.resolve()
    flag_file = resolved_root / _RUNTIME_FLAG_REL
    if not flag_file.is_file():
        return False

    try:
        raw = flag_file.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("runtime-protection flag unreadable; treating as absent: %s", exc)
        return False

    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("runtime-protection flag is not valid JSON; ignoring: %s", exc)
        return False
    if not isinstance(doc, dict):
        log.warning("runtime-protection flag root is not an object; ignoring")
        return False

    try:
        version = int(doc.get("version", 0))
    except (TypeError, ValueError):
        version = 0
    if version != _RUNTIME_FLAG_VERSION:
        log.warning("runtime-protection flag version %r unsupported; ignoring", doc.get("version"))
        return False

    issued_at = str(doc.get("issued_at") or "")
    issued_by = str(doc.get("issued_by") or "")
    repo = str(doc.get("repo") or "")
    signature_hex = str(doc.get("signature") or "")
    if not issued_at or not issued_by or not repo or not signature_hex:
        log.warning("runtime-protection flag missing required fields; ignoring")
        return False

    expected_repo = str(resolved_root)
    # Compare resolved paths case-insensitively on Windows.
    if os.name == "nt":
        if repo.lower() != expected_repo.lower():
            log.warning(
                "runtime-protection flag repo mismatch (flag=%r, sandbox=%r); ignoring",
                repo,
                expected_repo,
            )
            return False
    elif repo != expected_repo:
        log.warning(
            "runtime-protection flag repo mismatch (flag=%r, sandbox=%r); ignoring",
            repo,
            expected_repo,
        )
        return False

    key = _load_runtime_protection_key(resolved_root)
    if key is None:
        log.warning("runtime-protection signing key missing/invalid; ignoring flag")
        return False

    try:
        signature = bytes.fromhex(signature_hex)
    except ValueError:
        log.warning("runtime-protection flag signature is not hex; ignoring")
        return False

    expected = hmac.new(
        key,
        _runtime_signing_payload(version, issued_at, issued_by, repo),
        sha256,
    ).digest()
    if not hmac.compare_digest(expected, signature):
        log.warning("runtime-protection flag signature mismatch; ignoring")
        return False

    # A valid signature says a human authorised this. The window says they still mean it.
    if not _within_disable_window(doc):
        log.warning("runtime-protection flag is outside its break-glass window; protection stays on")
        return False
    return True


def _green_evolve_runtime_writes_enabled(sandbox_root: Path) -> bool:
    raw = str(os.environ.get(_GREEN_EVOLVE_RUNTIME_WRITES_ENV) or "").strip().lower()
    if raw not in {"1", "true", "yes", "on"}:
        return False
    try:
        root = sandbox_root.resolve()
    except OSError:
        return False
    return root.name == "green" and root.parent.name == "doppelganger" and root.parent.parent.name == "runtime"
