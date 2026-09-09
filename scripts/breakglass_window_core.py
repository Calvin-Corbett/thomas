"""Approval *window* for the breakglass Windows-Hello tap (a sudo-style timestamp).

Scope: this affects ONLY ``scripts.breakglass_auth.authorize_breakglass`` -- the
human-presence (Windows sign-in / Windows Hello) check. When a valid window is
active, that one gate returns "authorized" without re-prompting, so a human who
just proved presence does not have to tap again for every protected action for
the next few hours. It does NOT relax any other gate (secret scan, integrity,
tests, worktree rules, etc. all still run exactly as before). It is a switch for
THIS gate only.

Opt-in + human-gated: nothing exists until a human runs
``scripts/breakglass_window.py on`` (default 3h), which itself requires a real
Windows sign-in to mint the token. No tap, no window.

Storage (both under ``runtime/`` which is gitignored):
    runtime/.breakglass_window        signed JSON token
    runtime/.breakglass_window_key    per-install HMAC-SHA256 key (minted fresh
                                      each activation, like runtime_protection)

A window is valid only when ALL hold (fail-closed -- any error => not active):
    * the HMAC signature verifies against the per-install key,
    * the recorded repo matches this repo,
    * the recorded actor matches the current Windows user, and
    * the current time is strictly before ``expires_at_epoch``.

Forgery resistance (same bar as the breakglass auth it gates): the token + key
are in the hardcoded protected-file list (``thomas/tools/filesystem.py``), so
agent file tools refuse to write them, and ``shell.exec`` is off by default with
shell-writes caught by rules_of_road. An agent therefore has no path to mint or
extend a window -- only a real human Windows sign-in (which mints the key) opens
one, and the signature + actor + hard expiry stop cross-user or stale reuse. The
only actor who can still write these files is a human at the OS itself (the
machine owner), which is the authorized party, not a threat.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

TOKEN_REL = "runtime/.breakglass_window"
KEY_REL = "runtime/.breakglass_window_key"
WINDOW_VERSION = 1

# Default and hard ceiling for the window length. 3h is the friendly default;
# the ceiling keeps "I tapped once this morning" from meaning "no human check
# for a whole day" on a machine that might be left unlocked. Bump MAX only with
# a clear reason -- a longer no-tap window is a bigger blast radius if the
# session is hijacked.
DEFAULT_WINDOW_HOURS = 3.0
MAX_WINDOW_HOURS = 12.0


def _token_path(root: Path) -> Path:
    return Path(root) / TOKEN_REL


def _key_path(root: Path) -> Path:
    return Path(root) / KEY_REL


def _signing_payload(version: int, issued_at: str, actor: str, expires_at_epoch: int, repo: str) -> bytes:
    """Canonical signed byte string. Writer and validator MUST agree byte-for-byte."""
    return f"{int(version)}|{issued_at}|{actor}|{int(expires_at_epoch)}|{repo}".encode()


def _norm_actor(actor: str) -> str:
    return " ".join(str(actor or "").split()).strip().lower()


def _load_key(root: Path) -> bytes | None:
    try:
        raw = _key_path(root).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        return None
    return key or None


def active_window(repo_root: str | os.PathLike[str], current_actor: str) -> dict | None:
    """Return the token dict iff a valid, unexpired, actor-matching window exists.

    Fail-closed: returns ``None`` on any missing/parse/signature/expiry/mismatch
    condition, so the caller falls back to the normal Windows prompt.
    """
    root = Path(repo_root).resolve()
    token = _token_path(root)
    if not token.is_file():
        return None
    try:
        doc = json.loads(token.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    try:
        version = int(doc.get("version", 0))
        expires_at_epoch = int(doc.get("expires_at_epoch", 0))
    except (TypeError, ValueError):
        return None
    if version != WINDOW_VERSION or expires_at_epoch <= 0:
        return None

    issued_at = str(doc.get("issued_at") or "")
    actor = str(doc.get("actor") or "")
    repo = str(doc.get("repo") or "")
    signature_hex = str(doc.get("signature") or "")
    if not issued_at or not actor or not repo or not signature_hex:
        return None

    expected_repo = str(root)
    if os.name == "nt":
        if repo.lower() != expected_repo.lower():
            return None
    elif repo != expected_repo:
        return None

    if _norm_actor(actor) != _norm_actor(current_actor):
        return None

    if time.time() >= expires_at_epoch:
        return None

    key = _load_key(root)
    if key is None:
        return None
    try:
        signature = bytes.fromhex(signature_hex)
    except ValueError:
        return None
    expected = hmac.new(
        key,
        _signing_payload(version, issued_at, actor, expires_at_epoch, repo),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(expected, signature):
        return None
    return doc


def clamp_hours(hours: float | int | str | None) -> float:
    """Coerce a requested window length into (0, MAX_WINDOW_HOURS]."""
    try:
        value = float(hours)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_HOURS
    if value <= 0:
        return DEFAULT_WINDOW_HOURS
    return min(value, MAX_WINDOW_HOURS)


def mint_window(repo_root: str | os.PathLike[str], actor: str, hours: float | int | str | None) -> dict:
    """Mint a fresh key + signed token granting a window of ``hours`` for ``actor``.

    Callers MUST have just verified the human (Windows sign-in) before calling
    this -- minting is what turns a single real tap into a time-boxed window.
    """
    root = Path(repo_root).resolve()
    window_hours = clamp_hours(hours)

    key_file = _key_path(root)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    key_file.write_text(key.hex() + "\n", encoding="utf-8")
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass

    now = time.time()
    expires = now + window_hours * 3600.0
    issued_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    expires_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires))
    repo = str(root)
    signature = hmac.new(
        key,
        _signing_payload(WINDOW_VERSION, issued_at, actor, int(expires), repo),
        hashlib.sha256,
    ).hexdigest()

    doc = {
        "version": WINDOW_VERSION,
        "issued_at": issued_at,
        "actor": actor,
        "expires_at": expires_at,
        "expires_at_epoch": int(expires),
        "hours": window_hours,
        "repo": repo,
        "signature": signature,
        "note": "breakglass approval window; revoke with: python scripts/breakglass_window.py off",
    }
    token_file = _token_path(root)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(token_file, 0o600)
    except OSError:
        pass
    return doc


def clear_window(repo_root: str | os.PathLike[str]) -> bool:
    """Revoke any window by removing the token + key. Returns True if anything was removed."""
    root = Path(repo_root).resolve()
    removed = False
    for path in (_token_path(root), _key_path(root)):
        try:
            if path.exists():
                path.unlink()
                removed = True
        except OSError:
            pass
    return removed


def window_status(repo_root: str | os.PathLike[str], current_actor: str) -> dict:
    """Human-readable status used by the CLI's ``status`` command."""
    root = Path(repo_root).resolve()
    doc = active_window(root, current_actor)
    if doc is not None:
        remaining = max(0, int(doc.get("expires_at_epoch", 0) - time.time()))
        return {
            "active": True,
            "actor": str(doc.get("actor") or ""),
            "expires_at": str(doc.get("expires_at") or ""),
            "remaining_seconds": remaining,
            "hours": doc.get("hours"),
        }
    # Distinguish "no token" from "present but invalid/expired" for a clearer message.
    present = _token_path(root).is_file()
    return {"active": False, "token_present": present}
