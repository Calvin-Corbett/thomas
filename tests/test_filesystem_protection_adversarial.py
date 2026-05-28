"""Adversarial tests for the runtime-protection bypass fix."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.filesystem_protection_helpers import (
    _flag,
    _key,
    _plant_key,
    _run,
    _write_signed_flag,
    sandbox,
)
from thomas.tools.filesystem import (
    WriteFileTool,
    _is_protected_runtime_path,
    _is_runtime_protection_disabled,
)


def test_fs_write_file_refused_for_flag_path(sandbox: Path) -> None:
    tool = WriteFileTool(sandbox)
    result = _run(tool, {"path": "runtime/.runtime_protection_disabled", "content": ""})
    assert result.ok is False
    assert result.error is not None
    assert "runtime-protection control file" in result.error
    assert ".runtime_protection_disabled" in result.error
    assert not _flag(sandbox).exists()


def test_fs_write_file_refused_for_key_path(sandbox: Path) -> None:
    tool = WriteFileTool(sandbox)
    result = _run(tool, {"path": "runtime/.runtime_protection_key", "content": "00" * 32})
    assert result.ok is False
    assert result.error is not None
    assert "runtime-protection control file" in result.error
    assert not _key(sandbox).exists()


def test_fs_write_file_still_works_for_unprotected_runtime_subpath(sandbox: Path) -> None:
    tool = WriteFileTool(sandbox)
    result = _run(tool, {"path": "runtime/agent_logs/job_42.log", "content": "ok"})
    assert result.ok is True
    assert (sandbox / "runtime" / "agent_logs" / "job_42.log").read_text() == "ok"


def test_empty_flag_does_not_bypass(sandbox: Path) -> None:
    _flag(sandbox).parent.mkdir(parents=True, exist_ok=True)
    _flag(sandbox).write_text("")
    assert _is_runtime_protection_disabled(sandbox) is False
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
    _write_signed_flag(sandbox, key=b"\x00" * 32)
    assert _is_runtime_protection_disabled(sandbox) is False


def test_flag_with_wrong_signature_does_not_bypass(sandbox: Path) -> None:
    real_key = _plant_key(sandbox)
    wrong_key = bytes(b"\xff" * 32)
    assert wrong_key != real_key
    _write_signed_flag(sandbox, key=wrong_key)
    assert _is_runtime_protection_disabled(sandbox) is False


def test_flag_with_unsupported_version_does_not_bypass(sandbox: Path) -> None:
    key = _plant_key(sandbox)
    _write_signed_flag(sandbox, key=key, version=99)
    assert _is_runtime_protection_disabled(sandbox) is False


def test_flag_with_mismatched_repo_does_not_bypass(sandbox: Path) -> None:
    key = _plant_key(sandbox)
    _write_signed_flag(sandbox, key=key, repo="/some/other/repo")
    assert _is_runtime_protection_disabled(sandbox) is False


def test_flag_with_modified_field_after_signing_does_not_bypass(sandbox: Path) -> None:
    key = _plant_key(sandbox)
    _write_signed_flag(sandbox, key=key, issued_by="calvin")
    doc = json.loads(_flag(sandbox).read_text())
    doc["issued_by"] = "attacker"
    _flag(sandbox).write_text(json.dumps(doc))
    assert _is_runtime_protection_disabled(sandbox) is False


def test_signed_flag_with_matching_key_does_bypass(sandbox: Path) -> None:
    key = _plant_key(sandbox)
    _write_signed_flag(sandbox, key=key)
    assert _is_runtime_protection_disabled(sandbox) is True
    assert _is_protected_runtime_path(sandbox, sandbox / "thomas" / "core" / "_db.py") is None


def test_signed_flag_repo_match_is_case_insensitive_on_windows(sandbox: Path) -> None:
    import os as _os

    if _os.name != "nt":
        pytest.skip("Windows-only path semantics")
    key = _plant_key(sandbox)
    repo_str = str(sandbox.resolve()).swapcase()
    _write_signed_flag(sandbox, key=key, repo=repo_str)
    assert _is_runtime_protection_disabled(sandbox) is True
