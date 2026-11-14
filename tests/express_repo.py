"""A throwaway git repository and folder layout shaped like the one the Express referee works against.

``ExpressLayout`` names the folders (pins, referee state, cage inbox and outbox) under one scratch root, so a test
never has to know the real ``C:/ProgramData`` paths. ``TempGitRepo`` is a real repository on branch ``dev`` whose
commits are deterministic: the clock is injected, the identity is fixed, the environment is scrubbed and git is
called by an absolute path the caller pins. Two labs built with the same clock make identical commit ids.

The repository's own configuration is sealed: the config file git wrote at ``init`` is restored, and
``info/attributes`` removed, before every git call. A fixture or a test that writes into ``.git`` cannot make git run
a command (a ``filter`` or ``textconv`` driver, say); ``config_resets`` counts how often that was needed.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from tests.express_fakes import FakeClock
from tests.express_winfs import EnvironmentUnavailable

CRASH_STATUS = 0xC0000000  # a Windows exception status (stack overflow, access violation): the process did not exit


class ChildCrashed(RuntimeError):
    """A git child died by signal or exception, or did not finish in time. Different from git saying "no"."""


BASE_FILES: dict[str, bytes] = {
    "README.md": b"# scratch repo\n",
    "changelog.d/existing-fragment.md": b"### Added\n- A fragment that is already in the tree.\n",
    "thomas/core/leaf.py": b"VALUE = 1\n",
    "scripts/cage/self_change_promoter.py": b"PROMOTER = True\n",
    "docs/notes.md": b"plain notes\n",
}


EOL_RULES = b"* text=auto\n*.md text eol=crlf\n"


def resolved_git() -> str:
    """The absolute path of the git found on this machine's PATH; a test skips when there is none.

    This only looks the binary up. The referee's real pin (a path whose hash is checked) is the installer's job.
    """
    found = shutil.which("git")
    if not found:
        raise EnvironmentUnavailable("git is not installed here")
    return str(Path(found).resolve())


class ExpressLayout:
    """Every folder the referee and the cage use, under one scratch root."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.pins = root / "ThomasPins"
        self.referee = root / "ThomasReferee"
        self.state = self.referee / "state"
        self.hooks = self.referee / "empty-hooks"
        self.cage = root / "ThomasCage"
        self.inbox = self.cage / "inbox"
        self.outbox = self.cage / "outbox"
        self.requests = self.cage / "express-requests"
        self.repo = root / "repo"

    def build(self) -> ExpressLayout:
        for folder in (self.pins, self.state, self.inbox, self.outbox, self.requests, self.hooks):
            folder.mkdir(parents=True, exist_ok=True)
        return self

    def write_pin(self, name: str, data: bytes | str) -> str:
        """Write a pin file and return its sha256, the way a manifest would record it."""
        raw = data.encode("utf-8") if isinstance(data, str) else data
        (self.pins / name).write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    sha: str


class TempGitRepo:
    """A real repository on branch ``dev``, made and moved only through deterministic commits."""

    def __init__(self, root: Path, clock: FakeClock, hooks: Path, git_path: str | None = None) -> None:
        self.root = root
        self.clock = clock
        self.hooks = hooks
        self.git_path = git_path or resolved_git()
        self.autocrlf = False
        self.config_resets = 0
        self._sealed: bytes | None = None  # the config git writes at init, once there is one
        root.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "dev")
        self._sealed = (root / ".git" / "config").read_bytes()

    def _seal(self) -> None:
        """Put the config git wrote at ``init`` back and drop ``info/attributes``: no fixture content configures git."""
        config = self.root / ".git" / "config"
        if self._sealed is not None and config.read_bytes() != self._sealed:
            config.write_bytes(self._sealed)
            self.config_resets += 1
        (self.root / ".git" / "info" / "attributes").unlink(missing_ok=True)

    def filtered_bytes(self, blob: str, path: str) -> bytes:
        """The bytes git would write to the working copy for ``blob`` at ``path``."""
        return self.git("cat-file", "--filters", f"--path={path}", blob).stdout

    def move_dev(self, note: str = "dev moved") -> str:
        """Advance ``dev`` by one commit that touches nothing a fixture uses; returns the new head."""
        return self.commit_files({f"docs/moved-{self.clock.monotonic():.0f}.md": note.encode() + b"\n"}, note)

    def env(self, **extra: str) -> dict[str, str]:
        """The scrubbed environment: no inherited git variables, no user or system config, fixed identity."""
        date = self.clock.git_date()
        env = {
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_AUTHOR_NAME": "lab",
            "GIT_AUTHOR_EMAIL": "lab@example.invalid",
            "GIT_COMMITTER_NAME": "lab",
            "GIT_COMMITTER_EMAIL": "lab@example.invalid",
            "GIT_AUTHOR_DATE": date,
            "GIT_COMMITTER_DATE": date,
        }
        env.update(extra)
        return env

    def git(
        self, *args: str, data: bytes | None = None, check: bool = True, **env: str
    ) -> subprocess.CompletedProcess[bytes]:
        self._seal()
        command = [
            self.git_path,
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.autocrlf={'true' if self.autocrlf else 'false'}",
            "-c",
            f"core.hooksPath={self.hooks}",
            "-c",
            "core.quotepath=false",
            *args,
        ]
        try:
            done = subprocess.run(
                command, cwd=self.root, env=self.env(**env), input=data, capture_output=True, timeout=60
            )
        except subprocess.TimeoutExpired as exc:
            raise ChildCrashed(f"git {' '.join(args)} did not finish in 60 seconds") from exc
        if done.returncode < 0 or done.returncode >= CRASH_STATUS:
            raise ChildCrashed(f"git {' '.join(args)} died with status {done.returncode}")
        if check and done.returncode:
            raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.decode('utf-8', 'replace')[:300]}")
        return done

    def text(self, *args: str, **env: str) -> str:
        return self.git(*args, **env).stdout.decode("utf-8", "replace").strip()

    def commit_files(self, files: Mapping[str, bytes | str], message: str) -> str:
        """Write files into the working copy and commit exactly them. The clock moves one minute."""
        for rel, content in files.items():
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        self.git("add", "--", *files)
        self.clock.advance(60)
        self.git("commit", "-q", "-m", message)
        return self.head()

    def head(self) -> str:
        return self.text("rev-parse", "HEAD")

    def entry(self, data: bytes, mode: str = "100644") -> TreeEntry:
        sha = self.git("hash-object", "-w", "--stdin", data=data).stdout.decode().strip()
        return TreeEntry(mode, sha)

    def _private_tree(self, base: str, build: Mapping[str, TreeEntry | None] | bytes) -> str:
        """The tree id of ``base`` plus tree edits (a mapping) or plus a patch (bytes), in a private index.

        ``base`` is resolved to one commit first, so a moving ``dev`` cannot give the index and the comparison
        different trees. Neither the working copy nor ``dev`` moves.
        """
        index = str(self.root / ".git" / "lab-index")
        Path(index).unlink(missing_ok=True)
        try:
            self.git("read-tree", base, GIT_INDEX_FILE=index)
            if isinstance(build, bytes):
                self.git("apply", "--cached", "-", data=build, GIT_INDEX_FILE=index)
            for path, entry in (build if isinstance(build, Mapping) else {}).items():
                if entry is None:
                    self.git("update-index", "--force-remove", "--", path, GIT_INDEX_FILE=index)
                else:
                    cacheinfo = f"{entry.mode},{entry.sha},{path}"
                    self.git("update-index", "--add", "--cacheinfo", cacheinfo, GIT_INDEX_FILE=index)
            return self.text("write-tree", GIT_INDEX_FILE=index)
        finally:
            Path(index).unlink(missing_ok=True)

    def patch_for(self, edits: Mapping[str, TreeEntry | None], base: str = "HEAD") -> bytes:
        """The real ``git diff --binary`` that turns ``base`` into itself plus these tree edits.

        A value of None removes the path. Modes such as 120000 (symlink) and 160000 (gitlink) go straight into the
        tree, which is how a patch can carry them without the file system ever holding one.
        """
        commit = self.text("rev-parse", base)
        tree = self._private_tree(commit, edits)
        return self.git("diff", "--binary", "--full-index", "-M", f"{commit}^{{tree}}", tree).stdout

    def raw_lines(self, patch: bytes, base: str = "HEAD") -> list[list[str]]:
        """What git itself says a patch changes: ``[old mode, new mode, old sha, new sha, status, *paths]`` per path.

        The paths come from git's tree comparison, never from the patch's text. Git refusing the patch raises.
        """
        commit = self.text("rev-parse", base)
        tree = self._private_tree(commit, patch)
        raw = self.git("diff-tree", "-r", "-M", "--raw", "--no-abbrev", "-z", f"{commit}^{{tree}}", tree).stdout
        parts, rows, at = raw.split(b"\0"), [], 0
        while at < len(parts) and parts[at]:
            meta = parts[at].decode("ascii").lstrip(":").split()
            count = 2 if meta[4][:1] in ("R", "C") else 1
            names = [n.decode("utf-8", "replace") for n in parts[at + 1 : at + 1 + count]]
            rows.append([*meta, *names])
            at += 1 + count
        return rows
