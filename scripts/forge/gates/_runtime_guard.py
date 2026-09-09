"""Signed-flag validator for the runtime-protection toggle (gate side).

B9 (praxis-unbypassable-2026-05-29): several gates honored the disable flag
``runtime/.runtime_protection_disabled`` by PRESENCE only
(``flag.is_file()``), so an agent that could plant an unsigned file (e.g. via
shell) disabled all of them at once. The flag is only legitimate when it is
HMAC-signed by ``scripts/runtime_protection_toggle.py`` (which itself requires
a Windows credential prompt) using the per-install key in
``runtime/.runtime_protection_key``.

This validator mirrors ``thomas.tools.filesystem._is_runtime_protection_disabled``
but is kept dependency-light (stdlib only) so gate scripts can import it in a
minimal CI environment without pulling in the ``thomas`` package. The two MUST
stay in sync; ``tests/test_runtime_guard_signed_flag.py`` pins the behavior.

Fail-closed: any IO/parse/signature/missing-key/repo-mismatch error returns
False (i.e. protection is NOT considered disabled, so the gate runs normally).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path

_FLAG_REL = "runtime/.runtime_protection_disabled"
_KEY_REL = "runtime/.runtime_protection_key"
_FLAG_VERSION = 1


def _signing_payload(version: int, issued_at: str, issued_by: str, repo: str) -> bytes:
    """Canonical signed byte string. Order matches the toggle + filesystem.py."""
    return f"{int(version)}|{issued_at}|{issued_by}|{repo}".encode()


def _load_key(root: Path) -> bytes | None:
    try:
        raw = (root / _KEY_REL).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        return None
    return key or None


def runtime_protection_disabled(repo_root: str | os.PathLike[str]) -> bool:
    """True iff a *validly signed* disable flag is present for ``repo_root``."""
    root = Path(repo_root).resolve()
    flag = root / _FLAG_REL
    if not flag.is_file():
        return False
    try:
        doc = json.loads(flag.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(doc, dict):
        return False
    try:
        version = int(doc.get("version", 0))
    except (TypeError, ValueError):
        return False
    if version != _FLAG_VERSION:
        return False

    issued_at = str(doc.get("issued_at") or "")
    issued_by = str(doc.get("issued_by") or "")
    repo = str(doc.get("repo") or "")
    signature_hex = str(doc.get("signature") or "")
    if not issued_at or not issued_by or not repo or not signature_hex:
        return False

    expected_repo = str(root)
    if os.name == "nt":
        if repo.lower() != expected_repo.lower():
            return False
    elif repo != expected_repo:
        return False

    key = _load_key(root)
    if key is None:
        return False
    try:
        signature = bytes.fromhex(signature_hex)
    except ValueError:
        return False
    expected = hmac.new(key, _signing_payload(version, issued_at, issued_by, repo), hashlib.sha256).digest()
    return hmac.compare_digest(expected, signature)
