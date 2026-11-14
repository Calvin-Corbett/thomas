"""A slim checkout: a git copy of one tip that holds only a list of paths (spec 2026-10-29 section 3, Copy).

Made the way a green is (``git clone --shared --no-checkout --separate-git-dir``), then a ``--no-cone`` sparse checkout
of exactly the given paths, anchored and literal. Git still lists every tracked path, so a test that asks git what
exists sees the whole tree while only a plugin's proof set is on disk.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SlimCheckout:
    work: Path
    git_dir: Path
    tip: str
    files: int


def _git(*args: str, stdin: bytes | None = None) -> None:
    subprocess.run(["git", *args], input=stdin, capture_output=True, check=True, timeout=600)


def _literal(path: str) -> str:
    """A sparse-checkout pattern (gitignore syntax) matching exactly *path* from the root."""
    return "/" + "".join("\\" + c if c in "*?[]\\" else c for c in path)


def create_slim(blue: Path, root: Path, name: str, tip: str, paths: Sequence[str]) -> SlimCheckout:
    """Copy *tip* of the repo at *blue* into ``<root>/work/<name>``, with only *paths* on disk."""
    root = Path(root)
    work, git_dir = root / "work" / name, root / "git" / name
    if work.exists() or git_dir.exists():
        raise ValueError(f"a slim copy named {name} already exists under {root}")
    work.parent.mkdir(parents=True, exist_ok=True)
    git_dir.parent.mkdir(parents=True, exist_ok=True)
    _git("clone", "--quiet", "--shared", "--no-checkout", f"--separate-git-dir={git_dir}", str(blue), str(work))
    unique = sorted(set(paths))
    patterns = ("\n".join(_literal(p) for p in unique) + "\n").encode("utf-8")
    _git("-C", str(work), "sparse-checkout", "set", "--no-cone", "--stdin", stdin=patterns)
    _git("-C", str(work), "checkout", "--quiet", "--detach", tip)
    return SlimCheckout(work=work, git_dir=git_dir, tip=tip, files=len(unique))


def _writable(func, path, _exc) -> None:
    os.chmod(path, stat.S_IWRITE)  # git's object files are read-only on Windows
    func(path)


def remove_slim(copy: SlimCheckout) -> None:
    """Delete the copy's work folder and its git folder."""
    for folder in (copy.work, copy.git_dir):
        if folder.exists():
            shutil.rmtree(folder, onexc=_writable)
