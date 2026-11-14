"""A Thomas that is reused must not be one running code that has since changed.

Reusing the running copy means a launch after you edit the code keeps serving the old
Python: a server reads its modules once, when it starts, and the ``dirty`` flag in
/api/health is read once too. The launcher used to replace the server on every launch
(``ALWAYS start fresh``) and that is how an edit got picked up. So a server that is
this copy is reused only while it is current: not started from a tree with
uncommitted changes, and no ``.py`` under ``thomas\\`` and no ``thomas.toml`` written
since it started (now minus the ``uptime_s`` it reports). Otherwise it is replaced like another copy, and
left running, with a message that says why, when a Build is in flight. These tests use
stand-in servers and real folders with files of a chosen age; nothing is stopped.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pytest

from tests.launcher_powershell_support import needs_windows_powershell
from tests.launcher_server_plan_support import BUSY, IDLE, health, plan_lines

UP_FOR = 600  # seconds: the stand-in servers started ten minutes ago
STALE = "is out of date (started with uncommitted changes, or before the code or thomas.toml here last changed)"


def _copy(
    root: Path, name: str, *, py_age: float, other_age: float | None = None, toml_age: float | None = None
) -> str:
    """A folder with ``thomas\\pkg\\mod.py`` last written *py_age* seconds ago, and optionally a non-Python file
    and a ``thomas.toml`` (the file a server reads its settings from when it starts)."""
    package = root / name / "thomas" / "pkg"
    package.mkdir(parents=True)
    files = {package / "mod.py": py_age}
    if other_age is not None:
        files[package / "app.js"] = other_age
    if toml_age is not None:
        files[root / name / "thomas.toml"] = toml_age
    now = time.time()
    for path, age in files.items():
        path.write_text("x = 1\n", encoding="ascii")
        os.utime(path, (now - age, now - age))
    return str(root / name)


@pytest.fixture(scope="module")
def got(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    work = tmp_path_factory.mktemp("stale")
    unchanged = _copy(work, "unchanged", py_age=3600)
    edited = _copy(work, "edited", py_age=60)
    js_only = _copy(work, "js only", py_age=3600, other_age=60)
    config_kept = _copy(work, "config kept", py_age=3600, toml_age=3600)
    config_edited = _copy(work, "config edited", py_age=3600, toml_age=60)
    # name -> (health, status, the folder it is launched from: the one the server says it runs from)
    cases = {
        "code unchanged since start": (health(root=unchanged, uptime=UP_FOR), IDLE, unchanged),
        "code written since start": (health(root=edited, uptime=UP_FOR), IDLE, edited),
        "code written since start, building": (health(root=edited, uptime=UP_FOR), BUSY, edited),
        "code written since start, will not say": (health(root=edited, uptime=UP_FOR), 500, edited),
        "config unchanged since start": (health(root=config_kept, uptime=UP_FOR), IDLE, config_kept),
        "config written since start": (health(root=config_edited, uptime=UP_FOR), IDLE, config_edited),
        "config written since start, building": (health(root=config_edited, uptime=UP_FOR), BUSY, config_edited),
        "code written, no uptime reported": (health(root=edited), IDLE, edited),
        "code written, uptime that is not a number": (health(root=edited, uptime="soon"), IDLE, edited),
        "only a script written since start": (health(root=js_only, uptime=UP_FOR), IDLE, js_only),
        "started with uncommitted changes": (health(dirty=True), IDLE, None),
        "started with uncommitted changes, building": (health(dirty=True), BUSY, None),
    }
    return plan_lines(
        {name: (h, s) for name, (h, s, _) in cases.items()},
        work,
        {name: root for name, (_, _, root) in cases.items() if root},
    )


@needs_windows_powershell
def test_a_server_started_after_the_last_edit_is_reused(got: dict[str, str]) -> None:
    for name in ("code unchanged since start", "only a script written since start", "config unchanged since start"):
        assert got[name].startswith(f"{name}|attach|Using the Thomas already running"), got["raw"]
        assert got[f"left:{name}"] == "0"
    # Static files are read on each request, so they are not code the server is holding.
    # A server that reports no uptime cannot be compared with the files, so it is taken as current.
    for name in ("code written, no uptime reported", "code written, uptime that is not a number"):
        assert got[name].startswith(f"{name}|attach|Using the Thomas already running"), got["raw"]


@needs_windows_powershell
def test_a_server_started_before_a_py_file_was_written_is_replaced(got: dict[str, str]) -> None:
    name = "code written since start"

    assert got[name].startswith(f"{name}|replace|Replacing the Thomas on port"), got["raw"]
    assert f"; it {STALE}." in got[name], got["raw"]
    assert got[f"left:{name}"] == "0"


@needs_windows_powershell
def test_a_server_started_before_thomas_toml_was_edited_is_replaced(got: dict[str, str]) -> None:
    """The server reads its settings once, at start: an API key or a model added to thomas.toml is not loaded until it restarts."""
    name = "config written since start"

    assert got[name].startswith(f"{name}|replace|Replacing the Thomas on port"), got["raw"]
    assert f"; it {STALE}." in got[name], got["raw"]
    busy = got["config written since start, building"]
    assert busy.startswith("config written since start, building|attach|The Thomas on port"), got["raw"]
    assert got["left:config written since start, building"] == "1"


@needs_windows_powershell
def test_a_server_with_uncommitted_changes_at_start_is_replaced(got: dict[str, str]) -> None:
    name = "started with uncommitted changes"

    assert got[name].startswith(f"{name}|replace|Replacing the Thomas on port"), got["raw"]
    assert "+dirty" in got[name] and f"; it {STALE}." in got[name], got["raw"]


@needs_windows_powershell
def test_an_out_of_date_thomas_in_the_middle_of_a_build_is_left_running_and_says_so(got: dict[str, str]) -> None:
    for name in ("code written since start, building", "started with uncommitted changes, building"):
        assert got[name].startswith(f"{name}|attach|The Thomas on port"), got["raw"]
        assert f") {STALE} and is running 1 Build run(s), so it was left running" in got[name], got["raw"]
        # The command names the launched copy's own folder, so it works from wherever the log is opened.
        assert re.search(
            r'powershell -NoProfile -ExecutionPolicy Bypass -File "[A-Za-z]:\\[^"]+\\scripts\\run-ui\.ps1" -Restart -Port \d+',
            got[name],
        ), got[name]
        assert got[f"left:{name}"] == "1"
        assert got[f"{name} -ReplaceIt"].startswith(f"{name} -ReplaceIt|refuse|"), got["raw"]
    blind = "code written since start, will not say"
    assert got[blind].startswith(f"{blind}|attach|") and "would not say whether a Build is running" in got[blind]
    assert got[f"left:{blind}"] == "1"
