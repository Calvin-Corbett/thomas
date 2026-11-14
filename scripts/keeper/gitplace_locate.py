"""Where a place's git data lives, refusing every redirection the main repository did not register (design section 3).

A linked worktree's git folder is taken from the main repository's registration, never from the ``.git`` file in the
worktree, and an object folder whose alternates leave this machine or pass through a link is refused. Part of
``gitplace`` (see its notes), which re-exports these names.
"""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from scripts.cage.referee.nofollow import REPARSE

from .gitplace_files import Unreadable, _norm, _plain_folder, small


@dataclass(frozen=True)
class GitPlace:
    work: Path  # the working folder
    git_dir: Path  # where HEAD and the index live
    common: Path  # where objects and refs live
    linked: bool  # a linked worktree of the main repository


def _registration(fs, main_git: Path, dotgit: Path) -> Path | None:
    root = main_git / "worktrees"
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return None
    for name in names:
        reg = root / name
        info = os.lstat(reg)
        if getattr(info, "st_file_attributes", 0) & REPARSE or not stat.S_ISDIR(info.st_mode):
            continue
        data = small(fs, reg / "gitdir", 4096)
        if data and _norm(data.decode("utf-8", "replace").strip()) == _norm(dotgit):
            return reg
    return None


def _fixed_drive(path: Path) -> bool:
    """True when ``path`` is on a local fixed disk (never a mapped network drive), judged without touching it."""
    if sys.platform != "win32":
        return True
    import ctypes

    drive = os.path.splitdrive(os.path.abspath(path))[0]
    if len(drive) != 2:  # no drive letter: a UNC or device path
        return False
    return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == 3  # DRIVE_FIXED


def check_alternates(fs, objects: Path, depth: int = 0) -> None:
    """Refuse an object folder whose alternates leave this machine or pass through a link.

    Git follows ``objects/info/alternates`` (and theirs, five deep) when it reads objects. A network path there would
    make git, running as you, open a share someone else names; a link would take it somewhere unchecked.
    """
    if depth > 5:
        raise Unreadable(f"{objects}: alternates nest deeper than git follows")
    data = small(fs, objects / "info" / "alternates", 1 << 16) or b""
    for line in data.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        target = Path(line) if os.path.isabs(line) else objects / line
        remote = line.startswith(('"', "\\\\", "//")) or "://" in line or str(target).startswith(("\\\\", "//"))
        if remote or not _fixed_drive(target):
            raise Unreadable(f"{objects} borrows objects from {line!r}, which is not a plain local folder")
        if os.path.lexists(target):
            _plain_folder(fs, target)
            check_alternates(fs, target, depth + 1)


def locate(fs, place: Path, main_git: Path | None = None) -> GitPlace:
    """Where a place's git data lives, refusing every redirection the main repository did not register."""
    place = Path(os.path.abspath(place))
    dotgit = place / ".git"
    try:
        info = os.lstat(dotgit)
    except FileNotFoundError as exc:
        raise Unreadable(f"{place} has no .git") from exc
    if getattr(info, "st_file_attributes", 0) & REPARSE or stat.S_ISLNK(info.st_mode):
        raise Unreadable(f"{dotgit} is a link; it is never followed")
    if stat.S_ISDIR(info.st_mode):
        _plain_folder(fs, dotgit)
        if os.path.lexists(dotgit / "commondir"):
            raise Unreadable(f"{dotgit} redirects to another git folder (commondir)")
        git_dir, common, linked = dotgit, dotgit, False
    else:
        if main_git is None:
            raise Unreadable("a linked worktree is read only through its registration in the main repository (--main)")
        pointer = small(fs, dotgit, 4096) or b""
        text = pointer.decode("utf-8", "replace").strip()
        if not text.startswith("gitdir:"):
            raise Unreadable(f"{dotgit} is not a gitdir pointer")
        target = Path(text[len("gitdir:") :].strip())
        target = target if target.is_absolute() else place / target
        reg = _registration(fs, Path(main_git), dotgit)
        if reg is None:
            raise Unreadable("this working copy is not registered in the main repository")
        if _norm(target) != _norm(reg):
            raise Unreadable("this working copy points somewhere Thomas did not register")
        git_dir, common, linked = reg, Path(os.path.abspath(main_git)), True
    for folder in (git_dir, common, common / "objects"):
        _plain_folder(fs, folder)
    if os.path.lexists(common / "reftable"):
        raise Unreadable("unreadable: reftable")
    check_alternates(fs, common / "objects")
    return GitPlace(place, git_dir, common, linked)
