"""Setting the file-access level in config did nothing.

`thomas.toml` has a `[tools] file_access` key, `ToolsConfig` parses it, and
`register_filesystem_tools` honours it. But the delegation path that decides
whether a task may touch the Thomas repo did not:

    effective_file_access = clamp_file_access_level(file_access if file_access is not None else 1)

A literal 1. `clamp_file_access_level` even takes a ``default=`` keyword built
for exactly this and the call bypassed it, so when a request did not carry an
explicit level, every worker was pinned to WORKSPACE no matter what the owner
had configured -- and a task aimed at the repo was refused at the door.

The fallback now asks what the owner actually configured.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.core import file_access as fa


@pytest.fixture(autouse=True)
def _clear_cache():
    fa.configured_file_access_level.cache_clear()
    yield
    fa.configured_file_access_level.cache_clear()


def _write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "thomas.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_a_configured_level_is_what_gets_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMAS_CONFIG", str(_write_config(tmp_path, "[tools]\nfile_access = 2\n")))
    assert fa.configured_file_access_level() == fa.PROJECT


def test_an_unset_level_falls_back_to_the_ladder_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Absent config is workspace, exactly as before. This widens nothing on its own."""
    monkeypatch.setenv("THOMAS_CONFIG", str(_write_config(tmp_path, "[tools]\nallow_shell = true\n")))
    assert fa.configured_file_access_level() == fa.DEFAULT_FILE_ACCESS_LEVEL


def test_an_unreadable_config_does_not_take_the_caller_down(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A broken config must not raise on a path that only wants a number."""
    monkeypatch.setenv("THOMAS_CONFIG", str(_write_config(tmp_path, "this is not valid toml {{{")))
    assert fa.configured_file_access_level() == fa.DEFAULT_FILE_ACCESS_LEVEL


def test_a_nonsense_level_is_clamped_not_trusted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMAS_CONFIG", str(_write_config(tmp_path, "[tools]\nfile_access = 99\n")))
    assert fa.configured_file_access_level() == fa.FULL


def test_the_delegation_fallback_no_longer_hardcodes_workspace() -> None:
    """The bug itself: a literal 1 in the path that gates repo access.

    Read from source, because the call site is what decides -- a helper that
    exists but is not used is the failure this whole change is about.
    """
    src = (Path(__file__).resolve().parents[1] / "thomas" / "server" / "chat_delegation.py").read_text(encoding="utf-8")
    assert "file_access is not None else 1" not in src, "the hardcoded workspace fallback is still there"
    assert "configured_file_access_level" in src, "the delegation path never asks what was configured"
