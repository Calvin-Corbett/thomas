"""The only door to git for the referee: a scrubbed environment, a pinned binary, and no repo-local surprises.

Every git call in this package goes through ``GitRunner.run``. It starts from an empty environment (system and
user config off, an explicit ``GIT_DIR``, no external diff, no prompt), calls git by the absolute path the caller
pinned, and passes ``-c`` overrides for fsmonitor, the hooks path and the attributes file.

Overrides cannot undo a driver that a repository's own ``.git/config`` and ``.git/info/attributes`` define (a
``filter.<name>.clean`` command, a ``textconv``). So there are two ways to run:

* ``isolated_view`` (the default for analysis): git runs in a private, referee-owned git directory whose config is
  fixed bytes written here, with no ``info/attributes`` and an empty hooks folder. It reads the real repository's
  objects through ``objects/info/alternates``. The real ``config`` and ``info/attributes`` are never read, so
  nothing planted in them can run. New objects (``write-tree``, ``hash-object -w``) land in the private directory.
* ``direct``: git runs in the real git directory, for the operations that must change it (the compare-and-swap,
  the index sync). Every call lists the repository's own config keys through git itself and builds ``-c``
  overrides from them (``configscan``): a filter, textconv, diff or merge driver, a hooks path, fsmonitor, pager,
  editor, ssh, askpass, credential helper and gpg program are neutralised, known harmless keys (remote, branch,
  user, lfs, gc, pack, index, submodule, url, alias, a few core keys) are allowed, and anything else
  (an include, ``core.worktree``, an unknown key) is refused with the key named (``GitUnsafe``). A non-empty
  ``info/attributes``, a ``config.worktree`` file or a config git cannot read is refused too, as are a common dir
  that differs from the git dir, a ``commondir`` or ``gitdir`` pointer file and ``objects/info/alternates``. The
  audited files are held (Windows: no write, rename or delete sharing) from the audit until the command ends and
  re-hashed afterwards (``repoaudit``); the audit is repeated on every call and is not cached, unless the caller opens a
``gitsession.GitSession``, which holds the same files once, audits once and verifies after every command.
"""

from __future__ import annotations

import functools
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .nofollow import PortableFs, default_fs
from .repoaudit import fingerprint, held, inspect_repo_local

CRASH_STATUS = 0xC0000000  # a Windows exception status: the process did not exit
PRISTINE_CONFIG = (
    b"[core]\n\trepositoryformatversion = 0\n\tfilemode = false\n\tbare = true\n\tautocrlf = false\n"
    b"\tsafecrlf = false\n\tfsmonitor = false\n\tquotepath = false\n[gc]\n\tauto = 0\n"
)


@functools.cache
def _default_fs() -> PortableFs:
    return default_fs()


class GitFailed(RuntimeError):
    """Git said no (``crashed`` False) or died or did not finish in time (``crashed`` True)."""

    def __init__(self, message: str, *, crashed: bool = False) -> None:
        super().__init__(message)
        self.crashed = crashed


class GitUnsafe(RuntimeError):
    """The repository holds something that could make git run a command, so no git call was made."""


class HoldRefused(GitUnsafe):
    """A held session could not start because a file of the git directory could not be held (a sharing violation).

    Nothing was found wrong with the repository: someone else has the file open. The service refuses or holds the one
    hand-in it was working on and goes on to the next; it never halts the lane for this.
    """


def audit_repo_local(runner: GitRunner) -> list[str]:
    """What stops ``direct`` from running at all. An empty list means every risky key can be neutralised."""
    return inspect_repo_local(runner)[1]


@dataclass(frozen=True)
class GitRunner:
    git_path: str  # the pinned absolute path of git, injected by the caller
    git_dir: Path
    hooks_dir: Path  # an empty folder
    cwd: Path  # supplied by the caller; temporary index files live under it too
    audit: bool = False  # True for ``direct``: inspect the real config on every call
    safe_directory: Path | None = None  # the checkout, given on the command line (the only place git honours it)
    timeout: float = 60.0
    fs: PortableFs | None = None  # the file-holding seam; default is the real one for this platform
    slot: Any = field(default=None, compare=False)  # a ``gitsession.SessionSlot``: lets one audit cover a run of calls

    def __post_init__(self) -> None:
        if not os.path.isabs(self.git_path) or not os.path.isfile(self.git_path):
            raise ValueError("git must be given as the absolute path of an existing file")

    def env(self, index: Path | None = None, *, repo: bool = True) -> dict[str, str]:
        here = os.path.abspath(self.git_dir)
        env = {
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "TMP": str(self.cwd),
            "TEMP": str(self.cwd),
            "GIT_DIR": here,
            "GIT_COMMON_DIR": here,  # makes git ignore any ``commondir`` file, however late it appears
            "GIT_OBJECT_DIRECTORY": os.path.join(here, "objects"),
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": "",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
        }
        if index is not None:
            env["GIT_INDEX_FILE"] = str(index)
        if not repo:  # reading a config file needs no repository, and a hostile one must not get to break the read
            for name in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY"):
                del env[name]
            env["GIT_CEILING_DIRECTORIES"] = str(self.cwd)
        return env

    def run(
        self, *args: str, data: bytes | None = None, index: Path | None = None, check: bool = True, repo: bool = True
    ) -> subprocess.CompletedProcess[bytes]:
        live = self.slot.active() if self.slot is not None else None
        if live is not None:  # an open ``GitSession`` of this thread: audited once, held, verified after every command
            return live.run(self, args, data, index, check, repo)
        if not self.audit:
            return self._spawn(args, [], data, index, check, repo)
        try:
            with held(self.fs or _default_fs(), self.git_dir):  # nothing audited may change until the command is done
                before = fingerprint(self.git_dir)
                extra, found = inspect_repo_local(self)
                if found:
                    raise GitUnsafe("; ".join(found))
                done = self._spawn(args, extra, data, index, check, repo)
                if fingerprint(self.git_dir) != before:
                    raise GitUnsafe("the repository config changed while git ran; the result is discarded")
                return done
        except PermissionError as exc:
            raise HoldRefused(str(exc)) from exc

    def _spawn(self, args, extra, data, index, check, repo) -> subprocess.CompletedProcess[bytes]:
        extra = list(extra)
        if self.safe_directory is not None:
            extra += ["-c", f"safe.directory={self.safe_directory.as_posix()}"]
        command = [
            self.git_path,
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.attributesFile={os.devnull}",
            "-c",
            f"core.hooksPath={self.hooks_dir}",
            *extra,
            *args,
        ]
        try:
            done = subprocess.run(
                command,
                cwd=self.cwd,
                env=self.env(index, repo=repo),
                input=data,
                stdin=None if data is not None else subprocess.DEVNULL,
                capture_output=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitFailed(f"git {args[0]} did not finish in {self.timeout} seconds", crashed=True) from exc
        if done.returncode < 0 or done.returncode >= CRASH_STATUS:
            raise GitFailed(f"git {args[0]} died with status {done.returncode}", crashed=True)
        if check and done.returncode:
            raise GitFailed(f"git {args[0]} failed: {done.stderr.decode('utf-8', 'replace')[:200]}")
        return done

    def text(self, *args: str, **kwargs: object) -> str:
        return self.run(*args, **kwargs).stdout.decode("utf-8", "replace").strip()  # type: ignore[arg-type]


def isolated_view(git_path: str, real_git_dir: Path, root: Path, cwd: Path | None = None) -> GitRunner:
    """A runner in a private git directory under ``root`` that reads ``real_git_dir``'s objects and nothing else."""
    objects = real_git_dir / "objects"
    if not objects.is_dir():
        raise GitUnsafe(f"{real_git_dir} has no objects folder")
    view, hooks = root / "gitview", root / "empty-hooks"
    for folder in (view / "objects" / "info", view / "refs" / "heads", view / "info", hooks):
        folder.mkdir(parents=True, exist_ok=True)
    fixed = {
        view / "HEAD": b"ref: refs/heads/dev\n",
        view / "config": PRISTINE_CONFIG,
        view / "objects" / "info" / "alternates": objects.resolve().as_posix().encode() + b"\n",
    }
    for path, content in fixed.items():
        if not path.is_file() or path.read_bytes() != content:
            path.write_bytes(content)
    (view / "info" / "attributes").unlink(missing_ok=True)
    return GitRunner(git_path, view, hooks, cwd or root)


def direct(
    git_path: str, real_git_dir: Path, hooks_dir: Path, cwd: Path, safe_directory: Path | None = None, slot: Any = None
) -> GitRunner:
    """A runner in the real git directory. Risky keys are neutralised per call; unknown ones refuse the call.

    ``hooks_dir`` must be the referee's own empty, administrator-owned folder. ``safe_directory`` is the checkout
    (default: the folder holding ``.git``), supplied on the command line because git ignores it in repo config.
    """
    checkout = safe_directory or (real_git_dir.parent if real_git_dir.name == ".git" else None)
    return GitRunner(git_path, real_git_dir, hooks_dir, cwd, audit=True, safe_directory=checkout, slot=slot)
