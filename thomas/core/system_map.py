"""System map -- everything that exists in this project, and what has been forgotten.

This module answers a question no gate in this repo has ever asked: *what is
lying around?*

Every existing check compares one change to the change before it. Each of those
comparisons passed, every time, while 591 changes piled up outside ``main`` for
64 days across 57 separate working copies. Nothing was wrong with any single
step. Nothing was watching the SUM. The owner of this project is not a
programmer and had no instrument that could have shown him -- the only way to
see it was to know the git commands, which is the same as not being able to see
it at all.

So this module inventories, in plain facts:

* **Versions of the project** (branches) -- how many, how old, whether their
  work is already safely on the shared copy or exists nowhere else.
* **Separate working copies** (worktrees) -- whole second copies of the project
  scattered across the machine, each sitting on a different version. These are
  the biggest surprise: they are invisible from inside any one of them, and 39
  of the 57 in this repo were created automatically by Thomas's own agents.
* **Set-aside piles** (stashes) -- work parked mid-thought and never picked up.
  The oldest here is still labelled with a branch name the project stopped
  using.
* **Unsaved edits** -- work that would die with the machine.
* **The landing verdict** -- reused wholesale from :mod:`thomas.core.landing_health`
  rather than recomputed, so the two surfaces can never disagree.

Every item gets a STATUS in words a non-programmer can act on -- ``active``,
``idle``, ``forgotten`` -- derived from age, not from git's data model. The
ranking principle throughout is *would this surprise the owner*, which is why
every list is sorted OLDEST FIRST. Every other git tool shows newest first;
newest is the stuff you already remember.

Design rules this file is held to, same as its sibling:

* **It never raises and it never hangs.** Short per-command timeouts under a
  shared deadline. Anything unreadable becomes an honest note in ``notes``,
  never a crash and never a zero -- "I could not check" and "there is nothing"
  are different answers.
* **It never touches the network.** Everything here is already on this machine.
* **It never changes anything.** No prune, no drop, no delete. This surface
  reports; cleaning up is the owner's decision to make with full information.
* **No LLM calls.** These are facts, and facts should not cost tokens.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from thomas.core.landing_health import collect_landing_health

# ---------------------------------------------------------------------------
# Thresholds -- all tuning in one place.
#
# Chosen around human memory, not around git. A week is "I still remember
# starting this". A month is "I would have to go and look". Past a month, work
# you have forgotten about is indistinguishable from work you never did, except
# that it is still on your disk taking up a name.
# ---------------------------------------------------------------------------

#: Days since anything last happened to an item before it stops being "current".
DAYS_ACTIVE = 7.0

#: Days after which an item is treated as forgotten rather than merely idle.
#: Three weeks, matching ``landing_health``'s own "act" thresholds exactly. The
#: two surfaces must not disagree about how long is too long -- a page that
#: calls something forgotten while its sibling still calls it fine teaches the
#: owner to trust neither.
DAYS_FORGOTTEN = 21.0

#: How that threshold reads in a sentence. Kept beside the number so the two
#: can never drift apart.
FORGOTTEN_PHRASE = "three weeks"

#: How many separate working copies is normal. More than a handful means copies
#: are being created faster than they are being cleaned up.
WORKTREES_NOTABLE = 5

#: Set-aside piles. A few is a working habit; dozens is a graveyard.
STASHES_NOTABLE = 10

#: Versions of the project sitting on this machine.
LOCAL_BRANCHES_NOTABLE = 20

#: Per-command and whole-collection ceilings. Nothing here may outlive these.
GIT_COMMAND_TIMEOUT_SECONDS = 8.0
GIT_TOTAL_BUDGET_SECONDS = 25.0

STATUS_ACTIVE = "active"
STATUS_IDLE = "idle"
STATUS_FORGOTTEN = "forgotten"
STATUS_UNKNOWN = "unknown"

# Where a separate working copy lives, and why the owner should care.
PLACE_PROJECT = "project"
PLACE_AGENT = "agent"
PLACE_TEMP = "temp"
PLACE_ELSEWHERE = "elsewhere"

_PLACE_LABELS = {
    PLACE_PROJECT: "your project folder",
    PLACE_AGENT: "a folder Thomas's agents create for themselves",
    PLACE_TEMP: "a temporary folder Windows can delete without warning",
    PLACE_ELSEWHERE: "somewhere else on this machine",
}

# Every failure a git probe here is allowed to meet, named explicitly. A broad
# ``except Exception`` would turn a real bug in this file into a calm "could not
# read", which is the exact class of quiet lie this module exists to expose.
#   OSError                    -- git not on PATH, working dir gone, dead pipe
#   subprocess.SubprocessError -- TimeoutExpired and its siblings
#   ValueError                 -- bad argument shape, undecodable output
_GIT_ERRORS = (OSError, subprocess.SubprocessError, ValueError)

_SECONDS_PER_DAY = 86400.0
_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Field separator for git's ``--format`` output. Tab, because branch names and
#: stash messages may contain almost anything else.
_SEP = "\t"


@dataclass(frozen=True)
class MapItem:
    """One thing that exists in this project.

    ``days_since`` is ``None`` when the date could not be read -- never 0, which
    would read as "brand new" and is the opposite of the truth.
    """

    kind: str
    name: str
    status: str
    days_since: float | None = None
    commit: str = ""
    merged: bool | None = None
    scope: str = ""
    path: str = ""
    place: str = ""
    place_label: str = ""
    exists: bool = True
    subject: str = ""
    days_since_files: float | None = None
    #: Saved changes this version has that the shared copy does not, and vice
    #: versa. ``None`` when there was no shared copy to compare against -- which
    #: is a different answer from 0 and must never be flattened into it.
    ahead: int | None = None
    behind: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "status": self.status,
            "days_since": self.days_since,
            "commit": self.commit,
            "merged": self.merged,
            "scope": self.scope,
            "path": self.path,
            "place": self.place,
            "place_label": self.place_label,
            "exists": self.exists,
            "subject": self.subject,
            "days_since_files": self.days_since_files,
            "ahead": self.ahead,
            "behind": self.behind,
        }


@dataclass(frozen=True)
class SystemMap:
    """One complete reading of what exists in this project."""

    ok: bool
    headline: str
    checked_at: float
    repo_root: str = ""
    summary: dict[str, Any] = field(default_factory=dict)
    findings: list[dict[str, str]] = field(default_factory=list)
    branches: list[MapItem] = field(default_factory=list)
    worktrees: list[MapItem] = field(default_factory=list)
    stashes: list[MapItem] = field(default_factory=list)
    landing: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    took_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe view, for the API and for logs."""
        return {
            "ok": self.ok,
            "headline": self.headline,
            "checked_at": self.checked_at,
            "repo_root": self.repo_root,
            "summary": dict(self.summary),
            "findings": [dict(f) for f in self.findings],
            "branches": [item.as_dict() for item in self.branches],
            "worktrees": [item.as_dict() for item in self.worktrees],
            "stashes": [item.as_dict() for item in self.stashes],
            "landing": dict(self.landing),
            "notes": list(self.notes),
            "took_ms": self.took_ms,
            "thresholds": {
                "days_active": DAYS_ACTIVE,
                "days_forgotten": DAYS_FORGOTTEN,
                "worktrees_notable": WORKTREES_NOTABLE,
                "stashes_notable": STASHES_NOTABLE,
                "local_branches_notable": LOCAL_BRANCHES_NOTABLE,
            },
        }


class _GitReader:
    """Runs read-only git commands under a hard total time budget.

    Deliberately parallel to ``landing_health._GitProbe`` rather than importing
    it: this reader needs a larger budget and tab-delimited multi-line parsing,
    and reaching into a sibling module's private class to get it would couple
    two files that should be free to tune their own timeouts. The hardening it
    repeats is the part that must never be dropped -- git must never stop to ask
    a human anything, and must never take the index lock just to answer a
    question.
    """

    def __init__(self, root: Path, budget_seconds: float = GIT_TOTAL_BUDGET_SECONDS) -> None:
        self.root = root
        self.deadline = time.monotonic() + budget_seconds
        self.failures: list[str] = []
        self.env = dict(os.environ)
        self.env["GIT_TERMINAL_PROMPT"] = "0"
        self.env["GIT_OPTIONAL_LOCKS"] = "0"

    def run(self, *args: str) -> str | None:
        """Return stripped stdout, or None if the command failed or timed out."""
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            self.failures.append(f"git {args[0] if args else '?'} (ran out of time)")
            return None
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
                ["git", *args],
                cwd=str(self.root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=min(GIT_COMMAND_TIMEOUT_SECONDS, remaining),
                stdin=subprocess.DEVNULL,
                env=self.env,
                check=False,
            )
        except _GIT_ERRORS:
            self.failures.append(f"git {args[0] if args else '?'}")
            return None
        if proc.returncode != 0:
            self.failures.append(f"git {args[0] if args else '?'}")
            return None
        return (proc.stdout or "").strip()

    def lines(self, *args: str) -> list[str] | None:
        """Non-empty output lines, or None if the command failed."""
        out = self.run(*args)
        if out is None:
            return None
        return [line for line in out.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def _days_between(now: float, then: float | None) -> float | None:
    if then is None:
        return None
    return max(0.0, (now - then) / _SECONDS_PER_DAY)


def _status_for(days: float | None) -> str:
    """Turn an age into a word the owner can act on."""
    if days is None:
        return STATUS_UNKNOWN
    if days <= DAYS_ACTIVE:
        return STATUS_ACTIVE
    if days < DAYS_FORGOTTEN:
        return STATUS_IDLE
    return STATUS_FORGOTTEN


def _to_epoch(raw: str) -> float | None:
    try:
        return float(raw.strip())
    except (ValueError, AttributeError):
        return None


def _things(count: int, singular: str, plural: str = "") -> str:
    """'1 copy' / '3 copies' -- so no sentence ever reads '1 copies'."""
    word = singular if count == 1 else (plural or singular + "s")
    return f"{count} {word}"


def _split_ahead_behind(raw: str) -> tuple[int | None, int | None]:
    """Parse git's ``ahead-behind`` atom, which prints '581 0'."""
    parts = str(raw or "").split()
    if len(parts) != 2:
        return (None, None)
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return (None, None)


def _verb(count: int, singular: str, plural: str) -> str:
    """Agree the verb with the count, so no sentence reads '1 copy sit'."""
    return singular if count == 1 else plural


def _age_phrase(days: float | None) -> str:
    """A duration in words, never in dates -- 'about 2 months ago'."""
    if days is None:
        return "at an unknown time"
    whole = int(days)
    if whole < 1:
        return "today"
    if whole == 1:
        return "yesterday"
    if whole < 14:
        return f"{whole} days ago"
    if whole < 60:
        return f"about {max(2, round(days / 7))} weeks ago"
    return f"about {round(days / 30)} months ago"


def _sort_key(item: MapItem) -> tuple[int, float]:
    """Oldest first, unknown-age last.

    Deliberately the reverse of every other git tool. The newest branch is the
    one the owner is working in right now; it is the oldest one he has never
    heard of that this page exists to show him.
    """
    if item.days_since is None:
        return (1, 0.0)
    return (0, -item.days_since)


# ---------------------------------------------------------------------------
# Collectors -- one git call each, so the whole map costs a handful of processes
# rather than one per item. With 57 worktrees and 237 branches, per-item calls
# would take minutes.
# ---------------------------------------------------------------------------


def _read_merged(reader: _GitReader, default_branch: str) -> set[str]:
    """Names whose work is already on the shared copy, so they hold nothing unique."""
    merged: set[str] = set()
    if not default_branch:
        return merged
    for args in (
        ("branch", "--merged", default_branch, "--format=%(refname:short)"),
        ("branch", "-r", "--merged", default_branch, "--format=%(refname:short)"),
    ):
        for line in reader.lines(*args) or []:
            merged.add(line.strip())
    return merged


def _read_branches(
    reader: _GitReader, now: float, merged: set[str], default_branch: str
) -> tuple[list[MapItem], dict[str, float]]:
    """Every version of the project, on this machine and on the server.

    One git call per scope, and the scope comes from WHICH call answered rather
    than from the shape of the name. Guessing "a slash means it is on the
    server" was wrong here: this repo has two remotes (``origin`` and
    ``dev-origin``) and dozens of local branches with slashes in their names
    (``codex/...``, ``claude/...``), so the guess put 2 branches on the wrong
    side of the count. Asking git twice is exact and costs one extra process.

    ``ahead``/``behind`` ride along as an extra format atom rather than as 237
    separate ``rev-list`` calls -- same processes, about a second more, and it
    is what lets the map show how much unlanded work each version is carrying
    instead of merely that some exists. The atom is only asked for when there
    is a shared copy to compare against, because git makes the WHOLE command
    fatal when the base ref is missing; the plain format is retried if it does.

    Also returns a name -> commit-timestamp map, which the worktree pass reuses
    so it does not have to ask git 57 more times.
    """
    base_fields = ["%(refname:short)", "%(committerdate:unix)", "%(objectname:short)", "%(contents:subject)"]
    items: list[MapItem] = []
    dates: dict[str, float] = {}
    for scope, ref_root in (("local", "refs/heads"), ("remote", "refs/remotes")):
        lines = None
        counted = bool(default_branch)
        if counted:
            fmt = _SEP.join([*base_fields, f"%(ahead-behind:{default_branch})"])
            lines = reader.lines("for-each-ref", f"--format={fmt}", ref_root)
        if lines is None:
            counted = False
            lines = reader.lines("for-each-ref", f"--format={_SEP.join(base_fields)}", ref_root) or []
        for line in lines:
            parts = line.split(_SEP)
            if len(parts) < 3:
                continue
            name = parts[0].strip()
            # origin/HEAD is a pointer at another branch, not a branch of its own.
            if not name or name.endswith("/HEAD"):
                continue
            stamp = _to_epoch(parts[1])
            if stamp is not None:
                dates.setdefault(name, stamp)
            days = _days_between(now, stamp)
            ahead, behind = _split_ahead_behind(parts[4]) if counted and len(parts) > 4 else (None, None)
            items.append(
                MapItem(
                    kind="branch",
                    name=name,
                    status=_status_for(days),
                    days_since=None if days is None else round(days, 2),
                    commit=parts[2].strip(),
                    merged=name in merged,
                    scope=scope,
                    ahead=ahead,
                    behind=behind,
                    subject=parts[3].strip() if len(parts) > 3 else "",
                )
            )
    items.sort(key=_sort_key)
    return items, dates


def _classify_place(path: str, repo_root: Path) -> str:
    """Where a separate copy lives -- and therefore how at-risk it is."""
    lowered = path.replace("\\", "/").lower()
    root = str(repo_root).replace("\\", "/").lower()
    if lowered == root:
        return PLACE_PROJECT
    if "/.claude/worktrees" in lowered:
        return PLACE_AGENT
    for marker in ("/temp/", "/tmp/", "/appdata/local/temp"):
        if marker in lowered:
            return PLACE_TEMP
    return PLACE_ELSEWHERE


def _folder_mtime_days(path: str, now: float) -> float | None:
    """How long since anything in the top of that folder changed.

    Only the folder itself is stat-ed, never a walk: 57 recursive scans of a
    full project checkout would take longer than every git call combined.
    """
    try:
        stamp = os.stat(path).st_mtime
    except (OSError, ValueError):
        return None
    return _days_between(now, stamp)


def _read_worktrees(
    reader: _GitReader,
    now: float,
    repo_root: Path,
    branch_dates: dict[str, float],
    merged: set[str],
) -> list[MapItem]:
    """Every separate working copy of this project, in one git call.

    The dates come from the branch map built above, so this costs one process
    no matter how many copies exist.
    """
    raw = reader.lines("worktree", "list", "--porcelain")
    if raw is None:
        return []
    items: list[MapItem] = []
    current: dict[str, str] = {}

    def flush() -> None:
        path = current.get("worktree", "")
        if not path:
            return
        branch = current.get("branch", "")
        short = branch.split("refs/heads/", 1)[-1] if branch else ""
        stamp = branch_dates.get(short)
        days_commit = _days_between(now, stamp)
        exists = Path(path).is_dir()
        days_files = _folder_mtime_days(path, now) if exists else None
        # Either kind of touch counts as "someone was here", so the freshest
        # of the two decides the status. Using the commit date alone would
        # file an actively-edited copy as forgotten.
        candidates = [d for d in (days_commit, days_files) if d is not None]
        days = min(candidates) if candidates else None
        place = _classify_place(path, repo_root)
        items.append(
            MapItem(
                kind="worktree",
                name=Path(path.replace("\\", "/")).name or path,
                status=_status_for(days),
                days_since=None if days is None else round(days, 2),
                commit=(current.get("HEAD", "") or "")[:8],
                merged=(short in merged) if short else None,
                scope=short or "a single point in history (no branch)",
                path=path,
                place=place,
                place_label=_PLACE_LABELS.get(place, _PLACE_LABELS[PLACE_ELSEWHERE]),
                exists=exists,
                days_since_files=None if days_files is None else round(days_files, 2),
            )
        )

    for line in raw:
        if line.startswith("worktree "):
            flush()
            current = {"worktree": line[len("worktree ") :].strip()}
        elif line.startswith("HEAD "):
            current["HEAD"] = line[len("HEAD ") :].strip()
        elif line.startswith("branch "):
            current["branch"] = line[len("branch ") :].strip()
        elif line.strip() == "detached":
            current["branch"] = ""
    flush()
    items.sort(key=_sort_key)
    return items


def _read_stashes(reader: _GitReader, now: float) -> list[MapItem]:
    """Every set-aside pile, in one git call."""
    fmt = _SEP.join(["%gd", "%ct", "%gs"])
    raw = reader.lines("stash", "list", f"--format={fmt}")
    items: list[MapItem] = []
    for line in raw or []:
        parts = line.split(_SEP, 2)
        if len(parts) < 2:
            continue
        stamp = _to_epoch(parts[1])
        days = _days_between(now, stamp)
        message = parts[2].strip() if len(parts) > 2 else ""
        # "On dev: pre-merge remainder" -- the branch it was parked from is the
        # useful half, especially when that branch no longer exists.
        parked_from = ""
        if message.startswith("On ") and ":" in message:
            parked_from = message[3:].split(":", 1)[0].strip()
        items.append(
            MapItem(
                kind="stash",
                name=parts[0].strip(),
                status=_status_for(days),
                days_since=None if days is None else round(days, 2),
                subject=message,
                scope=parked_from,
            )
        )
    items.sort(key=_sort_key)
    return items


def _read_working_copy(reader: _GitReader) -> tuple[int | None, int | None]:
    """Files with unsaved edits, and files git has never been told about."""
    raw = reader.lines("status", "--porcelain")
    if raw is None:
        return (None, None)
    untracked = sum(1 for line in raw if line.startswith("??"))
    return (len(raw) - untracked, untracked)


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------


def _findings(
    branches: list[MapItem],
    worktrees: list[MapItem],
    stashes: list[MapItem],
    landing: dict[str, Any],
) -> list[dict[str, str]]:
    """The things most likely to make the owner say 'I did not know that'.

    Ordered by surprise, not by category. A copy of the project sitting in a
    folder Windows may delete outranks a tidy count of branches every time.
    """
    out: list[dict[str, str]] = []

    def add(level: str, title: str, detail: str) -> None:
        out.append({"level": level, "title": title, "detail": detail})

    stray = [w for w in worktrees if w.place != PLACE_PROJECT]
    forgotten_copies = [w for w in stray if w.status == STATUS_FORGOTTEN]
    if forgotten_copies:
        oldest = forgotten_copies[0]
        add(
            "act",
            f"{_things(len(forgotten_copies), 'separate copy', 'separate copies')} of your project "
            f"{_verb(len(forgotten_copies), 'has', 'have')} not been touched in over {FORGOTTEN_PHRASE}",
            f'The most neglected is "{oldest.name}", last worked on {_age_phrase(oldest.days_since)}, '
            f"in {oldest.place_label}. Each copy is a full second checkout of this project on your disk, "
            f"sitting on its own version of the code.",
        )
    elif len(stray) > WORKTREES_NOTABLE:
        # Volume, not age. Every copy here was made in the last few weeks, so
        # nothing is "forgotten" by the age test -- and 56 of them is still the
        # single most surprising fact on this page. A check that only ever
        # measured age would have reported all-clear on exactly the thing the
        # owner did not know existed.
        newest = min((w.days_since for w in stray if w.days_since is not None), default=None)
        add(
            "watch",
            f"{_things(len(stray), 'separate copy', 'separate copies')} of your project exist outside your project folder",
            f"Each one is a full second checkout of this project on your disk, sitting on its own version "
            f"of the code. They are being made faster than they are being cleared away -- the newest was "
            f"created {_age_phrase(newest)}. Nothing here deletes them; that is your call.",
        )

    at_risk = [w for w in worktrees if w.place == PLACE_TEMP]
    if at_risk:
        add(
            "act",
            f"{_things(len(at_risk), 'copy', 'copies')} of your project "
            f"{_verb(len(at_risk), 'sits', 'sit')} in a temporary folder",
            "Windows clears temporary folders on its own schedule. Anything saved only in there "
            "is one cleanup away from being gone, with no warning and no undo.",
        )

    missing = [w for w in worktrees if not w.exists]
    if missing:
        add(
            "watch",
            f"{_things(len(missing), 'copy', 'copies')} your project still lists "
            f"{_verb(len(missing), 'does', 'do')} not exist on disk any more",
            "The folder was deleted without telling this project, so the record of it is now stale.",
        )

    unmerged_forgotten = [b for b in branches if b.merged is False and b.status == STATUS_FORGOTTEN]
    if unmerged_forgotten:
        oldest = unmerged_forgotten[0]
        add(
            "act",
            f"{_things(len(unmerged_forgotten), 'version')} of your project "
            f"{_verb(len(unmerged_forgotten), 'holds', 'hold')} work that exists nowhere else",
            f"None of it has reached the shared copy, and none of it has been touched in over "
            f'{FORGOTTEN_PHRASE}. The oldest, "{oldest.name}", was last worked on '
            f"{_age_phrase(oldest.days_since)}.",
        )

    old_stashes = [s for s in stashes if s.status == STATUS_FORGOTTEN]
    if old_stashes:
        oldest = old_stashes[0]
        parked = f' from a version called "{oldest.scope}"' if oldest.scope else ""
        add(
            "watch",
            f"{_things(len(old_stashes), 'set-aside pile')} of work "
            f"{_verb(len(old_stashes), 'has', 'have')} been sitting untouched for over {FORGOTTEN_PHRASE}",
            f"Set-aside work is invisible everywhere else in this project -- it is not on any version "
            f"and it is not in any copy. The oldest was parked {_age_phrase(oldest.days_since)}{parked}.",
        )
    elif len(stashes) > STASHES_NOTABLE:
        add(
            "watch",
            f"{_things(len(stashes), 'set-aside pile')} of work are parked in this project",
            "Set-aside work is invisible everywhere else -- it is not on any version and not in any copy.",
        )

    local = [b for b in branches if b.scope == "local"]
    if len(local) > LOCAL_BRANCHES_NOTABLE:
        forgotten_local = sum(1 for b in local if b.status == STATUS_FORGOTTEN)
        add(
            "watch",
            f"{_things(len(local), 'version')} of your project sit on this machine",
            f"{forgotten_local} of them have not been touched in over {FORGOTTEN_PHRASE}. "
            f"Each one is a separate line of work you started and named.",
        )

    severity = str(landing.get("severity") or "")
    headline = str(landing.get("headline") or "")
    if severity in ("act", "watch") and headline:
        sentences = landing.get("sentences") or []
        detail = " ".join(str(s) for s in sentences[1:3]) if len(sentences) > 1 else ""
        add(severity, headline, detail)

    return out


def _headline(summary: dict[str, Any]) -> str:
    """One sentence, in the owner's words, about the size of what he cannot see."""
    total = int(summary.get("total_items") or 0)
    forgotten = int(summary.get("forgotten") or 0)
    if total == 0:
        return "Nothing is lying around. This project has no leftover copies, versions, or set-aside work."
    if forgotten == 0:
        return f"{_things(total, 'thing')} exist in this project, and all of them have been touched recently."
    return (
        f"{_things(total, 'thing')} exist in this project. "
        f"{forgotten} of them have not been touched in over {FORGOTTEN_PHRASE}."
    )


def _unreadable(reason: str, took_ms: int) -> SystemMap:
    """A reading that honestly says it could not read anything."""
    headline = "Thomas could not read what is in this project."
    return SystemMap(
        ok=False,
        headline=headline,
        checked_at=time.time(),
        notes=[reason],
        took_ms=took_ms,
    )


def collect_system_map(repo_root: str | Path | None = None) -> SystemMap:
    """Inventory everything that exists in ``repo_root`` (this repo by default).

    Never raises. Never touches the network. Never changes anything. Anything
    that could not be read becomes a note rather than a crash or a false zero.
    """
    started = time.monotonic()
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT

    def elapsed_ms() -> int:
        return int((time.monotonic() - started) * 1000)

    if shutil.which("git") is None:
        return _unreadable(
            "Git is not installed on this machine, so there is no way to see what this project contains.",
            elapsed_ms(),
        )

    reader = _GitReader(root)
    if reader.run("rev-parse", "--show-toplevel") is None:
        return _unreadable(
            f"{root} is not a project Thomas can read, so there is nothing to inventory.",
            elapsed_ms(),
        )

    now = time.time()
    landing = collect_landing_health(root).as_dict()
    default_branch = str(landing.get("default_branch") or "")

    merged = _read_merged(reader, default_branch)
    branches, branch_dates = _read_branches(reader, now, merged, default_branch)
    worktrees = _read_worktrees(reader, now, root, branch_dates, merged)
    stashes = _read_stashes(reader, now)
    unsaved, untracked = _read_working_copy(reader)

    everything = [*branches, *worktrees, *stashes]
    local = [b for b in branches if b.scope == "local"]
    remote = [b for b in branches if b.scope == "remote"]

    def count(items: list[MapItem], status: str) -> int:
        return sum(1 for i in items if i.status == status)

    ages = [i.days_since for i in everything if i.days_since is not None]
    summary: dict[str, Any] = {
        "total_items": len(everything),
        "active": count(everything, STATUS_ACTIVE),
        "idle": count(everything, STATUS_IDLE),
        "forgotten": count(everything, STATUS_FORGOTTEN),
        "unknown_age": count(everything, STATUS_UNKNOWN),
        "branches_total": len(branches),
        "branches_local": len(local),
        "branches_remote": len(remote),
        "branches_unmerged": sum(1 for b in branches if b.merged is False),
        "branches_forgotten": count(branches, STATUS_FORGOTTEN),
        "worktrees": len(worktrees),
        "worktrees_outside_project": sum(1 for w in worktrees if w.place != PLACE_PROJECT),
        "worktrees_in_temp": sum(1 for w in worktrees if w.place == PLACE_TEMP),
        "worktrees_missing": sum(1 for w in worktrees if not w.exists),
        "worktrees_forgotten": count(worktrees, STATUS_FORGOTTEN),
        "stashes": len(stashes),
        "stashes_forgotten": count(stashes, STATUS_FORGOTTEN),
        "unsaved_files": unsaved,
        "untracked_files": untracked,
        "default_branch": default_branch,
        "current_branch": str(landing.get("branch") or ""),
        "oldest_days": round(max(ages), 2) if ages else None,
        # The single largest pile of unlanded work on any one version. The map
        # scales its longest thread to this, so the biggest thing on screen is
        # always the biggest thing in the project.
        "max_ahead": max([b.ahead for b in branches if b.ahead is not None], default=None),
        "days_since_default_moved": landing.get("days_since_default_moved"),
    }

    notes: list[str] = []
    if unsaved is None:
        notes.append("Thomas could not read which files have unsaved edits.")
    if not default_branch:
        notes.append(
            "This project has no shared copy set up, so Thomas cannot tell which work has already landed safely."
        )
    for failure in dict.fromkeys(reader.failures):
        notes.append(f"One reading did not come back in time ({failure}), so a count here may be low.")

    return SystemMap(
        ok=True,
        headline=_headline(summary),
        checked_at=now,
        repo_root=str(root),
        summary=summary,
        findings=_findings(branches, worktrees, stashes, landing),
        branches=branches,
        worktrees=worktrees,
        stashes=stashes,
        landing=landing,
        notes=notes,
        took_ms=elapsed_ms(),
    )
