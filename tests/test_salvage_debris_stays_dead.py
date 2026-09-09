"""Four files rode through the worktree-fleet salvage/restore operation as
debris and were never cleaned up: `thomas/server/app_part03.py` is an
orphan half of a `*_part*.py` loader that only activates when ALL FOUR
`app_part01..04.py` exist (`thomas/server/app.py:16-25`) -- only this one is
present, so the branch has been permanently dead since the salvage. The three
`apps/site/src/app/globals_part01/02/03.css` files duplicate content already
present, in full, in the still-live `globals.css`.

Both orphan sets trace to `36ad0730 praxis-salvage snapshot of full (10613
files)` and are dated May 22 on disk -- carried through the salvage, never
resurrected on purpose, never used.

**The landing is split TWICE, deliberately.** All four files are deleted on
disk and all four have real graveyard death records written via the actual
`graveyard.py record-file` API -- but committing that is blocked two
different ways, discovered independently while landing this task:

1. `docs/ops/graveyard.json` became a protected `enforcement_file` at
   `28518073` (2026-08-25, the phase-1.2 graveyard-wiring landing) --
   `protected_files_gate.py`'s local/staged mode has no agent-usable
   override, only a native Windows sign-in
   (`scripts/breakglass_window.py on`). It rides the pending protected-files
   tap tracked in `plans/thomas/tasks/PRAXIS-PHASE14-BREAKGLASS/batch.md`
   (step 6a).
2. The three `globals_part0N.css` deletions independently trip
   `scripts/forge/gates/site_visual_proof.py` (path-scoped to
   `apps/site/src/app/`). Investigated, not routed around: regenerating the
   proof with the three files RESTORED still showed a 37-60% footer-focus
   pixel-diff against the committed baseline (threshold 2%), varying between
   runs with no file changes at all -- pre-existing, non-deterministic
   baseline drift on `dev`, unrelated to this deletion and out of this
   task's scope to fix. Silently regenerating a fresh baseline to make the
   gate pass would have masked that drift rather than disclosed it.

Only `thomas/server/app_part03.py`'s deletion is committed by the change
that adds this test. The other three paths are deleted on disk, have real
graveyard records on disk, but are NOT yet committed -- so a fresh CI
checkout of HEAD still contains them. That gap is real, disclosed, and
time-boxed below, not silently tolerated.

Contracts pinned here, the phase-1.2 anti-resurrection style used by
`tests/test_a_dead_file_does_not_ride_back_in.py`:

1. every one of the four paths MUST NOT exist on the local filesystem --
   true unconditionally, everywhere, right now (all four are actually
   deleted).
2. every path already committed as deleted MUST NOT exist in HEAD's
   committed tree either -- what a fresh CI checkout actually sees. A path
   still present in HEAD is checked against `_PENDING_COMMIT_REASONS`
   below: an undisclosed pending path is an immediate FAIL (no silent
   gaps); a disclosed one gets the same skip-before-expiry /
   fail-after-expiry treatment as the graveyard records, via
   `_assert_or_skip_pending`.
3. every path with a graveyard death record on disk has one naming
   `salvage-debris` -- true today in a local working tree (`graveyard.load`
   reads disk, not git history) but not yet in CI, which only sees the
   committed `docs/ops/graveyard.json`. Same skip-before-expiry treatment.
"""

from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import pytest
from scripts.forge import graveyard

REPO_ROOT = Path(__file__).resolve().parent.parent

_DEAD_PATHS = (
    "thomas/server/app_part03.py",
    "apps/site/src/app/globals_part01.css",
    "apps/site/src/app/globals_part02.css",
    "apps/site/src/app/globals_part03.css",
)

# Both split-landing gaps (deletion-commit and graveyard-record) are expected
# to close well before this date. Past it, a still-pending path is no longer
# an honest "disclosed, tracked wait" story -- it is a FAIL, so neither skip
# below can rot into a permanent pass-by-omission.
_SPLIT_LANDING_EXPIRY = dt.date(2026, 10, 1)

# Why each path's DELETION is not yet committed, keyed by path. Every path
# in _DEAD_PATHS that is still present in HEAD's committed tree must have an
# entry here -- an undisclosed gap is a hard FAIL, never a silent skip.
_PENDING_COMMIT_REASONS = {
    "apps/site/src/app/globals_part01.css": (
        "blocked by scripts/forge/gates/site_visual_proof.py: pre-existing "
        "footer-focus pixel-diff drift (37-60% vs 2% threshold, reproduced "
        "with these files both present AND deleted, varying run to run with "
        "no file changes) -- not caused by this deletion, out of scope to fix here"
    ),
    "apps/site/src/app/globals_part02.css": (
        "blocked by scripts/forge/gates/site_visual_proof.py: pre-existing "
        "footer-focus pixel-diff drift (37-60% vs 2% threshold, reproduced "
        "with these files both present AND deleted, varying run to run with "
        "no file changes) -- not caused by this deletion, out of scope to fix here"
    ),
    "apps/site/src/app/globals_part03.css": (
        "blocked by scripts/forge/gates/site_visual_proof.py: pre-existing "
        "footer-focus pixel-diff drift (37-60% vs 2% threshold, reproduced "
        "with these files both present AND deleted, varying run to run with "
        "no file changes) -- not caused by this deletion, out of scope to fix here"
    ),
}


def _exists_in_committed_head(path: str) -> bool:
    """True if `path` is still present in HEAD's committed tree.

    This is what a fresh CI checkout actually sees -- independent of a local
    working-tree deletion that has not been committed yet. `git cat-file -e`
    exits 0 when the object resolves, non-zero when it does not.
    """
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"HEAD:{path}"],
        capture_output=True,
    )
    return proc.returncode == 0


def _assert_or_skip_pending(pending: list[str], *, what: str, tracker: str) -> None:
    """Shared honesty handling for both split-landing gaps (see module
    docstring): before the expiry, a disclosed pending item is a
    `pytest.skip` naming what it is waiting for; at or after the expiry, the
    same absence is a hard FAIL, so neither gap can quietly outlive its own
    disclosed reason.
    """
    today = dt.date.today()
    if today < _SPLIT_LANDING_EXPIRY:
        pytest.skip(
            f"{what} still pending for {pending} -- tracked in {tracker} "
            f"(expected before {_SPLIT_LANDING_EXPIRY.isoformat()})"
        )
    pytest.fail(
        f"{what} STILL pending for {pending} past {_SPLIT_LANDING_EXPIRY.isoformat()} "
        f"-- {tracker} did not land in time; this is no longer an honest pending skip"
    )


def test_the_four_salvage_orphans_do_not_exist_on_the_local_filesystem() -> None:
    still_present = [path for path in _DEAD_PATHS if (REPO_ROOT / path).exists()]

    assert still_present == [], f"salvage debris rode back in: {still_present}"


def test_every_committed_salvage_orphan_deletion_does_not_exist_in_head() -> None:
    pending = [path for path in _DEAD_PATHS if _exists_in_committed_head(path)]
    if not pending:
        return

    undisclosed = [path for path in pending if path not in _PENDING_COMMIT_REASONS]
    assert undisclosed == [], f"path(s) pending a commit with NO disclosed reason: {undisclosed}"

    _assert_or_skip_pending(
        pending,
        what="deletion commit",
        tracker="test module's _PENDING_COMMIT_REASONS (see docstring for the site_visual_proof blocker)",
    )


def test_each_salvage_orphan_has_a_graveyard_death_record_naming_salvage_debris() -> None:
    gy = graveyard.load(REPO_ROOT)
    dead = gy.dead_file_paths()

    missing = [path for path in _DEAD_PATHS if path not in dead]
    if missing:
        _assert_or_skip_pending(
            missing,
            what="graveyard death record",
            tracker="plans/thomas/tasks/PRAXIS-PHASE14-BREAKGLASS/batch.md (step 6a)",
        )
        return

    for path in _DEAD_PATHS:
        record = dead[path]
        assert record["kind"] == "file"
        assert "salvage-debris" in record["reason"]


def test_the_working_tree_graveyard_still_loads_cleanly_with_the_new_records() -> None:
    """Named for what this actually reads: `graveyard.load` reads
    `docs/ops/graveyard.json` off the local filesystem, not off git history
    -- this passes today because the four new records are on disk, whether
    or not they are committed yet (fix round 1, review finding M2: the
    original name said "committed", which overclaimed)."""
    gy = graveyard.load(REPO_ROOT)

    assert isinstance(gy.records, tuple)
    for record in gy.records:
        assert record["kind"] in ("branch", "file", "resurrection-approved")
