"""What is on Thomas's refs and not on dev: the ratchet's backlog, in the order it is proven.

Sources: the custodian's ``survey`` over local branches, salvage snapshots and
remote branches, keeping the rows it calls UNIQUE_WORK (and ACTIVE, reported as
such). Work is keyed by its tip commit, never by ref name: on 2026-09-24 seven
branches pointed at one commit (fcb5f06), and seven salvage snapshots sat one
commit on top of it -- that stack is recorded as ``stacked_on``.

Not for the ratchet, and reported with the reason, never dropped:

* the public repository's history: anything carrying one of its commits, and
  anything with no history in common with dev (17 of its 35 commits have another
  first commit; 18 share dev's, so membership decides). ``refs/remotes/origin/*``
  is that history only in a copy that keeps its work on ``dev-origin``; see
  ``_origin_is_public``;
* dependabot's dependency updates;
* work touched in the last three days (the custodian's ACTIVE): someone may be on it.

``refs/archive`` is not read: 308 snapshots whose intent nobody recorded.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.forge.branch_custodian import DEFAULT_ACTIVE_DAYS, BranchStatus, survey
from thomas.server.ratchet.gitrepo import GitFailed, Repo

NAMESPACES = ("refs/heads", "refs/salvage", "refs/remotes")
PUBLIC_REFS = "refs/remotes/origin/"
TRUNK_REMOTE_REFS = "refs/remotes/dev-origin/"
DEPENDABOT_EMAIL = "49699333+dependabot[bot]@users.noreply.github.com"
CENSUS_NAME = "census.json"

PUBLIC = "the public repository's history, which never goes to dev"
CARRIES_PUBLIC = "it carries {n} commit(s) of the public repository's history, which never goes to dev"
NO_SHARED_HISTORY = "it shares no history with dev (a different first commit), so it cannot be merged onto it"
DEPENDABOT = "a dependabot dependency update; those are yours to take, not the ratchet's"
ACTIVE = "changed in the last {days} days, so someone may still be working on it"
# A stash kept as a salvage snapshot is a working-tree save, often a temporary revert, not work meant to land: on
# 2026-09-28 one would have asked you to delete 11 files dev still has. Work a branch also holds is not one of these.
STASH_REFS = "refs/salvage/stash-"
STASH = "a git stash kept as a salvage snapshot: a working-tree save, not work meant to land"


@dataclass(frozen=True)
class Candidate:
    sha: str
    refs: tuple[str, ...]
    unique_commits: int
    files: tuple[str, ...]
    committed_at: int
    stacked_on: str = ""

    @property
    def ref(self) -> str:
        return self.refs[0]

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "ref": self.ref}


@dataclass(frozen=True)
class Skipped:
    sha: str
    refs: tuple[str, ...]
    status: str  # "not_for_ratchet" or "active"
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Census:
    dev_sha: str
    candidates: tuple[Candidate, ...]
    skipped: tuple[Skipped, ...]
    refs_seen: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "dev_sha": self.dev_sha,
            "candidates": [c.as_dict() for c in self.candidates],
            "skipped": [s.as_dict() for s in self.skipped],
            "refs_seen": dict(self.refs_seen),
        }


def _refs(repo: Repo, namespace: str) -> dict[str, tuple[str, int]]:
    """short name -> (full name, tip commit time) for every ref in *namespace* that is not symbolic."""
    fmt = "--format=%(refname:short)%09%(refname)%09%(symref)%09%(committerdate:unix)"
    found: dict[str, tuple[str, int]] = {}
    for line in repo.out("for-each-ref", fmt, namespace).splitlines():
        short, full, symref, when = (line.split("\t") + ["", "", "", ""])[:4]
        if short and not symref:
            found[short] = (full, int(when or 0))
    return found


def _origin_is_public(repo: Repo) -> bool:
    """True when this copy keeps its work on ``dev-origin``, which is what makes ``origin`` the public one.

    ``scripts/forge/trunk_divergence.py`` fixes that layout (``TRUNK_REMOTE = "dev-origin"``,
    ``PUBLIC_REF = "origin/main"``). A copy cloned straight from the work repository has a
    single remote, named ``origin``, carrying the very branches the ratchet exists to land:
    there the name says nothing about what a ref is, and membership has to decide.
    """
    return bool(repo.out("for-each-ref", "--count=1", "--format=%(refname)", TRUNK_REMOTE_REFS))


def _public_commits(repo: Repo, dev_sha: str, orphans: Sequence[str], origin_is_public: bool) -> set[str]:
    """The public repository's commits: its remote's when ``origin`` is it, else the orphan lines found here.

    Without a ``dev-origin`` to tell the two apart, the sanitized line is still
    recognisable by what it is -- a history that does not begin where dev's does --
    so anything sitting on top of one is caught as carrying it.
    """
    if origin_is_public:
        return set(repo.out("rev-list", "--remotes=origin", "--not", dev_sha).split())
    return set(repo.out("rev-list", *orphans, "--not", dev_sha).split()) if orphans else set()


def _stop_if_closing() -> None:
    """The survey asks git about every old branch, one at a time; a closing server must not wait for the rest."""
    from thomas.server.precard import workers  # here: precard imports the ratchet's neighbours as it loads

    if workers.closing():
        raise GitFailed("Thomas is closing, so the survey of branches stopped")


def _not_for_ratchet(
    repo: Repo, dev_sha: str, sha: str, refs: tuple[str, ...], public: set[str], origin_is_public: bool
) -> str:
    _stop_if_closing()
    if origin_is_public and any(ref.startswith(PUBLIC_REFS) for ref in refs):
        return PUBLIC
    if refs and all(ref.startswith(STASH_REFS) for ref in refs):
        return STASH
    if repo.run("merge-base", dev_sha, sha, ok=(0, 1)).returncode != 0:
        return NO_SHARED_HISTORY
    unique = [line.split("\t") for line in repo.out("log", "--format=%H%x09%ae", f"{dev_sha}..{sha}").splitlines()]
    carried = [row for row in unique if row[0] in public]
    if carried:
        return CARRIES_PUBLIC.format(n=len(carried))
    authors = {row[1] for row in unique if len(row) > 1}
    if authors == {DEPENDABOT_EMAIL} or any("/dependabot/" in ref for ref in refs):
        return DEPENDABOT
    return ""


def _order(candidates: list[Candidate], commits: dict[str, list[str]]) -> list[Candidate]:
    """Fewest files first, then oldest; a candidate stacked on another comes after it."""
    shas = {c.sha for c in candidates}
    stacked = []
    for cand in candidates:
        inside = [s for s in commits[cand.sha] if s in shas and s != cand.sha]  # newest first: the nearest one
        stacked.append(replace(cand, stacked_on=inside[0] if inside else ""))
    pending = sorted(stacked, key=lambda c: (len(c.files), c.committed_at, c.sha))
    placed: list[Candidate] = []
    while pending:
        done = {p.sha for p in placed}
        ready = next(c for c in pending if not c.stacked_on or c.stacked_on in done)
        pending.remove(ready)
        placed.append(ready)
    return placed


def discover(repo: Repo, *, trunk: str = "dev", active_days: int = DEFAULT_ACTIVE_DAYS) -> Census:
    """Every commit on a ref that dev does not have, as a candidate or as a reported exclusion."""
    dev_sha = repo.sha(f"refs/heads/{trunk}")
    origin_is_public = _origin_is_public(repo)
    grouped: dict[str, dict[str, Any]] = {}
    seen: dict[str, int] = {}
    for namespace in NAMESPACES:
        names = _refs(repo, namespace)
        seen[namespace] = len(names)
        report = survey(repo.runner(), trunk=trunk, active_days=active_days, namespace=namespace)
        for row in report.branches:
            if row.name not in names or row.unique_commits <= 0:
                continue
            if row.status not in (BranchStatus.UNIQUE_WORK, BranchStatus.ACTIVE):
                continue
            full, when = names[row.name]
            entry = grouped.setdefault(
                row.sha, {"refs": [], "status": row.status, "files": row.unique_files, "when": when}
            )
            entry["refs"].append(full)
    _stop_if_closing()
    orphans = []
    for sha in grouped:
        _stop_if_closing()
        if repo.run("merge-base", dev_sha, sha, ok=(0, 1)).returncode != 0:
            orphans.append(sha)
    public = _public_commits(repo, dev_sha, orphans, origin_is_public)
    candidates: list[Candidate] = []
    skipped: list[Skipped] = []
    commits: dict[str, list[str]] = {}
    for sha, entry in grouped.items():
        refs = tuple(sorted(entry["refs"]))
        why, status = _not_for_ratchet(repo, dev_sha, sha, refs, public, origin_is_public), "not_for_ratchet"
        if not why and entry["status"] is BranchStatus.ACTIVE:
            why, status = ACTIVE.format(days=active_days), "active"
        if why:
            skipped.append(Skipped(sha, refs, status, why))
            continue
        commits[sha] = repo.out("rev-list", f"{dev_sha}..{sha}").split()
        candidates.append(Candidate(sha, refs, len(commits[sha]), tuple(entry["files"]), int(entry["when"])))
    ordered = _order(candidates, commits)
    return Census(dev_sha, tuple(ordered), tuple(sorted(skipped, key=lambda s: s.refs)), seen)


def write_census(folder: Path, census: Census) -> Path:
    """The last discovery, for GET /api/ratchet and Chat, written whole or not at all."""
    folder.mkdir(parents=True, exist_ok=True)
    payload = {**census.as_dict(), "discovered_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    tmp = folder / f".{CENSUS_NAME}.tmp"
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, folder / CENSUS_NAME)
    return folder / CENSUS_NAME


def read_census(folder: Path) -> dict[str, Any]:
    try:
        data = json.loads((folder / CENSUS_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


__all__ = [
    "CENSUS_NAME",
    "DEPENDABOT_EMAIL",
    "NAMESPACES",
    "PUBLIC_REFS",
    "TRUNK_REMOTE_REFS",
    "Candidate",
    "Census",
    "Skipped",
    "discover",
    "read_census",
    "write_census",
]
