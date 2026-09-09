#!/usr/bin/env python3
"""Incident surfacing: session start counts the open incidents that lack closure.

WHY THIS EXISTS (phase 1.5 Task 3): the closure gate
(``scripts/forge/gates/problem_closure_gate.py``) refuses a RESOLVING
incident with no closure line, but says nothing about incidents that are
already open and have been sitting there without ever being pointed at a
fix, a tombstone, or an accepted risk. Nothing counted that until now. This
module reads every ``plans/thomas/problems/**/PROBLEM.md`` (any depth, see
"ANY-DEPTH DISCOVERY" below), reusing the
closure gate's own fence-aware parser and RESOLUTION logic (never
reimplemented -- this repo's "reuse, never rebuild" constraint) and reports
how many are open (header status != ``resolved``) with no closure that
actually RESOLVES, so an agent sees the honest count at session start
instead of discovering it by accident.

CLOSURE MEANS RESOLVING CLOSURE (fix round 1, Important-2): a file-present
``closure:`` line is not enough -- the plan says this module reads
"problems/ + the registries". An incident's closure lines are evaluated
through ``problem_closure_gate._evaluate_incident`` (the exact function the
gate itself uses to decide PASS/FAIL at commit time), which resolves each
form against its real registry: ``gate:<filename>`` against
``RED_PATH_CASES`` (imported from ``tests.test_every_enforcing_gate_can_fail``
-- the SAME import the gate performs on every commit; measured cold-import
cost ~0.26s, paid once per session start, not per incident), ``tombstone:<id>``
against ``graveyard.load()``, and ``accepted-risk:<id>`` against
``accepted_risks.load()`` -- INCLUDING expiry (``is_expired``). A dangling
reference (names nothing) or an expired accepted risk resolves to
``classification == "failed"``, which counts as open-without-closure, same
as a genuinely missing line -- the gate's design says expiry re-opens the
incident, and this count now agrees.

DISCLOSED NARROWING: when a registry (or the RED_PATH_CASES import itself)
is unavailable -- malformed JSON, or the test module fails to import --
``_evaluate_incident`` reports ``classification == "unavailable"``. This
module treats that the same way the gate itself does: PASS-not-FAIL, never
counted as a violation (an infrastructure problem is not evidence the
closure is bad), but tracked separately as ``unverifiable`` so the summary
still surfaces the degradation instead of silently trusting an unverifiable
closure. This means a ``gate:``/``tombstone:``/``accepted-risk:`` closure
line on an incident is reported as "has closure" only when it was actually
possible to check it this run -- an honest, disclosed narrowing, not a
silent one.

PER-FILE FAILURES NEVER SILENCE THE WHOLE SCAN (fix round 1, Important-1):
a prior version caught only ``OSError`` around the per-file read, so an
invalid-UTF-8 ``PROBLEM.md`` raised ``UnicodeDecodeError`` (a ``ValueError``,
not an ``OSError``), escaped the per-file guard, and ``summarize()``'s
blanket catch degraded the ENTIRE scan to "unavailable" -- silencing the
honest count of every OTHER open incident over one bad file. Every stage of
per-file work (read, parse, closure resolution, date-sort-key extraction) now
runs inside a SINGLE per-file try/except covering ``OSError``,
``UnicodeDecodeError``, ``ValueError``, ``TypeError``, ``AttributeError``,
and ``RuntimeError`` -- deliberately one wide net around the whole per-file
body rather than several narrower ones, so a failure at ANY step (not just
the read) demotes only that one file to ``unreadable``, never the whole
scan. ``summarize()``'s own outer catch is now a last-resort backstop for
genuine top-level infrastructure failure (a broken glob, a missing
directory permission at the ``problems/`` level itself), not a place where
one malformed file's failure mode can hide.

REUSE, NOT REBUILD: the fence-aware ``closure:`` parser
(``_header_status``/``_closure_lines``), the value/task-id line grammar
(``_strip_value``/``_task_id_from_marker``), and the full per-incident
resolution (``_evaluate_incident``) all import from
``problem_closure_gate`` -- none are reimplemented here. A future change to
the fence rule, the closure grammar, or a registry's resolution semantics
never has two copies to keep in sync.

FAST AND NEVER FATAL: ``startup_router.py`` calls ``summarize()`` at every
agent session start. No git subprocess anywhere in this module or in the
reused gate functions -- pure file reads (``Path.glob``, ``read_text``,
``json.loads`` inside the registries) plus one one-time Python import for
``gate:`` resolution. ``summarize()`` never raises: any internal failure is
caught and reported as an ``{"ok": False, ...}`` payload; ``render_text()``
turns that into a single ``INCIDENTS: unavailable (<reason>)`` line. Session
start must never fail on this line, matching this program's
UNAVAILABLE-not-a-refusal precedent (``claim_evidence``, ``graveyard``,
``accepted_risks``).

EXPIRY RE-OPENS A RESOLVED INCIDENT (final-review fix wave, Critical-1): the
gate (``problem_closure_gate.py``) runs on diffs -- it CANNOT catch time
passing after a resolution has already landed, and its
already-resolved-unchanged scoping (``problem_closure_gate.py:500-501``) is
correct and stays untouched. Nothing else was re-checking a standing
``resolved`` incident's closure -- so an accepted risk that expired AFTER
the incident closed was invisible everywhere, forever, even though the
registry itself correctly reported it expired. This module is the only
process that runs every session start (the phase-1.4 expiry-sweep
precedent), so it is the re-open channel: a ``resolved`` incident's closure
line is now evaluated through the SAME ``_evaluate_incident`` call used for
open incidents, not skipped. A resolved incident whose closure still
resolves stays invisible (no noise -- the common case). A resolved incident
whose single closure line no longer resolves for a REAL reason -- expired,
dangling (names nothing), or an unrecognized form -- lands in a new
``reopen_due`` bucket, rendered as its own ``REOPEN DUE:`` line (honest zero
printed as zero) after ``INCIDENTS:``, and is never added to the open count
(a separate truth, a separate line -- re-opening is a fact about the past
resolution, not a new open incident this scan discovered). Deliberately
excluded from ``reopen_due``: a resolved incident with ZERO closure lines
(``classification == "missing_closure"``) -- that is the disclosed,
passive legacy-drain population (incidents resolved before the closure
gate existed), and flooding it into a "re-open" banner would misrepresent
"never checked" as "checked and now failing". A resolved incident whose
verification itself could not run (a malformed registry, or the
``RED_PATH_CASES`` import failing -- ``classification == "unavailable"``)
lands in the SAME ``unverifiable`` bucket already used for open incidents,
not a separate one -- one honest "couldn't check this" signal regardless of
which population it came from. No new registry-loading code was added here:
the resolved population reuses the exact same ``_evaluate_incident`` call
the open population already made, so this stays "file reads only", pays no
extra per-incident cost, and never becomes a second implementation of
registry resolution.

RECURRING VOCABULARY (phase 2 repair, recon #10): a ``PROBLEM.md`` header
carrying a ``- recurring: <one-line cadence statement>`` line (mirroring the
existing header field grammar -- ``- Status:``, ``- Updated At:``, etc., an
optional leading dash, case-insensitive key) names STANDING work: a task
that is designed to re-fire by nature (e.g. ``ELECTRON-BUMP-RECURRING``:
"on every new Electron stable major"), not one sitting neglected. Such a
record is EXCLUDED from the open-without-closure count -- the count means
"has been sitting there without ever being pointed at a fix", which does
not describe standing work -- but NEVER excluded from existence: it always
lands in its own ``recurring`` bucket, rendered as a new ``RECURRING: N
standing`` line, regardless of its status or closure state. THE CLOSURE
GATE NEEDS NO CHANGE FOR THIS: a recurring record's status field is
untouched by this branch, so adding or editing the ``- recurring:`` line
never creates a ``status=resolved`` transition for ``problem_closure_gate``
to even look at -- the gate's existing scope rule (only board/header status
reaching ``resolved`` puts an incident in scope) already ignores it, proven
by a test that runs the real gate over a real git repo. A recurring record
is detected BEFORE closure resolution runs at all, so it also never pays
the ``gate:``/``tombstone:``/``accepted-risk:`` registry lookup cost the
open/reopen_due paths do.

ANY-DEPTH DISCOVERY (phase 2 repair, fix round 1, reviewer-found): a task_id
containing a literal ``/`` (created by whatever wrote its directory, not
sanitized to a single path component) produces a ``PROBLEM.md`` nested TWO
OR MORE levels under ``plans/thomas/problems/`` instead of one -- e.g.
``plans/thomas/problems/folder claim for thomas/forge, thomas/cli (+9
more)/PROBLEM.md`` is three real directories deep. The prior glob,
``plans/thomas/problems/*/PROBLEM.md``, is depth-1-only and silently never
visits such a file -- not "counts it as closed", not "marks it unreadable",
just never enumerates it at all, so it never reaches ANY classification
branch below. A record the instrument cannot see is the exact disease this
whole module exists to catch (the ledger lying by omission), so
``PROBLEMS_GLOB`` now reads ``plans/thomas/problems/**/PROBLEM.md`` --
``pathlib``'s recursive wildcard, matching zero or more intermediate
directories, still rooted at (and unable to walk outside) the fixed
``plans/thomas/problems/`` prefix. No other per-file logic changes: a
record reached this way is read, classified, and reported through the exact
same path as a depth-1 record, and its ``problem_path`` in every returned
row is its REAL (possibly multi-level) relative path -- the anomaly is
surfaced, never silently normalized to a bare directory name.

CLI: ``python scripts/crew/brief/incident_surfacing.py [--repo-root PATH]
[--json]``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.forge.gates.problem_closure_gate import (
        _closure_lines,
        _evaluate_incident,
        _fenced_line_mask,
        _header_status,
        _strip_value,
        _task_id_from_marker,
    )
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    from forge.gates.problem_closure_gate import (  # type: ignore
        _closure_lines,
        _evaluate_incident,
        _fenced_line_mask,
        _header_status,
        _strip_value,
        _task_id_from_marker,
    )

ROOT = _REPO_ROOT
PROBLEMS_GLOB = "plans/thomas/problems/**/PROBLEM.md"

_UPDATED_AT_RE = re.compile(r"^-?\s*updated\s+at\s*:\s*(.+)$", re.IGNORECASE)
_LEADING_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_RECURRING_RE = re.compile(r"^-?\s*recurring\s*:\s*(.+)$", re.IGNORECASE)

# Every exception a per-file evaluation step could plausibly raise: OSError/
# UnicodeDecodeError from the read (UnicodeDecodeError IS a ValueError
# subclass, but named explicitly so the intent reads clearly), ValueError
# from a malformed date inside a resolved registry record (e.g.
# accepted_risks.Risks.is_expired's dt.date.fromisoformat -- load() only
# checks required KEYS are present, not that expires_on is a real date), and
# TypeError/AttributeError/RuntimeError as a defensive backstop for the
# regex-based parsers. Deliberately ONE tuple shared by every per-file catch
# so the same failure modes are always caught the same way, everywhere.
_PER_FILE_EXCEPTIONS = (OSError, UnicodeDecodeError, ValueError, TypeError, AttributeError, RuntimeError)


def _relpath(path: Path, repo_root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(repo_root).resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _reopen_reason(evaluation: dict[str, Any]) -> str:
    """A compact, one-clause reason a RESOLVED incident's closure no longer
    holds, e.g. ``accepted-risk:2026-08-25-x-1 expired 2026-09-30`` or
    ``tombstone:bogus-id dangling (no matching record)``. Built from the
    evaluation dict's own fields rather than re-deriving anything -- the
    full ``detail`` sentence in that dict is written for the gate's FAIL
    output, not a three-line session-start note, so this extracts the
    essentials instead of printing it verbatim."""
    classification = str(evaluation.get("classification") or "")
    if classification == "ambiguous_closure":
        closures = evaluation.get("closures") or []
        return f"ambiguous: {len(closures)} closure lines"

    closure = str(evaluation.get("closure") or "")
    detail = str(evaluation.get("detail") or "")
    if "EXPIRED" in detail:
        match = re.search(r"expired (\d{4}-\d{2}-\d{2})", detail)
        return f"{closure} expired {match.group(1)}" if match else f"{closure} expired"
    if "does not resolve" in detail:
        return f"{closure} dangling (no matching record)"
    if "not a recognized form" in detail:
        return f"{closure} not a recognized closure form"
    return closure or "closure no longer resolves"


def _recurring_cadence(text: str) -> str:
    """The first UNFENCED ``- recurring:`` line's value (mirroring
    ``_UPDATED_AT_RE``'s convention -- optional leading dash, case-
    insensitive key), or ``""`` when absent, the normal case for a non-
    recurring incident.

    FENCE-AWARE (final-review fix wave, Important-1): reuses the gate's own
    ``_fenced_line_mask`` -- the SAME mask ``_closure_lines`` applies to
    closure lines, imported rather than reimplemented (this module's "reuse,
    not rebuild" rule). Before this fix, a ``- recurring:`` line documented
    as a FENCED EXAMPLE inside a template or a "how this vocabulary works"
    explanation (the same authoring pattern the closure-form examples
    already use, per the module docstring's "recurring vocabulary" section)
    silently moved a genuinely open incident out of the open-without-closure
    count and into ``RECURRING`` -- the CONCEALMENT direction, the one this
    whole program treats as the dangerous one (an incident is easy to
    re-surface if wrongly counted open; one silently hidden the wrong way
    can sit invisible indefinitely). Reproduced by an external review with a
    fenced ``- recurring:`` example on an otherwise-ordinary open record:
    `open: 0 recurring: 1` for a record that was not actually recurring.

    NOT bounded to a "header region" (deliberately, for consistency, not by
    omission): ``_header_status`` -- the sibling field-reader this function
    was already modeled on -- has no such bound either; it takes the first
    ``- status:``-shaped line anywhere in the file (see its own docstring's
    Minor-2 for the identical, already-accepted tradeoff). Adding a
    header-region bound to ONLY this one field would give the module two
    different conventions for reading a header field from the same file
    for no behavioral gain: the real, reviewer-demonstrated risk is a FENCED
    documentation example, which the fence mask fully closes; an unfenced
    stray ``- recurring:`` line in body prose is the same pre-existing,
    already-accepted authoring foot-gun ``_header_status`` and
    ``_date_sort_key`` already carry, not a new asymmetry introduced here.
    A test pins this choice: an unfenced ``- recurring:`` line below the
    header, in body prose, IS still recognized -- intentional, not
    accidental scope creep of the fence fix.
    """
    lines = text.splitlines()
    fenced = _fenced_line_mask(lines)
    for idx, raw_line in enumerate(lines):
        if fenced[idx]:
            continue
        match = _RECURRING_RE.match(raw_line.strip())
        if match:
            return _strip_value(match.group(1))
    return ""


def _date_sort_key(text: str) -> str:
    """The `- Updated At:` field's leading ``YYYY-MM-DD``, or ``""`` when
    absent OR present-but-unparseable -- an empty key sorts first
    (oldest/most-suspicious first), never raises on a missing or malformed
    date. A garbage date string is treated the same as a missing one rather
    than sorted by its raw text (which would push it out of the oldest-three
    window, the opposite of "most deserving attention")."""
    for raw_line in text.splitlines():
        match = _UPDATED_AT_RE.match(raw_line.strip())
        if not match:
            continue
        value = _strip_value(match.group(1))
        date_match = _LEADING_DATE_RE.match(value)
        return date_match.group(1) if date_match else ""
    return ""


def open_incidents_without_closure(repo_root: Path) -> dict[str, list[dict[str, str]]]:
    """Every ``plans/thomas/problems/**/PROBLEM.md`` (any depth -- see the
    module docstring's "any-depth discovery"), evaluated for two
    separate truths (reusing the closure gate's own parser and resolution
    logic throughout -- see the module docstring's "reuse, not rebuild",
    "closure means resolving closure", and "expiry re-opens a resolved
    incident"):

    Returns ``{"open": [...], "reopen_due": [...], "unreadable": [...],
    "unverifiable": [...], "recurring": [...]}``:
      * ``"open"`` -- non-``resolved`` incidents with no closure line that
        actually RESOLVES. Sorted oldest-first by the record's
        ``- Updated At:`` date (a missing/unparseable date sorts first, as
        the case most deserving attention). Includes zero closure lines,
        more than one (ambiguous), or exactly one that does not resolve.
      * ``"reopen_due"`` -- ``resolved`` incidents whose single closure line
        no longer resolves for a real reason (expired, dangling, or an
        unrecognized form). NEVER included in ``"open"`` -- re-opening is a
        separate truth about a past resolution, not a newly-discovered open
        incident. A resolved incident with zero closure lines (the
        disclosed legacy-drain population) is deliberately excluded here,
        not silently added.
      * ``"unreadable"`` -- every ``PROBLEM.md`` that could not be read or
        whose content could not be evaluated at all, each named with a
        reason. Never silently dropped and never folded into ``"open"``.
      * ``"unverifiable"`` -- an incident (open OR resolved) whose closure
        line COULD resolve in principle but couldn't be checked this run
        because a registry (or the RED_PATH_CASES import) was unavailable.
        Not counted as a violation and not counted as re-opened -- an infra
        problem is not evidence the closure is bad -- but never silently
        trusted either.
      * ``"recurring"`` -- incidents carrying a ``- recurring:`` header line
        (see the module docstring's "recurring vocabulary"). Standing work,
        never counted in ``"open"`` or ``"reopen_due"`` regardless of status
        or closure state, but always present here -- excluded from the
        open-without-closure count, never from existence.

    Never raises -- a per-file failure at any step (read, parse, closure
    resolution) is caught and recorded in ``"unreadable"``, and scanning
    continues with the next file.
    """
    repo_root = Path(repo_root)
    open_incidents: list[dict[str, str]] = []
    reopen_due: list[dict[str, str]] = []
    unreadable: list[dict[str, str]] = []
    unverifiable: list[dict[str, str]] = []
    recurring: list[dict[str, str]] = []

    for problem_path in sorted(repo_root.glob(PROBLEMS_GLOB)):
        rel_path = _relpath(problem_path, repo_root)
        try:
            text = problem_path.read_text(encoding="utf-8")
        except _PER_FILE_EXCEPTIONS as exc:
            unreadable.append({"problem_path": rel_path, "reason": f"cannot read: {exc}"})
            continue

        try:
            status = _header_status(text)
            task_id = _task_id_from_marker(text, problem_path.parent.name)
            cadence = _recurring_cadence(text)
            if cadence:
                # Standing/recurring work (recon #10): checked BEFORE closure
                # resolution runs at all, so a recurring record never pays
                # the gate:/tombstone:/accepted-risk: registry lookup cost
                # and is never routed into "open" or "reopen_due" -- it
                # always lands here instead, regardless of status or closure
                # state (see the module docstring's "recurring vocabulary").
                recurring.append(
                    {
                        "task_id": task_id,
                        "problem_path": rel_path,
                        "status": status or "(no status)",
                        "cadence": cadence,
                    }
                )
                continue

            # Every incident's closure lines are evaluated regardless of
            # status -- RESOLVED is no longer a reason to skip evaluation.
            # It only changes what a non-"resolved" classification MEANS
            # (see the branch below): open-without-closure for a live
            # incident, re-open-due for one already marked resolved.
            closures = _closure_lines(text)
            evaluation = _evaluate_incident(task_id, rel_path, closures, repo_root)
            classification = str(evaluation.get("classification") or "")
            is_resolved = status == "resolved"

            if classification == "resolved":
                continue  # closure holds -- invisible either way, no noise

            if classification == "unavailable":
                unverifiable.append(
                    {
                        "task_id": task_id,
                        "problem_path": rel_path,
                        "reason": str(evaluation.get("reason") or "closure registry unavailable"),
                    }
                )
                continue

            if is_resolved:
                if classification == "missing_closure":
                    continue  # disclosed legacy-drain population, not a re-open
                reopen_due.append(
                    {
                        "task_id": task_id,
                        "problem_path": rel_path,
                        "reason": _reopen_reason(evaluation),
                    }
                )
                continue

            # Non-resolved with missing_closure / ambiguous_closure / failed
            # -- genuinely open without a closure that resolves.
            date_key = _date_sort_key(text)
        except _PER_FILE_EXCEPTIONS as exc:
            # ONE wide net around the whole per-file body (not just the
            # read): a failure at ANY step here -- parsing, closure
            # resolution, date extraction -- demotes only this file to
            # unreadable. It must never propagate to summarize()'s outer
            # catch and degrade the entire scan over one bad file.
            unreadable.append({"problem_path": rel_path, "reason": f"cannot evaluate: {exc}"})
            continue

        open_incidents.append(
            {
                "task_id": task_id,
                "problem_path": rel_path,
                "status": status or "(no status)",
                "date_key": date_key,
            }
        )

    open_incidents.sort(key=lambda row: (row["date_key"], row["problem_path"]))
    return {
        "open": open_incidents,
        "reopen_due": reopen_due,
        "unreadable": unreadable,
        "unverifiable": unverifiable,
        "recurring": recurring,
    }


def summarize(repo_root: Path) -> dict[str, Any]:
    """The session-start-safe summary: never raises, always returns a dict
    with an ``"ok"`` flag. This is now a last-resort backstop for genuine
    top-level infrastructure failure (a broken glob, an unreadable
    ``problems/`` directory itself) -- every per-file failure mode is
    already absorbed inside ``open_incidents_without_closure`` and never
    reaches here. On internal failure, ``"ok"`` is False and the caller
    (``startup_router.py``) must render that as an unavailable line, never
    let it propagate and fail session start."""
    try:
        result = open_incidents_without_closure(Path(repo_root))
    except _PER_FILE_EXCEPTIONS as exc:
        return {
            "ok": False,
            "error": str(exc),
            "count": 0,
            "oldest": [],
            "unreadable_count": 0,
            "unverifiable_count": 0,
            "reopen_due_count": 0,
            "reopen_due": [],
            "recurring_count": 0,
            "recurring": [],
        }

    open_incidents = result["open"]
    reopen_due = result["reopen_due"]
    recurring = result["recurring"]
    return {
        "ok": True,
        "count": len(open_incidents),
        "oldest": open_incidents[:3],
        "unreadable_count": len(result["unreadable"]),
        "unreadable": result["unreadable"],
        "unverifiable_count": len(result["unverifiable"]),
        "unverifiable": result["unverifiable"],
        "reopen_due_count": len(reopen_due),
        "reopen_due": reopen_due[:3],
        "recurring_count": len(recurring),
        "recurring": recurring[:3],
    }


def render_text(summary: dict[str, Any]) -> str:
    """Three honest lines (each with up to three detail lines): ``INCIDENTS:
    N open without closure``, ``REOPEN DUE: N resolved incidents whose
    closure no longer holds``, then ``RECURRING: N standing`` -- all printed
    even when N is 0. Degrades to a single ``INCIDENTS: unavailable
    (<reason>)`` line when ``summarize()`` reported ``ok=False`` -- never a
    crash, never a fabricated count."""
    if not summary.get("ok", False):
        reason = str(summary.get("error") or "unknown error")
        return f"INCIDENTS: unavailable ({reason})"

    count = int(summary.get("count") or 0)
    unreadable_count = int(summary.get("unreadable_count") or 0)
    unverifiable_count = int(summary.get("unverifiable_count") or 0)
    header = f"INCIDENTS: {count} open without closure"
    notes = []
    if unreadable_count:
        notes.append(f"unreadable={unreadable_count}")
    if unverifiable_count:
        notes.append(f"unverifiable={unverifiable_count}")
    if notes:
        header += " (" + ", ".join(notes) + ")"

    lines = [header]
    for row in summary.get("oldest") or []:
        lines.append(f"  - {row.get('task_id')} ({row.get('status')}): {row.get('problem_path')}")

    reopen_due_count = int(summary.get("reopen_due_count") or 0)
    lines.append(f"REOPEN DUE: {reopen_due_count} resolved incidents whose closure no longer holds")
    for row in summary.get("reopen_due") or []:
        lines.append(f"  - {row.get('task_id')}: {row.get('reason')}")

    recurring_count = int(summary.get("recurring_count") or 0)
    lines.append(f"RECURRING: {recurring_count} standing")
    for row in summary.get("recurring") or []:
        lines.append(f"  - {row.get('task_id')}: {row.get('cadence')}")

    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(ROOT), help="Repository root (default: inferred).")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = summarize(Path(args.repo_root))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(render_text(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
