"""A held hand-in is tried again by itself, once at a time across servers, and a restart never loses it.

The retries (thomas/server/autopilot_hold_tick.py) of the record in thomas/server/hand_in_hold.py; the record and
the settle that books it are tests/test_a_change_that_could_not_be_checked_waits.py.
"""

from __future__ import annotations

import asyncio
import errno
import sys
from pathlib import Path
from typing import Any

import pytest

from tests import hand_in_hold_support as support
from thomas.forge.anvil import forge_code_store
from thomas.server import (
    autopilot_hold_tick,
    autopilot_restart,
    capacity_ledger,
    chat_offers,  # noqa: F401 -- provides seams.FOLLOW_AFTER_RESTART
    hand_in_hold,
    precard,
    self_change_status,
    thomas_project,
)
from thomas.server.app_keys import APP_LOCAL_PORT
from thomas.server.landed_code_reload import APP_LANDED_CODE_DRAIN
from thomas.server.routes import evolve_agent_autopilot as route

_REAL_LISTENER_PROBE = autopilot_hold_tick._previous_listener_gone


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> support.Project:
    return support.make_project(tmp_path, monkeypatch)


@pytest.fixture(autouse=True)
def _own_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Use an isolated ledger and never probe host listeners except in explicit listener tests."""
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))
    monkeypatch.setattr(autopilot_hold_tick, "_previous_listener_gone", lambda _port: False)


def _no_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(autopilot_restart, "_runners_of", lambda _cid: ([], []))
    monkeypatch.setattr(self_change_status, "being_handed_in", lambda _cid: False)


def test_a_living_other_server_keeps_its_check_claim(project: support.Project) -> None:
    _work, catalog, cid = project
    booked = support.book(project)
    with hand_in_hold.check_claim(catalog, cid) as acquired:
        assert acquired and not hand_in_hold.claim_free(catalog, cid)
        assert support.tick(project) == [] and support.row(project) == booked
    assert hand_in_hold.claim_free(catalog, cid)


def test_initial_hand_in_waits_for_another_servers_check_claim(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another server booked the turn and holds the check's claim: this server holds the row with no strike, due in
    900 s, and that server's own try stands down at its next test, because the row is no longer checking."""
    work, catalog, cid = project
    gen = support.book(project)["gen"]
    settle = thomas_project.settle_if_finished

    def check_while_this_server_tries(_eid: str) -> precard.Checked:
        asyncio.run(route._settle_thomas_project(work, catalog, cid))  # this server's try, during the other's check
        return precard.Checked(precard.PASSED, "tests passed", patch="patch")

    monkeypatch.setattr(thomas_project, "settle_if_finished", lambda *_a, **_k: pytest.fail("parallel check"))
    monkeypatch.setattr(thomas_project.green_handoff, "size_problems", lambda _eid: [])
    monkeypatch.setattr(precard.review, "held_check", lambda _eid: None)
    monkeypatch.setattr(precard, "check_for_hand_in", check_while_this_server_tries)
    monkeypatch.setattr(precard.review, "second_look", lambda *_a: pytest.fail("a held change was reviewed"))
    monkeypatch.setattr(thomas_project.green_handoff, "settle", lambda *_a, **_k: pytest.fail("handed in"))
    with hand_in_hold.check_claim(catalog, cid) as acquired:
        assert acquired
        assert settle(work, catalog, cid, expected_gen=gen) is None, "the other server's try stands down"
    held = support.row(project)
    assert (held["state"], held["tries"], held["strikes"]) == ("held", 1, 0)
    assert held["next_at"] > hand_in_hold.clock() + hand_in_hold.RETRY_S / 2, "tried again when due"
    assert thomas_project.settled_record(catalog, cid) is None


@pytest.mark.parametrize(
    ("exc", "step", "strikes"),
    [
        (precard.ReviewUnavailable("your Claude plan's usage limit is reached"), "second look", 0),
        (precard.CheckUnavailable("Not checked before this card: no interpreter", costly=True), "check", 1),
        (precard.CheckUnavailable("Not checked before this card: the drive has 1 GB free", costly=False), "check", 0),
    ],
)
def test_the_first_try_is_booked_and_an_unavailable_step_holds_it(
    project: support.Project, monkeypatch: pytest.MonkeyPatch, exc: Exception, step: str, strikes: int
) -> None:
    work, catalog, cid = project

    def unavailable(*_args: Any, **_kwargs: Any) -> None:
        assert support.row(project)["state"] == "checking", "the try is booked before the check starts"
        raise exc

    monkeypatch.setattr(thomas_project, "settle_if_finished", unavailable)
    asyncio.run(route._settle_thomas_project(work, catalog, cid, app={APP_LOCAL_PORT: 8899}))
    held = support.row(project)
    assert (held["state"], held["step"], held["tries"], held["strikes"]) == ("held", step, 1, strikes)
    assert held["why"] == str(exc) and not self_change_status.being_handed_in(cid)


def test_booking_failure_never_calls_settle(project: support.Project, monkeypatch: pytest.MonkeyPatch) -> None:
    work, catalog, cid = project
    monkeypatch.setattr(hand_in_hold, "book", lambda *_a, **_k: None)
    monkeypatch.setattr(thomas_project, "settle_if_finished", lambda *_a, **_k: pytest.fail("unbooked hand-in"))
    asyncio.run(route._settle_thomas_project(work, catalog, cid, app={APP_LOCAL_PORT: 8899}))
    assert not self_change_status.being_handed_in(cid) and support.row(project) is None


def test_a_due_hold_is_retried_once_on_the_same_turn(project: support.Project, monkeypatch: pytest.MonkeyPatch) -> None:
    work, catalog, cid = project
    scheduled: list[dict[str, Any]] = []
    _no_runner(monkeypatch)
    monkeypatch.setattr(autopilot_hold_tick, "_previous_listener_gone", lambda _port: False)
    monkeypatch.setattr(autopilot_hold_tick, "_schedule", lambda _app, held, _catalog: scheduled.append(held) or True)
    support.book(project)
    held = hand_in_hold.hold(work, catalog, cid, "check", "temporarily offline", costly=False)
    assert held is not None
    support.due(project)
    assert support.tick(project, port=8898) == []  # another server's port cannot take this hold
    assert support.tick(project) == [cid]
    retried = support.row(project)
    assert retried is not None and retried == scheduled[0]
    assert (retried["state"], retried["tries"], retried["strikes"]) == ("checking", 2, 0)
    assert (retried["gen"], retried["step"], retried["why"]) == (held["gen"], "check", "temporarily offline")
    assert support.tick(project) == [] and len(scheduled) == 1  # not due again: no second try at once
    assert hand_in_hold.phase(work, catalog, cid)[0] == "waiting"


def test_live_runner_defers_a_due_hold_without_consuming_an_attempt(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, catalog, cid = project
    monkeypatch.setattr(autopilot_restart, "_runners_of", lambda _cid: (["still-running"], []))
    monkeypatch.setattr(self_change_status, "being_handed_in", lambda _cid: False)
    monkeypatch.setattr(autopilot_hold_tick, "_schedule", lambda *_args: pytest.fail("live runner was checked over"))
    support.book(project)
    hand_in_hold.hold(work, catalog, cid, "check", "no checker", costly=False)
    support.due(project)
    before = support.row(project)
    assert support.tick(project) == [] and support.row(project) == before


def test_stop_discards_a_due_hold_without_rechecking(project: support.Project, monkeypatch: pytest.MonkeyPatch) -> None:
    work, catalog, cid = project
    old = support.book(project)
    hand_in_hold.hold(work, catalog, cid, "check", "no interpreter", costly=False)
    monkeypatch.setattr(hand_in_hold, "clock", lambda: old["next_at"] + 1)
    monkeypatch.setattr(autopilot_restart, "_runners_of", lambda _cid: ([], []))
    monkeypatch.setattr(autopilot_hold_tick, "_schedule", lambda *_args: pytest.fail("stopped change was retried"))
    monkeypatch.setattr(thomas_project, "stop_requested", lambda _conversation: True)
    monkeypatch.setattr(hand_in_hold, "still_current", lambda *_args, **_kwargs: False)
    assert asyncio.run(autopilot_hold_tick.tick({APP_LOCAL_PORT: 8899}, catalog)) == []
    assert support.row(project) is None


def test_a_queued_steer_survives_a_refused_start(project: support.Project, monkeypatch: pytest.MonkeyPatch) -> None:
    _work, catalog, cid = project
    support.book(project)
    thomas_project.hold_steer(cid, "change the requested behavior")
    monkeypatch.setattr(hand_in_hold, "still_current", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(autopilot_restart, "_runners_of", lambda _cid: ([], []))

    async def refused(_app: Any, _root: Path, _catalog: Path, _cid: str) -> None:
        return None

    monkeypatch.setattr(autopilot_hold_tick, "_steered", refused)
    try:
        assert asyncio.run(autopilot_hold_tick.tick({APP_LOCAL_PORT: 8899}, catalog)) == []
        assert support.row(project) is not None
        assert thomas_project.held_steers(cid) == ["change the requested behavior"]
    finally:
        thomas_project.drop_steers(cid, 1)


def test_a_steer_that_supersedes_a_hold_starts_its_run_and_removes_the_hold(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    _work, catalog, cid = project
    support.book(project)
    thomas_project.hold_steer(cid, "change the requested behavior")
    monkeypatch.setattr(hand_in_hold, "still_current", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(autopilot_restart, "_runners_of", lambda _cid: ([], []))
    started: list[str] = []

    async def start(_app: Any, _conversation: dict[str, Any], conversation_id: str, catalog_root: Path) -> None:
        assert catalog_root == catalog
        started.append(conversation_id)
        thomas_project.drop_steers(conversation_id, 1)  # the run took your steer

    monkeypatch.setattr(route, "_start_steered_round", start)
    try:
        assert asyncio.run(autopilot_hold_tick.tick({APP_LOCAL_PORT: 8899}, catalog)) == []
        assert started == [cid] and support.row(project) is None
    finally:
        thomas_project.drop_steers(cid, len(thomas_project.held_steers(cid)))


def test_chat_follow_only_runs_for_a_distinct_chat(project: support.Project, monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.server import chat_self_project

    booked = support.book(project)
    calls: list[tuple[Any, ...]] = []

    async def follow(*args: Any, **kwargs: Any) -> None:
        calls.append((*args, kwargs))

    monkeypatch.setattr(chat_self_project, "follow_after_restart", follow)
    asyncio.run(autopilot_hold_tick._follow({}, booked, project[1]))
    assert len(calls) == 1
    assert calls[0][1:5] == (project[2], project[0], project[1], "chat-1") and "waits" in calls[0][5]["text"]
    asyncio.run(autopilot_hold_tick._follow({}, {**booked, "chat": project[2]}, project[1]))
    assert len(calls) == 1


def test_check_exception_during_retry_retains_a_hold_not_an_approval(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, catalog, cid = project
    support.book(project)
    old = hand_in_hold.hold(work, catalog, cid, "second look", "reader offline", costly=False)
    assert old is not None
    checking = {**old, "state": "checking", "tries": 2}
    assert hand_in_hold.change(catalog, cid, old["gen"], checking, expected=old)
    monkeypatch.setattr(autopilot_hold_tick, "_space_available", lambda _root: True)

    async def fail(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("retry crashed")

    monkeypatch.setattr(route, "_settle_thomas_project", fail)
    asyncio.run(autopilot_hold_tick._check({APP_LOCAL_PORT: 8899}, checking, catalog))
    held = support.row(project)
    assert held is not None and held["state"] == "held"
    assert held["step"] == "check" and "retry crashed" in held["why"]
    assert forge_code_store.load_conversation(work, cid)["thomas_project"].get("settled_at") is None


def test_reload_drain_does_not_start_or_spend_a_held_check(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    booked = support.book(project)
    _no_runner(monkeypatch)
    catalog, cid = project[1], project[2]
    app = {APP_LOCAL_PORT: 8899, APP_LANDED_CODE_DRAIN: True}
    monkeypatch.setattr(autopilot_hold_tick, "_schedule", lambda *_args: pytest.fail("check started during drain"))
    for _ in range(hand_in_hold.MAX_TRIES + 1):
        assert asyncio.run(autopilot_hold_tick.tick(app, catalog)) == []
    assert support.row(project) == booked

    # A task scheduled just before the drain must defer its booked try, too.
    checking = {**booked, "state": "checking", "tries": 1}
    assert hand_in_hold.change(catalog, cid, booked["gen"], checking, expected=booked)
    asyncio.run(autopilot_hold_tick._check(app, checking, catalog))
    row = support.row(project)
    assert row is not None and row["state"] == "held" and row["tries"] == 0


def test_restart_retries_held_checks_booked_on_an_abandoned_port(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_runner(monkeypatch)
    monkeypatch.setattr(autopilot_hold_tick, "_previous_listener_gone", lambda port: port == 8899, raising=False)
    monkeypatch.setattr(autopilot_hold_tick, "_schedule", lambda *_args: True)
    booked = support.book(project)
    assert booked["port"] == 8899
    held = hand_in_hold.hold(project[0], project[1], project[2], "check", "temporarily offline", costly=False)
    assert held is not None
    support.due(project)
    assert support.tick(project, port=8898) == [project[2]]
    row = support.row(project)
    assert (row["state"], row["port"], row["tries"]) == ("checking", 8898, 2)


def test_restart_does_not_lose_its_tick_when_listener_probe_is_unavailable(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_runner(monkeypatch)
    booked = support.book(project)
    assert hand_in_hold.hold(project[0], project[1], project[2], "check", "temporarily offline", costly=False)
    support.due(project)
    before = support.row(project)
    monkeypatch.setitem(sys.modules, "psutil", None)

    def unavailable(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("listener probe unavailable")

    original_socket = autopilot_hold_tick.socket.socket

    def probe_socket(*args: Any, **kwargs: Any) -> Any:
        if len(args) > 2 and args[2] and "fileno" not in kwargs:
            return unavailable()
        return original_socket(*args, **kwargs)

    with monkeypatch.context() as probe_patch:
        probe_patch.setattr(autopilot_hold_tick.socket, "socket", probe_socket)
        assert autopilot_hold_tick._previous_listener_gone(8899) is False
    monkeypatch.setattr(autopilot_hold_tick, "_previous_listener_gone", lambda _port: False)
    assert support.tick(project, port=8898) == []
    assert support.row(project) == before
    assert booked["port"] == 8899


def test_restart_retries_without_optional_psutil_when_old_port_refuses(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_runner(monkeypatch)
    monkeypatch.setitem(sys.modules, "psutil", None)

    class RefusedSocket:
        def __enter__(self) -> RefusedSocket:
            return self

        def __exit__(self, *_args: Any) -> None:
            pass

        def settimeout(self, _timeout: float) -> None:
            pass

        def connect(self, _address: Any) -> None:
            raise ConnectionRefusedError(errno.ECONNREFUSED, "old listener exited")

    original_socket = autopilot_hold_tick.socket.socket

    def probe_socket(*args: Any, **kwargs: Any) -> Any:
        if len(args) > 2 and args[2] and "fileno" not in kwargs:
            return RefusedSocket()
        return original_socket(*args, **kwargs)

    monkeypatch.setattr(autopilot_hold_tick, "_schedule", lambda *_args: True)
    support.book(project)
    assert hand_in_hold.hold(project[0], project[1], project[2], "check", "temporarily offline", costly=False)
    support.due(project)
    with monkeypatch.context() as probe_patch:
        probe_patch.setattr(autopilot_hold_tick.socket, "socket", probe_socket)
        listener_gone = _REAL_LISTENER_PROBE(8899)
    assert listener_gone is True
    # Restore the real socket constructor before asyncio.run creates its event loop.
    monkeypatch.setattr(autopilot_hold_tick, "_previous_listener_gone", lambda _port: listener_gone)
    assert support.tick(project, port=8898) == [project[2]]
    assert support.row(project)["port"] == 8898


def test_restart_leaves_held_checks_on_a_living_other_listener(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_runner(monkeypatch)
    monkeypatch.setattr(autopilot_hold_tick, "_previous_listener_gone", lambda _port: False)
    booked = support.book(project)
    held = hand_in_hold.hold(project[0], project[1], project[2], "check", "temporarily offline", costly=False)
    assert held is not None
    support.due(project)
    before = support.row(project)
    assert support.tick(project, port=8898) == []
    assert support.row(project) == before
    assert booked["port"] == 8899


def test_restart_reclaims_interrupted_check_on_an_abandoned_port(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_runner(monkeypatch)
    monkeypatch.setattr(autopilot_hold_tick, "_previous_listener_gone", lambda _port: True)
    booked = support.book(project)
    assert support.tick(project, port=8898) == []
    held = support.row(project)
    assert held is not None
    assert (held["state"], held["port"], held["tries"]) == ("held", 8898, 1)
    support.due(project)
    monkeypatch.setattr(autopilot_hold_tick, "_schedule", lambda *_args: True)
    assert support.tick(project, port=8898) == [project[2]]
    assert support.row(project)["tries"] == 2
    assert booked["port"] == 8899


def test_restart_rechecks_on_the_original_listener_and_follows_chat_once(
    project: support.Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thomas.server import chat_self_project

    support.book(project)
    _no_runner(monkeypatch)
    monkeypatch.setattr(autopilot_hold_tick, "_previous_listener_gone", lambda _port: False)
    followed: list[str] = []

    async def follow(_app: Any, _cid: str, _root: Path, _catalog: Path, chat: str, *, text: str) -> None:
        followed.append(chat)

    monkeypatch.setattr(chat_self_project, "follow_after_restart", follow)
    monkeypatch.setattr(autopilot_hold_tick, "_schedule", lambda *_args: True)
    assert support.tick(project, port=8898) == [] and support.row(project)["state"] == "checking"
    assert support.tick(project) == [] and support.row(project)["state"] == "held"
    assert followed == ["chat-1"]
    support.due(project)
    assert support.tick(project) == [project[2]] and support.row(project)["tries"] == 2
    assert followed == ["chat-1"]
