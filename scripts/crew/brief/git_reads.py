"""Batched git reads for the scoped commit path: one process where the commit tool used to start dozens. Stdlib only.

Measured on the live checkout (2026-10-07): the serial ladder asked git "is this gate script tracked?" 43 times
(2.2 s) before running a single gate, and two gates read 28 and 66 blobs one ``git show`` process at a time. A process
start is the whole cost, so each of those is one ``git ls-files`` or one ``git cat-file --batch`` now.
"""

from __future__ import annotations

import os
import posixpath
import subprocess
from collections.abc import Iterable
from pathlib import Path

# CREATE_NO_WINDOW. A child of a windowless parent opens its own console window otherwise, and so does every git it starts.
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class GitReadError(RuntimeError):
    """The batch stream was not what batch mode promises. Callers fall back to one read per name."""


def run_git(
    repo_root: Path | str,
    args: Iterable[str],
    *,
    env: dict[str, str] | None = None,
    stdin: bytes | None = None,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        env=env,
        input=stdin,
        capture_output=True,
        check=False,
        creationflags=NO_WINDOW,
        timeout=timeout,
    )


def cat_file_batch(
    repo_root: Path | str, names: Iterable[str], *, env: dict[str, str] | None = None
) -> dict[str, bytes | None]:
    """``git cat-file --batch`` over ``names`` (any object name: ``:path`` is the index, ``<sha>:path`` a commit).

    A blob comes back as bytes, a name that does not resolve (or is not a blob) as None. Anything else in the stream
    raises GitReadError, so a caller never reads a half-parsed answer.
    """
    wanted = list(dict.fromkeys(names))
    if not wanted:
        return {}
    if any("\n" in name for name in wanted):
        raise GitReadError("an object name with a newline cannot go through batch mode")
    proc = run_git(repo_root, ["cat-file", "--batch"], env=env, stdin=("\n".join(wanted) + "\n").encode("utf-8"))
    if proc.returncode != 0:
        raise GitReadError(proc.stderr.decode("utf-8", "replace").strip() or "git cat-file --batch failed")
    data, pos = proc.stdout, 0
    out: dict[str, bytes | None] = {}
    for name in wanted:
        eol = data.find(b"\n", pos)
        if eol < 0:
            raise GitReadError("batch stream ended early")
        header = data[pos:eol].decode("utf-8", "replace")
        pos = eol + 1
        if header.endswith(" missing"):
            out[name] = None
            continue
        parts = header.split(" ")
        if len(parts) != 3 or not parts[2].isdigit():
            raise GitReadError(f"unexpected batch header {header!r}")
        size = int(parts[2])
        body = data[pos : pos + size]
        if len(body) != size:
            raise GitReadError("batch body was cut short")
        pos += size + 1  # the LF after every body
        out[name] = body if parts[1] == "blob" else None
    return out


def _key(path: str) -> str:
    text = str(path or "").replace("\\", "/")
    return text.casefold() if os.name == "nt" else text  # core.ignorecase: git matches case-blind on Windows


def tracked_among(repo_root: Path | str, paths: Iterable[str], *, env: dict[str, str] | None = None) -> set[str] | None:
    """The subset of ``paths`` that git tracks, from one ``git ls-files``. None when git could not say.

    The one-call-per-path check this replaces treated "git failed" as "tracked", so a caller treats None the same way:
    nothing is untracked unless git said so.
    """
    wanted = [p for p in dict.fromkeys(str(p) for p in paths) if p]
    if not wanted:
        return set()
    root = Path(repo_root).resolve()
    ask: dict[str, list[str]] = {}  # canonical repo-relative spelling -> every spelling the caller used for it
    outside: set[str] = set()
    for original in wanted:
        relative = _canonical(original, root)
        if relative is None:
            # git cannot say anything about a path outside the repo; the old one-call check said "not untracked"
            outside.add(original)
        else:
            ask.setdefault(relative, []).append(original)
    if not ask:
        return outside
    # Compared by name below, so git reading a glob character as a pattern cannot make an untracked path look tracked.
    proc = run_git(repo_root, ["ls-files", "-z", "--", *ask], env=env)
    if proc.returncode != 0:
        return None
    listed = {_key(row) for row in proc.stdout.decode("utf-8", "replace").split("\0") if row}
    return outside | {original for relative, names in ask.items() if _key(relative) in listed for original in names}


def _canonical(path: str, root: Path) -> str | None:
    """``path`` the way git lists it (repo-relative, forward slashes, no ``./``, ``//`` or ``..``), or None when it is outside.

    The comparison in tracked_among is between git's listing and the caller's spelling, so ``./scripts/x.py`` must become
    ``scripts/x.py`` first: left alone, a tracked gate spelled that way read as untracked and was silently left out.
    """
    text = path.replace("\\", "/")
    if Path(path).is_absolute():
        try:
            return Path(path).resolve().relative_to(root).as_posix()
        except ValueError:
            return None
    relative = posixpath.normpath(text)
    return None if relative == "." or relative == ".." or relative.startswith("../") else relative


def _is_object_name(text: str) -> bool:
    return len(text) in (40, 64) and all(ch in "0123456789abcdef" for ch in text.lower())


class HeadProbe:
    """The branch tip, read from git's ref files: a file read, not a process.

    Used to bracket each gate run. A gate whose bracket saw the tip anywhere but the base it was built on judged a moving
    target, and its verdict is not trusted either way.

    A branch's ref is a loose file until ``git gc`` or ``git pack-refs`` moves it into ``packed-refs``; a loose file wins
    when both exist, which is what git itself does. Measured with the ref packed: answering through ``git rev-parse HEAD``
    instead added about 80 git processes to every ladder. Only a ref neither file can answer (the reftable format, a
    damaged file) still goes to git.
    """

    def __init__(self, repo_root: Path | str, branch: str):
        self.repo_root = Path(repo_root)
        self._ref = f"refs/heads/{branch}"
        self._loose = self._git_path(self._ref)
        self._packed = self._git_path("packed-refs")

    def _git_path(self, name: str) -> Path | None:
        proc = run_git(self.repo_root, ["rev-parse", "--git-path", name])
        text = proc.stdout.decode("utf-8", "replace").strip() if proc.returncode == 0 else ""
        return self.repo_root / text if text else None

    def _read_loose(self) -> str:
        try:
            text = self._loose.read_text(encoding="ascii").strip() if self._loose else ""
        except (OSError, ValueError):
            return ""
        return text if _is_object_name(text) else ""

    def _read_packed(self) -> str:
        try:
            rows = self._packed.read_text(encoding="utf-8", errors="replace").splitlines() if self._packed else []
        except OSError:
            return ""
        for row in rows:
            sha, _space, name = row.partition(" ")
            if name.strip() == self._ref and _is_object_name(sha):
                return sha
        return ""

    def __call__(self) -> str:
        sha = self._read_loose() or self._read_packed()
        if sha:
            return sha
        proc = run_git(self.repo_root, ["rev-parse", "HEAD"])
        return proc.stdout.decode("utf-8", "replace").strip()
