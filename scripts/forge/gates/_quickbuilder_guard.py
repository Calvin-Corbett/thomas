"""QuickBuilder mode — signed-flag validator + suppressible-gate policy.

QuickBuilder is a human-activated build mode that relaxes the *workflow /
coordination / location* gates (am-I-in-the-right-worktree, did-I-claim-this,
is-the-tree-dirty, workboard bookkeeping) and the breakglass cooldown, while
keeping every *code-engineering and security* gate fully enforced (tests, ruff,
enforcement-integrity, the secret-scan, exception-handler, type-safety,
architecture, monolith, protected-files, etc.).

It is activated only via ``scripts/quickbuilder_toggle.py on`` which requires a
Windows credential (Hello) prompt, and writes an HMAC-signed flag at
``runtime/.quickbuilder_mode`` signed with the per-install key at
``runtime/.quickbuilder_key``. This validator recomputes the signature, so a
forged or unsigned flag is ignored — an agent cannot self-activate the mode by
planting a file. Mirrors the proven ``_runtime_guard`` pattern; stdlib-only so
gate scripts can import it in a minimal CI environment.

Fail-closed: any IO/parse/signature/missing-key/repo-mismatch error returns
False (QuickBuilder is NOT considered active, so every gate runs normally).

Allowlist semantics: ``should_suppress`` only ever returns True for a hook that
is BOTH (a) listed in SUPPRESSIBLE_HOOKS and (b) under an active, validly signed
flag. A gate whose id is not in the list can never be suppressed, even if it
calls this helper -- so the code-engineering / security spine is structurally
un-suppressible.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path

_FLAG_REL = "runtime/.quickbuilder_mode"
_KEY_REL = "runtime/.quickbuilder_key"
_FLAG_VERSION = 1

# Workflow / coordination / location / ergonomics gates that QuickBuilder may
# suppress. NOTHING that checks code correctness, tests, security, secrets, or
# tamper-resistance belongs here. Adding a gate here is a deliberate, reviewed
# decision (this file is integrity-protected).
SUPPRESSIBLE_HOOKS: frozenset[str] = frozenset(
    {
        "thomas-worktree-branch-guard",
        "thomas-worktree-rules-gate",
        "thomas-workboard-claims-gate",
        "thomas-workboard-agent-claim-gate",
        "thomas-workboard-changed-files-gate",
        "thomas-workboard-task-problems-gate",
        "thomas-plan-structure-gate",
        "thomas-merge-readiness",
    }
)
# NOTE: the workboard INBOX gates are deliberately NOT suppressible -- inbound
# agent coordination must surface even in a fast solo build, so a QuickBuilder
# session can't accidentally bulldoze another agent's blocker message.


def _signing_payload(version: int, issued_at: str, issued_by: str, repo: str) -> bytes:
    """Canonical signed byte string. Order matches the toggle byte-for-byte."""
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


def quickbuilder_active(repo_root: str | os.PathLike[str]) -> bool:
    """True iff a *validly signed* QuickBuilder flag is present for ``repo_root``."""
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


def should_suppress(hook_id: str, repo_root: str | os.PathLike[str]) -> bool:
    """True iff ``hook_id`` is suppressible AND QuickBuilder is validly active."""
    if hook_id not in SUPPRESSIBLE_HOOKS:
        return False
    return quickbuilder_active(repo_root)


def announce_suppressed(hook_id: str, repo_root: str | os.PathLike[str], label: str) -> bool:
    """Gate convenience: if QuickBuilder suppresses ``hook_id``, print a SKIP
    line and return True (the caller should then ``return 0``); else False."""
    if should_suppress(hook_id, repo_root):
        print(f"{label}: SKIP (QuickBuilder mode)")
        return True
    return False
