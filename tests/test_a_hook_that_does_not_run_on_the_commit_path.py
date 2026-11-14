"""A hook that does not run where agents commit is not protecting anything.

Found 2026-09-09. ``scripts/crew/brief/commit.py`` -- the tool every agent in
this repository commits through -- creates its commit with git PLUMBING:
``write-tree``, then ``commit-tree``, then ``update-ref``. Plumbing fires no git
hook of any kind. So ``.pre-commit-config.yaml`` is not merely un-mirrored on
that path, it is structurally unreachable from it, and ``LOCAL_GATE_COMMANDS``
is a REPLACEMENT registry rather than a copy.

Nothing had ever compared the two. Eight commit-stage hooks had no counterpart:
ruff, ruff-format, thomas-worktree-safety, thomas-untracked-import-gate,
thomas-enforcement-integrity, thomas-plan-structure-gate,
thomas-bulk-commit-guard and thomas-commit-growth-guard.

The worst of those is thomas-enforcement-integrity, the anti-tamper check for the
gate scripts themselves: the check that notices a gate has been altered did not
run on the path used to alter gates. Next is thomas-worktree-safety, the snapshot
that exists so a refused commit cannot destroy uncommitted work -- absent from the
path where commits are actually refused.

WHY THIS MATTERS MORE THAN A GATE THAT BLOCKS TOO MUCH. A gate that wrongly
refuses is loud, and someone fixes it within the hour. A gate that silently does
not run reports the same green as a gate that ran and passed. Asked independently
what breaks a repository at a hundred agents that nobody notices at ten, codex
answered: not races -- FALSE CONFIDENCE that survives after the races are fixed.
This is exactly that, named in advance by someone who had not seen it.

MATCHING IS BY SCRIPT PATH. The config calls one ``thomas-bulk-commit-guard`` and
the commit tool calls it ``bulk_commit``; a test keyed on names needs a
translation table, and translation tables rot in silence. The script path is the
one identifier both registries must already agree on to be running the same code.
Two hooks run no repo script at all -- ruff and ruff-format -- so they are mapped
explicitly in EXTERNAL_HOOK_GATES, and an unmapped external hook counts as
uncovered rather than as unknowable.

THE REGISTRY IS READ BY IMPORT, NOT BY PARSING. commit.py splices its parity
gates in from another module with ``*HOOK_PARITY_GATES``, so reading the file as
text would see a star and miss eight gates. Importing gives the resolved registry
that actually runs, which is the thing under test.

Hooks deliberately left off the path -- withheld pending repair, or covered at
merge readiness -- are held to the same standard in
tests/test_a_gate_left_off_the_commit_path_is_accounted_for.py. The readers both
files use live in tests/_hook_parity_readers.py, so neither file crosses the
per-commit growth cap.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.crew.brief.gate_parity import (  # noqa: E402
    COVERED_AT_MERGE_READINESS,
    EXTERNAL_HOOK_GATES,
    HOOK_ONLY_BY_DESIGN,
    HOOK_WITHHELD_PENDING_REPAIR,
)

from tests._hook_parity_readers import (  # noqa: E402
    _commit_stage_hooks,
    _gate_script,
    _hook_blocks,
    _scoped_path_coverage,
)


def test_the_readers_find_something() -> None:
    """Both sides must parse, or every assertion below passes on emptiness."""
    hooks = _commit_stage_hooks()
    scripts, names = _scoped_path_coverage()
    assert len(hooks) > 20, f"parsed only {len(hooks)} commit-stage hooks; the config reader is wrong"
    assert len(names) > 20, f"scoped path exposes only {len(names)} gates; the registry reader is wrong"
    assert len(scripts) > 20, f"only {len(scripts)} gate scripts on the scoped path; reader is wrong"


def test_every_commit_hook_has_a_counterpart_on_the_scoped_path() -> None:
    """The regression this file exists for.

    A commit-stage hook must either run on the path agents commit through, or be
    listed in HOOK_ONLY_BY_DESIGN with the reason it does not.
    """
    scripts, names = _scoped_path_coverage()
    uncovered: list[str] = []
    for hook_id, block in sorted(_commit_stage_hooks().items()):
        if (
            hook_id in HOOK_ONLY_BY_DESIGN
            or hook_id in HOOK_WITHHELD_PENDING_REPAIR
            or hook_id in COVERED_AT_MERGE_READINESS
        ):
            continue
        script = _gate_script(block["entry"])
        if script:
            if script not in scripts:
                uncovered.append(f"  {hook_id}: runs {script}, which nothing on the scoped path runs")
            continue
        mapped = EXTERNAL_HOOK_GATES.get(hook_id)
        if not mapped:
            uncovered.append(f"  {hook_id}: runs no repo script and has no EXTERNAL_HOOK_GATES entry")
        elif mapped not in names:
            uncovered.append(f"  {hook_id}: mapped to gate {mapped!r}, which the scoped path does not run")
    assert not uncovered, (
        "these hooks do not run where agents actually commit, so they report nothing "
        "and their silence reads as a pass:\n"
        + "\n".join(uncovered)
        + "\n\nAdd the gate to HOOK_PARITY_GATES, or record the exemption in "
        "HOOK_ONLY_BY_DESIGN with the reason it cannot apply per commit."
    )


def test_every_exemption_names_a_hook_that_still_exists() -> None:
    """An exemption must not outlive its hook.

    A standing permission for a hook nobody runs any more is a permission waiting
    for someone to reuse the name.
    """
    known = set(_hook_blocks())
    assert known, "parsed no hooks at all; see the reader test"
    listed = [*HOOK_ONLY_BY_DESIGN, *HOOK_WITHHELD_PENDING_REPAIR, *COVERED_AT_MERGE_READINESS]
    stale = sorted(hook_id for hook_id in listed if hook_id not in known)
    assert not stale, (
        "these exemptions name hooks that no longer exist: "
        + ", ".join(stale)
        + " -- delete the entries rather than leaving the permission lying around"
    )


def test_every_exemption_gives_a_reason_worth_reading() -> None:
    """A one-word reason is an exemption with extra steps."""
    thin = sorted(hook_id for hook_id, reason in HOOK_ONLY_BY_DESIGN.items() if len(reason.strip()) < 80)
    assert not thin, (
        "these exemptions have a reason too short to be one: "
        + ", ".join(thin)
        + " -- say what the hook checks and why a single commit cannot answer it"
    )


def test_an_exemption_is_not_a_way_to_hide_a_commit_stage_hook() -> None:
    """Exemptions are for hooks that genuinely cannot run per commit.

    Every current entry is pre-push. If someone exempts a commit-stage hook, that
    is the very divergence this file exists to catch, wearing a permission slip.
    """
    blocks = _hook_blocks()
    smuggled = sorted(
        hook_id for hook_id in HOOK_ONLY_BY_DESIGN if hook_id in blocks and "push" not in blocks[hook_id]["stages"]
    )
    assert not smuggled, (
        "these are commit-stage hooks excused from the commit path: "
        + ", ".join(smuggled)
        + " -- a commit-stage hook that cannot run on the commit path is the bug, "
        "not the exception. Make it run, or move it to the pre-push stage where "
        "its absence here is honest."
    )
