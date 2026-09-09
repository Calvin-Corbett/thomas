#!/usr/bin/env python3
"""An anonymous branch cannot reach a remote -- this gate is the pre-push
side of ``branch_claims.py``.

WHY THIS EXISTS: the cleanup that motivated this program found 150+ remote
branches with no owner and no reason recorded for any of them -- forking was
free, landing was expensive, and nothing on the push path ever asked "whose
branch is this and when does it stop being needed". ``branch_claims.py`` /
``docs/ops/branch_claims.json`` is the registry that answers that; this gate
is what refuses to let a push CREATE a new remote branch ref without a live
entry in it, mirroring what ``dead_ref_gate.py`` does for dead names instead
of unclaimed ones.

WHAT IS GATED, AND WHAT IS NOT (identical pre-push stdin contract to
``dead_ref_gate.py`` -- see its module docstring for the full git-hook
protocol explanation): each stdin line is
``<local ref> SP <local sha1> SP <remote ref> SP <remote sha1>``. A
``remote sha1`` of forty zeros means this push would CREATE that ref on the
remote -- the only case this gate inspects. An UPDATE to a ref the remote
already has (any non-zero remote sha1) passes untouched, and so does any
DELETION (which git also reports via a non-zero remote sha1, since the ref
already existed before being removed) -- there is nothing left for a claim
to protect once the branch is already alive on the remote or already gone.
Only refs under ``refs/heads/`` are considered; a push creating something
under a different namespace (``refs/archive/...``, a tag, ...) is not a
branch claim's business and is skipped without comment.

GRANDFATHERING (fix round 1, MIN-3, stated plainly because it was previously
left implicit): because only ref CREATION is gated, this repo's ~150
existing remote branches -- created before this gate ever existed -- remain
pushable (update, force-update, delete) INDEFINITELY with no claim of their
own. This is the plan's literal contract (creation-only, Task 2), not an
oversight: retroactively demanding a claim for every already-existing remote
branch would need either a bulk grandfather-claim seed or a bespoke
existing-branch check this gate does not perform. Only a NEW branch name
being pushed for the first time is asked to justify itself.

EXEMPT NAMES: ``dev`` and ``main`` never need a claim -- they are trunk, not
a fork. See ``_EXEMPT_BRANCHES``.

ARGV FALLBACK: ``--ref NAME`` checks a single ref name directly, as if a push
were creating it, without reading stdin at all -- for testing and for
non-hook callers (CI, ad hoc checks), same as ``dead_ref_gate.py``'s.

THE ASYMMETRY THIS GATE IS BUILT AROUND: destruction fails closed,
surfacing fails open with a note. This
gate only ever BLOCKS A PUSH (fully reversible -- retry after claiming the
branch); ``branch_sweep.py`` DELETES a local branch (destructive, only
reversible via the archive ref it writes first). So the two modules make
OPPOSITE decisions about the exact same "registry file is entirely absent"
condition:
  * this gate checks ``branch_claims.path(repo_root).exists()`` itself
    BEFORE calling ``load()``. If the file does not exist at all, that is
    infrastructure never having been provisioned on this machine/checkout --
    blocking every push over that would be paralyzing, so this gate PASSES
    with a loud note instead of enforcing.
  * a registry file that EXISTS but fails to parse (``branch_claims.load``
    raises ``SystemExit``) gets the same treatment -- a broken registry is
    also not evidence the push itself is bad, matching
    ``problem_closure_gate.py``'s identical "UNREADABLE REGISTRY" precedent
    for ``accepted_risks``/``graveyard``.
  * a registry file that EXISTS, PARSES, and is simply empty (nobody has
    claimed anything yet) is NOT infrastructure absence -- it is a live,
    working, empty registry, and every unclaimed push still fails against
    it. Only the file's outright absence gets the leniency.
``branch_sweep.py`` treats the identical "file absent" condition as
"unreadable registry -- refuse to delete anything" instead, because deleting
a branch needs positive proof it truly has no claim, not merely "nobody set
this up yet". See that module's docstring.

HONESTY CONTRACT: this gate always prints how many claims it consulted and
how many ref-creations it checked, even when both are zero.
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

from scripts.forge import branch_claims  # noqa: E402

ROOT = _REPO_ROOT
_ZERO_SHA = "0" * 40
_EXEMPT_BRANCHES = frozenset({"dev", "main"})


def _runtime_protection_disabled() -> bool:
    """B9 (praxis-unbypassable-2026-05-29): only a validly SIGNED disable flag
    counts. Mirrors dead_ref_gate.py's identical guard."""
    try:
        from scripts.forge.gates._runtime_guard import runtime_protection_disabled
    except ImportError:  # pragma: no cover - import path varies by run context
        try:
            from forge.gates._runtime_guard import runtime_protection_disabled
        except ImportError:
            from _runtime_guard import runtime_protection_disabled
    return runtime_protection_disabled(ROOT)


def _parse_pushes(stdin_text: str) -> list[tuple[str, str, str, str]]:
    """Parse pre-push stdin lines. Identical to dead_ref_gate.py's
    ``_parse_pushes``: a malformed line is skipped, never raised on."""
    pushes: list[tuple[str, str, str, str]] = []
    for raw in (stdin_text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) == 4:
            pushes.append((parts[0], parts[1], parts[2], parts[3]))
    return pushes


def run_check(
    repo_root: Path,
    *,
    stdin_text: str = "",
    ref: str | None = None,
) -> dict[str, Any]:
    """Run the branch-claim check and return a JSON-serializable report.

    ``ref`` truthy selects the argv-fallback mode: a single ref name, checked
    as though a push were creating it. Otherwise this parses ``stdin_text``
    as pre-push hook input and inspects only the lines that CREATE a
    ``refs/heads/...`` ref (remote sha1 all zeros) -- see the module
    docstring.

    Fix round 1 (MIN-2): ``ref`` is normalized by stripping a leading
    ``refs/heads/`` before being wrapped in ``refs/heads/{ref}`` below.
    Without this, ``--ref refs/heads/feat/x`` built the doubled path
    ``refs/heads/refs/heads/feat/x`` -- a genuinely claimed ``feat/x`` then
    read as an unrelated, unclaimed branch (reproduced). CI's real callers
    (``github.head_ref`` / ``github.ref_name`` in gates.yml) always pass a
    short name already, so this never affected the shipped wiring, but the
    argv fallback exists precisely for ad hoc/non-hook callers who may not
    know that.
    """
    if ref:
        short_ref = ref.removeprefix("refs/heads/")
        creating = [(f"refs/heads/{short_ref}", "", f"refs/heads/{short_ref}", _ZERO_SHA)]
        mode = "ref-arg"
    else:
        pushes = _parse_pushes(stdin_text)
        creating = [p for p in pushes if p[3] == _ZERO_SHA]
        mode = "stdin"

    branch_creations = [
        remote_ref.removeprefix("refs/heads/")
        for _local_ref, _local_sha, remote_ref, _remote_sha in creating
        if remote_ref.startswith("refs/heads/") and remote_ref.removeprefix("refs/heads/")
    ]
    branch_creations = [name for name in branch_creations if name not in _EXEMPT_BRANCHES]

    registry_path = branch_claims.path(repo_root)
    if not registry_path.exists():
        return {
            "ok": True,
            "mode": mode,
            "repo_root": str(repo_root),
            "branch_creations_checked": len(branch_creations),
            "claims_consulted": 0,
            "note": (
                f"branch claims registry {registry_path} does not exist -- passing without enforcing "
                "(infrastructure absence, not evidence any of these pushes is unclaimed)"
            ),
            "violations": [],
        }

    try:
        claims = branch_claims.load(repo_root)
    except SystemExit as exc:
        return {
            "ok": True,
            "mode": mode,
            "repo_root": str(repo_root),
            "branch_creations_checked": len(branch_creations),
            "claims_consulted": 0,
            "note": f"branch claims registry unreadable ({exc}) -- passing without enforcing (infrastructure absence)",
            "violations": [],
        }

    violations: list[dict[str, Any]] = []
    for name in branch_creations:
        expired = claims.is_expired(name)
        if expired is None:
            violations.append({"branch": name, "reason": "unclaimed", "record": None})
        elif expired:
            violations.append({"branch": name, "reason": "expired", "record": claims.get(name)})

    return {
        "ok": not violations,
        "mode": mode,
        "repo_root": str(repo_root),
        "branch_creations_checked": len(branch_creations),
        "claims_consulted": len(claims.records),
        "note": None,
        "violations": violations,
    }


def _render_violation(violation: dict[str, Any]) -> str:
    branch = violation["branch"]
    reason = violation["reason"]
    lines = [f"  - {branch!r}: {reason}"]
    record = violation.get("record")
    if reason == "expired" and record:
        lines.append(f"      claimed by {record.get('owner')!r}, expired {record.get('expires_on')}")
    lines.append(
        "      remedy: python scripts/forge/branch_claims.py record "
        f"--branch {branch} --owner <you> --purpose <why this branch exists> "
        "--expires-on <YYYY-MM-DD, at most 60 days out>"
    )
    return "\n".join(lines)


def main() -> int:
    if _runtime_protection_disabled():
        print("Branch claim gate: PASS (runtime protection disabled by human)")
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
        "CREATING it. Skips stdin entirely. For testing and non-hook callers.",
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
            f"Branch claim gate ({result['mode']}): consulted {result['claims_consulted']} claim(s) against "
            f"{result['branch_creations_checked']} branch-creation(s)."
        )
        if result["note"]:
            print(f"Branch claim gate: NOTE -- {result['note']}")
        if result["ok"]:
            print("Branch claim gate: PASS -- every new branch ref creation has a live claim.")
        else:
            violations = result["violations"]
            print(f"Branch claim gate: FAIL -- {len(violations)} branch(es) pushed without a live claim:")
            for violation in violations:
                print(_render_violation(violation))

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
