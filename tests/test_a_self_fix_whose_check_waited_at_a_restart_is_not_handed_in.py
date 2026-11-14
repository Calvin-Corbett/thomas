"""A self-fix whose check was sent away by a restart is left as the restart leaves it, never handed in unchecked.

The check before a delegated self-fix's card (``chat_delegation_emitter._settle_green``) waits for its turn on the
check threads like a Thomas project's. When the server begins to stop while it waits, the check ends as busy; a
self-fix has no hold to wait in, so it must not go on to ``green_handoff.settle``, which would hand the unchecked
change in and remove its green.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests import restart_check_support as support
from thomas.server import capacity_ledger, green_checkout, green_handoff, precard
from thomas.server.chat_delegation_emitter import _DelegationEmitter
from thomas.server.precard import check


class _Emitter:
    """What ``_settle_green`` uses of the delegation emitter: the real check before the card."""

    _check_before_card = staticmethod(_DelegationEmitter._check_before_card)

    async def _emit_event(self, _event: object) -> None:
        return None


def test_a_self_fix_whose_check_waited_at_a_restart_is_not_handed_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    green = support.in_line(tmp_path, monkeypatch, wait_s=60)
    ran: list[str] = []
    monkeypatch.setattr(check, "_against_dev", lambda *_a: ran.append("ran") or check.Checked(check.PASSED, "passed"))
    monkeypatch.setattr(green_checkout, "find_green", lambda _eid: green)
    monkeypatch.setattr(precard, "check_for_hand_in", lambda _eid: support.admitted(green))
    handed: list[dict[str, object]] = []
    monkeypatch.setattr(green_handoff, "settle", lambda _eid, **kwargs: handed.append(kwargs))
    emitter, settles = _Emitter(), []

    async def started(_app: object) -> None:
        record = {"execution_id": "same", "session_id": "chat-1"}
        settles.append(asyncio.create_task(_DelegationEmitter._settle_green(emitter, record, promote=True, text="t")))
        assert await asyncio.to_thread(support.until_waiting), "the self-fix's check must be waiting for its turn"

    async def stopped(_app: object) -> None:  # the settle is given its chance to finish before the loop closes
        await asyncio.wait_for(asyncio.shield(settles[0]), 5)

    with support.one_ahead(tmp_path):
        support.serve_once(monkeypatch, started, drain_s=5, stopped=stopped)
    assert support.until_idle()

    assert handed == [], "a self-fix whose check never ran was handed in"
    assert ran == [] and capacity_ledger.rows() == []
    assert settles[0].done() and not settles[0].cancelled() and settles[0].exception() is None
