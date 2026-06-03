"""QuickBuilder mode — signed-flag activation + suppressible-gate policy.

Pins the safety properties:
* QuickBuilder is OFF unless a *validly HMAC-signed* flag is present (a forged or
  unsigned flag is ignored -- an agent cannot self-activate by planting a file).
* Only workflow/coordination/location gates are suppressible; the
  code-engineering and security spine (tests, ruff, enforcement-integrity, the
  secret-scan, exception-handler, protected-files, ...) can NEVER be suppressed.
* A suppressible gate self-skips when QuickBuilder is active; a non-suppressible
  one does not.
"""

from __future__ import annotations

import hmac
import importlib
import json
import secrets
import sys
from hashlib import sha256
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

qb = importlib.import_module("forge.gates._quickbuilder_guard")


def _activate(root: Path, *, sign: bool = True, with_key: bool = True) -> None:
    """Write a QuickBuilder flag at ``root`` (validly signed unless told not to)."""
    runtime = root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    if with_key:
        (runtime / ".quickbuilder_key").write_text(key.hex() + "\n", encoding="utf-8")
    issued_at = "2026-06-03T00:00:00Z"
    issued_by = "tester"
    repo_str = str(root.resolve())
    payload = f"1|{issued_at}|{issued_by}|{repo_str}".encode()
    signature = hmac.new(key, payload, sha256).hexdigest() if sign else "deadbeef"
    doc = {
        "version": 1,
        "issued_at": issued_at,
        "issued_by": issued_by,
        "repo": repo_str,
        "signature": signature,
    }
    (runtime / ".quickbuilder_mode").write_text(json.dumps(doc), encoding="utf-8")


def test_inactive_by_default(tmp_path) -> None:
    assert qb.quickbuilder_active(tmp_path) is False
    assert qb.should_suppress("thomas-worktree-branch-guard", tmp_path) is False


def test_active_with_validly_signed_flag(tmp_path) -> None:
    _activate(tmp_path)
    assert qb.quickbuilder_active(tmp_path) is True
    assert qb.should_suppress("thomas-worktree-branch-guard", tmp_path) is True


def test_forged_flag_is_ignored(tmp_path) -> None:
    _activate(tmp_path, sign=False)  # wrong signature
    assert qb.quickbuilder_active(tmp_path) is False
    assert qb.should_suppress("thomas-merge-readiness", tmp_path) is False


def test_flag_without_key_is_ignored(tmp_path) -> None:
    _activate(tmp_path, with_key=False)  # no signing key on disk
    assert qb.quickbuilder_active(tmp_path) is False


def test_security_and_engineering_gates_are_never_suppressible() -> None:
    # The spine that protects code correctness, secrets, and tamper-resistance
    # must NOT be in the suppressible allowlist.
    for critical in (
        "thomas-enforcement-integrity",
        "thomas-publish-preflight",  # secret scan
        "thomas-protected-files-gate",
        "thomas-protected-deletions-gate",
        "thomas-precommit-skip-policy-gate",
        "thomas-exception-handler-gate",
        "thomas-type-safety-gate",
        "thomas-circular-imports-gate",
        "thomas-monolith-guard",
        "thomas-changelog-gate",
        "thomas-repo-identity-gate",
        "thomas-workboard-inbox-gate",  # coordination must surface
        "thomas-workboard-inbox-final-gate",
    ):
        assert critical not in qb.SUPPRESSIBLE_HOOKS, critical
    # And a non-suppressible hook is never suppressed even when QB is active.


def test_non_suppressible_hook_not_suppressed_even_when_active(tmp_path) -> None:
    _activate(tmp_path)
    assert qb.quickbuilder_active(tmp_path) is True
    assert qb.should_suppress("thomas-enforcement-integrity", tmp_path) is False
    assert qb.should_suppress("thomas-publish-preflight", tmp_path) is False


def test_worktree_branch_guard_self_skips_when_active(tmp_path, monkeypatch, capsys) -> None:
    guard = importlib.import_module("forge.gates.worktree_branch_guard")
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    _activate(tmp_path)
    rc = guard.run([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "QuickBuilder" in out


def test_announce_suppressed_prints_and_returns(tmp_path, capsys) -> None:
    _activate(tmp_path)
    assert qb.announce_suppressed("thomas-merge-readiness", tmp_path, "Merge readiness") is True
    assert "QuickBuilder" in capsys.readouterr().out
    assert qb.announce_suppressed("thomas-enforcement-integrity", tmp_path, "Integrity") is False
