"""Which gates a rebased landing may leave standing after the branch moved under it. Stdlib only.

A landing builds its temporary index from the branch tip it read (the base). When a neighbour lands first the tip moves,
the swap would lose, and the landing rebases: it rebuilds the index on the new tip and tries again. This module decides
what that next attempt has to judge again. The rule is conservative by construction: EVERY gate runs again unless it is
named below, and a gate added to the registry tomorrow is not named below.

Two kinds of pass are kept:

* ``active_folder_guard`` scans every process on the machine (4.4 s of a 6 s ladder) to ask whether another agent is working
  in the same folders. Within one landing the answer from a few seconds ago is the answer, and the project already holds
  that a message arriving during a gate run "cannot concern work that is already done" (workboard_inbox.py). Its pass is
  reused for LIVE_REUSE_SECONDS inside the SAME landing. It is never carried to another landing or another process, so there
  is no cache anything else could write.

* ``exception_handler`` (4.6 s, the longest gate once the guard is reused) reads the staged diff of the selected paths, the
  base's blob of each selected path, and the safety policy. A pass is kept only against a FINGERPRINT of exactly those
  inputs, taken from this attempt's own index: the index entry and the base's tree entry of every selected path, and the
  bytes of each file in FINGERPRINTED. Any difference, in any of them, and the gate runs again. That includes a neighbour
  that changed the policy or the gate's own code, a selected file that was edited between two attempts, and a selected path
  the neighbour changed.

What this replaces, and why. The first version kept the pass of 17 "selection only" gates unless the neighbour's commit
touched a selected path. Review found three ways that let a landing through that a fresh run would refuse: a neighbour
that changed agent_safety.toml, pyproject.toml or a gate (none of them a selected path); a selected file edited between
two attempts (the index is rebuilt from the working tree each time, the old pass judged older bytes); and gates such as
commit_growth and protected_files that also consult the break-glass state, which can end between two attempts. Only
exception_handler was read through to its last input, so only it is kept. The others cost 0.2 to 0.4 s each.

``tests/test_commit_gate_reuse.py`` holds each input to a test, and holds the watch list to the gate's own imports.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from scripts.crew.brief import git_reads

LIVE_REUSE_SECONDS = 60.0
REUSABLE_LIVE = frozenset({"active_folder_guard"})
# Gate -> the working-tree files it reads besides the selected paths (the policy file and its local overlay, the gate's
# script, and the one module that script imports from this repo). Anything else the gate reads is the index and base blobs
# of the selected paths, which the fingerprint covers.
FINGERPRINTED: dict[str, tuple[str, ...]] = {
    "exception_handler": (
        "agent_safety.toml",
        "agent_safety.local.toml",
        "scripts/forge/gates/exception_handler_gate.py",
        "scripts/crew/brief/safety_config.py",
    ),
}


@dataclass(frozen=True)
class Passed:
    """A gate's last trusted pass: it ran with the tip still on its base, and exited 0."""

    finished: float  # a monotonic clock reading
    fingerprint: str | None = None  # of its inputs, for the gates in FINGERPRINTED


def watch_digest(repo_root: Path | str, files: Iterable[str]) -> str:
    """One digest over the bytes of ``files`` (working tree). A file that cannot be read never digests the same twice."""
    digest = hashlib.sha256()
    for relative in files:
        try:
            part = hashlib.sha256((Path(repo_root) / relative).read_bytes()).hexdigest()
        except FileNotFoundError:
            part = "absent"
        except OSError:
            part = "unreadable-" + os.urandom(8).hex()
        digest.update(f"{relative}\0{part}\0".encode())
    return digest.hexdigest()


def _tree_part(repo_root: Path | str, args: Sequence[str], env: dict[str, str]) -> bytes | None:
    try:
        proc = git_reads.run_git(repo_root, args, env={**env, "GIT_LITERAL_PATHSPECS": "1"})
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


class Fingerprints:
    """The inputs of one attempt's gates, digested lazily and at most once per gate.

    The working-tree files are digested when this is built, before any gate of the attempt runs, and again when a pass is
    about to be kept: a file that changed while the gate ran means the gate judged something that no longer exists.
    """

    def __init__(
        self,
        repo_root: Path | str,
        *,
        index_env: dict[str, str],
        base: str,
        selected: Iterable[str],
    ):
        self.repo_root, self.index_env, self.base = repo_root, index_env, base
        self.selected = sorted({str(path) for path in selected})
        self._watch = {name: watch_digest(repo_root, files) for name, files in FINGERPRINTED.items()}
        self._memo: dict[str, str | None] = {}

    def of(self, name: str) -> str | None:
        """The fingerprint, or None when the gate is not fingerprinted or git could not say."""
        if name not in FINGERPRINTED:
            return None
        if name not in self._memo:
            self._memo[name] = self._take(name)
        return self._memo[name]

    def _take(self, name: str) -> str | None:
        if not self.selected:
            return None
        paths = ["--", *self.selected]
        staged = _tree_part(self.repo_root, ["ls-files", "-s", "-z", *paths], self.index_env)
        committed = _tree_part(self.repo_root, ["ls-tree", "-r", "-z", self.base, *paths], dict(os.environ))
        if staged is None or committed is None:
            return None
        digest = hashlib.sha256()
        for part in (staged, committed, self._watch[name].encode()):
            digest.update(len(part).to_bytes(8, "big") + part)
        return digest.hexdigest()

    def stamp(self, name: str) -> str | None:
        """The fingerprint to keep with a pass that just finished, or None when the pass must not be kept."""
        if watch_digest(self.repo_root, FINGERPRINTED.get(name, ())) != self._watch.get(name):
            return None
        return self.of(name)


def rerun_set(
    names: Iterable[str],
    passed: Mapping[str, Passed],
    *,
    now: float,
    fingerprint_of: Callable[[str], str | None],
) -> set[str]:
    """The gates (by name) the next attempt must run."""
    again: set[str] = set()
    for name in names:
        record = passed.get(name)
        if record is None:
            again.add(name)
        elif name in REUSABLE_LIVE:
            if now - record.finished > LIVE_REUSE_SECONDS:
                again.add(name)
        elif name in FINGERPRINTED:
            current = fingerprint_of(name)
            if current is None or record.fingerprint != current:
                again.add(name)
        else:
            again.add(name)
    return again
