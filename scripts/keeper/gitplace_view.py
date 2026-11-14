"""The private git view every git call runs in, and the listing, history and bundle commands run there.

``make_view`` is a bare git folder under the capture's work folder that reads the given object folders through
alternates and nothing else of theirs; no call here names the place. Part of ``gitplace`` (see its notes), which
re-exports these names.
"""

from __future__ import annotations

import os
from pathlib import Path

from scripts.cage.referee.gitenv import PRISTINE_CONFIG, GitRunner


def make_view(
    git_path: str, root: Path, object_dirs: list[Path], timeout: float = 600.0, name: str = "gitview"
) -> GitRunner:
    """A private bare git folder under ``root`` that reads these object folders and nothing else of theirs."""
    view, hooks = root / name, root / "empty-hooks"
    for folder in (view / "objects" / "info", view / "refs" / "heads", view / "info", hooks):
        folder.mkdir(parents=True, exist_ok=True)
    alternates = b"".join(Path(os.path.abspath(d)).as_posix().encode("utf-8") + b"\n" for d in object_dirs)
    (view / "HEAD").write_bytes(b"ref: refs/heads/dev\n")
    (view / "config").write_bytes(PRISTINE_CONFIG)
    (view / "objects" / "info" / "alternates").write_bytes(alternates)
    return GitRunner(git_path, view, hooks, root, timeout=timeout)


def _path(raw: bytes) -> str:
    return raw.decode("utf-8", "replace")


def ls_tree(runner: GitRunner, rev: str) -> dict[str, tuple[str, str]]:
    """``path -> (mode, blob id)`` for every file of a commit (gitlinks are left out)."""
    out: dict[str, tuple[str, str]] = {}
    for rec in runner.run("ls-tree", "-r", "-z", "--full-tree", rev).stdout.split(b"\0"):
        if rec:
            meta, _, path = rec.partition(b"\t")
            mode, kind, oid = meta.split()
            if kind == b"blob":
                out[_path(path)] = (mode.decode(), oid.decode())
    return out


def ls_index(runner: GitRunner, index_copy: Path, empty: Path) -> dict[str, tuple[str, str, int, bool]]:
    """``path -> (mode, blob id, stage, skip-worktree)`` from a byte copy of a place's index.

    A skip-worktree entry (a sparse checkout) is absent from the folder on purpose, never a deletion. A split index
    fails here and the place reads unreadable.
    """
    out: dict[str, tuple[str, str, int, bool]] = {}
    done = runner.run(f"--work-tree={empty}", "ls-files", "--stage", "-t", "-z", index=index_copy)
    for rec in done.stdout.split(b"\0"):
        if rec:
            meta, _, path = rec.partition(b"\t")
            tag, mode, oid, stage = meta.split()
            if mode != b"160000":
                out.setdefault(_path(path), (mode.decode(), oid.decode(), int(stage), tag == b"S"))
    return out


def objects_size(runner: GitRunner, tips: list[str], nots: list[str]) -> int:
    """Bytes the objects reachable from ``tips`` but not ``nots`` take on disk: about what their bundle will take."""
    return int(runner.text("rev-list", "--objects", "--disk-usage", *tips, "--not", *nots) or 0)


def unique_count(runner: GitRunner, tip: str, nots: list[str]) -> int:
    return int(runner.text("rev-list", "--count", tip, "--not", *nots) or 0)


def commit_log(runner: GitRunner, tips: list[str], nots: list[str], limit: int = 500) -> list[dict]:
    fmt = "--format=%H%x1f%P%x1f%an%x1f%aI%x1f%s%x1f%b%x1e"
    out = runner.run("log", f"--max-count={limit}", fmt, *tips, "--not", *nots).stdout.decode("utf-8", "replace")
    rows = []
    for rec in out.split("\x1e"):
        fields = rec.strip("\n").split("\x1f")
        if len(fields) == 6:
            sha, parents, author, at, subject, body = fields
            rows.append(
                {"sha": sha, "parents": parents.split(), "author": author, "at": at, "subject": subject, "body": body}
            )
    return rows


def write_bundle(runner: GitRunner, tips: list[str], nots: list[str], out_path: Path) -> list[str]:
    """Bundle ``tips`` (as ``refs/keep/<n>`` in the private view) minus what ``nots`` already hold."""
    names = []
    for number, sha in enumerate(tips):
        names.append(f"refs/keep/{number}")
        runner.run("update-ref", names[-1], sha)
    runner.run("bundle", "create", "--quiet", str(out_path), *names, "--not", *nots)
    return names
