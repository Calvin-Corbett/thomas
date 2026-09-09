#!/usr/bin/env python3
"""The sprawl curve, measured -- not narrated.

WHY THIS EXISTS: any claim that a previous fix moved branch sprawl needs a
number behind it rather than a story. This
module is a READ-ONLY analyzer: it never writes anything, never fetches the
network, and never estimates a value it cannot source. Every field in its
output is either MEASURED (computed live, right now, from this repo's own
refs/reflogs/registries) or CITED (a fixed value copied from a specific,
named, dated document, because the state that produced it no longer exists on
disk to be re-measured) or UNKNOWN (explicitly, because no source covers it).
Nothing in this module's output is guessed, interpolated, or smoothed.

THE HONESTY CONTRACT THIS MODULE EXISTS TO SATISFY: "the analyzer never
guesses -- unknown windows are marked unknown; the proof doc's every number
[is] regenerable by the committed analyzer." A CITED value satisfies
"regenerable" the same way a MEASURED one does -- re-running this module
reproduces the identical cited constant, because it is a constant with a
named source, not a computation this module performs. What it does NOT do is
pretend a cited constant is a live measurement, or fill the gap between two
anchors with a straight line. See ANCHORS below.

FIVE DATA SOURCES, FIVE DIFFERENT HONESTY SHAPES:

1. **Remote-tracking reflogs** (``.git/logs/refs/remotes/<remote>/**``, read
   directly off disk -- no subprocess, no ``git reflog show`` per branch,
   which would be 150+ process spawns for one run). A branch's reflog file's
   FIRST line is the earliest local record of it (a fetch or push storing
   event) -- a lower-bound "first seen" signal, not a true creation date (a
   branch can exist on the remote for days before this clone/worktree ever
   fetches it). Its LAST line is the most recent recorded update. Both are
   real dates from real git objects; both undercount, because a branch that
   was pushed, worked, and deleted from the remote before this reflog was
   ever read leaves no trace here at all -- ITS DEATH, AND SOMETIMES ITS
   ENTIRE LIFE, IS INVISIBLE TO THIS SOURCE. Stated as a blind spot, not
   silently absorbed into a lower count.

2. **``docs/ops/graveyard.json``** (``scripts/forge/graveyard.py``): the
   richest deletion-side source by record count (210 branch deaths, 499 file
   deaths) -- but every single branch record in it shares ``deleted_on =
   2026-08-25`` and a ``reason`` starting ``"seeded:"`` (verified by reading
   the file, not assumed): these are a RETROACTIVE bulk recording of the
   2026-08-24 worktree-fleet closure and custodian archive, written the
   morning after. The graveyard's date field is honestly the date it was
   RECORDED, not the date each branch actually died -- this module never
   conflates the two, and reports the seed-date clustering explicitly rather
   than presenting 210 branches as if they died evenly across a period they
   did not.

3. **``refs/archive/stash/*`` and ``refs/archive/worktree/*``** (created by
   this program's own salvage tooling, phase 0.3 and this session's stash
   sweep): each archive ref's NAME carries the archival date; the commit IT
   POINTS AT carries the object's own ``creatordate`` -- the real original
   date the stash or worktree snapshot was made, often weeks before its
   archival date. Read via one ``for-each-ref --format`` call per namespace
   (git resolves ``%(creatordate)`` server-side; no per-ref subprocess).

4. **Milestone commits**: a small, hardcoded table of (label, sha) pairs for
   the interventions the plan names by name -- the advisory rule, the
   custodian, the squash, the worktree closure, the gates-enforcing fix, the
   graveyard seed. Every date is resolved LIVE via ``git show -s
   --format=%cI <sha>`` at run time, never hardcoded as a string -- if the
   sha does not resolve in this checkout (shallow clone, history rewrite),
   the milestone reports ``date: None, resolved: False`` instead of a stale
   guess.

5. **Two CITED anchors**: the plan's own evidence line (746 unpushed / 63
   local / 70 stashes / 150+ remote, dated 2026-08-27, before this session's
   fixes) and this program's own mid-session measurement
   (754 unpushed / 2 local / 157 remote(mirror) / 0 stashes). Neither
   is re-derivable: the 61 local branches the first anchor counted are
   deleted, unarchived by any graveyard record, and their reflogs are gone
   with them (see BLIND SPOT below) -- there is no git state left to
   re-measure them from. Both anchors are reproduced here as citations, with
   their source document named, not as computations.

BLIND SPOT, STATED PLAINLY: most branches this repo ever created were
deleted on 2026-08-27, in the same cleanup this plan is proving out. Their
reflogs are deleted with them (git removes a branch's reflog file when the
branch ref itself is deleted). This module can name how many branches died
in aggregate at two points in time (the two CITED anchors above) and can
show every branch death the graveyard bothered to record individually (210,
all bulk-seeded from the 2026-08-24 salvage, not this cleanup) -- but it
CANNOT name which 61 local branches died today, when each was created, or
how long each sat unclaimed. That gap is not filled with an estimate here.

TODAY'S LIVE NUMBERS reuse ``scripts/crew/brief/trunk_health.py``'s own
``count_unpushed``/``count_branches``/``count_stashes`` -- the same reads
session start already trusts -- rather than re-implementing them, so this
module's "measured, right now" anchor is provably the same instrument as the
TRUNK line, not a second implementation that could silently drift from it.

CLI: ``python scripts/forge/sprawl_history.py [--repo-root PATH] [--json]
[--since YYYY-MM-DD]``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = _REPO_ROOT

from scripts.crew.brief import trunk_health  # noqa: E402 - needs sys.path set first
from scripts.forge import graveyard as graveyard_mod  # noqa: E402

TRUNK_REMOTE = "dev-origin"
DEFAULT_SINCE = date(2026, 5, 1)
WEEK_DAYS = 7

_SAFE_EXCEPTIONS = (
    OSError,
    UnicodeDecodeError,
    ValueError,
    TypeError,
    AttributeError,
    RuntimeError,
    subprocess.SubprocessError,
)

# Every interpretive intervention the plan names, resolved live against the
# real commit object at run time -- never a hardcoded date string. A sha that
# does not resolve in this checkout reports ``date: None`` rather than a
# guess (see module docstring, source 4).
MILESTONES: tuple[dict[str, str], ...] = (
    {
        "key": "advisory_rule",
        "sha": "a2f50b48d00751f13251fb05c7e3915991478a65",
        "label": "CLAUDE.md branch-awareness advisory rule introduced",
    },
    {
        "key": "branch_custodian",
        "sha": "ca020741ec41862d4a675e66577e6b9017ba6075",
        "label": "branch_custodian.py lands (thomas consolidate)",
    },
    {
        "key": "squash",
        "sha": "ccea30271a79b351e79db07980cebe055e48bc40",
        "label": "the ccea3027 squash (two months of work landed at once)",
    },
    {
        "key": "worktree_closure_phase_0_3",
        "sha": "0c4b46edfdc5239f21d66b8b32aae22312716572",
        "label": "worktree fleet closure phase 0.3 (59 archived+removed, 7 skipped, 0 bytes lost)",
    },
    {
        "key": "worktree_closure_complete",
        "sha": "d12571cdfdc3567d7d66382153405e14798c3223",
        "label": "worktree fleet closure complete (one worktree remains: the checkout itself)",
    },
    {
        "key": "gates_enforcing_fix",
        "sha": "db808bdf7b198092dc4f33f28bcf2185adc50cb9",
        "label": "the monolith guard scans the repository it guards (the gates-not-enforcing window closes)",
    },
    {
        "key": "graveyard_seeded",
        "sha": "b8128754e4eedcb71069c4ec6f46e5bb36d4cbf4",
        "label": "the graveyard is seeded -- 709 retroactive death records written",
    },
)

# Two measurements this module cannot re-derive, because the state that
# produced them is gone (see module docstring, source 5). Each names its
# exact source so a reader can verify the citation independently of this
# module's own output.
CITED_ANCHORS: tuple[dict[str, Any], ...] = (
    {
        "date": "2026-08-27",
        "label": "original cleanup finding (before this session's fixes)",
        "source": "the original cleanup review's evidence basis line",
        "unpushed": 746,
        "local_branches": 63,
        "remote_branches": 150,
        "remote_branches_note": "150+, plan states as a lower bound",
        "stashes": 70,
    },
    {
        "date": "2026-08-27",
        "label": "mid-session measurement (Task 1's trunk_health, live TRUNK line)",
        "source": "the T1 review line (mid-session trunk_health run)",
        "unpushed": 754,
        "local_branches": 2,
        "remote_branches": 157,
        "remote_branches_note": "mirror (on-disk refs/remotes cache); T1 review also found live ls-remote showed 151",
        "stashes": 0,
    },
)

BLIND_SPOTS: tuple[str, ...] = (
    "Most branches this repo ever created were deleted on 2026-08-27, in the "
    "same cleanup this analyzer proves out. A deleted branch's reflog is "
    "deleted with it -- this analyzer cannot name which branches died today, "
    "when each was created, or how long each sat unclaimed.",
    "The graveyard's 210 branch-death records all share deleted_on=2026-08-25 "
    "and a reason starting 'seeded:' -- that is the date they were RECORDED "
    "(a retroactive bulk write the morning after the 2026-08-24 worktree "
    "closure), not the date each branch actually died. This analyzer reports "
    "the seed-date clustering as-is; it does not spread the 210 across the "
    "period they were archived in, because it does not know the true "
    "per-branch dates.",
    "Remote-tracking reflogs only exist for branches still present in this "
    "checkout's refs/remotes mirror. A branch pushed, worked, and deleted "
    "from the remote before this checkout ever fetched it leaves no reflog "
    "trace at all -- its entire life is invisible to this source.",
    "This checkout's own HEAD reflog only reaches back to its earliest "
    "surviving entry (reported below as reflog_horizons.head.earliest) -- "
    "any branch activity on this machine before that point is unrecoverable "
    "from this source.",
    "Weekly live-branch and unpushed-commit counts are reported only at the "
    "small set of ANCHOR dates this module can source (two cited, one "
    "measured live). Every other week is explicitly 'unknown' -- this "
    "module performs no interpolation between anchors.",
)


def _run_git(args: list[str], repo_root: Path, *, timeout: float = 10.0) -> tuple[bool, str, str]:
    """One git plumbing command against ``repo_root``. Never raises -- see
    ``trunk_health._run_git``, the same shape, reproduced here so this
    module has no import-time dependency beyond what it already needs."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode == 0, proc.stdout, proc.stderr
    except _SAFE_EXCEPTIONS as exc:  # pragma: no cover - defensive
        return False, "", str(exc)


def _git_common_dir(repo_root: Path) -> Path | None:
    """The shared git directory (``git rev-parse --git-common-dir``) --
    correct even inside a worktree, where reflogs live in the COMMON dir,
    not the worktree-private one. ``None`` if this is not a git repo at
    all (fixture teardown, bad path) -- callers degrade to 'unavailable'."""
    ok, out, _err = _run_git(["rev-parse", "--git-common-dir"], repo_root)
    if not ok:
        return None
    raw = out.strip()
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_absolute() else (repo_root / p).resolve()


def _parse_reflog_line(line: str) -> str | None:
    """One raw ``.git/logs/...`` line's ISO-8601 timestamp, or ``None`` if
    the line is malformed. Format: ``<old> <new> <name> <email> <ts> <tz>\\t<msg>``
    -- ``<ts>`` is a unix epoch integer, ``<tz>`` an offset like ``-0500``."""
    header = line.split("\t", 1)[0]
    parts = header.split(" ")
    if len(parts) < 6:
        return None
    ts_raw, tz_raw = parts[-2], parts[-1]
    try:
        epoch = int(ts_raw)
    except ValueError:
        return None
    if len(tz_raw) != 5 or tz_raw[0] not in "+-":
        return None
    try:
        sign = 1 if tz_raw[0] == "+" else -1
        offset = timedelta(hours=int(tz_raw[1:3]), minutes=int(tz_raw[3:5])) * sign
    except ValueError:
        return None
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc) + offset
    return dt.replace(tzinfo=timezone(offset)).isoformat()


def _repo_root_commit_iso(repo_root: Path) -> str | None:
    """The committer date of this repository's own root commit(s)
    (``git log --max-parents=0``) -- the earliest a reflog entry could
    possibly be genuine. ``None`` if it cannot be determined (shallow
    clone, git failure) -- callers treat a missing floor as 'no lower
    bound available', never as 'anything goes'."""
    ok, out, _err = _run_git(["log", "--max-parents=0", "--format=%cI"], repo_root)
    if not ok:
        return None
    candidates = []
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            candidates.append((datetime.fromisoformat(ln), ln))
        except ValueError:
            continue
    if not candidates:
        return None
    return min(candidates, key=lambda pair: pair[0])[1]


def _plausible_timestamp(iso_ts: str, *, floor: str | None, now: datetime) -> bool:
    """A reflog/ref timestamp is only plausible if it falls between the
    repository's own root-commit date (``floor``, when known) and ``now``
    (+1 day tolerance for clock skew). MINOR-2 (adversarial review, fix
    round 1, 2026-08-27): a fixture reflog with a first entry dated seven
    years before the repo's own root commit was previously passed through
    verbatim as 'measured' first-seen data, with no signal that it was
    impossible. A timestamp outside this window cannot be real regardless
    of what the raw file says -- reporting it as measured would misreport
    corruption as evidence, exactly the failure mode this module exists to
    avoid. ``floor is None`` (root commit undeterminable) only enforces the
    upper bound -- it never widens into 'no lower bound check at all' by
    silently passing everything, it just cannot rule out an early date it
    has no reference point for."""
    try:
        dt = datetime.fromisoformat(iso_ts)
    except ValueError:
        return False
    if dt > now + timedelta(days=1):
        return False
    if floor is not None:
        try:
            floor_dt = datetime.fromisoformat(floor)
        except ValueError:
            floor_dt = None
        if floor_dt is not None and dt < floor_dt:
            return False
    return True


def remote_branch_first_seen(repo_root: Path, *, remote: str = TRUNK_REMOTE) -> dict[str, Any]:
    """For every ``refs/remotes/<remote>/<branch>`` reflog file on disk:
    the earliest and latest PLAUSIBLE recorded timestamp (earliest local
    record of that branch -- a lower-bound 'first seen', not a true
    creation date). Read directly off disk (no subprocess per branch --
    see module docstring, source 1). Every entry is checked against
    ``_plausible_timestamp`` before being allowed to set ``first_seen``/
    ``last_seen``; an entry that fails (garbage, or a date outside the
    repo's own root-commit..now window) is treated exactly like an
    unparseable line -- skipped, never passed through as measured data.
    If every entry for a branch is implausible or unparseable, that
    branch's ``first_seen``/``last_seen`` are ``None`` (unknown), not a
    guess at which entry to trust.

    Returns ``{"available": False, "reason": ...}`` if the common git dir
    or the remote's reflog directory cannot be found -- never a fabricated
    empty result presented as if the remote genuinely has zero branches."""
    common = _git_common_dir(repo_root)
    if common is None:
        return {"available": False, "reason": "cannot resolve git common dir", "branches": {}}
    log_dir = common / "logs" / "refs" / "remotes" / remote
    if not log_dir.is_dir():
        return {"available": False, "reason": f"no reflog directory for remote {remote!r}", "branches": {}}

    floor = _repo_root_commit_iso(repo_root)
    now = datetime.now(timezone.utc)

    branches: dict[str, dict[str, str | None]] = {}
    for path in log_dir.rglob("*"):
        if not path.is_file() or path.name == "HEAD":
            continue
        branch_name = path.relative_to(log_dir).as_posix()
        try:
            lines = [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
        except OSError:
            continue
        if not lines:
            continue
        parsed = [_parse_reflog_line(ln) for ln in lines]
        plausible = [ts for ts in parsed if ts is not None and _plausible_timestamp(ts, floor=floor, now=now)]
        # Compare by the parsed absolute instant, not the raw ISO string --
        # two entries with different UTC offsets can sort wrong lexically
        # even when one is genuinely earlier than the other.
        first_ts = min(plausible, key=datetime.fromisoformat) if plausible else None
        last_ts = max(plausible, key=datetime.fromisoformat) if plausible else None
        branches[branch_name] = {"first_seen": first_ts, "last_seen": last_ts}
    return {"available": True, "reason": "", "branches": branches}


def remote_branch_tip_dates(repo_root: Path, *, remote: str = TRUNK_REMOTE) -> dict[str, str]:
    """Every ``refs/remotes/<remote>/*`` branch's tip commit date, via one
    batched ``for-each-ref --format`` call (git resolves ``%(creatordate)``
    itself -- no per-branch subprocess). Empty dict if the remote has no
    refs or the call fails; callers treat empty as 'nothing known', which
    is also the honest answer for a repo with no such remote."""
    ok, out, _err = _run_git(
        ["for-each-ref", f"refs/remotes/{remote}", "--format=%(refname)\t%(creatordate:iso-strict)"], repo_root
    )
    if not ok:
        return {}
    tips: dict[str, str] = {}
    prefix = f"refs/remotes/{remote}/"
    for line in out.splitlines():
        if not line.strip() or "\t" not in line:
            continue
        ref, ts = line.split("\t", 1)
        if ref.endswith("/HEAD") or not ref.startswith(prefix):
            continue
        tips[ref[len(prefix) :]] = ts.strip()
    return tips


def archive_ref_events(repo_root: Path, *, namespace: str) -> dict[str, Any]:
    """Every ``refs/archive/<namespace>/*`` ref's object date
    (``%(creatordate)``, one batched call) -- used for both
    ``refs/archive/stash`` (name carries the archival date; the commit's
    own date is the true original snapshot date) and
    ``refs/archive/worktree`` (salvaged worktree checkpoints)."""
    ok, out, _err = _run_git(
        ["for-each-ref", f"refs/archive/{namespace}", "--format=%(refname)\t%(creatordate:iso-strict)"], repo_root
    )
    if not ok:
        return {"available": False, "reason": "for-each-ref failed", "refs": {}}
    refs: dict[str, str] = {}
    prefix = f"refs/archive/{namespace}/"
    for line in out.splitlines():
        if not line.strip() or "\t" not in line:
            continue
        ref, ts = line.split("\t", 1)
        if ref.startswith(prefix):
            refs[ref[len(prefix) :]] = ts.strip()
    return {"available": True, "reason": "", "refs": refs}


def _parse_stash_archived_on(archive_name: str) -> str | None:
    """A stash archive ref's name is ``<YYYY-MM-DD>-<n>-<slug>`` (verified
    against the real refs this module was built against). Returns the date
    prefix, or ``None`` if the name doesn't match -- never a guessed date."""
    parts = archive_name.split("-", 3)
    if len(parts) < 4:
        return None
    candidate = "-".join(parts[:3])
    try:
        date.fromisoformat(candidate)
    except ValueError:
        return None
    return candidate


def head_reflog_span(repo_root: Path) -> dict[str, Any]:
    """This checkout's own HEAD reflog: earliest and latest PLAUSIBLE
    recorded timestamps, read directly off disk. This is the horizon the
    plan asks to be stated plainly -- activity on this machine before
    ``earliest`` is unrecoverable from this source. Same plausibility
    filtering as ``remote_branch_first_seen`` (MINOR-2, fix round 1): an
    entry outside the repo's own root-commit..now window is treated as
    unparseable, never passed through as measured data."""
    common = _git_common_dir(repo_root)
    if common is None:
        return {"available": False, "reason": "cannot resolve git common dir", "earliest": None, "latest": None}
    head_log = common / "logs" / "HEAD"
    if not head_log.is_file():
        return {"available": False, "reason": "no HEAD reflog on disk", "earliest": None, "latest": None}
    try:
        lines = [ln for ln in head_log.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    except OSError as exc:
        return {"available": False, "reason": f"cannot read HEAD reflog: {exc}", "earliest": None, "latest": None}
    if not lines:
        return {"available": False, "reason": "HEAD reflog is empty", "earliest": None, "latest": None}
    floor = _repo_root_commit_iso(repo_root)
    now = datetime.now(timezone.utc)
    parsed = [_parse_reflog_line(ln) for ln in lines]
    timestamps = [ts for ts in parsed if ts is not None and _plausible_timestamp(ts, floor=floor, now=now)]
    if not timestamps:
        return {"available": False, "reason": "no plausible HEAD reflog lines", "earliest": None, "latest": None}
    return {
        "available": True,
        "reason": "",
        "earliest": min(timestamps, key=datetime.fromisoformat),
        "latest": max(timestamps, key=datetime.fromisoformat),
    }


def graveyard_summary(repo_root: Path) -> dict[str, Any]:
    """Group ``docs/ops/graveyard.json``'s records by kind and recorded
    ``deleted_on`` date, and flag whether every record in a kind shares a
    'seeded:' reason (the honesty distinction the module docstring's
    source 2 explains: a seed date is a RECORDING date, not necessarily a
    death date)."""
    gy = graveyard_mod.load(repo_root)
    out: dict[str, Any] = {}
    for kind in ("branch", "file"):
        records = [r for r in gy.records if r.get("kind") == kind]
        by_date: dict[str, int] = {}
        for r in records:
            d = str(r.get("deleted_on") or "unknown")
            by_date[d] = by_date.get(d, 0) + 1
        all_seeded = bool(records) and all(str(r.get("reason") or "").startswith("seeded:") for r in records)
        if not records:
            note = "no records of this kind -- an honest zero, not evidence anything is clean"
        elif all_seeded:
            note = (
                "every record's deleted_on is a RECORDING date (bulk-written the morning after "
                "the 2026-08-24 worktree closure), not a verified per-item death date"
            )
        else:
            note = "at least one record has an organic (non-seeded) reason; dates are mixed provenance"
        out[kind] = {
            "total": len(records),
            "by_deleted_on": dict(sorted(by_date.items())),
            "all_records_seeded": all_seeded,
            "note": note,
        }
    return out


def resolve_milestones(repo_root: Path) -> list[dict[str, Any]]:
    """Every ``MILESTONES`` entry, resolved live via ``git show -s
    --format=%cI <sha>``. A sha this checkout does not have resolves to
    ``date: None, resolved: False`` -- never a hardcoded fallback date."""
    resolved = []
    for entry in MILESTONES:
        ok, out, _err = _run_git(["show", "-s", "--format=%cI", entry["sha"]], repo_root)
        date_str = out.strip() if ok and out.strip() else None
        resolved.append(
            {
                "key": entry["key"],
                "sha": entry["sha"],
                "label": entry["label"],
                "date": date_str,
                "resolved": date_str is not None,
            }
        )
    return resolved


def live_anchor_today(repo_root: Path) -> dict[str, Any]:
    """Today's real numbers, via the exact same reads ``trunk_health``'s
    TRUNK line already trusts -- not a reimplementation."""
    unpushed = trunk_health.count_unpushed(repo_root)
    branches = trunk_health.count_branches(repo_root)
    stashes = trunk_health.count_stashes(repo_root)
    return {
        "date": date.today().isoformat(),
        "label": "measured live, this run",
        "source": "scripts/crew/brief/trunk_health.py (count_unpushed/count_branches/count_stashes)",
        "unpushed": unpushed.get("count") if unpushed.get("ok") else None,
        "unpushed_ok": unpushed.get("ok", False),
        "local_branches": branches.get("local"),
        "remote_branches": branches.get("remote"),
        "remote_branches_note": "mirror (on-disk refs/remotes cache)" if branches.get("remote_ok") else "unavailable",
        "stashes": stashes.get("count") if stashes.get("ok") else None,
        "stashes_ok": stashes.get("ok", False),
    }


def _week_bucket(iso_ts: str | None, since: date) -> int | None:
    """Which week index (0-based, ``WEEK_DAYS``-day buckets from
    ``since``) an ISO timestamp falls into, or ``None`` if it predates
    ``since`` or fails to parse."""
    if not iso_ts:
        return None
    try:
        d = datetime.fromisoformat(iso_ts).date()
    except ValueError:
        return None
    if d < since:
        return None
    return (d - since).days // WEEK_DAYS


def build_weekly_series(repo_root: Path, *, since: date = DEFAULT_SINCE, until: date | None = None) -> list[dict[str, Any]]:
    """The weekly series: one row per ``WEEK_DAYS``-day bucket from
    ``since`` through ``until`` (default: today). Every count field is
    always derivable (0 is an honest zero); ``live_branch_local`` and
    ``unpushed_estimate`` are ``"unknown"`` except at the anchor weeks
    (see module docstring, source 5) -- no interpolation is performed
    between them."""
    until = until or date.today()
    n_weeks = max(1, (until - since).days // WEEK_DAYS + 1)

    remote_first_seen = remote_branch_first_seen(repo_root)
    stash_events = archive_ref_events(repo_root, namespace="stash")
    worktree_events = archive_ref_events(repo_root, namespace="worktree")
    gy = graveyard_summary(repo_root)
    milestones = resolve_milestones(repo_root)
    live_today = live_anchor_today(repo_root)

    rows: list[dict[str, Any]] = []
    for idx in range(n_weeks):
        week_start = since + timedelta(days=idx * WEEK_DAYS)
        week_end = week_start + timedelta(days=WEEK_DAYS - 1)
        rows.append(
            {
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
                "live_branch_local": "unknown",
                "live_branch_local_provenance": "unknown",
                "unpushed_estimate": "unknown",
                "unpushed_provenance": "unknown",
                "remote_branch_first_seen_count": 0,
                "graveyard_branch_deaths_recorded": 0,
                "graveyard_file_deaths_recorded": 0,
                "stash_original_created_count": 0,
                "worktree_archive_original_created_count": 0,
                "milestones": [],
            }
        )

    def _bump(field: str, iso_ts: str | None) -> None:
        idx = _week_bucket(iso_ts, since)
        if idx is not None and 0 <= idx < len(rows):
            rows[idx][field] += 1

    if remote_first_seen.get("available"):
        for info in remote_first_seen["branches"].values():
            _bump("remote_branch_first_seen_count", info.get("first_seen"))

    if stash_events.get("available"):
        for archive_name, created in stash_events["refs"].items():
            _bump("stash_original_created_count", created)

    if worktree_events.get("available"):
        for created in worktree_events["refs"].values():
            _bump("worktree_archive_original_created_count", created)

    for by_date_key, field in (("branch", "graveyard_branch_deaths_recorded"), ("file", "graveyard_file_deaths_recorded")):
        for date_str, count in gy[by_date_key]["by_deleted_on"].items():
            try:
                d = date.fromisoformat(date_str)
            except ValueError:
                continue
            idx = _week_bucket(d.isoformat(), since)
            if idx is not None and 0 <= idx < len(rows):
                rows[idx][field] += count

    for m in milestones:
        idx = _week_bucket(m["date"], since)
        if idx is not None and 0 <= idx < len(rows):
            rows[idx]["milestones"].append(m["label"])

    # Anchors: fill live_branch_local / unpushed_estimate ONLY in the weeks
    # they actually land in -- never interpolated to neighboring weeks.
    for anchor in (*CITED_ANCHORS, live_today):
        provenance = "measured" if anchor is live_today else "cited"
        try:
            d = date.fromisoformat(anchor["date"])
        except (KeyError, ValueError):
            continue
        idx = _week_bucket(d.isoformat(), since)
        if idx is None or not (0 <= idx < len(rows)):
            continue
        row = rows[idx]
        if anchor.get("local_branches") is not None:
            row["live_branch_local"] = anchor["local_branches"]
            row["live_branch_local_provenance"] = provenance
        if anchor.get("unpushed") is not None:
            row["unpushed_estimate"] = anchor["unpushed"]
            row["unpushed_provenance"] = provenance

    return rows


def summarize(repo_root: Path, *, since: date = DEFAULT_SINCE) -> dict[str, Any]:
    """The complete, JSON-stable summary. Never raises -- every sub-read
    already degrades honestly; this outer call is still wrapped as a
    last-resort backstop matching this program's session-start hardening
    convention, even though this module is a CLI tool, not a session-start
    hook."""
    try:
        repo_root = Path(repo_root)
        return {
            "version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "repo_root": str(repo_root),
            "since": since.isoformat(),
            "until": date.today().isoformat(),
            "blind_spots": list(BLIND_SPOTS),
            "reflog_horizons": {
                "head": head_reflog_span(repo_root),
                "remote_first_seen": _remote_horizon(remote_branch_first_seen(repo_root)),
            },
            "milestones": resolve_milestones(repo_root),
            "graveyard_summary": graveyard_summary(repo_root),
            "anchors": [*CITED_ANCHORS, live_anchor_today(repo_root)],
            "weekly_series": build_weekly_series(repo_root, since=since),
            "regenerate_command": f"python scripts/forge/sprawl_history.py --repo-root {repo_root} --json",
        }
    except _SAFE_EXCEPTIONS as exc:  # pragma: no cover - defensive
        return {"version": 1, "ok": False, "error": str(exc)}


def _remote_horizon(remote_first_seen: dict[str, Any]) -> dict[str, Any]:
    """Reduce ``remote_branch_first_seen``'s per-branch map to one
    earliest/latest horizon, the same shape as ``head_reflog_span``."""
    if not remote_first_seen.get("available"):
        return {
            "available": False,
            "reason": remote_first_seen.get("reason", "unavailable"),
            "earliest": None,
            "latest": None,
            "branch_count": 0,
        }
    all_first = [v["first_seen"] for v in remote_first_seen["branches"].values() if v.get("first_seen")]
    if not all_first:
        return {"available": False, "reason": "no parseable reflog entries", "earliest": None, "latest": None, "branch_count": 0}
    return {
        "available": True,
        "reason": "",
        "earliest": min(all_first),
        "latest": max(all_first),
        "branch_count": len(remote_first_seen["branches"]),
    }


def render_table(summary: dict[str, Any]) -> str:
    """Human-readable table + honesty footer. Never a fabricated curve --
    ``live_branch_local``/``unpushed_estimate`` print literally
    ``unknown`` outside the anchor weeks."""
    if not summary.get("weekly_series"):
        return f"sprawl_history: no data ({summary.get('error', 'unknown error')})"

    lines = [
        f"SPRAWL HISTORY -- {summary['since']} through {summary['until']} (generated {summary['generated_at']})",
        "",
        f"{'week':12} {'live-local':11} {'unpushed':10} {'rem-1st-seen':13} {'gy-branch':10} {'gy-file':8} {'stash':6} {'wtree':6}  milestone",
    ]
    for row in summary["weekly_series"]:
        live = row["live_branch_local"]
        live_s = str(live) if live != "unknown" else "unknown"
        unpushed = row["unpushed_estimate"]
        unpushed_s = str(unpushed) if unpushed != "unknown" else "unknown"
        milestone_s = "; ".join(row["milestones"])[:60]
        lines.append(
            f"{row['week_start']:12} {live_s:11} {unpushed_s:10} "
            f"{row['remote_branch_first_seen_count']:<13} {row['graveyard_branch_deaths_recorded']:<10} "
            f"{row['graveyard_file_deaths_recorded']:<8} {row['stash_original_created_count']:<6} "
            f"{row['worktree_archive_original_created_count']:<6}  {milestone_s}"
        )

    lines.append("")
    lines.append("ANCHORS (dates git state can no longer re-derive are CITED; today is MEASURED live):")
    for a in summary["anchors"]:
        prov = "measured" if a.get("label") == "measured live, this run" else "cited"
        lines.append(
            f"  [{prov}] {a['date']}  {a['label']}  -- unpushed={a.get('unpushed')} "
            f"local={a.get('local_branches')} remote={a.get('remote_branches')} stashes={a.get('stashes')}  "
            f"(source: {a['source']})"
        )

    lines.append("")
    lines.append("MILESTONES:")
    for m in summary["milestones"]:
        marker = m["date"] if m["resolved"] else "UNRESOLVED (sha not found)"
        lines.append(f"  {marker:26} {m['label']}")

    lines.append("")
    lines.append("BLIND SPOTS:")
    for spot in summary["blind_spots"]:
        lines.append(f"  - {spot}")

    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(ROOT), help="Repository root (default: inferred).")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of the human table.")
    parser.add_argument("--since", default=DEFAULT_SINCE.isoformat(), help="Series start date, YYYY-MM-DD.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        since = date.fromisoformat(args.since)
    except ValueError:
        since = DEFAULT_SINCE
    summary = summarize(Path(args.repo_root), since=since)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(render_table(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
