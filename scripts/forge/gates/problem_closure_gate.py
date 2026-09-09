#!/usr/bin/env python3
"""The closure gate: an incident may end in a practice or an owned risk, never a shrug.

WHY THIS GATE EXISTS (phase 1.5, spec the internal design record
praxis-first-design.md §1.5): nothing in this repo stopped a Task Problems
entry or a PROBLEM.md header from flipping to ``status=resolved`` with
nothing behind it -- no landed fix, no tombstone, no owner sign-off. That
"resolved" then reads as done forever, because closure is never re-checked.
This gate refuses that transition unless the record names something that
actually RESOLVES: a gate registered in RED_PATH_CASES (a fix that a red-path
selftest proves still catches its violation), a graveyard tombstone (a
deliberate removal, already recorded per ``scripts/forge/graveyard.py``), or
an unexpired accepted risk (an owner's dated, expiring sign-off, per
``scripts/forge/accepted_risks.py``). A closure string that names nothing is
a FAIL naming the defect -- this program's every phase found the same
disease: strings that point at nothing.

SCOPE (the phase-1.4 lesson applied at design time -- see
``workboard_evidence_gate.py``'s "THE BLIND WINDOW"): an incident is IN SCOPE
whenever it reaches ``status=resolved`` in the NEW state (either the
WORKBOARD.md ``## Task Problems`` entry's ``status=`` field, or the
PROBLEM.md header's ``- status:``/``- Status:`` field) AND either
  (a) it was NOT already resolved in the OLD state, or
  (b) it WAS already resolved, but its ``closure:`` line(s) changed.
Only a truly standing resolved -- resolved on both sides, with the identical
closure line(s) -- is out of scope (checking that again would duplicate
whatever originally validated it, not this gate's job). This mirrors
``workboard_evidence_gate.py``'s ``_done_transitions`` scoping exactly:
status-only scoping would miss a closure SWAPPED in place on a standing
resolved, the same blind spot a status-only "done" check had for evidence.

TWO MODES, ONE CHECK (mirrors workboard_evidence_gate.py):
  * staged (default, the local pre-commit form): HEAD vs the staged index.
  * diff-range (``--base``/``--head``, the CI form): base ref vs head ref.

THE THREE CLOSURE FORMS AND HOW EACH RESOLVES:
  * ``gate:<filename>``       -> ``<filename>`` must be a key of
                                  ``RED_PATH_CASES`` in
                                  ``tests/test_every_enforcing_gate_can_fail.py``.
  * ``tombstone:<id>``        -> ``<id>`` must match some record's ``id`` in
                                  ``scripts/forge/graveyard.py``'s ``load()``.
  * ``accepted-risk:<id>``    -> ``<id>`` must resolve via
                                  ``scripts/forge/accepted_risks.py``'s
                                  ``load().get()`` AND be unexpired
                                  (``is_expired`` False). An id that resolves
                                  but has EXPIRED is a FAIL naming the owner
                                  and the expiry date, with the re-open
                                  instruction: the incident is open again
                                  until the owner lands a fix or records a
                                  fresh acceptance.
Zero closure lines on a resolving incident is a FAIL (closure is the whole
point). More than one is also a FAIL naming the ambiguity -- an incident has
exactly one terminus, never two competing explanations for how it ended.

REGISTRY IMPORT MECHANISM (measured, not assumed -- see Task 2 report for
the evidence): ``tests/`` has an ``__init__.py`` (a real package) and every
gate under ``scripts/forge/gates/`` already inserts the repo root onto
``sys.path`` at import time (see below). ``import tests.test_every_
enforcing_gate_can_fail`` therefore resolves cleanly from this gate's own
process regardless of what ``--repo-root`` fixture is under test -- the
import reads THIS checkout's real RED_PATH_CASES, exactly as intended (a
gate fixture that could fabricate its own RED_PATH_CASES would defeat the
whole point of requiring gate-form closures to be REAL red-path-covered
gates). A plain ``importlib.util.spec_from_file_location`` path-load was
measured and rejected: it is strictly more code for an identical result once
the package import is confirmed to work, and it would re-import the module
under a different name than pytest uses, risking two live copies of
``RED_PATH_CASES`` (and its module-level ``pytest`` import, which must
already be installed for the test suite to run at all -- see the gates.yml
job this ships with, which installs ``pytest`` alongside the gate run for
exactly that reason).

UNREADABLE REGISTRY (never silent, never a refusal on absent infrastructure,
matching claim_evidence's UNAVAILABLE semantics precedent): ``graveyard.load``
and ``accepted_risks.load`` both raise ``SystemExit`` on a malformed (not
missing -- missing is legitimately empty) registry file. This gate catches
that at the boundary and reports the affected incident as ``unavailable``
(PASS with a printed note), never a FAIL -- the registry being broken is an
infrastructure problem, not evidence that the closure itself is bad. The
same treatment covers a ``RED_PATH_CASES`` import that fails outright (as
opposed to succeeding and simply not containing the named gate, which IS a
real FAIL). A MISSING ``closure:`` line on a resolving incident is never
covered by this leniency -- that is always a FAIL, because the missing-
closure case is the exact thing this gate exists to catch.

THE BOUNDARY IS FILE-LEVEL VS RECORD-LEVEL (fix round 2, reviewer-found): a
WHOLE registry file that fails to parse is file-level infrastructure absence
-- ``unavailable``, as above. A single RECORD that loads fine but carries a
garbage value -- an ``accepted-risk:<id>`` whose ``expires_on`` is not a real
date, reachable only by hand-editing ``docs/ops/accepted_risks.json`` (record-
time validation in ``accepted_risks.record_risk`` rejects it before it can
ever be written normally) -- is a POSITIVE DEFECT IN THAT RECORD, never a
note-pass: treating a garbage date as unavailable would make a hand-edited
garbage ``expires_on`` an immortal-risk evasion channel (a risk that can
never expire because it can never be checked). ``_resolve_closure`` guards
``risks.is_expired`` and reports a garbage-date record as ``failed``, naming
the record id and the parse defect -- never raising past ``run_check``'s
"never raises" contract (the bug this round fixes: the unguarded call raised
``ValueError`` straight through to the caller).

HONESTY CONTRACT: like every gate in this family, always prints how many
Task Problems entries and changed PROBLEM.md files it consulted and how many
resolving incidents it found, even when both are zero.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.forge import accepted_risks, graveyard  # noqa: E402
from scripts.forge.gates import workboard_task_problems as task_problems_gate  # noqa: E402

ROOT = _REPO_ROOT
WORKBOARD_REL_PATH = "plans/thomas/WORKBOARD.md"
PROBLEMS_PREFIX = task_problems_gate.PROBLEMS_PREFIX
TASK_PROBLEMS_HEADING = task_problems_gate.TASK_PROBLEMS_HEADING
_norm = task_problems_gate._norm  # noqa: SLF001 - deliberate reuse, see module docstring

_STATUS_LINE_RE = re.compile(r"^-?\s*status\s*:\s*(.+)$", re.IGNORECASE)
# Closure requires the leading "- " (a bullet directive); status does not
# (a bare header field). Deliberate, not an oversight: closure is meant to be
# written as one canonical bullet form (`- closure: <form>`) so a stray prose
# sentence mentioning "closure:" is never mistaken for a real one -- see
# _evaluate_incident's missing_closure detail, which names that exact form.
_CLOSURE_LINE_RE = re.compile(r"^-\s*closure\s*:\s*(.+)$", re.IGNORECASE)
_TASK_ID_MARKER_RE = re.compile(r"^-?\s*task_id\s*:\s*(.+)$", re.IGNORECASE)
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")

_FAIL_CLASSIFICATIONS = ("missing_closure", "ambiguous_closure", "failed")


def _runtime_protection_disabled() -> bool:
    """B9 (praxis-unbypassable-2026-05-29): only a validly SIGNED disable flag
    counts. Mirrors workboard_evidence_gate.py's identical guard."""
    try:
        from scripts.forge.gates._runtime_guard import runtime_protection_disabled
    except ImportError:  # pragma: no cover - import path varies by run context
        try:
            from forge.gates._runtime_guard import runtime_protection_disabled
        except ImportError:
            from _runtime_guard import runtime_protection_disabled
    return runtime_protection_disabled(ROOT)


def _strip_value(raw: str) -> str:
    value = str(raw or "").strip()
    if len(value) >= 2 and value[0] == "`" and value[-1] == "`":
        value = value[1:-1].strip()
    return value


def _normalize_path(value: str) -> str:
    return str(value or "").strip().replace("\\", "/")


def _git_show(repo_root: Path, ref: str) -> str | None:
    """`git show <ref>`'s stdout, or None if the ref/path does not resolve.
    None is always treated as "did not exist there" by callers, never an
    error -- identical contract to workboard_evidence_gate.py's helper."""
    try:
        proc = subprocess.run(
            ["git", "show", ref],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _git_diff_name_only(repo_root: Path, args: list[str]) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _header_status(text: str) -> str:
    """The first `- status:`/`- Status:` line's value. Takes the FIRST match,
    not the last -- a header-only PROBLEM.md (no workboard entry) with a
    contradictory decoy status line placed above the real one can mask
    resolution for that off-board scope path (Minor-2, fix round 1 review).
    Low severity and not fixed here: it requires a deliberately self-
    contradictory file, the WORKBOARD-tracked path is unaffected, and
    workboard_task_problems.py already forces a board entry for every
    tracked task -- evasion-by-intent only, the same class as any text-
    format gate. Revisit with a last-match or `## `-boundary rule if this
    parser is touched again for something unrelated."""
    for raw_line in text.splitlines():
        match = _STATUS_LINE_RE.match(raw_line.strip())
        if match:
            return _norm(_strip_value(match.group(1)))
    return ""


def _fenced_line_mask(lines: list[str]) -> list[bool]:
    """True for every line index inside a fenced code block (```` ``` ```` or
    ``~~~``, tracked while scanning -- fix round 1, Important-1). The fence
    delimiter line itself counts as "inside" (it is markup, never content).
    An UNCLOSED fence swallows every remaining line to EOF: once a fence
    opens there is no way to know where it "should" have closed, and reading
    everything after it as still-fenced is the honest interpretation of
    broken markdown -- never re-synchronizing on a guess.

    Required because Task 3's `## Closure` template stub documents the three
    closure forms with a fenced example (`- closure: gate:example.py`
    inside a ``` block) -- without fence-awareness that documentation line
    reads as a second real closure and a legitimately-closed incident FAILs
    as ambiguous the moment the template ships."""
    mask = [False] * len(lines)
    fence_char: str | None = None
    for idx, line in enumerate(lines):
        match = _FENCE_RE.match(line.strip())
        if fence_char is None:
            if match:
                fence_char = match.group(1)[0]
                mask[idx] = True
            continue
        mask[idx] = True
        if match and match.group(1)[0] == fence_char:
            fence_char = None
    return mask


def _closure_lines(text: str) -> list[str]:
    lines = text.splitlines()
    fenced = _fenced_line_mask(lines)
    return [
        _strip_value(m.group(1))
        for idx, line in enumerate(lines)
        if not fenced[idx] and (m := _CLOSURE_LINE_RE.match(line.strip()))
    ]


def _task_id_from_marker(text: str, fallback: str) -> str:
    for raw_line in text.splitlines():
        match = _TASK_ID_MARKER_RE.match(raw_line.strip())
        if match:
            value = _strip_value(match.group(1))
            if value:
                return value
    return fallback


def _board_map(text: str) -> dict[str, dict[str, str]]:
    """task_id (lowercased) -> its full field dict from ## Task Problems.

    Uses the PINNED validator's own private line-grammar
    (``workboard_task_problems._find_section``/``_bullet_indices``/
    ``_parse_kv_entry``) rather than reimplementing it -- this repo's "reuse,
    never rebuild" constraint, and the identical pattern
    workboard_evidence_gate.py already uses for claim_evidence's parser."""
    lines = text.splitlines()
    section = task_problems_gate._find_section(lines, heading_prefix=TASK_PROBLEMS_HEADING)  # noqa: SLF001
    if section is None:
        return {}
    start, end = section
    out: dict[str, dict[str, str]] = {}
    for idx in task_problems_gate._bullet_indices(lines, start, end):  # noqa: SLF001
        _entry, fields, err = task_problems_gate._parse_kv_entry(idx + 1, lines[idx])  # noqa: SLF001
        if err or not fields:
            continue
        task_id = str(fields.get("task_id", "")).strip()
        if task_id:
            out[_norm(task_id)] = fields
    return out


def _changed_problem_paths(repo_root: Path, *, mode: str, base: str, head_ref: str) -> list[str]:
    args = ["--cached"] if mode == "staged" else [base, head_ref]
    out: list[str] = []
    for raw_path in _git_diff_name_only(repo_root, args):
        path = _normalize_path(raw_path)
        if _norm(path).startswith(_norm(PROBLEMS_PREFIX)) and _norm(path).endswith("/problem.md"):
            out.append(path)
    return out


def _show_side(repo_root: Path, *, mode: str, base: str, head_ref: str, side: str, path: str) -> str | None:
    if mode == "diff-range":
        ref = base if side == "old" else head_ref
        return _git_show(repo_root, f"{ref}:{path}")
    ref_prefix = "HEAD:" if side == "old" else ":"
    return _git_show(repo_root, f"{ref_prefix}{path}")


def _gather_candidates(new_board: dict[str, dict[str, str]], changed_paths: list[str]) -> dict[str, dict[str, str]]:
    """key -> {"problem_path", "task_id"} for every incident that might be
    resolving: every board entry with a `problem=` path, plus every changed
    PROBLEM.md file not already covered by a board entry (a header-only
    resolution, per the module docstring's scope rule)."""
    candidates: dict[str, dict[str, str]] = {}
    seen_paths: set[str] = set()
    for key, fields in new_board.items():
        path = _normalize_path(fields.get("problem", ""))
        if not path:
            continue
        candidates[key] = {"problem_path": path, "task_id": str(fields.get("task_id", "")).strip() or key}
        seen_paths.add(_norm(path))
    for path in changed_paths:
        if _norm(path) in seen_paths:
            continue
        fallback_id = Path(path).parent.name or path
        candidates[f"path:{_norm(path)}"] = {"problem_path": path, "task_id": fallback_id}
    return candidates


def _resolve_closure(task_id: str, problem_path: str, closure: str, repo_root: Path) -> dict[str, Any]:
    base: dict[str, Any] = {"task_id": task_id, "problem_path": problem_path, "closure": closure}

    if closure.startswith("gate:"):
        filename = closure[len("gate:") :].strip()
        try:
            from tests.test_every_enforcing_gate_can_fail import RED_PATH_CASES
        except ImportError as exc:  # infrastructure absence (e.g. pytest missing), never a refusal
            return {**base, "classification": "unavailable", "reason": f"RED_PATH_CASES could not be imported: {exc}"}
        if filename in RED_PATH_CASES:
            return {**base, "classification": "resolved", "reason": f"`{filename}` is RED_PATH-covered"}
        return {
            **base,
            "classification": "failed",
            "detail": (
                f"incident `{task_id}` closure `gate:{filename}` does not resolve -- `{filename}` is not "
                f"registered in RED_PATH_CASES ({problem_path})"
            ),
        }

    if closure.startswith("tombstone:"):
        tomb_id = closure[len("tombstone:") :].strip()
        try:
            gy = graveyard.load(repo_root)
        except SystemExit as exc:
            return {**base, "classification": "unavailable", "reason": f"graveyard registry unreadable: {exc}"}
        if any(record.get("id") == tomb_id for record in gy.records):
            return {**base, "classification": "resolved", "reason": f"tombstone `{tomb_id}` found in graveyard"}
        return {
            **base,
            "classification": "failed",
            "detail": (
                f"incident `{task_id}` closure `tombstone:{tomb_id}` does not resolve -- no graveyard record "
                f"with that id ({problem_path})"
            ),
        }

    if closure.startswith("accepted-risk:"):
        risk_id = closure[len("accepted-risk:") :].strip()
        try:
            risks = accepted_risks.load(repo_root)
        except SystemExit as exc:
            return {**base, "classification": "unavailable", "reason": f"accepted-risks registry unreadable: {exc}"}
        record = risks.get(risk_id)
        if record is None:
            return {
                **base,
                "classification": "failed",
                "detail": (
                    f"incident `{task_id}` closure `accepted-risk:{risk_id}` does not resolve -- no accepted-risk "
                    f"record with that id ({problem_path})"
                ),
            }
        try:
            expired = risks.is_expired(risk_id)
        except (ValueError, TypeError) as exc:
            # Reachable only by hand-editing docs/ops/accepted_risks.json: record-time
            # validation (accepted_risks._validate_expires_on) rejects a garbage
            # expires_on before it can ever be written by record_risk(). This is a
            # RECORD-level defect, not file-level infrastructure absence -- it must
            # never note-pass, or a hand-edited garbage date becomes an immortal-risk
            # evasion channel (fix round 2, reviewer-found: run_check's "never raises"
            # contract was violated here -- risks.is_expired's dt.date.fromisoformat
            # raised straight through, uncaught). Widened to also catch TypeError
            # (fix round 3, verifier-found): expires_on present but non-string --
            # null or an int both pass load()'s key-presence check and both are
            # hand-edit-reachable -- makes dt.date.fromisoformat raise TypeError,
            # not ValueError; same record-level defect, same classification.
            return {
                **base,
                "classification": "failed",
                "detail": (
                    f"incident `{task_id}` closure `accepted-risk:{risk_id}` names a malformed accepted-risk "
                    f"record -- `expires_on` is unparseable ({exc}) -- fix the registry record or use a "
                    f"different closure ({problem_path})"
                ),
            }
        if expired:
            return {
                **base,
                "classification": "failed",
                "detail": (
                    f"incident `{task_id}` closure `accepted-risk:{risk_id}` has EXPIRED "
                    f"(expired {record['expires_on']}, owner {record['owner']}) -- the incident re-opens: "
                    f"{record['owner']} must land a fix (closure: gate:<filename> or closure: tombstone:<id>) "
                    f"or record a new accepted risk with a fresh expiry ({problem_path})"
                ),
            }
        return {**base, "classification": "resolved", "reason": f"accepted-risk `{risk_id}` unexpired (owner {record['owner']})"}

    return {
        **base,
        "classification": "failed",
        "detail": (
            f"incident `{task_id}` closure `{closure}` is not a recognized form -- expected `gate:<filename>`, "
            f"`tombstone:<id>`, or `accepted-risk:<id>` ({problem_path})"
        ),
    }


def _evaluate_incident(task_id: str, problem_path: str, closures: list[str], repo_root: Path) -> dict[str, Any]:
    if not closures:
        return {
            "task_id": task_id,
            "problem_path": problem_path,
            "classification": "missing_closure",
            "detail": (
                f"incident `{task_id}` resolves with no closure line in {problem_path} -- "
                "add a bullet in the exact form `- closure: gate:<filename>`, `- closure: tombstone:<id>`, "
                "or `- closure: accepted-risk:<id>` (the leading `- ` is required; a dash-less or fenced "
                "`closure:` mention does not count)"
            ),
        }
    if len(closures) > 1:
        return {
            "task_id": task_id,
            "problem_path": problem_path,
            "classification": "ambiguous_closure",
            "closures": closures,
            "detail": (
                f"incident `{task_id}` has {len(closures)} `closure:` lines in {problem_path} -- exactly one is "
                "required, an incident has one terminus"
            ),
        }
    return _resolve_closure(task_id, problem_path, closures[0], repo_root)


def run_check(repo_root: Path, *, base: str | None = None, head: str = "HEAD") -> dict[str, Any]:
    """Run the closure check and return a JSON-serializable report. Never
    raises -- an unresolvable closure becomes a `"failed"` /
    `"missing_closure"` / `"ambiguous_closure"` classification inside
    `results`/`violations`, not an exception."""
    normalized_base = str(base or "").strip()
    head_ref = str(head or "HEAD").strip() or "HEAD"

    if normalized_base:
        mode = "diff-range"
        old_board_text = _git_show(repo_root, f"{normalized_base}:{WORKBOARD_REL_PATH}") or ""
        new_board_text = _git_show(repo_root, f"{head_ref}:{WORKBOARD_REL_PATH}") or ""
    else:
        mode = "staged"
        old_board_text = _git_show(repo_root, f"HEAD:{WORKBOARD_REL_PATH}") or ""
        new_board_text = _git_show(repo_root, f":{WORKBOARD_REL_PATH}") or ""

    old_board = _board_map(old_board_text)
    new_board = _board_map(new_board_text)
    changed_paths = _changed_problem_paths(repo_root, mode=mode, base=normalized_base, head_ref=head_ref)
    candidates = _gather_candidates(new_board, changed_paths)

    results: list[dict[str, Any]] = []
    for key, entry in candidates.items():
        problem_path = entry["problem_path"]
        old_text = _show_side(repo_root, mode=mode, base=normalized_base, head_ref=head_ref, side="old", path=problem_path)
        new_text = _show_side(repo_root, mode=mode, base=normalized_base, head_ref=head_ref, side="new", path=problem_path)

        new_board_status = _norm(str(new_board.get(key, {}).get("status", "")))
        new_resolved = new_board_status == "resolved" or _header_status(new_text or "") == "resolved"
        if not new_resolved:
            continue

        old_board_status = _norm(str(old_board.get(key, {}).get("status", "")))
        old_resolved = old_board_status == "resolved" or _header_status(old_text or "") == "resolved"

        new_closures = _closure_lines(new_text or "")
        old_closures = _closure_lines(old_text or "")
        if old_resolved and old_closures == new_closures:
            continue  # already-resolved-unchanged: out of scope

        task_id = entry["task_id"]
        if key.startswith("path:"):
            task_id = _task_id_from_marker(new_text or old_text or "", task_id)

        results.append(_evaluate_incident(task_id, problem_path, new_closures, repo_root))

    violations = [r for r in results if r["classification"] in _FAIL_CLASSIFICATIONS]

    return {
        "ok": not violations,
        "mode": mode,
        "repo_root": str(repo_root),
        "base": normalized_base,
        "head": head_ref,
        "board_entries_consulted": len(new_board),
        "problem_files_changed": len(changed_paths),
        "incidents_checked": len(results),
        "resolved_count": sum(1 for r in results if r["classification"] == "resolved"),
        "unavailable_count": sum(1 for r in results if r["classification"] == "unavailable"),
        "results": results,
        "violations": violations,
    }


def main() -> int:
    if _runtime_protection_disabled():
        print("Problem closure gate: PASS (runtime protection disabled by human)")
        return 0

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None, help="Repository root (default: inferred from script location).")
    parser.add_argument(
        "--base",
        default="",
        help="Git base ref. Presence switches to diff-range mode (base..head), the CI form. "
        "Omit for staged mode (the local pre-commit form).",
    )
    parser.add_argument("--head", default="HEAD", help="Git head ref for diff-range mode (default: HEAD).")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT
    result = run_check(repo_root, base=str(args.base or ""), head=str(args.head or "HEAD"))

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1

    print(
        f"Problem closure gate ({result['mode']}): consulted {result['board_entries_consulted']} Task Problems "
        f"entr(y/ies), {result['problem_files_changed']} changed PROBLEM.md file(s), found "
        f"{result['incidents_checked']} resolving incident(s) "
        f"(resolved={result['resolved_count']}, unavailable={result['unavailable_count']})."
    )
    for item in result["results"]:
        if item["classification"] == "unavailable":
            print(f"UNAVAILABLE (pass, not a failure): incident `{item['task_id']}` -- {item['reason']}")

    if result["ok"]:
        print("Problem closure gate: PASS -- every resolving incident in this diff names something that resolves.")
    else:
        violations = result["violations"]
        print(f"Problem closure gate: FAIL -- {len(violations)} resolving incident(s) end in a shrug:")
        for item in violations:
            print(f"  - {item['detail']}")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
