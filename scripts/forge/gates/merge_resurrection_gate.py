#!/usr/bin/env python3
"""A three-way merge cannot tell a deletion from an absence -- this gate can.

WHY THIS EXISTS: `git diff` between two branches shows an added path exactly
the same way whether that path is genuinely new or whether it is a file this
repo deliberately killed on `dev` after the file was gone. A merge or a
carelessly-staged `git add` cannot distinguish "never existed here" from
"existed and was removed on purpose" -- both read as an ADD. The graveyard
(``scripts/forge/graveyard.py`` / ``docs/ops/graveyard.json``) is the record
that makes that distinction legible; this gate is what refuses to let a dead
path quietly ride back in without someone explicitly approving its return.

TWO MODES, ONE CHECK:
  * staged (default, what a local pre-commit hook runs): every path staged
    as an ADD (``git diff --cached --name-status --diff-filter=A``).
  * diff-range (``--base``/``--head``, what CI runs over a PR/push range):
    every path added between two refs
    (``git diff --name-status --diff-filter=A base..head``).
Both modes run the identical check: for each added path, is it in the
graveyard's ``dead_file_paths()``, and if so, has ITS SPECIFIC death record
been resurrection-approved? A path can die, be approved, and die again --
``dead_file_paths()`` always returns the newest death record, and an
approval only ever clears the death id it names (see graveyard.py's
docstring for why that is safe under repeated deaths).

HONESTY CONTRACT: this gate always prints how many dead-file records it
consulted, even when that number is zero -- an empty graveyard is a fact
worth stating, not a silent pass (this repo's documented disease is
absence-reads-as-clean; see graveyard.py's own module docstring).

EVASION-RESISTANT BY CONSTRUCTION, NOT BY LUCK: an added path is matched
against the graveyard two ways. (1) Exact string match against
``dead_file_paths()``. (2) A casefolded match against the same set, so a
dead path re-added under a different letter-case (``Old/Retired.py`` for
``old/retired.py``) is caught even though it is a genuine ``git`` ADD and a
distinct string -- on a case-insensitive filesystem (NTFS, APFS default)
that "different" path lands on the very same file. Both git diff calls pass
``--no-renames``: this repo's git has rename detection on by default, and an
identical-content delete+add pair (``git mv`` a live file onto a dead path,
or an equivalent add+rm in one commit/stage) collapses into an R-status line
that ``--diff-filter=A`` would silently miss entirely -- the resurrection
would not just evade the check, it would never appear in the diff this gate
looks at. ``--no-renames`` forces git to report the add and the delete as
two separate lines so the ADD side is always visible to ``--diff-filter=A``.

VERIFICATION COST (documented, deliberate): this gate binds the git object
store and the graveyard file together at the same ``--repo-root`` -- there
is no lighter-weight "graveyard-only" verification path that skips git.
That is intentional: the rename-collapse and case-insensitive-filesystem
behaviors this gate defends against are properties of the git store and the
OS, not of the graveyard data alone, so verifying this gate against live
production data requires a full clone, not a sparse or graveyard-only
checkout.
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

from scripts.forge import graveyard  # noqa: E402

ROOT = _REPO_ROOT


def _runtime_protection_disabled() -> bool:
    """B9 (praxis-unbypassable-2026-05-29): only a validly SIGNED disable flag
    counts. Presence alone is not enough -- an unsigned planted flag must not
    disable this gate. Mirrors thomas.tools.filesystem signed-flag validation."""
    try:
        from scripts.forge.gates._runtime_guard import runtime_protection_disabled
    except ImportError:  # pragma: no cover - import path varies by run context
        try:
            from forge.gates._runtime_guard import runtime_protection_disabled
        except ImportError:
            from _runtime_guard import runtime_protection_disabled
    return runtime_protection_disabled(ROOT)


def _normalize(path: str) -> str:
    return str(path or "").strip().replace("\\", "/")


def _parse_added_paths(name_status_output: str) -> list[str]:
    """Pull the added path out of every ``git diff --name-status
    --diff-filter=A`` line. The diff filter already restricts the output to
    status ``A`` (or occasionally ``A1``/etc. with some git configs), so this
    only needs to grab the path column, not re-check the status."""
    out: list[str] = []
    for raw in name_status_output.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].strip().upper().startswith("A"):
            normalized = _normalize(parts[1])
            if normalized:
                out.append(normalized)
    return out


def _git_staged_added_paths(repo_root: Path) -> list[str]:
    # --no-renames: without it, git's default rename detection collapses a
    # delete-of-X + add-of-identical-content-Y into a single R-status line,
    # which --diff-filter=A does not match at all -- the resurrection would
    # not just evade the *check*, it would evade the *diff this gate reads*.
    # See the module docstring's "EVASION-RESISTANT BY CONSTRUCTION" section.
    proc = subprocess.run(
        ["git", "diff", "--cached", "--no-renames", "--name-status", "--diff-filter=A"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip() or "unknown git diff --cached failure"
        raise RuntimeError(msg)
    return _parse_added_paths(proc.stdout)


def _git_range_added_paths(repo_root: Path, *, base: str, head: str) -> list[str]:
    # --no-renames: same reasoning as _git_staged_added_paths above -- this is
    # the CI form, over a base..head range instead of the staged index.
    proc = subprocess.run(
        ["git", "diff", "--no-renames", "--name-status", "--diff-filter=A", f"{base}..{head}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip() or "unknown git diff failure"
        raise RuntimeError(msg)
    return _parse_added_paths(proc.stdout)


def run_check(
    repo_root: Path,
    *,
    base: str | None = None,
    head: str = "HEAD",
) -> dict[str, Any]:
    """Run the resurrection check and return a JSON-serializable report.

    ``base`` truthy selects diff-range mode (CI); otherwise this checks the
    staged index (the local pre-commit form). Never raises for a normal
    result -- a ``RuntimeError`` from the underlying git call is reported as
    ``ok=False`` with an ``error`` key, matching the sibling gates'
    convention (see deletions.py)."""
    normalized_base = str(base or "").strip()
    head_ref = str(head or "HEAD").strip() or "HEAD"

    try:
        if normalized_base:
            added_paths = _git_range_added_paths(repo_root, base=normalized_base, head=head_ref)
            mode = "diff-range"
        else:
            added_paths = _git_staged_added_paths(repo_root)
            mode = "staged"
    except RuntimeError as exc:
        return {"ok": False, "mode": "diff-range" if normalized_base else "staged", "error": str(exc)}

    gy = graveyard.load(repo_root)
    dead = gy.dead_file_paths()

    # Casefolded index alongside the exact one: core.ignorecase=true on this
    # repo (the Windows/NTFS default) means a dead path re-added under a
    # scrambled case (Agent_Memory/__Init__.py for agent_memory/__init__.py)
    # is a genuine, distinct-string git ADD -- an exact dict lookup misses it
    # even though it lands on the very same file on disk. Multiple dead
    # paths could theoretically collide under casefold, so this maps to a
    # list, not a single record.
    dead_by_casefold: dict[str, list[dict[str, Any]]] = {}
    for path, record in dead.items():
        dead_by_casefold.setdefault(path.casefold(), []).append(record)

    violations: list[dict[str, Any]] = []
    for path in added_paths:
        record = dead.get(path)
        if record is not None:
            if not gy.is_resurrection_approved(record["id"]):
                violations.append({**record, "matched_path": path, "case_variant": False})
            continue

        # No exact match -- check whether this is the SAME path under a
        # different letter-case than a dead record.
        for candidate in dead_by_casefold.get(path.casefold(), ()):
            if gy.is_resurrection_approved(candidate["id"]):
                continue
            violations.append({**candidate, "matched_path": path, "case_variant": True})

    return {
        "ok": not violations,
        "mode": mode,
        "repo_root": str(repo_root),
        "base": normalized_base,
        "head": head_ref,
        "added_paths_checked": len(added_paths),
        "dead_file_records_consulted": len(dead),
        "violations": violations,
    }


def _render_violation(record: dict[str, Any]) -> str:
    lines = [
        f"  - {record.get('name')} (death id {record.get('id')}, deleted_on {record.get('deleted_on')}): "
        f"{record.get('reason')}"
    ]
    if record.get("case_variant"):
        # Name BOTH spellings explicitly -- the whole point of this branch is
        # that they look like two different files but are the same path on a
        # case-insensitive filesystem, so the reader must be told plainly.
        lines.append(
            f"      re-added as {record.get('matched_path')!r} -- a CASE-ONLY variant of the dead path "
            f"{record.get('name')!r} (they are the same file on a case-insensitive filesystem)."
        )
    lines.append(
        f"      approve with: python scripts/forge/graveyard.py approve-resurrection {record.get('id')} "
        f"--reason <why this should come back> --by <you>"
    )
    return "\n".join(lines)


def main() -> int:
    if _runtime_protection_disabled():
        print("Merge-resurrection gate: PASS (runtime protection disabled by human)")
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
    parser.add_argument(
        "--head",
        default="HEAD",
        help="Git head ref for diff-range mode (default: HEAD).",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT
    result = run_check(repo_root, base=str(args.base or ""), head=str(args.head or "HEAD"))

    if "error" in result:
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Merge-resurrection gate: FAIL ({result['error']})")
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"Merge-resurrection gate ({result['mode']}): consulted {result['dead_file_records_consulted']} "
            f"dead file record(s) against {result['added_paths_checked']} added path(s)."
        )
        if result["ok"]:
            print("Merge-resurrection gate: PASS -- no dead file path was re-added without an approved resurrection.")
        else:
            violations = result["violations"]
            print(
                f"Merge-resurrection gate: FAIL -- {len(violations)} dead file path(s) "
                "re-added without an approved resurrection:"
            )
            for record in violations:
                print(_render_violation(record))

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
