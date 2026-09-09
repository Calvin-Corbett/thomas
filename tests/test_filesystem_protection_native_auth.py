"""Native-auth and toggle-script regressions for runtime protection."""

from __future__ import annotations

import hmac
import json
from hashlib import sha256
from pathlib import Path

import pytest

from tests.filesystem_protection_helpers import _run, sandbox
from thomas.tools.filesystem import (
    WriteProtectedFileTool,
    _is_runtime_protection_disabled,
    _runtime_signing_payload,
)


def test_write_protected_file_refused_without_auth(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "thomas.tools.native_auth.request_native_authorization",
        lambda action, reason: False,
    )
    tool = WriteProtectedFileTool(sandbox, project_root=sandbox)
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

    tool = WriteProtectedFileTool(sandbox, project_root=sandbox)
    target = "thomas/tools/evil.py"
    result = _run(
        tool,
        {
            "path": target,
            "content": "x = 1\n",
            "reason": "the product owner-approved emergency fix",
        },
    )
    assert result.ok is True
    assert (sandbox / target).read_text() == "x = 1\n"
    assert "the product owner-approved emergency fix" in captured["action"]
    assert "thomas/tools/evil.py" in captured["action"]


def test_write_protected_file_requires_reason(sandbox: Path) -> None:
    tool = WriteProtectedFileTool(sandbox, project_root=sandbox)
    result = _run(tool, {"path": "thomas/tools/x.py", "content": "x", "reason": ""})
    assert result.ok is False
    assert result.error is not None
    assert "reason" in result.error


def test_write_protected_file_works_for_unprotected_path_no_prompt(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def _track(action: str, reason: str) -> bool:
        calls["n"] += 1
        return True

    monkeypatch.setattr("thomas.tools.native_auth.request_native_authorization", _track)

    tool = WriteProtectedFileTool(sandbox, project_root=sandbox)
    result = _run(tool, {"path": "src/regular.py", "content": "ok", "reason": "no-op"})
    assert result.ok is True
    assert calls["n"] == 0


def test_write_protected_file_can_be_used_to_clear_the_flag(sandbox: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "thomas.tools.native_auth.request_native_authorization",
        lambda action, reason: True,
    )
    tool = WriteProtectedFileTool(sandbox, project_root=sandbox)
    result = _run(
        tool,
        {
            "path": "runtime/.runtime_protection_disabled",
            "content": "",
            "reason": "emergency re-enable",
        },
    )
    assert result.ok is True
    assert _is_runtime_protection_disabled(sandbox) is False


def test_toggle_script_signing_payload_matches_validator(sandbox: Path) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    try:
        from runtime_protection_toggle import _signing_payload as script_payload
    finally:
        sys.path.pop(0)

    args = (1, "2026-05-27T12:00:00Z", "owner", str(sandbox.resolve()))
    assert script_payload(*args) == _runtime_signing_payload(*args)


def test_toggle_script_writes_validator_acceptable_flag(sandbox: Path) -> None:
    import sys
    import time as _time

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    try:
        from runtime_protection_toggle import FLAG_VERSION, _flag_path, _mint_fresh_key, _signing_payload
    finally:
        sys.path.pop(0)

    key = _mint_fresh_key(sandbox)
    assert len(key) >= 32
    issued_at = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
    issued_by = "owner"
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
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    try:
        from runtime_protection_toggle import _flag_path, _key_path, _mint_fresh_key, cmd_on
    finally:
        sys.path.pop(0)

    _mint_fresh_key(sandbox)
    _flag_path(sandbox).write_text("{}")
    assert _key_path(sandbox).exists() and _flag_path(sandbox).exists()

    rc = cmd_on(sandbox)
    assert rc == 0
    assert not _key_path(sandbox).exists(), "cmd_on must remove the key"
    assert not _flag_path(sandbox).exists(), "cmd_on must remove the flag"
