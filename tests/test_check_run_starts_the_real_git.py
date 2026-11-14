"""A Build team's check.run starts the real git, not Git for Windows' launcher (2026-10-28).

``git`` on this PC's PATH is a launcher that starts ``..\\mingw64\\bin\\git.exe`` as a second process, so every git a
test starts was two processes. The check before your card already finds the real git first
(``thomas/server/proof/environment.py``); a team's own test runs through check.run did not: measured 2026-10-28,
child processes were 43-44% of the CPU of the most-selected test files, nearly all of them git, at 74 ms per git call
through the launcher against 40 ms direct.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from thomas.core import git_launcher
from thomas.tools import check_run


def _layout(root: Path) -> tuple[Path, Path]:
    """A fake Git for Windows under *root*: its launcher folder and the folder of the git it starts."""
    launcher, real, unix = root / "Git" / "cmd", root / "Git" / "mingw64" / "bin", root / "Git" / "usr" / "bin"
    for folder in (launcher, real, unix):
        folder.mkdir(parents=True)
    (launcher / "git.exe").write_bytes(b"launcher")
    (real / "git.exe").write_bytes(b"git")
    (unix / "sh.exe").write_bytes(b"sh")
    return launcher, real


def test_a_team_test_run_finds_the_real_git_before_the_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher, real = _layout(tmp_path)
    monkeypatch.setattr(git_launcher, "WINDOWS", True)
    monkeypatch.delenv("MSYSTEM", raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join([str(launcher), str(tmp_path / "later")]))

    env = check_run._child_env(tmp_path / "project")

    assert env["PATH"].split(os.pathsep)[:2] == [str(real), str(launcher)]


def test_off_windows_the_path_is_left_as_it_was(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    launcher, _real = _layout(tmp_path)
    monkeypatch.setattr(git_launcher, "WINDOWS", False)
    given = os.pathsep.join([str(launcher), str(tmp_path / "later")])
    monkeypatch.setenv("PATH", given)

    assert check_run._child_env(tmp_path / "project")["PATH"] == given
