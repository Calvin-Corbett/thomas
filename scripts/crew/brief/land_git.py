"""Git questions land.py asks: the idempotency trailer, "did this change already land?", and bypass counting. Stdlib only.

``find_landed`` never trusts a trailer alone. The key is only agent + message + paths, so a different change with the same
words would match it. A trailer hit counts as "already landed" only when the files that commit changed carry the same
content as the change now waiting (blob comparison) and nothing else in the paths being landed is still modified; with no
``--include`` that needs the commit tool's own staged set, and without it the answer is "not landed". A git question that
gets no answer (a timeout or an error exit) is never proof either: ``git`` returns None for it and the answer is "not
landed". The
search covers an explicit window of the newest commits (``window``); a landing older than that is not found, so the
answer is "not landed" and the change is tried again, which is the safe direction (the commit tool refuses a change that
is already in the tree).
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from scripts.crew.brief import landing_proc

TRAILER = "Landing-Ticket"
CHUNK = 40


def intent_key(agent: str, message: str, includes: Sequence[str], salt: str = "") -> str:
    raw = "\0".join([agent.lower(), message.strip(), ",".join(sorted(includes)), salt])
    return "lq-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def with_key(message: str, key: str) -> str:
    """Add the idempotency trailer to the last paragraph if that is already a trailer block, else as its own."""
    body = message.replace("\r\n", "\n").rstrip()
    last = body.split("\n\n")[-1].splitlines()
    trailer_block = (
        len(body.split("\n\n")) > 1 and last and all(": " in row and " " not in row.split(": ")[0] for row in last)
    )
    return f"{body}\n{TRAILER}: {key}\n" if trailer_block else f"{body}\n\n{TRAILER}: {key}\n"


def git(root: Path, *args: str, timeout: float = 60) -> str | None:
    """git's output, or None when git gave NO answer: it did not answer in ``timeout`` seconds, or it exited with an error.
    None is never the same as empty output. Every caller that could infer "landed" from an answer reads None as "not
    landed" (unproven means not landed); a slow git is said on stderr and never kills the caller."""
    try:
        done = landing_proc.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(
            f"land.py: git {args[0] if args else ''} did not answer in {timeout:g} s; read as no answer",
            file=sys.stderr,
        )
        return None
    return done.stdout if done.returncode == 0 else None


def _chunks(items: list[str]) -> list[list[str]]:
    return [items[i : i + CHUNK] for i in range(0, len(items), CHUNK)]


def _blobs(root: Path, rev: str, paths: list[str]) -> dict[str, str] | None:
    """Blob of each path at ``rev``; None when any part got no answer (never an empty map that compares as equal)."""
    out: dict[str, str] = {}
    for part in _chunks(paths):
        listing = git(root, "ls-tree", "-r", "-z", rev, "--", *part)
        if listing is None:
            return None
        for row in listing.split("\0"):
            meta, _, name = row.partition("\t")
            if name:
                out[name] = meta.split()[-1]
    return out


def _worktree_blobs(root: Path, paths: list[str]) -> dict[str, str] | None:
    """git's own hash of each existing working file (line-ending filters applied the way a commit would); None when any
    part got no answer or fewer hashes than files."""
    present = [p for p in paths if (root / p).is_file()]
    out: dict[str, str] = {}
    for part in _chunks(present):
        answer = git(root, "hash-object", "--", *part)
        hashes = answer.split() if answer is not None else []
        if len(hashes) != len(part):
            return None
        out.update(zip(part, hashes, strict=True))
    return out


def _dirty(root: Path, includes: Sequence[str]) -> set[str] | None:
    """Changed and untracked files inside ``includes``; None when git status gave no answer (never "nothing pending")."""
    answer = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *(list(includes) or ["."]))
    if answer is None:
        return None
    paths: set[str] = set()
    skip = False
    for row in answer.split("\0"):
        if skip:  # the old name of a rename follows its entry
            skip = False
            continue
        if len(row) > 3:
            paths.add(row[3:])
            skip = row[0] in "RC" or row[1] in "RC"
    return paths


def change_matches(
    root: Path, sha: str, includes: Sequence[str], staged: Callable[[], list[str] | None] | None = None
) -> bool:
    """True when the change now waiting IS what commit ``sha`` landed AND that landing is still in effect on dev's tip.

    * Every file the commit changed must hold, in the working tree, exactly what dev's TIP holds. A change that dev later
      reverted therefore does not count (the working file differs from the tip): it is landed again, not dropped.
    * Nothing else this landing would stage may still be pending. With ``--include`` that is the dirty files inside the
      included paths. Without it, ``staged`` (what the commit tool's dry run reports it would stage) names them, so the
      unrelated dirty files every shared checkout has never matter. When the staged set cannot be determined the answer is
      "not landed" (the unknown case errs toward not landed: the commit tool then decides, and refuses a change that is already in
      the tree).
    * Any git question that got no answer (a timeout or an error exit) makes the answer "not landed" too."""
    listing = git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", "-z", sha)
    names = [n for n in (listing or "").split("\0") if n]
    if not names:
        return False  # no answer, or an empty commit: nothing proves this change
    at_head, here = _blobs(root, "HEAD", names), _worktree_blobs(root, names)
    if at_head is None or here is None or any(here.get(name) != at_head.get(name) for name in names):
        return False
    if includes:
        dirty = _dirty(root, includes)
        return dirty is not None and not (dirty - set(names))
    pending = staged() if staged else None
    return pending is not None and not (set(pending) - set(names))


def find_landed(
    root: Path,
    key: str,
    includes: Sequence[str] = (),
    window: int = 400,
    staged: Callable[[], list[str] | None] | None = None,
) -> str | None:
    """sha of the newest commit in the last ``window`` commits of HEAD that carries this key AND this change's content."""
    log = git(root, "log", f"--max-count={int(window)}", "--format=%H%x01%B%x02", "HEAD")
    if log is None:
        return None
    pattern = re.compile(rf"^{TRAILER}: {re.escape(key)}\s*$", re.MULTILINE)
    for row in log.split("\x02"):
        sha, _, body = row.strip().partition("\x01")
        if sha and pattern.search(body) and change_matches(root, sha, includes, staged):
            return sha
    return None


def commits_outside_queue(root: Path, since: float) -> int | None:
    """Commits on dev since ``since`` without a landing ticket; None when git gave no answer (shown as unknown)."""
    log = git(root, "log", f"--since={int(since)}", "--format=%B%x1e", "HEAD")
    if log is None:
        return None
    return sum(1 for r in log.split("\x1e") if r.strip() and f"{TRAILER}:" not in r)
