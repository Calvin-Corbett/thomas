"""A paused Thomas can still restart to load a fix.

After a restart the server carries on whatever the restart interrupted, and it will not restart again while any of
that is still waiting. While Thomas is paused that pass carries nothing on, by design, so the waiting never ended:
on 2026-11-09, paused at your word with nothing running, the server sat "draining" for a landed fix and never
restarted. Pausing is what you do when Thomas misbehaves, which is when a fix most needs to load. Nothing is lost by
restarting then: what is still waiting is written down for the next server to pick up.
"""

from __future__ import annotations

import pytest
from aiohttp import web

from thomas.server import autopilot_restart, self_change_status
from thomas.server import landed_code_reload as reload
from thomas.server.precard import workers


@pytest.fixture
def quiet(monkeypatch: pytest.MonkeyPatch) -> web.Application:
    monkeypatch.setattr(reload, "active_code_runs", lambda app: {})
    monkeypatch.setattr(workers, "active_calls", lambda: 0)
    monkeypatch.setattr(reload, "_promoter_is_landing", lambda: False)
    monkeypatch.setattr(self_change_status, "active_hand_ins", lambda: {})
    monkeypatch.setattr(autopilot_restart, "report", lambda: {"pending": ["fc_waiting_to_be_carried_on"]})
    return web.Application()


def test_work_waiting_to_be_carried_on_holds_a_restart_while_thomas_runs(quiet, monkeypatch) -> None:
    monkeypatch.setattr(reload, "paused", lambda: False)
    assert reload.active_work(quiet) == ("restart pending",)


def test_it_does_not_hold_a_restart_while_thomas_is_paused(quiet, monkeypatch) -> None:
    monkeypatch.setattr(reload, "paused", lambda: True)
    assert reload.active_work(quiet) == ()


def test_a_build_that_is_running_still_holds_a_restart_while_paused(quiet, monkeypatch) -> None:
    monkeypatch.setattr(reload, "paused", lambda: True)
    monkeypatch.setattr(reload, "active_code_runs", lambda app: {"fc_1": "run-1"})
    assert reload.active_work(quiet) == ("Build run",)
