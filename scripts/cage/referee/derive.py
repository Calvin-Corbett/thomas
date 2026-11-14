"""Derive what a patch changes from git's own tree comparison, never from the patch's text.

The patch is applied to a private index read from the current ``dev`` tip, git writes the resulting tree, and the
change is the tree diff with modes (``diff-tree --raw -z -M -C``). Sizes and content of the new blobs come from two
batched ``cat-file`` calls. Nothing here looks at a header line of the patch or at any ``submission.json`` field,
and nothing is written to the working copy or to ``dev``: the only writes are a temporary index file and the
objects git makes in the runner's private directory.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .charter import Charter, Decision, decide
from .gitenv import GitFailed, GitRunner

SHA = re.compile(r"[0-9a-f]{40}")
READ_LIMIT = 64  # changes beyond this are never read: the Charter's file cap demotes them first
MAX_BLOB = 8192  # a blob larger than this is measured, never read
FRAGMENT_DIR = "changelog.d"


class DeriveFailed(Exception):
    """The change could not be derived; the submission goes to Regular with this code."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class Change:
    status: str
    old_mode: str
    new_mode: str
    old_sha: str
    new_sha: str
    path: str
    old_path: str | None = None


@dataclass(frozen=True)
class Derived:
    tip: str
    tree: str
    changes: tuple[Change, ...]
    sizes: dict[str, int]  # new blob sha -> size in bytes, -1 when git has no such blob
    blobs: dict[str, bytes]  # content of the new blobs that are small enough to read
    existing_names: frozenset[str]  # names already under changelog.d at the tip, for casefold collisions


def parse_raw(raw: bytes) -> tuple[Change, ...]:
    """Parse ``diff-tree --raw -z`` output: ``:old new osha nsha status NUL path [NUL path2]``."""
    parts, changes, at = raw.split(b"\0"), [], 0
    while at < len(parts) and parts[at]:
        meta = parts[at].decode("ascii", "replace").lstrip(":").split()
        if len(meta) != 5:
            raise DeriveFailed("unreadable_diff", "a raw diff line had an unexpected shape")
        two = meta[4][:1] in ("R", "C")
        names = [n.decode("utf-8", "replace") for n in parts[at + 1 : at + 1 + (2 if two else 1)]]
        changes.append(Change(meta[4][:1], meta[0], meta[1], meta[2], meta[3], names[-1], names[0] if two else None))
        at += 2 + two
    return tuple(changes)


def parse_batch(data: bytes) -> dict[str, bytes]:
    """Parse ``cat-file --batch`` output into sha -> content for the blobs git found."""
    found, at = {}, 0
    while at < len(data):
        end = data.index(b"\n", at)
        head = data[at:end].split()
        if len(head) == 3 and head[1] == b"blob":
            size = int(head[2])
            found[head[0].decode()] = data[end + 1 : end + 1 + size]
            at = end + 1 + size + 1
        else:
            at = end + 1
    return found


def derive(git: GitRunner, tip: str, patch: bytes) -> Derived:
    """The change ``patch`` makes to the tree at ``tip``, as git sees it.

    Raises ``DeriveFailed`` for a bad or missing tip (``bad_tip``, ``tip_missing``), a patch git cannot apply and any
    other git refusal (``git_failed``). A git that crashed or hung raises ``GitFailed`` with ``crashed`` True.
    """
    if not SHA.fullmatch(tip):
        raise DeriveFailed("bad_tip", "the dev tip must be a full commit id")
    if git.run("rev-parse", "--verify", "--quiet", f"{tip}^{{commit}}", check=False).returncode:
        raise DeriveFailed("tip_missing", f"git has no commit {tip}")
    try:
        return _derive(git, tip, patch)
    except GitFailed as exc:
        if exc.crashed:
            raise
        raise DeriveFailed("git_failed", str(exc)) from exc


def _derive(git: GitRunner, tip: str, patch: bytes) -> Derived:
    index = Path(tempfile.mkdtemp(prefix="idx-", dir=git.cwd)) / "index"
    try:
        git.run("read-tree", tip, index=index)
        try:
            git.run("apply", "--cached", "--binary", "--whitespace=nowarn", "-", data=patch, index=index)
        except GitFailed as exc:
            if exc.crashed:
                raise
            raise DeriveFailed("patch_does_not_apply", str(exc)) from exc
        tree = git.text("write-tree", index=index)
    finally:
        index.unlink(missing_ok=True)
        os.rmdir(index.parent)
    raw = git.run("diff-tree", "-r", "-z", "-M", "-C", "--raw", "--no-abbrev", "--no-ext-diff", f"{tip}^{{tree}}", tree)
    changes = parse_raw(raw.stdout)
    shas = [c.new_sha for c in changes if c.new_mode not in ("160000", "000000")]
    sizes = {s: -1 for s in shas}
    blobs: dict[str, bytes] = {}
    if shas and len(changes) <= READ_LIMIT:
        check = git.run("cat-file", "--batch-check", data="".join(f"{s}\n" for s in shas).encode())
        for line in check.stdout.decode("ascii", "replace").splitlines():
            head = line.split()
            if len(head) == 3 and head[1] == "blob":
                sizes[head[0]] = int(head[2])
        small = [s for s in shas if 0 <= sizes[s] <= MAX_BLOB]
        if small:
            blobs = parse_batch(git.run("cat-file", "--batch", data="".join(f"{s}\n" for s in small).encode()).stdout)
    names = git.run("ls-tree", "--name-only", "-z", tip, f"{FRAGMENT_DIR}/").stdout
    existing = frozenset(n.decode("utf-8", "replace").rsplit("/", 1)[-1] for n in names.split(b"\0") if n)
    return Derived(tip, tree, changes, sizes, blobs, existing)


TIP_CODES = {"bad_tip", "tip_missing"}


def evaluate(git: GitRunner, tip: str, patch: bytes, charter: Charter) -> Decision:
    """The lane for ``patch`` at ``tip``.

    A patch git cannot apply, or any other git refusal, demotes to Regular. A bad or missing ``tip`` raises
    ``DeriveFailed`` (the caller's tip is wrong, not the patch), and a crashed or hung git raises ``GitFailed``.
    """
    try:
        return decide(derive(git, tip, patch), charter)
    except DeriveFailed as exc:
        if exc.code in TIP_CODES:
            raise
        return Decision("regular", exc.code, exc.detail)
