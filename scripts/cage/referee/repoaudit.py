"""What the referee checks in the real git directory before a ``direct`` call, and how it keeps that true during it.

``inspect_repo_local`` asks git itself (never a hand-written scan) what config keys the repository holds and which
directories git will really read, and returns ``-c`` overrides plus refusals. ``held`` keeps the files that were
audited from being changed while the audit and the command run, and ``fingerprint`` proves they were not.

Only the Windows hold is a real defence: a handle that denies write, rename and delete sharing makes an atomic
replace of ``config`` fail. Where the platform cannot hold (``hold_file`` yields False) the fingerprint taken before
and after the command is all there is: a change is detected and the result discarded, but a command that already ran
cannot be undone. This module starts no process; every git call goes through the runner it is given.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path

from .configscan import scan
from .nofollow import UnsafeEntry

POINTER_FILES = ("commondir", "gitdir")  # each redirects git to a config the audit would not have read
WATCHED = ("config", "info/attributes", "HEAD", "config.worktree", "commondir", "gitdir", "objects/info/alternates")
HELD_FILES = ("config", "info/attributes", "HEAD")
REQUIRED_FILES = ("config", "HEAD")


def inspect_repo_local(runner) -> tuple[list[str], list[str]]:
    """``(-c overrides, refusals)`` for the real git directory. Refusals empty means ``direct`` may run.

    Git lists the key names of the repository's ``config`` (``config --file ... --list -z --name-only``), so no
    spelling of a header can hide a key. Git is also asked where it will read from (``rev-parse --git-dir
    --git-common-dir``): a common dir that differs, a ``commondir`` or ``gitdir`` pointer file and an
    ``objects/info/alternates`` file are refused, as is a ``config.worktree`` file, a config git cannot read and any
    non-comment line in ``info/attributes`` (an attributes line selects drivers by name). The alternates refusal is
    defence in depth only: an alternate object store adds content-addressed objects and cannot run a command.
    """
    quiet, git_dir = replace(runner, audit=False), runner.git_dir
    listing = quiet.run(
        "config", "--file", str(git_dir / "config"), "--list", "-z", "--name-only", check=False, repo=False
    )
    names = [n.decode("utf-8", "replace") for n in listing.stdout.split(b"\0") if n]
    overrides, found = scan(names, str(runner.hooks_dir))
    if listing.returncode:
        found.append("config could not be read by git")
    found += [f"{name} exists" for name in ("config.worktree", *POINTER_FILES) if (git_dir / name).exists()]
    if (git_dir / "objects" / "info" / "alternates").exists():
        found.append("objects/info/alternates exists")
    where = quiet.run("rev-parse", "--git-dir", "--git-common-dir", "--absolute-git-dir", check=False)
    lines = where.stdout.decode("utf-8", "replace").splitlines()
    if where.returncode or len(lines) != 3:
        found.append("git could not say where it reads from")
    else:
        git_here, common, absolute = (os.path.normcase(os.path.realpath(Path(runner.cwd, x))) for x in lines)
        if not git_here == common == absolute == os.path.normcase(os.path.realpath(git_dir)):
            found.append("the common dir differs from the git dir")
    try:
        attributes = (git_dir / "info" / "attributes").read_text(encoding="utf-8", errors="replace")
    except OSError:
        attributes = ""
    if any(ln.strip() and not ln.strip().startswith("#") for ln in attributes.splitlines()):
        found.append("info/attributes is not empty")
    return overrides, found


def fingerprint(git_dir: Path) -> tuple[str | None, ...]:
    """A hash of each watched file, or None where it is absent: equal before and after means nothing changed."""
    out: list[str | None] = []
    for name in WATCHED:
        try:
            out.append(hashlib.sha256((git_dir / name).read_bytes()).hexdigest())
        except FileNotFoundError:
            out.append(None)
    return tuple(out)


@contextmanager
def held(fs, git_dir: Path) -> Iterator[int]:
    """Hold the git directory, its ``info`` folder and the audited files. Yields how many handles were really held.

    The caller takes the hold before the audit and keeps it until the command has finished. ``config`` and ``HEAD``
    are required: if either cannot be held (missing, locked by someone else, any open error) this raises
    ``PermissionError`` naming it, never a silent "not held". ``info/attributes`` may be absent: creating it late
    is harmless, because every filter, diff and merge driver is neutralised by ``-c`` whatever an attributes file
    selects. Files that only redirect git (``commondir``, ``config.worktree``, ``gitdir``) are not held (a handle
    cannot hold an absence); the runner's environment makes git ignore them (``GIT_COMMON_DIR`` and friends).
    """
    count = 0
    with ExitStack() as stack:
        folders = [git_dir, *([git_dir / "info"] if (git_dir / "info").is_dir() else [])]
        files = [(name, name in REQUIRED_FILES) for name in HELD_FILES]
        try:
            for folder in folders:
                stack.enter_context(fs.hold_dir(folder))
            for name, required in files:
                count += bool(stack.enter_context(fs.hold_file(git_dir / name, required)))
        except (UnsafeEntry, OSError) as exc:
            raise PermissionError(f"could not hold {getattr(exc, 'code', exc)} in {git_dir}: {exc}") from exc
        yield count
