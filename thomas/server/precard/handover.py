"""The patch that was checked is the patch that is handed in, or nothing is.

``settle_if_finished`` used to read the green's patch twice: once in ``check_before_card`` and again in
``green_handoff.settle``. Nothing tied the two reads together. Processes the team had started in the green
were ended only inside ``settle``, after the check. One write into the green between the two reads was
enough: ``toctou_drive.py`` produced a submission whose ``change.patch`` broke
``tests/test_adder.py::test_add_makes_a_sum``, and whose ``checked`` field said "no failure this change
causes".

:func:`check_for_hand_in` closes that gap in three steps:

1. It ends every process the caged shell left running in the green before the check reads anything, so
   the team's own leftovers cannot write into it afterwards.
2. It runs the check, which carries the exact patch it read and that patch's sha256
   (``Checked.patch`` / ``Checked.patch_sha256``).
3. It reads the green's patch again and compares the sha256. If the two differ, the change moved while it
   was being checked. That is a finding, and nothing is handed in.

The caller then gives ``Checked.patch`` itself to ``green_handoff.settle(patch=...)``, so the submission is
those bytes and never a third read of the green.
"""

from __future__ import annotations

import dataclasses
import logging

from thomas.core import step_log
from thomas.server import green_checkout, green_handoff
from thomas.server.precard import check

log = logging.getLogger(__name__)

MOVED_LINE = "It changed while it was being checked, so it went back to its team."
MOVED_HEAD = "This change changed while it was being checked, so it was not handed in."


def moved_findings(checked_sha: str, now_sha: str) -> str:
    """The findings for a change that changed between its check and its hand-in."""
    return (
        f"{MOVED_HEAD}\n\n"
        f"The check before your card read a patch with sha256 {checked_sha}; when it was about to be handed in, "
        f"the same copy gave a patch with sha256 {now_sha}. Whatever changed was never checked, and the card "
        "would have said it was. Make sure nothing you started is still writing into this copy, then finish as "
        "usual: the check runs again on exactly what is handed in."
    )


def check_for_hand_in(execution_id: str, *, processes_ended: bool = False) -> check.Checked:
    """Check the change and confirm its bytes; end green's processes first unless already ended.

    Never raises, like :func:`check.check_before_card`. A change that moved is :data:`check.FAILED` with
    :func:`moved_findings`, so it goes back to its team the same way a failed check does.
    """
    if not processes_ended:
        green_handoff.end_green_processes(execution_id)
    with step_log.timed("check", execution_id=str(execution_id)) as noted:  # how long each check takes (2026-10-25)
        checked = check.check_before_card(execution_id)
        noted["outcome"] = checked.state
        if checked.cause:  # why a check could not give a verdict, e.g. busy or incomplete (2026-11-06)
            noted["cause"] = checked.cause
    if checked.failed or not checked.patch:
        return checked
    green = green_checkout.find_green(str(execution_id))
    try:
        now = green_checkout.green_patch(green) if isinstance(green, green_checkout.Green) else None
    except green_checkout.GreenUnavailable as exc:
        log.warning("green %s could not be read again after its check", execution_id, exc_info=True)
        return moved(checked, f"(it could not be read: {exc})")
    now_sha = check.patch_sha256(now) if now is not None else "(the copy is gone)"
    if now_sha == checked.patch_sha256:
        return checked
    log.warning("green %s changed while it was being checked: %s -> %s", execution_id, checked.patch_sha256, now_sha)
    return moved(checked, now_sha)


def moved(checked: check.Checked, now_sha: str) -> check.Checked:
    """*checked* as a failure: the change is not the bytes it was checked on, so that verdict says nothing about it."""
    return dataclasses.replace(
        checked,
        state=check.FAILED,
        line=MOVED_LINE,
        findings=moved_findings(checked.patch_sha256, now_sha),
    )


__all__ = ["MOVED_HEAD", "MOVED_LINE", "check_for_hand_in", "moved", "moved_findings"]
