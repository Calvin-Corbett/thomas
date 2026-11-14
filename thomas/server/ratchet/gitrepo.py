"""Git for the ratchet, on a repository named explicitly.

Every call names its repository (``git -C``) and drops every inherited ``GIT_*``
variable: one left over from whatever started the server would point these calls
at another repository. A green is named by its own git folder (``GIT_DIR``),
never through the ``.git`` pointer file in its work folder, which anything
running in the green can rewrite.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

_TIMEOUT_S = 600.0


class GitFailed(RuntimeError):
    """A git command the ratchet needed did not succeed."""


@dataclass(frozen=True)
class Repo:
    path: Path
    env: dict[str, str] = field(default_factory=dict)

    def _command(self, *args: str) -> list[str]:
        return ["git", "-C", str(self.path), "-c", "core.quotepath=off", "-c", "core.fsmonitor=false", *args]

    def _env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
        env.update(self.env)
        return env

    def run(self, *args: str, ok: Sequence[int] = (0,)) -> subprocess.CompletedProcess[str]:
        command = self._command(*args)
        env = self._env()
        try:
            done = subprocess.run(
                command,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise GitFailed(f"git {' '.join(args[:2])} could not run: {exc}") from exc
        if done.returncode not in ok:
            raise GitFailed(f"git {' '.join(args[:2])} exited {done.returncode}: {done.stderr.strip()[:300]}")
        return done

    def out(self, *args: str) -> str:
        return self.run(*args).stdout.strip()

    def blobs(self, oids: Sequence[str]) -> dict[str, bytes]:
        """Each blob in *oids*, byte for byte, read by one ``git cat-file --batch`` process.

        The proof set is chosen from the text of every test file (``proof_set.select``). Read with one
        ``git show`` per file, that was 1,787 git processes and 130-322 s for each selection on dev
        (measured 2026-10-07, 1,783 test files), paid once early and again on the green.
        """
        wanted = list(dict.fromkeys(oids))
        if not wanted:
            return {}
        try:
            done = subprocess.run(
                self._command("cat-file", "--batch"),
                env=self._env(),
                input="".join(f"{oid}\n" for oid in wanted).encode("ascii"),
                capture_output=True,
                timeout=_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, UnicodeEncodeError) as exc:
            raise GitFailed(f"git cat-file --batch could not run: {exc}") from exc
        if done.returncode != 0:
            why = done.stderr.decode("utf-8", "replace").strip()[:300]
            raise GitFailed(f"git cat-file --batch exited {done.returncode}: {why}")
        return _batch(done.stdout, wanted)

    def sha(self, rev: str) -> str:
        """The full commit id *rev* names; GitFailed when it names none."""
        return self.out("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")

    def has_path(self, rev: str, path: str) -> bool:
        return self.run("cat-file", "-e", f"{rev}:{path}", ok=(0, 1, 128)).returncode == 0

    def runner(self) -> Callable[[Sequence[str]], str]:
        """This repository as the custodian's git edge (``branch_custodian.GitRunner``)."""

        def _run(args: Sequence[str]) -> str:
            return self.run(*args).stdout

        return _run

    @contextlib.contextmanager
    def scratch(self) -> Iterator[Repo]:
        """This repository, writing any new object to a temporary store removed afterwards.

        ``git merge-tree --write-tree`` writes the merged tree. Measured on a
        scratch repository (2026-09-24): with ``GIT_OBJECT_DIRECTORY`` pointed at a
        temporary folder and the real store as an alternate, the real store gained
        no object. A merge is measured without writing to the running copy, by an
        account that may only read it.
        """
        common = Path(self.out("rev-parse", "--path-format=absolute", "--git-common-dir"))
        store = Path(tempfile.mkdtemp(prefix="ratchet-objects-"))
        try:
            yield Repo(
                self.path,
                {
                    **self.env,
                    "GIT_OBJECT_DIRECTORY": str(store),
                    "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(common / "objects"),
                },
            )
        finally:
            shutil.rmtree(store, ignore_errors=True)


def _batch(data: bytes, wanted: Sequence[str]) -> dict[str, bytes]:
    """``git cat-file --batch``'s answer, one "<oid> <type> <size>" line, the content and a newline per object."""
    found: dict[str, bytes] = {}
    at = 0
    for oid in wanted:
        end = data.find(b"\n", at)
        header = data[at:end].decode("ascii", "replace").split() if end >= 0 else []
        if len(header) != 3 or not header[2].isdigit():
            raise GitFailed(f"git cat-file --batch did not return {oid}: {' '.join(header) or 'no answer'}")
        size = int(header[2])
        if end + 1 + size > len(data):
            raise GitFailed(f"git cat-file --batch cut {oid} short")
        found[oid] = data[end + 1 : end + 1 + size]
        at = end + 1 + size + 1
    return found


__all__ = ["GitFailed", "Repo"]
