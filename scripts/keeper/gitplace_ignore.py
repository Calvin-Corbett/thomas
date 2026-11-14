"""A place's ignore rules, judged in a private shadow of its folder shape and never in the place itself.

``git check-ignore`` moves git's current folder into its work tree, so no git call names the place: the rules are
judged against ``IgnoreShadow``. Part of ``gitplace`` (see its notes), which re-exports these names.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from scripts.cage.referee.gitenv import GitFailed, GitRunner
from scripts.cage.referee.nofollow import UnsafeEntry

from .gitplace_view import _path
from .places import read_in_place

IGNORE_LIMIT = 4 * 1024 * 1024


class IgnoreShadow:
    """A private stand-in for the place as git's work tree when it judges ignore rules.

    ``git check-ignore`` needs a work tree, and git moves its current folder into it before it runs, so pointing it at
    the place would run git (and anything it loads by name) from a folder someone else can write. The shadow holds
    the place's folder shape (a folder-only rule such as ``build/`` looks at whether a path is a folder) and a copy of
    each ``.gitignore`` above the paths asked about, read here through the no-follow seam. A ``.gitignore`` that is a
    link, hard linked or too large is not copied, so its rules are not used and more is saved, never less. A sparse
    checkout's ``.gitignore`` that is absent from the place is absent here too, and git reads it from the index copy.
    """

    def __init__(self, fs, place: Path, root: Path) -> None:
        self.fs, self.place, self.root = fs, place, root
        root.mkdir(parents=True, exist_ok=True)
        self._copied: set[str] = set()

    def _copy_rules(self, folder: str) -> None:
        if folder in self._copied:
            return
        self._copied.add(folder)
        rel = f"{folder}/.gitignore" if folder else ".gitignore"
        try:
            data = read_in_place(self.fs, self.place, rel, IGNORE_LIMIT)[0]
            target = self.root.joinpath(*rel.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except (UnsafeEntry, OSError):
            pass  # absent, refused or unwritable here: its rules are not used, so the capture holds more

    def prepare(self, paths: Iterable[str], folders: bool) -> None:
        """Copy the rules above each path; with ``folders``, make each path a folder in the shadow too."""
        for path in paths:
            parts = path.split("/")
            for depth in range(len(parts)):
                self._copy_rules("/".join(parts[:depth]))
            if folders:
                try:
                    self.root.joinpath(*parts).mkdir(parents=True, exist_ok=True)
                except OSError:
                    pass  # a folder-only rule then does not match it: the folder is walked and saved, not skipped


def check_ignored(
    runner: GitRunner, shadow: Path, paths: list[str], exclude_copy: Path | None, index: Path | None = None
) -> set[str]:
    """Which of ``paths`` the place's ignore rules leave out, judged in ``shadow`` (``IgnoreShadow.root``).

    No attributes, filters or hooks are ever defined, and the place is never git's work tree or current folder. With
    ``index`` (the private copy of the place's index), a sparse checkout's ``.gitignore`` that is absent from the
    folder is read from the index, as git itself does; without one, ``--no-index``.
    """
    if not paths:
        return set()
    done = runner.run(
        "-c",
        f"core.excludesFile={exclude_copy.as_posix() if exclude_copy else os.devnull}",
        f"--work-tree={shadow}",
        "check-ignore",
        *([] if index else ["--no-index"]),
        "--stdin",
        "-z",
        data=b"".join(p.encode("utf-8") + b"\0" for p in paths),
        index=index,
        check=False,
    )
    if done.returncode not in (0, 1):
        raise GitFailed(f"git check-ignore failed: {done.stderr.decode('utf-8', 'replace')[:200]}")
    return {_path(p) for p in done.stdout.split(b"\0") if p}
