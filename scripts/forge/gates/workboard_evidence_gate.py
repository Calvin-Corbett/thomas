#!/usr/bin/env python3
"""The workboard refuses a `done` it cannot check (phase 1.4, task 4).

WHY THIS GATE EXISTS AS THE NET: `scripts/crew/tasks/reactivate.py`'s
`set_task_status` is today's only code path that drives an Active Task to
`status=done`, and as of phase 1.4 task 2 it already demands
machine-verifiable evidence at the moment of that transition
(`scripts/crew/workboard/claim_evidence.py`). That would be the whole story
if `reactivate.py` were the only writer capable of making the change. It is
not: `scripts/crew/workboard/issue.py` -- PINNED, untouchable this phase --
carries its OWN `_set_task_status(lines, *, task_id, status)`, a parallel
line-mutator with no evidence plumbing at all, already wired into that same
file's blocked/in_progress transitions. Nothing about today's code routes a
`done` transition through it, but nothing stops a FUTURE change from doing
exactly that, and a gate that only trusted `reactivate.py`'s call path would
never see it happen. So this gate does not trust any call path: it reads
the BOARD DIFF itself, at the same choke point every landing-time gate in
this repo already uses (the staged git index for a local pre-commit run, a
base..head diff for CI). Whatever wrote the `done` transition -- today's
`reactivate.py`, a hand-edited WORKBOARD.md, or a future writer routed
through `issue.py`'s `_set_task_status` -- the diff looks the same, and
this gate refuses it the same way if it cannot check the evidence.

TWO MODES, ONE CHECK (mirrors merge_resurrection_gate.py):
  * staged (default, the local pre-commit form): compares `HEAD:<workboard>`
    against the STAGED index blob (`git show :<workboard>`).
  * diff-range (`--base`/`--head`, the CI form): compares `<base>:<workboard>`
    against `<head>:<workboard>`.
Both modes run the identical check: parse the `## Active Tasks` section on
each side into a `task_id -> fields` map (fields include the raw `evidence=`
field workboard_claims.py's own pinned parser silently drops -- see
`_active_task_field_map`'s docstring below), then find every task whose NEW
status is `done` UNLESS the OLD status was ALSO `done` AND its `evidence=`
field is byte-for-byte unchanged (CORRECTED, fix round 2, post-review -- see
"THE BLIND WINDOW" below: a `done`-with-changed-evidence, including
`done` -> `done` with the field gone entirely, is IN SCOPE. Only a truly
standing done -- same status, same evidence, both sides -- is out of scope,
since re-checking THAT would duplicate the expiry sweep's job,
`claim_evidence_sweep.py`, not this gate's). Every such transition must
carry an `evidence=` field that (a) exists, (b) parses via
`claim_evidence.parse_evidence`, and (c) does not verify as `"failed"` for
a REAL reason.

THE BLIND WINDOW (fix round 2, post-review -- a reviewer-reproduced CRITICAL
finding): the ORIGINAL version of this scoping rule read "OLD status was
NOT already done" -- full stop, with no look at evidence at all. That let a
reopen-then-hand-reflip happen INSIDE ONE board diff, invisibly: HEAD has
`status=done; evidence=commit:<real-sha>` (a genuinely verified prior
cycle); the working copy reopens it through the real tooling
(`done -> queued`, which strips `evidence=` per the per-cycle-revocation
fix above) and then a bypass writer hand-flips `status=queued` straight
back to `status=done` WITHOUT ever committing the intermediate `queued`
state -- so the diff this gate actually reads is simply `done` (with
evidence) -> `done` (with NO evidence), both sides `"done"`, which the old
rule treated as "unchanged" and skipped entirely. A done with ZERO evidence
landed clean. The identical blind spot also let evidence be SWAPPED on a
standing done with no reopen at all -- a bypass writer could edit
`evidence=commit:<real-sha>` to `evidence=commit:<a-different-sha>`
in place, and the old rule would never even look at the field to notice.
Fixed by adding evidence-equality to the scoping test itself, not by
patching the symptom: this gate no longer needs to assume the strip
already happened by the time it looks -- it can SEE any evidence change
directly, reopened-then-reflipped or not.

VERDICT HANDLING (never silently green, never a refusal on absent
infrastructure):
  * `verified`   -> PASS.
  * `attested`   -> PASS, with a printed `ATTESTED-NOT-VERIFIED` note --
                    attested is recorded-not-proven (see claim_evidence's
                    BINDING SEMANTICS docstring); this gate is not the
                    place to hard-refuse what the transition tooling
                    already accepted.
  * `failed`, `reason_code` in `claim_evidence.UNAVAILABLE_REASON_CODES`
                 -> PASS, with a printed UNAVAILABLE note. A `reason_code`
                    in that set means the CHECK ITSELF never ran (no
                    `--run-store-db` for a run-kind claim, or `git` failing
                    to run at all) -- infrastructure absence, not a finding
                    that the evidence is bad. Passing `--run-store-db`
                    makes run-kind evidence actually re-checked here;
                    commit and gate kinds need no extra flag.
  * `failed`, any other reason -> FAIL, naming the task and the reason.
  * missing `evidence=` field entirely -> FAIL, naming the task.
  * an `evidence=` value that does not parse -> FAIL, naming the task and
    the grammar defect `parse_evidence` raised.

HONESTY CONTRACT: like `merge_resurrection_gate.py`, this always prints how
many Active Task lines it consulted and how many done-transitions it found,
even when both are zero -- an empty diff is a fact worth stating, not a
silent pass.

EVIDENCE IS PER-CYCLE: reopening a task (`done -> queued`, `done ->
claimed`) revokes its evidence -- enforced at the transition tooling
(`reactivate.set_task_status` calls `claim_evidence.strip_evidence` on
every FROM-`done` transition). CORRECTED (fix round 2, post-review): this
gate does NOT get to lean on that strip alone and skip building its own
staleness logic -- see "THE BLIND WINDOW" above. The strip only helps when
the reopened (evidence-free) state is itself visible on one side of a
diff this gate reads; a reopen-then-reflip that happens entirely between
two board commits is invisible to a pure status-diff, because both sides
still read `status=done`. This gate's evidence-aware scoping (`new status
is done AND (old status != done OR old evidence != new evidence)`) is what
actually closes that window -- not the strip by itself, and not the
old status-only rule either.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.crew.workboard import claim_evidence  # noqa: E402
from thomas.marketplace.observability import run_store  # noqa: E402

ROOT = _REPO_ROOT
WORKBOARD_REL_PATH = "plans/thomas/WORKBOARD.md"

_FAIL_CLASSIFICATIONS = ("missing_evidence", "malformed_evidence", "failed")


def _runtime_protection_disabled() -> bool:
    """B9 (praxis-unbypassable-2026-05-29): only a validly SIGNED disable flag
    counts. Mirrors merge_resurrection_gate.py's identical guard."""
    try:
        from scripts.forge.gates._runtime_guard import runtime_protection_disabled
    except ImportError:  # pragma: no cover - import path varies by run context
        try:
            from forge.gates._runtime_guard import runtime_protection_disabled
        except ImportError:
            from _runtime_guard import runtime_protection_disabled
    return runtime_protection_disabled(ROOT)


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _git_show(repo_root: Path, ref: str) -> str | None:
    """`git show <ref>`'s stdout, or None if the ref/path does not resolve
    (unborn HEAD, a file that does not exist at that point, a workboard
    that is not staged at all). None is always treated as an empty
    workboard by callers, never as an error -- "the file did not exist
    there" is a legitimate state on either side of a diff."""
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


def _active_task_field_map(text: str) -> dict[str, dict[str, str]]:
    """`task_id` (lowercased) -> its full raw field dict, keyed off the
    `## Active Tasks` section of `text`.

    Deliberately uses `claim_evidence`'s own private line-grammar parser
    (`_active_tasks_bounds` / `_parse_task_line_fields`), NOT
    `workboard_issue._parse_active_task_line` /
    `workboard_claims._parse_active_task_entry` (the pinned validator's real
    parser): that parser reads only the five REQUIRED fields (task_id,
    agent, scope, summary, status) and silently drops everything else --
    including `evidence=` -- when it builds an `ActiveTask` (see
    claim_evidence.py's module docstring, "Storage decision"). This gate's
    entire job is to see that field, so it must use the parser that keeps
    it.
    """
    lines = text.splitlines()
    try:
        start, end = claim_evidence._active_tasks_bounds(lines)  # type: ignore[attr-defined]
    except ValueError:
        return {}
    out: dict[str, dict[str, str]] = {}
    for line in lines[start:end]:
        if not line.strip().startswith("-"):
            continue
        fields = claim_evidence._parse_task_line_fields(line)  # type: ignore[attr-defined]
        task_id = str(fields.get("task_id", "")).strip()
        if not task_id:
            continue
        out[task_id.lower()] = fields
    return out


def _done_transitions(
    old_map: dict[str, dict[str, str]], new_map: dict[str, dict[str, str]]
) -> list[dict[str, str]]:
    """Every Active Task line in `new_map` whose status is `done`, EXCEPT a
    truly standing done: same status ('done') AND the identical `evidence=`
    value on both sides. In scope whenever new status is `done` AND (old
    status != `done` OR old evidence != new evidence) -- see the module
    docstring's "THE BLIND WINDOW" (fix round 2, post-review) for why
    status alone is not enough: a reopen (which strips evidence) followed
    by a hand-reflip back to `done`, both happening between two board
    commits, reads as `done` on both sides of THIS diff even though the
    evidence vanished -- and a bypass writer can swap a standing done's
    evidence field in place without ever touching status at all. Comparing
    evidence too catches both.
    """
    transitions: list[dict[str, str]] = []
    for key, fields in new_map.items():
        if _norm(fields.get("status", "")) != "done":
            continue
        old_fields = old_map.get(key)
        old_status_done = old_fields is not None and _norm(old_fields.get("status", "")) == "done"
        if old_status_done:
            old_evidence = str((old_fields or {}).get("evidence", "")).strip()
            new_evidence = str(fields.get("evidence", "")).strip()
            if old_evidence == new_evidence:
                continue  # truly standing: same status, same evidence -- out of scope
        transitions.append(fields)
    return transitions


def _verify_with_guard(
    ev: claim_evidence.Evidence, repo_root: Path, db_path: Path | None, task_id: str
) -> claim_evidence.Verdict:
    """`verify_evidence`'s run-kind check re-points `run_store`'s
    module-global `_DB_PATH` as a side effect (see claim_evidence's BINDING
    SEMANTICS docstring). Save/restore around every call, exactly like
    `reactivate.set_task_status` and `claim_evidence_sweep.py` already do,
    so this gate never leaves the process pointed at a fixture/CI db."""
    saved_db_path = run_store._DB_PATH
    try:
        return claim_evidence.verify_evidence(ev, repo_root, db_path=db_path, task_id=task_id)
    finally:
        run_store._DB_PATH = saved_db_path


def _evaluate_task(task_id: str, fields: dict[str, str], repo_root: Path, db_path: Path | None) -> dict[str, Any]:
    raw = str(fields.get("evidence", "")).strip()
    if not raw:
        return {
            "task_id": task_id,
            "classification": "missing_evidence",
            "evidence": "",
            "detail": f"task `{task_id}` transitions to `done` with no `evidence=` field on its Active Task line",
        }
    try:
        ev = claim_evidence.parse_evidence(raw)
    except ValueError as exc:
        return {
            "task_id": task_id,
            "classification": "malformed_evidence",
            "evidence": raw,
            "detail": f"task `{task_id}` evidence `{raw}` is malformed: {exc}",
        }

    verdict = _verify_with_guard(ev, repo_root, db_path, task_id)

    if verdict.status == "verified":
        return {"task_id": task_id, "classification": "verified", "evidence": raw, "reason": verdict.reason}
    if verdict.status == "attested":
        return {"task_id": task_id, "classification": "attested", "evidence": raw, "reason": verdict.reason}

    # verdict.status == "failed"
    if verdict.reason_code in claim_evidence.UNAVAILABLE_REASON_CODES:
        return {
            "task_id": task_id,
            "classification": "unavailable",
            "evidence": raw,
            "reason": verdict.reason,
            "reason_code": verdict.reason_code,
        }
    return {
        "task_id": task_id,
        "classification": "failed",
        "evidence": raw,
        "reason": verdict.reason,
        "detail": f"task `{task_id}` evidence `{raw}` failed verification: {verdict.reason}",
    }


def run_check(
    repo_root: Path,
    *,
    base: str | None = None,
    head: str = "HEAD",
    run_store_db: Path | None = None,
) -> dict[str, Any]:
    """Run the evidence check and return a JSON-serializable report. Never
    raises -- a task whose evidence cannot be established becomes a
    `"failed"` / `"missing_evidence"` / `"malformed_evidence"`
    classification inside `results`/`violations`, not an exception."""
    normalized_base = str(base or "").strip()
    head_ref = str(head or "HEAD").strip() or "HEAD"

    if normalized_base:
        mode = "diff-range"
        old_text = _git_show(repo_root, f"{normalized_base}:{WORKBOARD_REL_PATH}") or ""
        new_text = _git_show(repo_root, f"{head_ref}:{WORKBOARD_REL_PATH}") or ""
    else:
        mode = "staged"
        old_text = _git_show(repo_root, f"HEAD:{WORKBOARD_REL_PATH}") or ""
        new_text = _git_show(repo_root, f":{WORKBOARD_REL_PATH}") or ""

    old_map = _active_task_field_map(old_text)
    new_map = _active_task_field_map(new_text)
    transitions = _done_transitions(old_map, new_map)

    results = [
        _evaluate_task(str(fields.get("task_id", "")).strip(), fields, repo_root, run_store_db)
        for fields in transitions
    ]
    violations = [r for r in results if r["classification"] in _FAIL_CLASSIFICATIONS]

    return {
        "ok": not violations,
        "mode": mode,
        "repo_root": str(repo_root),
        "base": normalized_base,
        "head": head_ref,
        "active_tasks_checked": len(new_map),
        "done_transitions_checked": len(results),
        "verified_count": sum(1 for r in results if r["classification"] == "verified"),
        "attested_count": sum(1 for r in results if r["classification"] == "attested"),
        "unavailable_count": sum(1 for r in results if r["classification"] == "unavailable"),
        "results": results,
        "violations": violations,
    }


def main() -> int:
    if _runtime_protection_disabled():
        print("Workboard evidence gate: PASS (runtime protection disabled by human)")
        return 0

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root (default: inferred from script location).",
    )
    parser.add_argument(
        "--base",
        default="",
        help="Git base ref. Presence switches to diff-range mode (base..head), the CI form. "
        "Omit for staged mode (the local pre-commit form).",
    )
    parser.add_argument("--head", default="HEAD", help="Git head ref for diff-range mode (default: HEAD).")
    parser.add_argument(
        "--run-store-db",
        default="",
        help="Path to a run_store sqlite db to re-verify run-kind evidence against. Without it, run-kind "
        "evidence is treated as unavailable infrastructure (PASS with a note), never a failure.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT
    db_path = Path(args.run_store_db).expanduser().resolve() if str(args.run_store_db or "").strip() else None

    result = run_check(repo_root, base=str(args.base or ""), head=str(args.head or "HEAD"), run_store_db=db_path)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1

    print(
        f"Workboard evidence gate ({result['mode']}): consulted {result['active_tasks_checked']} active task "
        f"line(s), found {result['done_transitions_checked']} done-transition(s) "
        f"(verified={result['verified_count']}, attested={result['attested_count']}, "
        f"unavailable={result['unavailable_count']})."
    )
    for item in result["results"]:
        if item["classification"] == "attested":
            print(f"ATTESTED-NOT-VERIFIED: task `{item['task_id']}` evidence `{item['evidence']}` -- {item['reason']}")
        elif item["classification"] == "unavailable":
            # Recon #7b (phase 2 batch 1): name the machine reason_code in the
            # human-readable note too, not just the --json payload -- a bare
            # "could not be re-checked" reads the same whether the cause is a
            # missing --run-store-db or git itself failing to run. Naming it
            # (e.g. `db_path_required` in a CI run that never passes
            # --run-store-db, see gates.yml) is the honest signal that this
            # is infrastructure absence, not a finding about the evidence.
            print(
                f"UNAVAILABLE ({item.get('reason_code', '')}, pass not a failure): task `{item['task_id']}` "
                f"evidence `{item['evidence']}` could not be independently re-checked -- {item['reason']}"
            )

    if result["ok"]:
        print("Workboard evidence gate: PASS -- every done transition in this diff carries evidence that checks out.")
    else:
        violations = result["violations"]
        print(f"Workboard evidence gate: FAIL -- {len(violations)} done transition(s) cannot be trusted:")
        for item in violations:
            print(f"  - {item['detail']}")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
