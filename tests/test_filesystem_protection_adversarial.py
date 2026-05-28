"""Adversarial tests for the runtime-protection bypass fix (2026-05-27).

Background: ``thomas/tools/filesystem.py::_is_protected_runtime_path`` blocks
agent writes inside Thomas's runtime tree. The gate honored a flag file at
``runtime/.runtime_protection_disabled``. The flag's path was *not* itself
protected, so an agent could call ``fs.write_file('runtime/.runtime_protection_disabled', '')``
and disable all runtime protection. The OS-auth promise in
``docs/SAFETY_ARCHITECTURE.md`` was fiction for any agent that noticed.

This file pins the post-fix behavior:

1. ``fs.write_file`` cannot create or modify either runtime-protection file.
2. A flag with forged/empty/missing-signature content is treated as absent —
   protection stays on (fail-closed).
3. The legitimate signing payload (mirroring what ``runtime_protection_toggle.py``
   produces after Windows auth) is honored.
4. The new ``fs.write_protected_file`` tool refuses without native-auth
   approval and allows the write when approved.
5. The ``runtime_protection_toggle.py`` end-to-end path (auth → signed flag
   → validator accepts) is unbroken.
"""

from __future__ import annotations

import asyncio
import hmac
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from thomas.tools.base import ToolResult
from thomas.tools.filesystem import (
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
    WriteProtectedFileTool,
    _is_protected_runtime_path,
    _is_read_protected_path,
    _is_runtime_protection_disabled,
    _runtime_signing_payload,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """Sandbox root mimicking the parts of Thomas the gate examines."""
    (tmp_path / "thomas" / "core").mkdir(parents=True)
    (tmp_path / "thomas" / "tools").mkdir(parents=True)
    (tmp_path / "scripts").mkdir(parents=True)
    (tmp_path / "agent_safety.toml").write_text("# stub\n")
    (tmp_path / "src").mkdir()
    return tmp_path


def _flag(sandbox: Path) -> Path:
    return sandbox / "runtime" / ".runtime_protection_disabled"


def _key(sandbox: Path) -> Path:
    return sandbox / "runtime" / ".runtime_protection_key"


def _write_signed_flag(
    sandbox: Path,
    *,
    key: bytes,
    issued_at: str = "2026-05-27T12:00:00Z",
    issued_by: str = "calvin",
    repo: str | None = None,
    version: int = 1,
    extra: dict[str, Any] | None = None,
) -> None:
    """Write a flag that the validator will accept."""
    if repo is None:
        repo = str(sandbox.resolve())
    sig = hmac.new(
        key,
        _runtime_signing_payload(version, issued_at, issued_by, repo),
        sha256,
    ).hexdigest()
    doc: dict[str, Any] = {
        "version": version,
        "issued_at": issued_at,
        "issued_by": issued_by,
        "repo": repo,
        "signature": sig,
    }
    if extra:
        doc.update(extra)
    _flag(sandbox).parent.mkdir(parents=True, exist_ok=True)
    _flag(sandbox).write_text(json.dumps(doc), encoding="utf-8")


def _plant_key(sandbox: Path) -> bytes:
    key = bytes(range(32))  # any 32 bytes; tests only care about consistency
    _key(sandbox).parent.mkdir(parents=True, exist_ok=True)
    _key(sandbox).write_text(key.hex() + "\n", encoding="utf-8")
    return key


def _run(tool, args: dict[str, Any]) -> ToolResult:
    return asyncio.run(tool.execute(args))


# ---------------------------------------------------------------------------
# 1. fs.write_file cannot create or modify either runtime-protection file
# ---------------------------------------------------------------------------


def test_fs_write_file_refused_for_flag_path(sandbox: Path) -> None:
    tool = WriteFileTool(sandbox)
    result = _run(tool, {"path": "runtime/.runtime_protection_disabled", "content": ""})
    assert result.ok is False
    assert result.error is not None
    assert "runtime-protection control file" in result.error
    assert ".runtime_protection_disabled" in result.error
    # The file was NOT created.
    assert not _flag(sandbox).exists()


def test_fs_write_file_refused_for_key_path(sandbox: Path) -> None:
    tool = WriteFileTool(sandbox)
    result = _run(tool, {"path": "runtime/.runtime_protection_key", "content": "00" * 32})
    assert result.ok is False
    assert result.error is not None
    assert "runtime-protection control file" in result.error
    assert not _key(sandbox).exists()


def test_fs_write_file_still_works_for_unprotected_runtime_subpath(sandbox: Path) -> None:
    """The fix must NOT lock down all of runtime/. Only the two specific files."""
    tool = WriteFileTool(sandbox)
    result = _run(tool, {"path": "runtime/agent_logs/job_42.log", "content": "ok"})
    assert result.ok is True
    assert (sandbox / "runtime" / "agent_logs" / "job_42.log").read_text() == "ok"


# ---------------------------------------------------------------------------
# 2. Forged / empty / unsigned flags are ignored (fail-closed)
# ---------------------------------------------------------------------------


def test_empty_flag_does_not_bypass(sandbox: Path) -> None:
    """The exact historical bug: empty flag should not bypass."""
    _flag(sandbox).parent.mkdir(parents=True, exist_ok=True)
    _flag(sandbox).write_text("")
    assert _is_runtime_protection_disabled(sandbox) is False
    # And the gate refuses the protected write.
    reason = _is_protected_runtime_path(sandbox, sandbox / "thomas" / "core" / "_db.py")
    assert reason is not None
    assert "protected runtime" in reason


def test_non_json_flag_does_not_bypass(sandbox: Path) -> None:
    _flag(sandbox).parent.mkdir(parents=True, exist_ok=True)
    _flag(sandbox).write_text("# disabled by attacker\n")
    assert _is_runtime_protection_disabled(sandbox) is False


def test_json_flag_without_signature_does_not_bypass(sandbox: Path) -> None:
    _flag(sandbox).parent.mkdir(parents=True, exist_ok=True)
    _flag(sandbox).write_text(json.dumps({"version": 1, "issued_by": "x"}))
    assert _is_runtime_protection_disabled(sandbox) is False


def test_flag_with_no_key_does_not_bypass(sandbox: Path) -> None:
    """Even a syntactically valid flag is ignored if the key file is missing."""
    # No _plant_key call.
    _write_signed_flag(sandbox, key=b"\x00" * 32)
    assert _is_runtime_protection_disabled(sandbox) is False


def test_flag_with_wrong_signature_does_not_bypass(sandbox: Path) -> None:
    real_key = _plant_key(sandbox)
    # Sign with a DIFFERENT key.
    wrong_key = bytes(b"\xff" * 32)
    assert wrong_key != real_key  # sanity
    _write_signed_flag(sandbox, key=wrong_key)
    assert _is_runtime_protection_disabled(sandbox) is False


def test_flag_with_unsupported_version_does_not_bypass(sandbox: Path) -> None:
    key = _plant_key(sandbox)
    _write_signed_flag(sandbox, key=key, version=99)
    assert _is_runtime_protection_disabled(sandbox) is False


def test_flag_with_mismatched_repo_does_not_bypass(sandbox: Path) -> None:
    """A flag signed for a different repo path must not work in this sandbox."""
    key = _plant_key(sandbox)
    _write_signed_flag(sandbox, key=key, repo="/some/other/repo")
    assert _is_runtime_protection_disabled(sandbox) is False


def test_flag_with_modified_field_after_signing_does_not_bypass(sandbox: Path) -> None:
    """Tampering with issued_by while keeping signature breaks validation."""
    key = _plant_key(sandbox)
    _write_signed_flag(sandbox, key=key, issued_by="calvin")
    doc = json.loads(_flag(sandbox).read_text())
    doc["issued_by"] = "attacker"  # tamper without re-signing
    _flag(sandbox).write_text(json.dumps(doc))
    assert _is_runtime_protection_disabled(sandbox) is False


# ---------------------------------------------------------------------------
# 3. Legitimate signing payload IS honored
# ---------------------------------------------------------------------------


def test_signed_flag_with_matching_key_does_bypass(sandbox: Path) -> None:
    """Mirrors what runtime_protection_toggle.py produces after auth."""
    key = _plant_key(sandbox)
    _write_signed_flag(sandbox, key=key)
    assert _is_runtime_protection_disabled(sandbox) is True
    # And the gate now lets a normally-protected write through.
    assert _is_protected_runtime_path(sandbox, sandbox / "thomas" / "core" / "_db.py") is None


def test_signed_flag_repo_match_is_case_insensitive_on_windows(sandbox: Path) -> None:
    """Windows path comparison must be case-insensitive (C:\\Users vs c:\\users)."""
    import os as _os

    if _os.name != "nt":
        pytest.skip("Windows-only path semantics")
    key = _plant_key(sandbox)
    repo_str = str(sandbox.resolve()).swapcase()
    _write_signed_flag(sandbox, key=key, repo=repo_str)
    assert _is_runtime_protection_disabled(sandbox) is True


# ---------------------------------------------------------------------------
# 4. fs.write_protected_file requires native-auth approval
# ---------------------------------------------------------------------------


def test_write_protected_file_refused_without_auth(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "thomas.tools.native_auth.request_native_authorization",
        lambda action, reason: False,
    )
    tool = WriteProtectedFileTool(sandbox)
    target = "thomas/tools/evil.py"
    result = _run(tool, {"path": target, "content": "x = 1", "reason": "test"})
    assert result.ok is False
    assert result.error is not None
    assert "protected runtime" in result.error
    assert not (sandbox / target).exists()


def test_write_protected_file_allowed_with_auth(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def _approve(action_description: str, reason: str) -> bool:
        captured["action"] = action_description
        captured["reason"] = reason
        return True

    monkeypatch.setattr("thomas.tools.native_auth.request_native_authorization", _approve)

    tool = WriteProtectedFileTool(sandbox)
    target = "thomas/tools/evil.py"
    result = _run(
        tool,
        {
            "path": target,
            "content": "x = 1\n",
            "reason": "Calvin-approved emergency fix",
        },
    )
    assert result.ok is True
    assert (sandbox / target).read_text() == "x = 1\n"
    # Audit content reaches the prompt.
    assert "Calvin-approved emergency fix" in captured["action"]
    assert "thomas/tools/evil.py" in captured["action"]


def test_write_protected_file_requires_reason(sandbox: Path) -> None:
    """An auth prompt without a reason is meaningless; refuse upfront."""
    tool = WriteProtectedFileTool(sandbox)
    result = _run(tool, {"path": "thomas/tools/x.py", "content": "x", "reason": ""})
    assert result.ok is False
    assert result.error is not None
    assert "reason" in result.error


def test_write_protected_file_works_for_unprotected_path_no_prompt(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """For non-protected targets, no auth prompt should fire."""
    calls = {"n": 0}

    def _track(action: str, reason: str) -> bool:
        calls["n"] += 1
        return True

    monkeypatch.setattr("thomas.tools.native_auth.request_native_authorization", _track)

    tool = WriteProtectedFileTool(sandbox)
    result = _run(tool, {"path": "src/regular.py", "content": "ok", "reason": "no-op"})
    assert result.ok is True
    assert calls["n"] == 0


def test_write_protected_file_can_be_used_to_clear_the_flag(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sanity: a Calvin-approved write via the new tool can target the flag
    path (e.g. emergency re-enable after the toggle script broke)."""
    monkeypatch.setattr(
        "thomas.tools.native_auth.request_native_authorization",
        lambda action, reason: True,
    )
    tool = WriteProtectedFileTool(sandbox)
    result = _run(
        tool,
        {
            "path": "runtime/.runtime_protection_disabled",
            "content": "",
            "reason": "emergency re-enable",
        },
    )
    assert result.ok is True
    # An empty payload at the flag path is NOT a valid signed bypass,
    # so protection stays on.
    assert _is_runtime_protection_disabled(sandbox) is False


# ---------------------------------------------------------------------------
# 5. runtime_protection_toggle.py end-to-end happy path still works
# ---------------------------------------------------------------------------


def test_toggle_script_signing_payload_matches_validator(sandbox: Path) -> None:
    """The script's signing payload must byte-match the validator's payload —
    if either drifts, the toggle silently stops working."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    try:
        from runtime_protection_toggle import _signing_payload as script_payload
    finally:
        sys.path.pop(0)

    args = (1, "2026-05-27T12:00:00Z", "calvin", str(sandbox.resolve()))
    assert script_payload(*args) == _runtime_signing_payload(*args)


def test_toggle_script_writes_validator_acceptable_flag(sandbox: Path) -> None:
    """Simulate what cmd_off does after a successful auth: load-or-create key,
    write signed JSON.  The validator must accept it."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    try:
        from runtime_protection_toggle import (
            FLAG_VERSION,
            _flag_path,
            _mint_fresh_key,
            _signing_payload,
        )
    finally:
        sys.path.pop(0)

    import time as _time

    key = _mint_fresh_key(sandbox)
    assert len(key) >= 32  # secrets-grade entropy
    issued_at = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
    issued_by = "calvin"
    repo_str = str(sandbox.resolve())
    sig = hmac.new(
        key,
        _signing_payload(FLAG_VERSION, issued_at, issued_by, repo_str),
        sha256,
    ).hexdigest()
    doc = {
        "version": FLAG_VERSION,
        "issued_at": issued_at,
        "issued_by": issued_by,
        "repo": repo_str,
        "signature": sig,
    }
    _flag_path(sandbox).write_text(json.dumps(doc), encoding="utf-8")

    assert _is_runtime_protection_disabled(sandbox) is True


def test_toggle_script_mints_fresh_key_every_call(sandbox: Path) -> None:
    """Per Codex hardening review msg-20260527214458: the toggle script must
    NOT trust an existing key file across sessions.  Each call to
    `_mint_fresh_key` overwrites the prior key, so any attacker-planted key
    is wiped on the next legitimate toggle."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    try:
        from runtime_protection_toggle import _mint_fresh_key
    finally:
        sys.path.pop(0)

    k1 = _mint_fresh_key(sandbox)
    k2 = _mint_fresh_key(sandbox)
    assert len(k1) >= 32 and len(k2) >= 32
    assert k1 != k2, "fresh key must differ from prior; persistence is the attack"


def test_toggle_script_cmd_on_removes_key_and_flag(sandbox: Path) -> None:
    """cmd_on must scrub both the flag AND the key, so the next 'off' mints
    a fresh key (no stale attacker-controlled key survives an enable cycle)."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    try:
        from runtime_protection_toggle import (
            _flag_path,
            _key_path,
            _mint_fresh_key,
            cmd_on,
        )
    finally:
        sys.path.pop(0)

    # Simulate post-`off` state: key + flag both exist.
    _mint_fresh_key(sandbox)
    _flag_path(sandbox).write_text("{}")
    assert _key_path(sandbox).exists() and _flag_path(sandbox).exists()

    rc = cmd_on(sandbox)
    assert rc == 0
    assert not _key_path(sandbox).exists(), "cmd_on must remove the key"
    assert not _flag_path(sandbox).exists(), "cmd_on must remove the flag"


# ---------------------------------------------------------------------------
# 6. Codex hardening review (msg-20260527214458): control files stay
#    protected even when a valid signed disable flag is in effect.
# ---------------------------------------------------------------------------


def test_fs_write_file_refused_for_key_even_with_active_signed_flag(sandbox: Path) -> None:
    """The historical patch returned None for ALL paths when the disable flag
    was valid — including the key file itself.  An attacker could overwrite
    the key while the flag is active and survive future toggle cycles.  The
    fix: control files are absolutely protected, never bypassed by the flag."""
    key = _plant_key(sandbox)
    _write_signed_flag(sandbox, key=key)
    assert _is_runtime_protection_disabled(sandbox) is True  # flag IS valid

    tool = WriteFileTool(sandbox)
    result = _run(
        tool,
        {"path": "runtime/.runtime_protection_key", "content": "ff" * 32},
    )
    assert result.ok is False
    assert result.error is not None
    assert "runtime-protection control file" in result.error
    # The key was NOT overwritten.
    assert _key(sandbox).read_text().strip() == key.hex()


def test_fs_write_file_refused_for_flag_even_with_active_signed_flag(sandbox: Path) -> None:
    """Same protection for the flag file itself — agents cannot rewrite it
    even when an active signed flag would normally pass writes through."""
    key = _plant_key(sandbox)
    _write_signed_flag(sandbox, key=key, issued_by="calvin")
    original = _flag(sandbox).read_text()

    tool = WriteFileTool(sandbox)
    result = _run(
        tool,
        {"path": "runtime/.runtime_protection_disabled", "content": "{}"},
    )
    assert result.ok is False
    assert "runtime-protection control file" in (result.error or "")
    assert _flag(sandbox).read_text() == original


def test_fs_write_file_to_unprotected_path_still_works_with_active_flag(
    sandbox: Path,
) -> None:
    """Sanity: the new always-protected-control-files block does not break
    the active-flag bypass for ordinary protected paths.  Calvin should
    still be able to do maintenance edits to thomas/core/ when disabled."""
    key = _plant_key(sandbox)
    _write_signed_flag(sandbox, key=key)
    assert _is_runtime_protection_disabled(sandbox) is True

    tool = WriteFileTool(sandbox)
    result = _run(tool, {"path": "thomas/core/maintenance.py", "content": "# work\n"})
    assert result.ok is True


def test_write_protected_file_can_still_reach_control_files_with_auth(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Calvin's per-operation OS-auth override remains a path to emergency-edit
    the control files (e.g. to clear a stuck flag after a toggle-script bug)."""
    monkeypatch.setattr(
        "thomas.tools.native_auth.request_native_authorization",
        lambda action, reason: True,
    )
    tool = WriteProtectedFileTool(sandbox)
    result = _run(
        tool,
        {
            "path": "runtime/.runtime_protection_key",
            "content": ("aa" * 32) + "\n",
            "reason": "emergency key rotation",
        },
    )
    assert result.ok is True
    assert _key(sandbox).read_text().strip() == "aa" * 32


# ---------------------------------------------------------------------------
# 7. Read-side protection on the HMAC key (Codex msg-20260527214458).
# ---------------------------------------------------------------------------


def test_fs_read_file_refused_for_key(sandbox: Path) -> None:
    """The key is a secret.  Reading it would let an attacker mint signatures
    (and write paths exist via shell.exec when Calvin enables it)."""
    _plant_key(sandbox)
    tool = ReadFileTool(sandbox)
    result = _run(tool, {"path": "runtime/.runtime_protection_key"})
    assert result.ok is False
    assert "signing key" in (result.error or "")


def test_fs_read_file_still_works_for_other_paths(sandbox: Path) -> None:
    """Read protection is scoped to the key file only — ordinary reads still
    work.  The disable flag is metadata only (timestamp + sig) and stays
    readable so Calvin can inspect toggle state from anywhere."""
    target = sandbox / "thomas" / "core" / "hello.py"
    target.write_text("print('hi')\n")
    tool = ReadFileTool(sandbox)
    result = _run(tool, {"path": "thomas/core/hello.py"})
    assert result.ok is True
    assert "print" in (result.data or "")


def test_fs_search_skips_key_contents(sandbox: Path) -> None:
    """SearchFilesTool reads file contents; without an exclusion it would
    leak the key's hex bytes on a matching regex.  Confirm the key is
    skipped even when its contents match the search."""
    key = _plant_key(sandbox)
    # Search for the literal key contents.
    tool = SearchFilesTool(sandbox)
    result = _run(
        tool,
        {"pattern": key.hex()[:16], "path": "runtime", "glob": "*"},
    )
    assert result.ok is True
    # The key file's contents must NOT appear in the search output.
    assert key.hex()[:16] not in (result.data or "")


def test_is_read_protected_path_only_covers_key(sandbox: Path) -> None:
    """Lock the scope of read protection — the flag, ordinary files, and
    unrelated runtime/ paths must remain readable."""
    flag = sandbox / "runtime" / ".runtime_protection_disabled"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("{}")
    other = sandbox / "runtime" / "agent_logs" / "job.log"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("ok")

    assert _is_read_protected_path(sandbox, flag) is None
    assert _is_read_protected_path(sandbox, other) is None
    assert _is_read_protected_path(sandbox, _key(sandbox)) is not None
