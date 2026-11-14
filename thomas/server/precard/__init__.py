"""The check that runs before a Thomas project's card is shown to you.

``settle_if_finished`` calls :func:`check_for_hand_in` after the size rule and before the hand-off. A
change that passes is handed in with a line saying what was checked, and the bytes handed in are the bytes
that were checked; a change that fails, or that changed while it was being checked, raises
:class:`ChangeFailedCheck` and goes back to its team as a repair round; a check that could not run
holds the change before any card instead of pretending it was checked.

The pieces: :mod:`~thomas.server.precard.scratch` makes the two copies of dev,
:mod:`~thomas.server.precard.slot` keeps room on the disk (and one check at a time when the parallel check is off),
:mod:`~thomas.server.precard.pool` runs every check's tests in one machine-wide pool,
:mod:`~thomas.server.precard.lint` runs ruff over the changed files on both,
:mod:`~thomas.server.precard.report` writes the card line and the findings,
:mod:`~thomas.server.precard.check` puts them in order, and :mod:`~thomas.server.precard.handover` ties
the checked patch to the handed-in one. The tests themselves are run by :mod:`thomas.server.proof`, which
stands apart so the ratchet can share it. After a change passes, :mod:`~thomas.server.precard.review` has a
second model read it against the request before any card.

This package's names are its front door (``door`` in plugins/checks.toml): code outside takes what it needs from here,
never from the pieces above, so they can change with only this plugin's tests to answer for them.
"""

from __future__ import annotations

from thomas.server.precard import review, workers
from thomas.server.precard.check import (
    CHECK_DEADLINE_S,
    CHECK_DISK_BYTES,
    CHECK_ENV,
    FAILED,
    NO_ROOM_PHRASE,
    PASSED,
    UNAVAILABLE,
    ChangeDoesNotApply,
    ChangeFailedCheck,
    Checked,
    check_before_card,
    patch_sha256,
    turned_off,
)
from thomas.server.precard.handover import MOVED_HEAD, moved
from thomas.server.precard.lint import ruff_findings
from thomas.server.precard.report import CONFLICT_HEAD, FINDINGS_HEAD, FORMER_HEADINGS, HEADINGS
from thomas.server.precard.review import ChangeFailedReview, CheckUnavailable, ReviewUnavailable
from thomas.server.precard.review_dial import pause_shown
from thomas.server.precard.review_job import cancellable
from thomas.server.precard.worker_process import check_for_hand_in  # in its own process outside tests (2026-10-27)

__all__ = [
    "CHECK_DEADLINE_S",
    "CHECK_DISK_BYTES",
    "CHECK_ENV",
    "CONFLICT_HEAD",
    "FAILED",
    "FINDINGS_HEAD",
    "FORMER_HEADINGS",
    "HEADINGS",
    "MOVED_HEAD",
    "NO_ROOM_PHRASE",
    "PASSED",
    "UNAVAILABLE",
    "ChangeDoesNotApply",
    "ChangeFailedCheck",
    "ChangeFailedReview",
    "CheckUnavailable",
    "Checked",
    "ReviewUnavailable",
    "cancellable",
    "review",
    "check_before_card",
    "check_for_hand_in",
    "moved",
    "patch_sha256",
    "pause_shown",
    "turned_off",
    "workers",
    "ruff_findings",
]
