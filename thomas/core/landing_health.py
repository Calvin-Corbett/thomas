"""Landing heartbeat -- is your work safely landed, or is it piling up?

This module answers one question, in words that do not require knowing what a
commit is: *is the work I have done safely on the shared copy of my project, or
is it stacking up somewhere it can only get harder to merge?*

It exists because of what happened to this repo. ``main`` stopped moving on
2026-06-09. Work kept happening on a side branch for two months. Nothing was
watching the CUMULATIVE total -- every individual gate only ever compared one
change to the one before it, and each of those looked fine. By the time anyone
looked, the pile was 576 changes across 1,890 files: too big for a person to
review, too old to merge cleanly, and big enough that a merge silently brought
back deleted code because the two sides had drifted so far apart.

Two kinds of trouble, so two kinds of trigger, each covering the other's blind
spot:

* **Size** catches ACCUMULATION -- "you have built more than can be landed
  safely in one go".
* **Time** catches ABANDONMENT -- three changes untouched for three weeks is a
  problem that no size threshold will ever notice.

The 2026-06-09 pile was both at once.

Design rules this file is held to:

* **It never raises and it never hangs.** No git, no repo, no remote, a
  detached HEAD, a network share that went away -- each one degrades to
  severity ``unknown`` with an honest sentence saying what could not be read.
  A health check that can crash the thing it is checking is worse than none.
* **It never touches the network.** Every git command here reads what is
  already on this machine. That keeps it fast and unblockable, at the honest
  cost that "how long since main moved" means "since the last time this machine
  heard about main".
* **No LLM calls.** These are facts, not opinions, and facts should not cost
  tokens or need a working API key to be true.
* **Plain language.** The output is written for the person who owns the
  project, not for the person who wrote the git manual.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Thresholds
#
# All tuning lives here so nobody has to hunt for a magic number in the logic.
# The numbers are chosen around what a HUMAN (or an AI reviewer) can actually
# hold in their head at once, not around what git can technically handle.
# ---------------------------------------------------------------------------

#: Saved changes waiting to land. ~25 is about one focused session's work; past
#: ~50 a reviewer stops reading individual changes and starts skimming.
COMMITS_AHEAD_WATCH = 25
COMMITS_AHEAD_ACT = 50

#: Files that differ from the shared copy. 100 files is a long afternoon of
#: review; 200 is past the point where any reviewer, human or AI, is really
#: reading it. (The pile that prompted this module was 1,890.)
FILES_DIVERGED_WATCH = 100
FILES_DIVERGED_ACT = 200

#: Days since the shared copy last moved. A week means a rhythm has slipped;
#: three weeks means the two copies are drifting far enough apart that merging
#: starts producing conflicts and surprise resurrections of deleted code.
DAYS_DEFAULT_STALE_WATCH = 7
DAYS_DEFAULT_STALE_ACT = 21

#: Days since the current branch itself last moved WHILE work sits unlanded.
#: This is the abandonment signal: a small pile that nobody is pushing forward
#: is still a pile, and size thresholds will never flag it.
DAYS_BRANCH_IDLE_WATCH = 7
DAYS_BRANCH_IDLE_ACT = 21

#: Files edited but not saved into the project's history at all. This is a
#: safety signal, not a landing one -- it is the work that dies with the
#: machine -- so it can raise a "watch" but never an "act".
UNCOMMITTED_FILES_WATCH = 20

#: Per-command and whole-check ceilings. Nothing here may outlive these.
GIT_COMMAND_TIMEOUT_SECONDS = 5.0
GIT_TOTAL_BUDGET_SECONDS = 15.0

SEVERITY_OK = "ok"
SEVERITY_WATCH = "watch"
SEVERITY_ACT = "act"
SEVERITY_UNKNOWN = "unknown"

_SEVERITY_RANK = {SEVERITY_OK: 0, SEVERITY_WATCH: 1, SEVERITY_ACT: 2}

# Every failure a git probe in this module is allowed to meet, named
# explicitly. A broad ``except Exception`` here would turn a genuine bug in
# this file into a calm "unknown" reading -- which is exactly the kind of
# quiet lie this module was written to prevent.
#   OSError                    -- git not on PATH, working dir gone, dead pipe
#   subprocess.SubprocessError -- TimeoutExpired and its siblings
#   ValueError                 -- bad argument shape, undecodable output
_GIT_ERRORS = (OSError, subprocess.SubprocessError, ValueError)

_SECONDS_PER_DAY = 86400.0
_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class LandingHealth:
    """One reading of the landing heartbeat.

    ``severity`` is the verdict, ``headline`` is the one-line version of it,
    and ``sentences`` is the whole thing in plain English (``sentences[0]`` is
    always the headline, so a caller that only renders the list still leads
    with the verdict). Every raw number is ``None`` when it could not be read
    -- never 0, because "I could not check" and "there is nothing" are
    different answers and this module refuses to conflate them.
    """

    severity: str
    headline: str
    sentences: list[str] = field(default_factory=list)
    branch: str = ""
    default_branch: str = ""
    commits_ahead: int | None = None
    files_diverged: int | None = None
    days_since_default_moved: float | None = None
    days_since_branch_commit: float | None = None
    uncommitted_files: int | None = None
    checked_at: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe view, for the API and for logs."""
        return {
            "severity": self.severity,
            "headline": self.headline,
            "sentences": list(self.sentences),
            "branch": self.branch,
            "default_branch": self.default_branch,
            "commits_ahead": self.commits_ahead,
            "files_diverged": self.files_diverged,
            "days_since_default_moved": self.days_since_default_moved,
            "days_since_branch_commit": self.days_since_branch_commit,
            "uncommitted_files": self.uncommitted_files,
            "checked_at": self.checked_at,
            "thresholds": {
                "commits_ahead_watch": COMMITS_AHEAD_WATCH,
                "commits_ahead_act": COMMITS_AHEAD_ACT,
                "files_diverged_watch": FILES_DIVERGED_WATCH,
                "files_diverged_act": FILES_DIVERGED_ACT,
                "days_default_stale_watch": DAYS_DEFAULT_STALE_WATCH,
                "days_default_stale_act": DAYS_DEFAULT_STALE_ACT,
                "days_branch_idle_watch": DAYS_BRANCH_IDLE_WATCH,
                "days_branch_idle_act": DAYS_BRANCH_IDLE_ACT,
                "uncommitted_files_watch": UNCOMMITTED_FILES_WATCH,
            },
        }

    def log_lines(self) -> list[str]:
        """The reading as lines for a server log, verdict first."""
        label = self.severity.upper()
        return [f"Landing check [{label}]: {line}" for line in self.sentences]


class _GitProbe:
    """Runs read-only git commands under a hard total time budget.

    Every command gets its own timeout AND draws from a shared deadline, so a
    repo on a stalled network drive cannot turn this check into a hang no
    matter how many probes it fails.
    """

    def __init__(self, root: Path, budget_seconds: float = GIT_TOTAL_BUDGET_SECONDS) -> None:
        self.root = root
        self.deadline = time.monotonic() + budget_seconds
        # git must never stop to ask a human anything, and must never take the
        # index lock just to answer a question.
        self.env = dict(os.environ)
        self.env["GIT_TERMINAL_PROMPT"] = "0"
        self.env["GIT_OPTIONAL_LOCKS"] = "0"

    def run(self, *args: str) -> str | None:
        """Return stripped stdout, or None if the command failed or timed out."""
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
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
            return None
        if proc.returncode != 0:
            return None
        return (proc.stdout or "").strip()

    def count_lines(self, *args: str) -> int | None:
        """Number of non-empty output lines, or None if the command failed."""
        out = self.run(*args)
        if out is None:
            return None
        return len([line for line in out.splitlines() if line.strip()])

    def timestamp(self, ref: str) -> float | None:
        """Unix time of the newest commit on ``ref``, or None."""
        out = self.run("log", "-1", "--format=%ct", ref)
        if not out:
            return None
        try:
            return float(out.split()[0])
        except (ValueError, IndexError):
            return None


def _unknown(reason: str, *, branch: str = "", default_branch: str = "") -> LandingHealth:
    """A reading that honestly says it could not read anything."""
    headline = "Thomas could not check whether your work is safely landed."
    return LandingHealth(
        severity=SEVERITY_UNKNOWN,
        headline=headline,
        sentences=[headline, reason],
        branch=branch,
        default_branch=default_branch,
        checked_at=time.time(),
    )


def _worst(*severities: str) -> str:
    """The most serious of the given severities."""
    return max(severities, key=lambda s: _SEVERITY_RANK.get(s, 0))


def _level(value: int | float, watch: int | float, act: int | float) -> str:
    if value >= act:
        return SEVERITY_ACT
    if value >= watch:
        return SEVERITY_WATCH
    return SEVERITY_OK


def _things(count: int, singular: str, plural: str = "") -> str:
    """'1 file' / '3 files' -- so no sentence ever reads '1 changes'."""
    word = singular if count == 1 else (plural or singular + "s")
    return f"{count} {word}"


def _days_ago(days: float) -> str:
    whole = int(days)
    if whole < 1:
        return "today"
    if whole == 1:
        return "1 day ago"
    return f"{whole} days ago"


def _resolve_default_branch(probe: _GitProbe) -> str | None:
    """Name the shared copy of the project, e.g. ``origin/main``.

    Prefers what the remote itself says its default branch is, then falls back
    to the conventional names. Returns None when there is no remote at all --
    a project that has never been shared has nowhere to land, and saying so is
    more honest than inventing a comparison.
    """
    head = probe.run("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if head and head.startswith("refs/remotes/"):
        candidate = head[len("refs/remotes/") :]
        if probe.run("rev-parse", "--verify", "--quiet", candidate):
            return candidate
    remotes = (probe.run("remote") or "").split()
    for remote in ["origin", *remotes]:
        for name in ("main", "master"):
            candidate = f"{remote}/{name}"
            if probe.run("rev-parse", "--verify", "--quiet", candidate):
                return candidate
    return None


def collect_landing_health(repo_root: str | Path | None = None) -> LandingHealth:
    """Read the landing heartbeat for ``repo_root`` (this repo by default).

    Never raises. Never touches the network. Returns severity ``unknown``
    rather than guessing whenever something could not be read.
    """
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT

    if shutil.which("git") is None:
        return _unknown(
            "Git is not installed on this machine, so there is no way to see what has been saved or where it is."
        )

    probe = _GitProbe(root)
    if probe.run("rev-parse", "--show-toplevel") is None:
        return _unknown(f"{root} is not a project Thomas can track, so there is nothing to check yet.")

    branch = probe.run("rev-parse", "--abbrev-ref", "HEAD") or ""
    if not branch:
        return _unknown("Thomas could not tell which version of the project you are working on.")
    if branch == "HEAD":
        return _unknown(
            "You are looking at a single point in the project's history rather than "
            "working on a named version of it, so there is nothing here that can be "
            "landed. Switching back to your working version will make this readable again.",
        )

    default_branch = _resolve_default_branch(probe)
    if default_branch is None:
        return _unknown(
            "This project has no shared copy set up, so there is nowhere for your "
            "work to land and no way to tell whether it is safe.",
            branch=branch,
        )

    commits_ahead = probe.count_lines("rev-list", f"{default_branch}..HEAD")
    files_diverged = probe.count_lines("diff", "--name-only", f"{default_branch}...HEAD")
    uncommitted = probe.count_lines("status", "--porcelain")
    if commits_ahead is None or files_diverged is None or uncommitted is None:
        return _unknown(
            "Thomas could not finish reading this project's history in time, so it "
            "cannot say whether your work is safely landed.",
            branch=branch,
            default_branch=default_branch,
        )

    now = time.time()
    default_ts = probe.timestamp(default_branch)
    branch_ts = probe.timestamp("HEAD")
    days_default = None if default_ts is None else max(0.0, (now - default_ts) / _SECONDS_PER_DAY)
    days_branch = None if branch_ts is None else max(0.0, (now - branch_ts) / _SECONDS_PER_DAY)

    severity, sentences = _describe(
        branch=branch,
        default_branch=default_branch,
        commits_ahead=commits_ahead,
        files_diverged=files_diverged,
        days_default=days_default,
        days_branch=days_branch,
        uncommitted=uncommitted,
    )
    return LandingHealth(
        severity=severity,
        headline=sentences[0],
        sentences=sentences,
        branch=branch,
        default_branch=default_branch,
        commits_ahead=commits_ahead,
        files_diverged=files_diverged,
        days_since_default_moved=None if days_default is None else round(days_default, 2),
        days_since_branch_commit=None if days_branch is None else round(days_branch, 2),
        uncommitted_files=uncommitted,
        checked_at=now,
    )


def _describe(
    *,
    branch: str,
    default_branch: str,
    commits_ahead: int,
    files_diverged: int,
    days_default: float | None,
    days_branch: float | None,
    uncommitted: int,
) -> tuple[str, list[str]]:
    """Turn the numbers into a verdict and plain-English sentences.

    The headline is decided last, from the worst signal found, so the first
    thing the owner reads is always the actual verdict.
    """
    shared = _short_name(default_branch)
    has_unlanded_work = commits_ahead > 0

    size_severity = _worst(
        _level(commits_ahead, COMMITS_AHEAD_WATCH, COMMITS_AHEAD_ACT),
        _level(files_diverged, FILES_DIVERGED_WATCH, FILES_DIVERGED_ACT),
    )
    body: list[str] = []

    if has_unlanded_work:
        waiting = _things(commits_ahead, "saved change")
        if size_severity == SEVERITY_ACT:
            body.append(
                f"{waiting} are waiting to land on {shared}, the shared copy of your "
                f"project. That is more than can be checked properly in one go."
            )
        elif size_severity == SEVERITY_WATCH:
            body.append(
                f"{waiting} are waiting to land on {shared}, the shared copy of your "
                f"project. Worth landing soon, while it is still a small job."
            )
        else:
            body.append(f"{waiting} are waiting to land on {shared}, the shared copy of your project.")

        if files_diverged >= FILES_DIVERGED_WATCH:
            body.append(
                f"They touch {_things(files_diverged, 'file')}. Past about "
                f"{FILES_DIVERGED_ACT} files, nobody -- person or AI -- can review a "
                f"change carefully enough to catch what it breaks."
            )
    else:
        body.append(f"Nothing is waiting to land: everything you have saved is already on {shared}.")

    # --- Time signals. Both only mean something while work is actually sitting
    # unlanded. A quiet week with an empty pile is a holiday, not a problem, and
    # a readiness check that nags about it stops being read.
    time_severity = SEVERITY_OK
    if has_unlanded_work and days_default is not None:
        stale = _level(days_default, DAYS_DEFAULT_STALE_WATCH, DAYS_DEFAULT_STALE_ACT)
        time_severity = _worst(time_severity, stale)
        if stale == SEVERITY_ACT:
            body.append(
                f"{shared} last moved {_days_ago(days_default)}. Everything built since "
                f"then has been piling up beside it instead of joining it -- which is "
                f"why landing it now is hard work rather than a routine step."
            )
        elif stale == SEVERITY_WATCH:
            body.append(f"{shared} last moved {_days_ago(days_default)}.")

    if has_unlanded_work and days_branch is not None:
        idle = _level(days_branch, DAYS_BRANCH_IDLE_WATCH, DAYS_BRANCH_IDLE_ACT)
        time_severity = _worst(time_severity, idle)
        if idle != SEVERITY_OK:
            body.append(
                f"Your work on {branch} has not moved since {_days_ago(days_branch)}, and "
                f"it still has not landed. Work left standing gets harder to land, not easier."
            )

    safety_severity = SEVERITY_OK
    if uncommitted >= UNCOMMITTED_FILES_WATCH:
        # Never an "act": unsaved work is a different risk from an unlanded
        # pile, and one file typed a minute ago should not read as an alarm.
        safety_severity = SEVERITY_WATCH
        body.append(
            f"{_things(uncommitted, 'file')} have edits that are not saved into the "
            f"project's history at all. If this machine died right now, that work would "
            f"be gone with it."
        )

    severity = _worst(size_severity, time_severity, safety_severity)
    headline = _headline(severity, shared)
    if severity == SEVERITY_ACT:
        body.append(
            "The way out is to land work in smaller pieces, more often. Each small "
            "piece can be checked on its own; one enormous one cannot."
        )
    return severity, [headline, *body]


def _headline(severity: str, shared: str) -> str:
    if severity == SEVERITY_ACT:
        return (
            f"Too much work is stacked up outside {shared}. This is the point where landing it safely stops being easy."
        )
    if severity == SEVERITY_WATCH:
        return "Your work is safe, but a pile is starting to build up."
    return f"Everything is on {shared}. You're ready to work."


def _short_name(default_branch: str) -> str:
    """'origin/main' reads as 'main' to someone who does not use git."""
    return default_branch.split("/", 1)[-1] if "/" in default_branch else default_branch
