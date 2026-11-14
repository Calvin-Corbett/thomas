"""Git facts about a place, read without running anything the place holds (design section 3).

Nothing here runs git inside a place. Refs, HEAD and the stash log are parsed by this module through the no-follow
seam. A linked worktree's git folder is taken from the main repository's registration, never from the ``.git`` file
in the worktree. Every git call runs in a private view (``make_view``): fixed config, an empty hooks folder, the
attributes file set to null, fsmonitor off and replace objects off, reading the place's objects (and the main
repository's) through alternates. The place's own config, hooks, attributes and info files are never read by git.
No git call names the place: ignore rules are judged against ``IgnoreShadow``, a private copy of the place's folder
shape and ``.gitignore`` files, because ``check-ignore`` moves git's current folder into its work tree.

Refs and blobs are read here. The rest lives in ``gitplace_files`` (the refusal and small-file reads),
``gitplace_locate`` (where a place's git data lives), ``gitplace_view`` (the private view and the commands run in it)
and ``gitplace_ignore`` (ignore rules), and is re-exported, so every ``from scripts.keeper.gitplace import`` stands.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from scripts.cage.referee.gitenv import GitFailed, GitRunner
from scripts.cage.referee.nofollow import UnsafeEntry

from .gitplace_files import Unreadable, _norm, _plain_folder, small
from .gitplace_ignore import IGNORE_LIMIT, IgnoreShadow, check_ignored
from .gitplace_locate import GitPlace, check_alternates, locate
from .gitplace_view import commit_log, ls_index, ls_tree, make_view, objects_size, unique_count, write_bundle
from .places import read_in_place, walk

HEX = re.compile(r"[0-9a-f]{40}")
BATCH = 1000
BATCH_BYTES = 64 * 1024 * 1024  # blob content held in memory at once
INDEX_LIMIT = 64 * 1024 * 1024  # the live checkout's index is 0.6 MB (2026-10-09); one bigger than this is refused
PACKED_REFS_LIMIT = 32 * 1024 * 1024
STASH_LIMIT = 16 * 1024 * 1024


def read_refs(fs, common: Path, problems: list[dict] | None = None) -> dict[str, str]:
    """Every ref of a repository, from ``packed-refs`` and loose files, parsed here (loose wins).

    With ``problems``, a ``packed-refs`` that cannot be read is listed there and the loose refs are still read.
    """
    refs: dict[str, str] = {}
    symbolic: dict[str, str] = {}
    try:
        packed = small(fs, common / "packed-refs", PACKED_REFS_LIMIT)
    except Unreadable as exc:
        if problems is None:
            raise
        problems.append({"path": "git:packed-refs", "code": "unreadable", "detail": str(exc)[:300]})
        packed = None
    for line in (packed or b"").decode("utf-8", "replace").splitlines():
        sha, _, name = line.partition(" ")
        if HEX.fullmatch(sha) and name.startswith("refs/"):
            refs[name] = sha
    if (common / "refs").is_dir():
        found = walk(fs, common / "refs")
        for rel in found.files:
            try:
                text = read_in_place(fs, common / "refs", rel, 4096)[0].decode("utf-8", "replace").strip()
            except UnsafeEntry:
                continue
            if HEX.fullmatch(text):
                refs["refs/" + rel] = text
            elif text.startswith("ref: "):
                symbolic["refs/" + rel] = text[5:].strip()
    for name, target in symbolic.items():
        if target in refs:
            refs[name] = refs[target]
    return refs


def read_head(fs, git_dir: Path, refs: dict[str, str]) -> str | None:
    text = (small(fs, git_dir / "HEAD", 4096) or b"").decode("utf-8", "replace").strip()
    if HEX.fullmatch(text):
        return text
    if text.startswith("ref: "):
        return refs.get(text[5:].strip())  # None: an unborn branch
    raise Unreadable(f"{git_dir / 'HEAD'} is neither a ref nor a commit id")


def stash_tips(fs, common: Path) -> list[str]:
    """Stash entries newest first, from ``logs/refs/stash``."""
    data = small(fs, common / "logs" / "refs" / "stash", STASH_LIMIT) or b""
    tips = []
    for line in data.decode("utf-8", "replace").splitlines():
        fields = line.split(" ")
        if len(fields) > 1 and HEX.fullmatch(fields[1]):
            tips.append(fields[1])
    return tips[::-1]


def cat_blobs(runner: GitRunner, oids) -> dict[str, bytes]:
    """The content of each blob found (missing ones are left out)."""
    unique, found = sorted(set(oids)), {}
    for start in range(0, len(unique), BATCH):
        chunk = unique[start : start + BATCH]
        out = runner.run("cat-file", "--batch", data=("\n".join(chunk) + "\n").encode()).stdout
        pos = 0
        while pos < len(out):
            end = out.index(b"\n", pos)
            head = out[pos:end].split()
            if len(head) == 2 and head[1] == b"missing":
                pos = end + 1
                continue
            size = int(head[2])
            found[head[0].decode()] = out[end + 1 : end + 1 + size]
            pos = end + 1 + size + 1
    return found


def present(runner: GitRunner, oids) -> set[str]:
    return set(blob_sizes(runner, oids))


def blob_sizes(runner: GitRunner, oids) -> dict[str, int]:
    """``oid -> size`` for each object found (missing ones are left out), without reading any content."""
    unique, sizes = sorted(set(oids)), {}
    for start in range(0, len(unique), BATCH):
        out = runner.run("cat-file", "--batch-check", data=("\n".join(unique[start : start + BATCH]) + "\n").encode())
        for line in out.stdout.decode().splitlines():
            fields = line.split()
            if len(fields) == 3 and fields[2].isdigit():
                sizes[fields[0]] = int(fields[2])
    return sizes


def blobs_in_order(
    runner: GitRunner, oids: list[str], limit: int, batch_bytes: int = BATCH_BYTES
) -> Iterator[tuple[str, bytes | None, str | None]]:
    """``(oid, content, None)`` for each oid in order, or ``(oid, None, "too_large" | "missing")``.

    Sizes are asked first, so a blob over ``limit`` is never read, and at most ``batch_bytes`` of content (or one
    blob, when a single one is bigger) is held at a time. Object sizes are whatever the place's objects say.
    """
    order = list(oids)
    sizes = blob_sizes(runner, order)

    def weight(oid: str) -> int:
        return sizes[oid] if sizes.get(oid, limit + 1) <= limit else 0

    start = 0
    while start < len(order):
        end, held = start + 1, weight(order[start])
        while end < len(order) and end - start < BATCH and held + weight(order[end]) <= batch_bytes:
            held += weight(order[end])
            end += 1
        chunk = order[start:end]
        got = cat_blobs(runner, [o for o in chunk if weight(o) or sizes.get(o) == 0])
        for oid in chunk:
            if oid in got:
                yield oid, got[oid], None
            else:
                yield oid, None, "missing" if oid not in sizes else "too_large"
        start = end
