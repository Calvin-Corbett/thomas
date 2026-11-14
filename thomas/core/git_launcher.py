"""Git for Windows' launcher, and the real git behind it.

``git`` on this PC's PATH is ``C:\\Program Files\\Git\\cmd\\git.exe``. It is a launcher: it starts
``..\\mingw64\\bin\\git.exe`` as a second process and waits for it (seen in the process tree, 2026-10-13), so every
git call starts two processes. Measured 2026-10-13: ``git rev-parse`` took 45.5 ms through the launcher and 25.8 ms
direct (18.7 ms apart, median of 200 alternated pairs, on a busy machine); the ratchet's test file starts 1,402 git
processes, and took 79.9 and 75.8 s with the launcher found first, 53.1 and 57.8 s with the real git found first.

Before it starts git, the launcher sets ``MSYSTEM=MINGW64`` and puts ``<Git>\\mingw64\\bin``, ``<Git>\\usr\\bin`` and
``%HOME%\\bin`` in front of PATH, so git's own children -- hooks, shell aliases, ssh, gpg, credential helpers -- find
``sh`` and the rest. Started directly with ``MSYSTEM`` not set, the real git does the same for its children (the
same three folders, ``%HOME%\\bin`` first; compared through a git alias, 2026-10-13), so a hook sees what it saw.
Started directly with ``MSYSTEM`` already set, it adds nothing, and with no ``usr\\bin`` on PATH it could not start a
hook or an alias at all (it crashed, exit 0xC0000005, 2026-10-13); then nothing here changes.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

# Git for Windows' layout: the launcher in <Git>\cmd, the git it starts in <Git>\mingw64\bin, the shell git runs
# hooks and aliases with in <Git>\usr\bin.
_LAUNCHER_DIR = "cmd"
_REAL_DIR = ("mingw64", "bin")
_SHELL = ("usr", "bin", "sh.exe")
# The launcher is a Windows program; a test sets this to try a layout anywhere.
WINDOWS = os.name == "nt"


def _key(env: Mapping[str, str], name: str) -> str | None:
    """The key *env* holds *name* under: Windows' variable names ignore case."""
    return next((key for key in env if key.upper() == name), None)


def _real_git_dir(launcher_dir: Path) -> Path | None:
    """``<Git>\\mingw64\\bin`` when *launcher_dir* is Git for Windows' ``<Git>\\cmd`` and its git and ``sh`` are there."""
    if launcher_dir.name.lower() != _LAUNCHER_DIR:
        return None
    top = launcher_dir.parent
    real = top.joinpath(*_REAL_DIR)
    return real if os.path.isfile(real / "git.exe") and os.path.isfile(top.joinpath(*_SHELL)) else None


def real_git_first(env: Mapping[str, str]) -> dict[str, str]:
    """A copy of *env* whose PATH finds the real git where it found the launcher; otherwise an unchanged copy.

    The real git's folder goes just before the first PATH folder that holds a ``git.exe``, and only when that folder
    is the launcher's: a process given this PATH that asks for ``git`` starts the git the launcher would have started,
    from the same install, and every folder that came before the launcher still comes first. Off Windows, with
    ``MSYSTEM`` already set, or with no launcher in front, nothing changes.
    """
    out = dict(env)
    path = _key(out, "PATH")
    if not WINDOWS or path is None or _key(out, "MSYSTEM") is not None:
        return out
    folders = out[path].split(os.pathsep)
    for at, folder in enumerate(folders):
        name = folder.strip().strip('"')
        if name and os.path.isfile(Path(name) / "git.exe"):  # the git a bare "git" finds on this PATH
            real = _real_git_dir(Path(name))
            if real is not None:
                out[path] = os.pathsep.join([*folders[:at], str(real), *folders[at:]])
            break
    return out


__all__ = ["WINDOWS", "real_git_first"]
