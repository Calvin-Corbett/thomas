"""The gates the scoped commit path was missing, and the ones it skips on purpose.

Found 2026-09-09. ``scripts/crew/brief/commit.py`` creates commits with git
PLUMBING -- ``write-tree``, ``commit-tree``, ``update-ref``. Plumbing fires no
git hook of any kind, so ``.pre-commit-config.yaml`` is not merely un-mirrored on
the agent commit path, it is structurally unreachable from it. That makes
``LOCAL_GATE_COMMANDS`` a REPLACEMENT registry rather than a mirror, and nothing
ever compared the two.

Eight commit-stage hooks had no counterpart there:

    ruff, ruff-format, thomas-worktree-safety, thomas-untracked-import-gate,
    thomas-enforcement-integrity, thomas-plan-structure-gate,
    thomas-bulk-commit-guard, thomas-commit-growth-guard

``thomas-enforcement-integrity`` is the anti-tamper anchor for the gate scripts
themselves, so the check that notices a gate has been edited did not run on the
path agents use to edit gates. ``thomas-worktree-safety`` is the snapshot that
exists so a refused commit cannot eat uncommitted work, and it was absent from
the path where commits are actually refused.

Separately, ``.git/hooks/commit-msg`` does not exist at all, so
``thomas-workboard-inbox-commit-msg-gate`` has never run on any path.

WHY A SEPARATE MODULE. commit.py is protected and carries a monolith waiver whose
stated reason is "gate-registry refactor target". Adding twenty lines of registry
to it works against that, and every line added to a protected file is a line that
needs an owner approval to land. The registry lives here, commit.py splices it in,
and its own diff stays at two lines.

WHY THESE ARE SAFE TO ADD, measured before adding them. Run against the shared
working tree, enforcement_integrity and both ruff hooks FAIL right now -- but that
is the wrong condition. A scoped commit runs its gates against a TEMPORARY INDEX
built from HEAD plus the paths being committed, so another agent's staged work is
not visible to them. Re-measured under that index: enforcement_integrity passes
across all 65 scripts, and ruff is clean on the selected paths. The whole-tree
failures were other agents' in-flight files and a pre-existing error in a file
nobody selected.

That distinction is the entire hazard here. commit.py already carries a comment
about an untracked gate that "refused every agent in this repo for twelve hours,
its own author included". A gate added to this path without being measured under
this path's real conditions does exactly that again.

SIX ON THIS PATH, ONE AT MERGE READINESS, ONE WITHHELD. thomas-plan-structure-gate is
a repository-wide check that the project deliberately moved to merge readiness:
scripts/forge/gates/merge_readiness.py runs it and tests/test_commit_gate_split.py
pins the split. COVERED_AT_MERGE_READINESS records that, and the parity test checks
the coverage is real rather than asserted. thomas-worktree-safety is withheld rather
than added. It is not a gate -- it always exits 0 -- and review found its restore
path unsafe in a shared checkout: every snapshot is an unattributed diff of the
whole working tree, and --restore applies the newest one by filename, whoever wrote
it. Putting it on every scoped commit would spread that, not the protection its
name promises. HOOK_WITHHELD_PENDING_REPAIR records the decision with its evidence
and an expiry, and the parity test holds it to that date.
"""

from __future__ import annotations

import sys

# Hook id -> why that hook deliberately has no counterpart on the scoped commit
# path. An entry here is a stated exemption, not a pardon: the parity test in
# tests/test_a_hook_that_does_not_run_on_the_commit_path.py fails on any
# commit-stage hook that is absent AND unlisted, and fails again if an entry
# names a hook that no longer exists.
HOOK_ONLY_BY_DESIGN: dict[str, str] = {
    "thomas-merge-readiness": (
        "pre-push stage. It asks whether a BRANCH is ready to leave this machine, "
        "which is not a question a single commit can answer, and running it per "
        "commit would refuse every intermediate step of work that is going to be "
        "ready by the time it is pushed."
    ),
    "thomas-publish-preflight": (
        "pre-push stage, and it checks the publication surface -- release metadata, "
        "signing, the public branch. A commit on dev is not a publication."
    ),
    "thomas-dead-ref-gate": (
        "pre-push stage. It sweeps refs across the repository, which is repository "
        "state rather than anything the commit being made contains."
    ),
    "thomas-branch-claim-gate": (
        "pre-push stage. A branch claim is about who may move a branch, which is "
        "settled when the branch moves, not when a commit object is written."
    ),
}

# Gates that must be handed the paths being committed. Without this ruff would
# lint the whole repository, which is both slow and wrong: pre-commit passes it
# only the changed files, and the repository currently carries a lint error in a
# file nobody here selected. A gate that fails on somebody else's file is a gate
# that blocks the fleet.
PATH_ARG_GATES: frozenset[str] = frozenset({"ruff", "ruff_format"})

# Hooks that run something other than a repo script, mapped to the scoped-path
# gate that covers them. Every other hook is matched by SCRIPT PATH, which is an
# identifier neither registry can drift from while still running the same code.
# These two have no script path to match on, so the correspondence has to be
# written down -- and being written down is the point: the parity test treats an
# unmapped external hook as uncovered, not as unknowable.
EXTERNAL_HOOK_GATES: dict[str, str] = {
    "ruff": "ruff",
    "ruff-format": "ruff_format",
}

# Commit-stage hooks the scoped path deliberately leaves to merge readiness, because
# they judge the repository as a whole rather than the commit being made. Each one
# must really be registered in scripts/forge/gates/merge_readiness.py and must NOT
# also be on the scoped path. The parity test checks both, so an entry here cannot
# describe a hook that simply runs nowhere.
COVERED_AT_MERGE_READINESS: dict[str, str] = {
    "thomas-plan-structure-gate": (
        "A repository-wide check the project deliberately moved to merge readiness, "
        "which scripts/forge/gates/merge_readiness.py runs and tests/test_commit_gate_split.py "
        "pins with an assertion that it is not a local commit gate. Adding it to every scoped "
        "commit would reverse that decision and judge one agent's commit on the state of the "
        "whole repository."
    ),
}

# Commit-stage hooks deliberately NOT propagated to the scoped path, because the
# hook itself is known to be defective and running it on every commit would spread
# the defect rather than the protection. Each entry carries its evidence and an
# expiry: this is owned, dated debt, not a quiet exemption. The parity test fails
# when an entry expires, so the decision has to be made again by someone instead of
# being inherited by default -- which is how eight gates went missing here at all.
HOOK_WITHHELD_PENDING_REPAIR: dict[str, dict[str, str]] = {
    "thomas-worktree-safety": {
        "reason": (
            "Not a gate -- it always exits 0 -- and its recovery path is unsafe in a "
            "shared checkout. capture() snapshots git diff HEAD --binary of the WHOLE "
            "working tree with no agent, branch or HEAD attribution, and latest() picks "
            "the newest patch by filename, so --restore applies whichever agent wrote "
            "last and can inject another agent's in-flight tree into yours. Inside a hook "
            "it also captures the wrong half: pre-commit has already checked the tree out "
            "from the index, so only the staged half, which cannot be destroyed, is saved. "
            "On the scoped path no checkout happens first, so every commit would snapshot "
            "every agent's uncommitted work into the pile that restore picks from blind."
        ),
        "evidence": (
            "scripts/forge/worktree_safety.py capture() line 113 and latest(), verified at "
            "HEAD 2026-09-10. Three independent reviews returned safeToLand=False; recovered "
            "and re-verified by claude in board message msg-20260910012300-claude. "
            "Renewed 2026-10-04, inside the owner-signed commit (this module is now an integrity-checked enforcement "
            "script), after re-reading HEAD 81cfd2cb: capture() still runs `git diff HEAD --binary` over the whole "
            "working tree (worktree_safety.py line 113), latest() still returns sorted(glob('*.patch'))[-1] "
            "(lines 142-146) with no agent, branch or HEAD in the choice, and the hook is still registered always_run "
            "in .pre-commit-config.yaml (lines 26-31). The only change since the first finding is fb75d0870, which "
            "also copies untracked files into a sidecar; that widens what a blind restore can inject and adds no "
            "attribution. Repairing it means putting agent and HEAD into the snapshot name and making --restore refuse "
            "a patch its caller did not write, which is a design change; this is a short renewal, not a repair, and a "
            "second renewal needs that repair."
        ),
        "expires": "2026-10-31",
    },
}

# Six of the eight that were missing, in the order pre-commit runs them.
# Formatting first, because a gate that reports on bytes a formatter is about to
# rewrite is reporting on bytes that will not be committed. plan_structure is
# covered at merge readiness and worktree_safety is withheld, both above.
HOOK_PARITY_GATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ruff", (sys.executable, "scripts/_gate_python.py", "-m", "ruff", "check")),
    ("ruff_format", (sys.executable, "scripts/_gate_python.py", "-m", "ruff", "format", "--check")),
    ("untracked_import", (sys.executable, "scripts/forge/gates/untracked_import_gate.py")),
    (
        "enforcement_integrity",
        (sys.executable, "scripts/forge/gates/enforcement_integrity.py", "--check-staged"),
    ),
    (
        "bulk_commit",
        (sys.executable, "scripts/forge/gates/bulk_commit_guard.py", "--max-files", "50"),
    ),
    (
        "commit_growth",
        (sys.executable, "scripts/forge/gates/commit_growth_guard.py", "--max-growth", "300"),
    ),
)
