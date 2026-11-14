"""A Thomas project's hand-in never adds a file the running Thomas ignores.

The running checkout ignores some runtime files only through its own ``.git/info/exclude`` (``thomas_search.db-wal``
and ``-shm``, the search index's SQLite journal), which a copy's separate git folder does not have. The hand-in
staged everything, so on 2026-09-27 a cleanup change reached your card carrying both journal files at the repo root.
A new file that the running copy ignores (its local excludes or the repo's own ``.gitignore``) is left out; a file
the repo already tracks is never dropped this way, so a real edit cannot be lost to an ignore pattern.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from thomas.server import green_checkout


def _git(cwd: Path, *args: str) -> None:
    command = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *args]
    subprocess.run(command, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> green_checkout.Green:
    blue = tmp_path / "blue"
    (blue / "pkg").mkdir(parents=True)
    (blue / "pkg" / "a.py").write_text("A = 1\n", encoding="utf-8")
    (blue / "fixture.db").write_text("tracked on purpose\n", encoding="utf-8")
    (blue / ".gitignore").write_text("*.log\n", encoding="utf-8")
    for args in (
        ("init", "-q", "-b", "dev"),
        ("add", "-A"),
        ("add", "-f", "fixture.db"),
        ("commit", "-q", "-m", "base"),
    ):
        _git(blue, *args)
    (blue / ".git" / "info").mkdir(exist_ok=True)
    (blue / ".git" / "info" / "exclude").write_text("# local\nsearch.db-wal\n*.db\n", encoding="utf-8")
    greens = tmp_path / "green"
    for folder in (greens / "work", greens / "git"):
        folder.mkdir(parents=True)
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(greens))
    return green_checkout.create_green(blue=blue, execution_id="thomas-ignored")


def test_new_files_the_running_copy_ignores_stay_out(green: green_checkout.Green) -> None:
    (green.work / "pkg" / "b.py").write_text("B = 1\n", encoding="utf-8")  # the team's new file
    (green.work / "search.db-wal").write_text("journal\n", encoding="utf-8")  # ignored by blue's local excludes
    (green.work / "run.log").write_text("log\n", encoding="utf-8")
    subprocess.run(green_checkout._git_command(green, "add", "-f", "run.log"), check=True, capture_output=True)

    assert green_checkout.changed_paths(green) == ["pkg/b.py"]


def test_an_edit_to_a_tracked_file_that_matches_an_ignore_pattern_is_kept(green: green_checkout.Green) -> None:
    (green.work / "fixture.db").write_text("edited by the team\n", encoding="utf-8")

    assert green_checkout.changed_paths(green) == ["fixture.db"]
