#!/usr/bin/env python3
"""Every place work can sit outside the trunk, counted.

`thomas consolidate` audits LOCAL branches. Run against this repository on
2026-09-03 it printed "2 branches (ceiling 10); 1 carry unique work" - green -
while the trunk was 73 commits unpushed, the public repo was 889 commits behind
with a shared ancestor from 9 June, 99 remote branches carried unlanded
commits, eight other clones sat on the disk, and twelve hours of work was
uncommitted. It was not wrong; it was measuring one dimension of five, and the
one it measured was the one already fine.

This measures all five, from git alone:

* ``unpushed``    - trunk commits not on its remote
* ``public``      - how far the public branch trails the trunk, and since when
* ``stranded``    - remote branches carrying unlanded commits, split by whether
                    their tip is recent enough to be live work rather than a
                    stale fork
* ``clones``      - other working copies of this repository on this machine
* ``uncommitted`` - work in no commit anywhere

Reports; never refuses; always exits zero. A gauge that can block a commit
becomes the thing it exists to measure. It also never fetches by default: it
reads remote-tracking refs, so ``--fetch`` is the opt-in that costs network.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRUNK = "dev"
TRUNK_REMOTE = "dev-origin"
PUBLIC_REF = "origin/main"
# A branch whose tip is older than this is a fork of history the trunk has
# moved past, not work waiting to land. Dating them is what separates a
# graveyard from a backlog: 99 branches here, 3 of them actually live.
ACTIVE_DAYS = 14
CLONE_SCAN_DEPTH = 3
NO_FINDING = "none"


def _git(*args: str, repo: Path | None = None, timeout: float = 30.0) -> str:
    """Run git and decode as UTF-8; empty string on any failure.

    Explicit encoding, not the platform default: one 0x9d byte in the workboard
    - half a curly quote - crashed a gate that captured git output as cp1252,
    and the failure surfaced as a file appearing absent from the index.
    """
    try:
        proc = subprocess.run(
            ("git", *args), cwd=str(repo or ROOT), capture_output=True,
            text=True, encoding="utf-8", errors="replace", check=False, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def _count(rev_range: str, repo: Path | None = None) -> int | None:
    out = _git("rev-list", "--count", rev_range, repo=repo).strip()
    return int(out) if out.isdigit() else None


def _ref_exists(ref: str, repo: Path | None = None) -> bool:
    return bool(_git("rev-parse", "--verify", "--quiet", ref, repo=repo).strip())


@dataclass
class Report:
    findings: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    detail: dict[str, object] = field(default_factory=dict)

    @property
    def consolidated(self) -> bool:
        return not self.findings and not self.unknown


def find_unpushed(
    trunk: str = TRUNK, remote: str = TRUNK_REMOTE, repo: Path | None = None
) -> tuple[list[str], list[str]]:
    ref = f"{remote}/{trunk}"
    if not _ref_exists(ref, repo=repo):
        return [], [f"no tracking ref `{ref}`, so unpushed work cannot be counted"]
    ahead = _count(f"{ref}..{trunk}", repo=repo)
    if ahead is None:
        return [], [f"could not count `{trunk}` against `{ref}`"]
    if ahead == 0:
        return [], []
    return [f"unpushed: {ahead} commit(s) on `{trunk}` are not on `{ref}`"], []


def find_public_lag(
    trunk: str = TRUNK, public: str = PUBLIC_REF, repo: Path | None = None
) -> tuple[list[str], list[str]]:
    if not _ref_exists(public, repo=repo):
        return [], [f"no public ref `{public}`, so release lag cannot be counted"]
    behind = _count(f"{public}..{trunk}", repo=repo)
    if behind is None:
        return [], [f"could not count `{public}` against `{trunk}`"]
    if behind == 0:
        return [], []
    base = _git("merge-base", public, trunk, repo=repo).strip()
    since = _git("log", "-1", "--format=%cs", base, repo=repo).strip() if base else ""
    tail = f", last shared commit {since}" if since else ""
    return [f"public: `{public}` is {behind} commit(s) behind `{trunk}`{tail}"], []


def find_stranded_branches(
    trunk: str = TRUNK,
    repo: Path | None = None,
    active_days: int = ACTIVE_DAYS,
    now: float | None = None,
) -> tuple[list[str], list[str]]:
    """Remote branches holding commits the trunk lacks, split live vs stale.

    ``--no-merged`` answers "which branches hold unlanded commits" in ONE git
    call. Counting per branch instead cost 180 calls and 25 seconds here, which
    is how a gauge stops being run at session start.
    """
    dates = _git(
        "for-each-ref", "--format=%(refname:short)%09%(committerdate:unix)", "refs/remotes", repo=repo
    )
    if not dates.strip():
        return [], ["no remote-tracking refs, so stranded work cannot be counted"]
    tip_at: dict[str, float] = {}
    for line in dates.splitlines():
        name, _, when = line.partition("	")
        try:
            tip_at[name.strip()] = float(when.strip())
        except ValueError:
            tip_at[name.strip()] = 0.0

    unlanded = _git("branch", "-r", "--no-merged", trunk, repo=repo)
    if not unlanded.strip():
        return [], []
    cutoff = (now if now is not None else time.time()) - active_days * 86400
    live: list[str] = []
    stale = 0
    for raw in unlanded.splitlines():
        name = raw.strip()
        if not name or "->" in name or name.endswith(f"/{trunk}"):
            continue
        if tip_at.get(name, 0.0) >= cutoff:
            ahead = _count(f"{trunk}..{name}", repo=repo)
            live.append(f"{name} ({ahead})" if ahead else name)
        else:
            stale += 1
    if not live and not stale:
        return [], []
    parts = []
    if live:
        shown = ", ".join(sorted(live)[:3])
        more = f" and {len(live) - 3} more" if len(live) > 3 else ""
        parts.append(f"{len(live)} with a tip inside {active_days}d: {shown}{more}")
    if stale:
        parts.append(f"{stale} stale fork(s) the trunk has moved past")
    return ["stranded: " + "; ".join(parts)], []


def _iter_git_dirs(base: Path, depth: int):
    """Directories named .git within `depth` levels of `base`, skipping noise."""
    skip = {"node_modules", ".venv", "site-packages", "__pycache__", "blobs", "AppData"}
    stack = [(base, 0)]
    while stack:
        current, level = stack.pop()
        try:
            entries = list(current.iterdir())
        except (OSError, PermissionError):
            continue
        for entry in entries:
            try:
                if not entry.is_dir():
                    continue
            except OSError:
                continue
            if entry.name == ".git":
                yield entry
                continue
            if level + 1 <= depth and entry.name not in skip and not entry.name.startswith("."):
                stack.append((entry, level + 1))


def _repo_identity(repo: Path) -> tuple[str, set[str]]:
    """This repository's root commit and its remote URLs, normalized."""
    root = _git("rev-list", "--max-parents=0", "HEAD", repo=repo).split()
    urls = {
        line.strip().rstrip("/").removesuffix(".git").lower()
        for line in _git("remote", "get-url", "--all", "origin", repo=repo).splitlines()
        + _git("remote", "get-url", "--all", "dev-origin", repo=repo).splitlines()
        if line.strip()
    }
    return (root[0] if root else ""), urls


def find_clones(
    repo_root: Path | None = None,
    depth: int = CLONE_SCAN_DEPTH,
    roots: Sequence[Path] | None = None,
) -> tuple[list[str], list[str]]:
    """Other working copies OF THIS REPOSITORY on this machine.

    Bounded on purpose: an unbounded walk of a whole drive took ten minutes
    when this was measured by hand, and a gauge nobody waits for is a gauge
    nobody runs.

    A candidate counts only if it shares this repo's root commit or names one
    of its remote URLs. Without that test the first version reported 53 - every
    unrelated git repo in the home directory - which is noise, and noise is how
    a gauge gets ignored.
    """
    here = (repo_root or ROOT).resolve()
    root_sha, urls = _repo_identity(here)
    candidates = [here.parent, Path.home()] if roots is None else [Path(r) for r in roots]
    seen: set[Path] = set()
    found: list[Path] = []
    for base in candidates:
        if not base.exists():
            continue
        for git_dir in _iter_git_dirs(base, depth):
            work = git_dir.parent.resolve()
            if work == here or work in seen:
                continue
            seen.add(work)
            if _is_same_repo(work, root_sha, urls):
                found.append(work)
    if not found:
        return [], []
    shown = ", ".join(p.name for p in sorted(found)[:3])
    more = f" and {len(found) - 3} more" if len(found) > 3 else ""
    return [f"clones: {len(found)} other working cop(y/ies) of this repo: {shown}{more}"], []


def _remote_urls(repo: Path) -> set[str]:
    """Every remote URL of `repo`, normalized for comparison."""
    urls: set[str] = set()
    for line in _git("remote", "-v", repo=repo, timeout=10.0).splitlines():
        parts = line.split()
        if len(parts) > 1:
            urls.add(parts[1].strip().rstrip("/").removesuffix(".git").lower())
    return urls


def _is_same_repo(candidate: Path, root_sha: str, urls: set[str]) -> bool:
    """A clone of this repo shares its root commit, or one of its remote URLs.

    Both tests are needed. The publish snapshots were made with rewritten
    history, so they share no root commit but do point at the same GitHub
    remote; a sandbox fork shares the root commit but may have no remote at all.
    """
    if root_sha:
        their_root = _git("rev-list", "--max-parents=0", "HEAD", repo=candidate, timeout=10.0).split()
        if their_root and their_root[0] == root_sha:
            return True
    return bool(urls and (_remote_urls(candidate) & urls))


def find_uncommitted(repo: Path | None = None) -> tuple[list[str], list[str]]:
    raw = _git("status", "--porcelain", repo=repo)
    lines = raw.splitlines()
    tracked = sum(1 for line in lines if line[:2].strip() and not line.startswith("??"))
    untracked = sum(1 for line in lines if line.startswith("??"))
    if not tracked and not untracked:
        return [], []
    return [f"uncommitted: {tracked} tracked file(s) modified, {untracked} untracked, in no commit anywhere"], []


def build_report(
    repo: Path | None = None,
    trunk: str = TRUNK,
    remote: str = TRUNK_REMOTE,
    public: str = PUBLIC_REF,
    scan_clones: bool = True,
    clone_roots: Sequence[Path] | None = None,
) -> Report:
    report = Report()
    checks = [
        find_unpushed(trunk, remote, repo=repo),
        find_public_lag(trunk, public, repo=repo),
        find_stranded_branches(trunk, repo=repo),
        find_uncommitted(repo=repo),
    ]
    if scan_clones:
        checks.append(find_clones(repo_root=repo, roots=clone_roots))
    for findings, unknown in checks:
        report.findings.extend(findings)
        report.unknown.extend(unknown)
    report.detail = {"trunk": trunk, "remote": remote, "public": public}
    return report


def render(report: Report) -> str:
    if report.consolidated:
        return f"DIVERGENCE: {NO_FINDING}"
    head = (
        f"DIVERGENCE: {len(report.findings)} place(s) work sits outside the trunk"
        if report.findings
        else f"DIVERGENCE: nothing red, {len(report.unknown)} dimension(s) could not be measured"
    )
    lines = [head]
    lines.extend(f"  - {item}" for item in report.findings)
    # An instrument that could not read something says so, rather than counting
    # it as clean.
    lines.extend(f"  - unmeasured: {item}" for item in report.unknown)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trunk", default=TRUNK)
    parser.add_argument("--remote", default=TRUNK_REMOTE)
    parser.add_argument("--public", default=PUBLIC_REF)
    parser.add_argument("--fetch", action="store_true", help="refresh remote-tracking refs first (network)")
    parser.add_argument("--no-clones", action="store_true", help="skip the clone scan")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.fetch:
        _git("fetch", "--all", "--prune", "--quiet", timeout=180.0)

    report = build_report(
        trunk=args.trunk, remote=args.remote, public=args.public,
        scan_clones=not args.no_clones,
    )
    if args.json:
        print(json.dumps({
            "findings": report.findings,
            "unmeasured": report.unknown,
            "consolidated": report.consolidated,
            **report.detail,
        }, indent=2))
    else:
        print(render(report))
    # Always zero. A gauge that can block a commit becomes what it measures.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
