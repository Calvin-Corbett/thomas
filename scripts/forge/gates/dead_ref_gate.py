#!/usr/bin/env python3
"""A dead branch name stays dead -- this gate is the pre-push side of the graveyard.

WHY THIS EXISTS: git's pre-push hook sees a ref about to be created or moved
on the remote, and nothing more. It cannot tell "a name nobody has ever used"
from "a name this repo deliberately killed" -- both look like an ordinary
push. The graveyard (``scripts/forge/graveyard.py`` /
``docs/ops/graveyard.json``) is the record that makes that distinction
legible; this gate is what refuses to let a dead branch name quietly come
back from a push, mirroring what ``merge_resurrection_gate.py`` does for
dead file paths.

WHAT IS GATED, AND WHAT IS NOT (the pre-push stdin contract, git docs):
each line git feeds this hook on stdin is
``<local ref> SP <local sha1> SP <remote ref> SP <remote sha1>``. A
``remote sha1`` of forty zeros means the remote does not have that ref yet --
this push would CREATE it. That is the only case this gate inspects. An
update to a ref the remote already has (any non-zero remote sha1) passes
untouched, no matter what name it carries: the name is already alive on the
remote, so there is nothing left for the graveyard to protect against, and a
gate that refused ordinary pushes to already-existing branches would be
noise, not protection.

CONTROLLER DESIGN NOTE: a lot of graveyard entries are generic seeded names
(``base``, ``full``, ``final``, ``publish``, ...) that plenty of throwaway
local worktrees reuse without incident -- this repo's own worktree fleet
salvage produced roughly 130 of them. Those stay refusable on purpose.
Because this gate only fires on a push that CREATES a remote ref, a local
branch named ``final`` that never leaves the machine never trips it -- only
the moment someone tries to push a dead name back onto a remote does the
friction apply, and pushing a dead name to a remote is exactly the situation
that deserves it.

ARGV FALLBACK: ``--ref NAME`` checks a single ref name directly, as if a
push were creating it, without reading stdin at all. This exists for testing
and for non-hook callers (CI, ad hoc checks) -- the real git pre-push hook
always invokes this script with stdin, never with ``--ref``.

HONESTY CONTRACT: this gate always prints how many dead branch names it
consulted and how many ref-creations it checked, even when both are zero --
see graveyard.py's module docstring on why an empty-looking result must
still be stated, not silently passed through (this repo's documented
disease is absence-reads-as-clean).

CASEFOLD: mirrors merge_resurrection_gate.py -- a dead branch name pushed
back under a different letter-case is matched too, because this repo's git
(core.ignorecase, the Windows/NTFS default) can treat two differently-cased
ref names as the very same loose ref on disk.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.forge import graveyard  # noqa: E402

ROOT = _REPO_ROOT
_ZERO_SHA = "0" * 40


def _runtime_protection_disabled() -> bool:
    """B9 (praxis-unbypassable-2026-05-29): only a validly SIGNED disable flag
    counts. Presence alone is not enough -- an unsigned planted flag must not
    disable this gate. Mirrors merge_resurrection_gate.py / thomas.tools.filesystem."""
    try:
        from scripts.forge.gates._runtime_guard import runtime_protection_disabled
    except ImportError:  # pragma: no cover - import path varies by run context
        try:
            from forge.gates._runtime_guard import runtime_protection_disabled
        except ImportError:
            from _runtime_guard import runtime_protection_disabled
    return runtime_protection_disabled(ROOT)


def _short_name(ref: str) -> str:
    """Strip refs/heads/ from a ref. Anything else (tags, refs/remotes/...) is
    returned unchanged -- the graveyard only ever records branch names, so a
    non-branch ref can never match one."""
    return str(ref or "").strip().removeprefix("refs/heads/")


def _parse_pushes(stdin_text: str) -> list[tuple[str, str, str, str]]:
    """Parse pre-push stdin lines: ``<local ref> <local sha> <remote ref>
    <remote sha>``. A malformed line (wrong field count) is skipped rather
    than raising -- a hook that crashes on an unexpected line is worse than
    one that ignores it, and git's own format is stable enough that this
    should never happen outside a hand-written test fixture."""
    pushes: list[tuple[str, str, str, str]] = []
    for raw in (stdin_text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) == 4:
            pushes.append((parts[0], parts[1], parts[2], parts[3]))
    return pushes


def _newest_branch_record(gy: graveyard.Graveyard, name: str) -> dict[str, Any] | None:
    """The newest ``kind="branch"`` record for this exact name, or None.
    Mirrors ``dead_file_paths()``'s "newest wins" rule but for a single
    lookup instead of the whole set, since the caller already has one
    specific candidate name to resolve."""
    newest: dict[str, Any] | None = None
    for record in gy.records:
        if record["kind"] == "branch" and record["name"] == name:
            newest = record
    return newest


def run_check(
    repo_root: Path,
    *,
    stdin_text: str = "",
    ref: str | None = None,
) -> dict[str, Any]:
    """Run the dead-ref check and return a JSON-serializable report.

    ``ref`` truthy selects the argv-fallback mode: a single ref name, checked
    as though a push were creating it. Otherwise this parses ``stdin_text``
    as pre-push hook input and inspects only the lines that CREATE a remote
    ref (remote sha1 all zeros) -- see the module docstring."""
    if ref:
        creating = [(f"refs/heads/{ref}", "", f"refs/heads/{ref}", _ZERO_SHA)]
        mode = "ref-arg"
    else:
        pushes = _parse_pushes(stdin_text)
        creating = [p for p in pushes if p[3] == _ZERO_SHA]
        mode = "stdin"

    gy = graveyard.load(repo_root)
    dead_names = gy.dead_ref_names()

    # Casefolded index alongside the exact one -- same reasoning as
    # merge_resurrection_gate.py's dead_by_casefold: this repo's git can
    # treat differently-cased ref names as the same loose ref on a
    # case-insensitive filesystem, so an exact-string lookup alone would
    # miss a real collision.
    dead_by_casefold: dict[str, list[str]] = {}
    for name in dead_names:
        dead_by_casefold.setdefault(name.casefold(), []).append(name)

    violations: list[dict[str, Any]] = []
    seen_record_ids: set[str] = set()
    for _local_ref, _local_sha, remote_ref, _remote_sha in creating:
        short = _short_name(remote_ref)
        if not short:
            continue

        candidates: set[str] = set()
        if short in dead_names:
            candidates.add(short)
        candidates.update(dead_by_casefold.get(short.casefold(), ()))

        for candidate_name in candidates:
            record = _newest_branch_record(gy, candidate_name)
            if record is None or gy.is_resurrection_approved(record["id"]):
                continue
            if record["id"] in seen_record_ids:
                continue
            seen_record_ids.add(record["id"])
            violations.append(
                {
                    **record,
                    "matched_ref": short,
                    "case_variant": candidate_name != short,
                }
            )

    return {
        "ok": not violations,
        "mode": mode,
        "repo_root": str(repo_root),
        "refs_creating_checked": len(creating),
        "dead_ref_names_consulted": len(dead_names),
        "violations": violations,
    }


def _render_violation(record: dict[str, Any]) -> str:
    lines = [
        f"  - {record.get('name')} (death id {record.get('id')}, deleted_on {record.get('deleted_on')}): "
        f"{record.get('reason')}"
    ]
    if record.get("case_variant"):
        lines.append(
            f"      pushed as {record.get('matched_ref')!r} -- a CASE-ONLY variant of the dead branch "
            f"{record.get('name')!r} (this repo's git treats them as the same ref)."
        )
    lines.append(
        f"      approve with: python scripts/forge/graveyard.py approve-resurrection {record.get('id')} "
        f"--reason <why this should come back> --by <you>"
    )
    return "\n".join(lines)


def main() -> int:
    if _runtime_protection_disabled():
        print("Dead-ref gate: PASS (runtime protection disabled by human)")
        return 0

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root (default: inferred from script location).",
    )
    parser.add_argument(
        "--ref",
        default=None,
        help="Argv fallback: check a single ref name directly, as if a push were "
        "CREATING it. Skips stdin entirely. For testing and non-hook callers "
        "(e.g. the janitor, CI).",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT

    stdin_text = ""
    if not args.ref and not sys.stdin.isatty():
        stdin_text = sys.stdin.read()

    result = run_check(repo_root, stdin_text=stdin_text, ref=args.ref)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"Dead-ref gate ({result['mode']}): consulted {result['dead_ref_names_consulted']} "
            f"dead branch name(s) against {result['refs_creating_checked']} ref-creation(s)."
        )
        if result["ok"]:
            print("Dead-ref gate: PASS -- no dead branch name was pushed back without an approved resurrection.")
        else:
            violations = result["violations"]
            print(
                f"Dead-ref gate: FAIL -- {len(violations)} dead branch name(s) "
                "pushed back without an approved resurrection:"
            )
            for record in violations:
                print(_render_violation(record))

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
