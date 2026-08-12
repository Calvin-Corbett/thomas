"""Control-file and read-side regressions for runtime protection."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.filesystem_protection_helpers import _flag, _key, _plant_key, _run, _write_signed_flag, sandbox
from thomas.tools.filesystem import (
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
    WriteProtectedFileTool,
    _is_read_protected_path,
    _is_runtime_protection_disabled,
)


def test_fs_write_file_refused_for_key_even_with_active_signed_flag(sandbox: Path) -> None:
    key = _plant_key(sandbox)
    _write_signed_flag(sandbox, key=key)
    assert _is_runtime_protection_disabled(sandbox) is True

    tool = WriteFileTool(sandbox, project_root=sandbox)
    result = _run(tool, {"path": "runtime/.runtime_protection_key", "content": "ff" * 32})
    assert result.ok is False
    assert result.error is not None
    assert "runtime-protection control file" in result.error
    assert _key(sandbox).read_text().strip() == key.hex()


def test_fs_write_file_refused_for_flag_even_with_active_signed_flag(sandbox: Path) -> None:
    key = _plant_key(sandbox)
    _write_signed_flag(sandbox, key=key, issued_by="calvin")
    original = _flag(sandbox).read_text()

    tool = WriteFileTool(sandbox, project_root=sandbox)
    result = _run(tool, {"path": "runtime/.runtime_protection_disabled", "content": "{}"})
    assert result.ok is False
    assert "runtime-protection control file" in (result.error or "")
    assert _flag(sandbox).read_text() == original


def test_fs_write_file_to_unprotected_path_still_works_with_active_flag(sandbox: Path) -> None:
    key = _plant_key(sandbox)
    _write_signed_flag(sandbox, key=key)
    assert _is_runtime_protection_disabled(sandbox) is True

    tool = WriteFileTool(sandbox, project_root=sandbox)
    result = _run(tool, {"path": "thomas/core/maintenance.py", "content": "# work\n"})
    assert result.ok is True


def test_write_protected_file_can_still_reach_control_files_with_auth(
    sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "thomas.tools.native_auth.request_native_authorization",
        lambda action, reason: True,
    )
    tool = WriteProtectedFileTool(sandbox, project_root=sandbox)
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


def test_fs_read_file_refused_for_key(sandbox: Path) -> None:
    _plant_key(sandbox)
    tool = ReadFileTool(sandbox)
    result = _run(tool, {"path": "runtime/.runtime_protection_key"})
    assert result.ok is False
    assert "signing key" in (result.error or "")


def test_fs_read_file_still_works_for_other_paths(sandbox: Path) -> None:
    target = sandbox / "thomas" / "core" / "hello.py"
    target.write_text("print('hi')\n")
    tool = ReadFileTool(sandbox)
    result = _run(tool, {"path": "thomas/core/hello.py"})
    assert result.ok is True
    assert "print" in (result.data or "")


def test_fs_search_skips_key_contents(sandbox: Path) -> None:
    key = _plant_key(sandbox)
    tool = SearchFilesTool(sandbox)
    result = _run(
        tool,
        {"pattern": key.hex()[:16], "path": "runtime", "glob": "*"},
    )
    assert result.ok is True
    assert key.hex()[:16] not in (result.data or "")


def test_is_read_protected_path_only_covers_key(sandbox: Path) -> None:
    flag = sandbox / "runtime" / ".runtime_protection_disabled"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("{}")
    other = sandbox / "runtime" / "agent_logs" / "job.log"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("ok")

    assert _is_read_protected_path(sandbox, flag) is None
    assert _is_read_protected_path(sandbox, other) is None
    assert _is_read_protected_path(sandbox, _key(sandbox)) is not None
