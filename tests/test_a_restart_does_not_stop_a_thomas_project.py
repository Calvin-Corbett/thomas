"""A restart does not stop a Thomas project: the run the server was doing carries on by itself, once.

A restart carries work on once without another message from you or replacing the original goal.
Build's start hook and Chat's stream are stubbed; unrelated services and process probes are isolated.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest

from tests.drain_recovery_fixture import restart_isolated as isolated  # noqa: F401
from tests.drain_recovery_fixture import runner_scan as runner_scan
from tests.restart_test_isolation import immediate_restart_retries, tmp_path_factory  # noqa: F401
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings
from thomas.server import (
    autopilot_park,
    autopilot_silence,
    green_checkout,
    green_handoff,
    thomas_project,
)
from thomas.server.app_keys import APP_LOCAL_PORT
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.routes import evolve_agent_autopilot as ap
from thomas.server.routes.autopilot_goal import instructions
from thomas.server.routes.evolve_agent_receipts import _action_receipt, _save_action_receipt
from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS

GOAL = "Remove the marketplace modules nothing calls"
FINDINGS = "tests/test_registry.py fails on dev's tip: thomas/tools/registry.py still imports marketplace.junk_sweep"
AGO = 20 * 60  # the stopped run started 20 minutes before the server did
FIRST_RUN = dict(model="claude-opus", transcript='{"fc":"tool","name":"check.run","input":{}}\n', changed_files=["thomas/marketplace/junk_sweep.py"], returncode=0,
                 ok=True, noop=False, reason="1 file(s) changed", outcome="completed", report={"open_risks": []})  # fmt: skip
REPLIED = {
    **FIRST_RUN,
    "changed_files": [],
    "transcript": '{"fc":"say","source":"model","text":"Checked the requested changes."}\n',
    "reason": "Thomas replied without changing files",
    "outcome": "conversation",
}
FAILED = {**FIRST_RUN, "ok": False, "returncode": 1, "outcome": "failed", "reason": "the run crashed before finishing"}


def _restart() -> Any:
    """Imported where used: before this change it did not exist, and each test must fail on its own assertion."""
    from thomas.server import autopilot_restart

    return autopilot_restart


def _iso(moment: float) -> str:
    return datetime.fromtimestamp(moment, timezone.utc).isoformat()


def _repair_due() -> dict[str, Any]:
    return {"round": 1, "why": thomas_project.SENT_BACK, "detail": FINDINGS, "dev": "5d9249e0", "sid": "self-t-1"}


def _stopped_run(tmp_path: Path, *, kind: str = "repair", autonomy: int = ap.AUTOPILOT, thomas: bool = True,
                 ago: float = AGO, state: str | None = "running") -> SimpleNamespace:  # fmt: skip
    """A project whose last run the server before was doing when it stopped: its start is recorded, its end is not.

    ``kind``: the stopped run was a repair round sent back with findings ("repair"), a done check ("review"), or
    your request itself, never answered ("request"). Build's run receipt for it says ``state``.
    """
    catalog, root = tmp_path / "catalog", tmp_path / "green-work"
    catalog.mkdir(parents=True)
    root.mkdir(parents=True)
    record = {"execution_id": "thomas-0123456789ab"} if thomas else None
    conversation = forge_code_store.draft_conversation(title="junk sweep", thomas_project=record)
    cid = conversation["id"]
    conversation["turns"] = [{"role": "user", "text": GOAL}]
    if kind != "request":
        conversation["turns"].append({"role": "agent", "model": "test", **FIRST_RUN})
    text = {"repair": ap.repair_message(GOAL, _repair_due()), "request": GOAL}.get(kind, "")
    text = text or ap.review_message(GOAL, FIRST_RUN, "medium")
    conversation["turns"].append(
        {"role": "user", "text": text, "request_id": "request-before", "request_fingerprint": "f"}
    )
    booted = time.time()
    for n, turn in enumerate(conversation["turns"]):  # yours two hours ago, the stopped run's start ``ago``
        turn["ts"] = _iso(booted - ago if n == len(conversation["turns"]) - 1 else booted - 7200 + 60 * n)
    if kind == "repair" and thomas:
        conversation["thomas_project"]["repairs"] = [{**_repair_due(), "at": _iso(booted - ago - 60)}]
    forge_code_store.write_conversation(root, conversation)
    settings = ForgeCodeSettings.from_payload(
        {"model": "claude:sonnet", "autonomy_level": autonomy}
    ).capability_report()
    from thomas.forge.anvil.forge_code_conversations import _load_registry, _write_registry

    registry = _load_registry(catalog)
    registry[cid] = {"project_root": str(root), "settings": settings}
    _write_registry(catalog, registry)
    if state:  # None: no receipt in this server's data, as for a run another server started
        _save_action_receipt(catalog, "run", "request-before", {"state": state, "response": {"run_id": "run-before"}})
    return SimpleNamespace(catalog=catalog, root=root, cid=cid, booted=booted)


def _app(catalog: Path, starts: list[dict[str, Any]]) -> dict[Any, Any]:
    async def start(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        starts.append(body)
        cid, request_id, run_id = body["conversation_id"], f"request-{len(starts)}", f"run-{len(starts)}"
        root = Path(body.get("project_root") or forge_code_projects.conversation_metadata(catalog, cid)["project_root"])
        # What the start route does with it: the message as the run's user turn, and Build's receipt for the run.
        _save_action_receipt(catalog, "run", request_id, {"state": "running", "response": {"run_id": run_id}})
        forge_code_store.append_user_turn(root, cid, body["message"], request_id=request_id, request_fingerprint="f")
        return 200, {"ok": True, "conversation_id": cid, "run_id": run_id}

    return {APP_PRAXIS_START_CODE_RUN: start, APP_LOCAL_PORT: 8898}


def _joined(p: SimpleNamespace) -> dict[str, Any]:
    return ap._load_joined_conversation(p.root, p.catalog, p.cid)


class _RecoveredChannels:
    """Praxis's run channels, holding the one its startup recovery reopened for the stopped run."""

    def __init__(self) -> None:
        self._runs, self.closed = {"run-before": object()}, []

    async def close(self, run_id: str) -> None:
        self.closed.append(run_id)
        self._runs.pop(run_id, None)


@pytest.mark.asyncio
async def test_a_stopped_repair_round_carries_on_once_with_its_goal_and_its_findings(tmp_path: Path) -> None:
    p = _stopped_run(tmp_path, kind="repair")
    channels = _RecoveredChannels()
    app = {**_app(p.catalog, starts := []), "praxis_run_channels": channels}

    report = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)

    assert report["resumed"] == [p.cid] and len(starts) == 1
    message = starts[0]["message"]
    assert message.startswith(ap.RESTART_PREFIX) and message.startswith(ap.CONTINUATION_PREFIX)
    assert "Thomas's server restarted" in message and "picks up where it stopped" in message
    assert FINDINGS in message and ap.repair_message(GOAL, _repair_due()) in message, "the round, in full"
    turns = forge_code_store.load_conversation(p.root, p.cid)["turns"]
    assert ap._goal(turns) == GOAL, "the goal is still your request"
    assert ap._continuation_count(turns) == 0, "a restart is not a retry"
    assert thomas_project.repair_due(_joined(p)) is None, "and not a second repair round"
    assert channels.closed == ["run-before"], "the old run's recovered helpers do not work beside the new run"
    again = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)
    assert again["resumed"] == [] and len(starts) == 1, "once per interruption"
    forge_code_store.append_agent_turn(p.root, p.cid, **FAILED)  # the resumed run dies: Autopilot's own rules
    decision = ap.decide(_joined(p))
    assert decision.action == "continue" and GOAL in decision.message and ap.RESTART_PREFIX not in decision.message
    assert (await _restart().resume_interrupted(app, p.catalog, booted=p.booted))["resumed"] == []


@pytest.mark.asyncio
async def test_steered_run_refused_during_drain_starts_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = _stopped_run(tmp_path)
    forge_code_store.append_agent_turn(p.root, p.cid, **FIRST_RUN)
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    conversation["turns"][-1]["ts"] = _iso(p.booted - 10)
    forge_code_store.write_conversation(p.root, conversation)
    _save_action_receipt(
        p.catalog, "run", "request-before", {"state": "completed", "response": {"run_id": "run-before"}}
    )
    thomas_project.hold_steer(p.cid, "Apply the new direction")
    starts = []
    app = _app(p.catalog, starts)

    async def draining(_body, *, port):
        assert port == 8898
        return 503, {"code": "reload_draining"}

    app[APP_PRAXIS_START_CODE_RUN] = draining
    await ap._start_steered_round(app, _joined(p), p.cid, p.catalog)
    assert _action_receipt(p.catalog, "run", "request-before")["state"] == "after_run_pending"
    assert thomas_project.held_steers(p.cid)
    monkeypatch.setattr(_restart(), "_runners_of", lambda _cid: ([], []))
    report = await _restart().resume_interrupted(_app(p.catalog, starts), p.catalog, booted=p.booted)
    assert report["resumed"] == [p.cid]
    assert len(starts) == 1 and "Apply the new direction" in starts[0]["message"]
    assert not thomas_project.held_steers(p.cid)


@pytest.mark.asyncio
async def test_non_autopilot_build_yielded_for_reload_carries_on(tmp_path: Path, monkeypatch) -> None:
    p = _stopped_run(tmp_path, autonomy=2, state="reload_yielded")
    forge_code_store.append_agent_turn(
        p.root, p.cid, **{**FAILED, "outcome": "reload_yielded", "reason": "Build yielded for landed-code reload"}
    )
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    conversation["turns"][-1]["ts"] = _iso(p.booted - 10)
    forge_code_store.write_conversation(p.root, conversation)
    app = _app(p.catalog, starts := [])
    monkeypatch.setattr(_restart(), "_runners_of", lambda _cid: ([], []))

    report = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)
    assert report["resumed"] == [p.cid]
    assert len(starts) == 1 and starts[0]["message"].startswith(ap.RESTART_PREFIX)
    assert (await _restart().resume_interrupted(app, p.catalog, booted=p.booted))["resumed"] == []


@pytest.mark.asyncio
async def test_finished_during_drain_decides_after_restart_without_rerunning_build(tmp_path: Path, monkeypatch) -> None:
    from thomas.server.landed_code_reload import APP_LANDED_CODE_DRAIN
    from thomas.server.routes.evolve_agent_receipts import _action_receipt

    p = _stopped_run(tmp_path, kind="repair", state="completed")
    user = forge_code_store.load_conversation(p.root, p.cid)["turns"][-1]
    forge_code_store.append_agent_turn(p.root, p.cid, **FAILED)
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    conversation["turns"][-1]["ts"] = _iso(p.booted - 10)
    forge_code_store.write_conversation(p.root, conversation)
    app = {**_app(p.catalog, starts := []), APP_LANDED_CODE_DRAIN: {"head": "new"}}

    async def finished():
        return None

    task = asyncio.create_task(finished())
    await task
    ap.attach_after_run(app, task, p.root, p.catalog, p.cid)
    await asyncio.sleep(0)
    assert _action_receipt(p.catalog, "run", user["request_id"])["state"] == "after_run_pending"
    app.pop(APP_LANDED_CODE_DRAIN)
    monkeypatch.setattr(_restart(), "_runners_of", lambda _cid: ([], []))
    report = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)
    assert report["resumed"] == [p.cid], report
    assert len(starts) == 1 and FINDINGS in starts[0]["message"]
    assert not starts[0]["message"].startswith(ap.RESTART_PREFIX)
    assert _action_receipt(p.catalog, "run", user["request_id"])["state"] == "finished"
    assert (await _restart().resume_interrupted(app, p.catalog, booted=p.booted))["resumed"] == []
    assert len(starts) == 1


@pytest.mark.asyncio
async def test_level_four_finished_during_drain_settles_after_restart(tmp_path: Path, monkeypatch) -> None:
    from thomas.server.landed_code_reload import APP_LANDED_CODE_DRAIN

    p = _stopped_run(tmp_path, kind="request", autonomy=4, state="completed")
    user = forge_code_store.load_conversation(p.root, p.cid)["turns"][-1]
    forge_code_store.append_agent_turn(p.root, p.cid, **FIRST_RUN)
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    conversation["turns"][-1]["ts"] = _iso(p.booted - 10)
    forge_code_store.write_conversation(p.root, conversation)
    app = {**_app(p.catalog, starts := []), APP_LANDED_CODE_DRAIN: {"head": "new"}}

    task = asyncio.create_task(asyncio.sleep(0))
    await task
    ap.attach_after_run(app, task, p.root, p.catalog, p.cid)
    await asyncio.sleep(0)
    assert _action_receipt(p.catalog, "run", user["request_id"])["state"] == "after_run_pending"
    app.pop(APP_LANDED_CODE_DRAIN)
    monkeypatch.setattr(_restart(), "_runners_of", lambda _cid: ([], []))
    settled = []

    async def settle(project_root, catalog_root, cid, *, app=None, gen=None):
        settled.append((project_root, catalog_root, cid))

    monkeypatch.setattr(ap, "_settle_thomas_project", settle)
    report = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)
    assert report["resumed"] == [p.cid], report
    assert settled == [(p.root, p.catalog, p.cid)]
    assert starts == [], "the completed Build must not run again"
    assert _action_receipt(p.catalog, "run", user["request_id"])["state"] == "finished"


@pytest.mark.asyncio
async def test_repair_refused_during_drain_starts_after_restart(tmp_path: Path, monkeypatch) -> None:
    from thomas.server.routes.evolve_agent_receipts import _action_receipt, _save_action_receipt

    p = _stopped_run(tmp_path, kind="repair", state="completed")
    user = forge_code_store.load_conversation(p.root, p.cid)["turns"][-1]
    forge_code_store.append_agent_turn(p.root, p.cid, **FAILED)
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    conversation["turns"][-1]["ts"] = _iso(p.booted - 10)
    forge_code_store.write_conversation(p.root, conversation)
    receipt = _action_receipt(p.catalog, "run", user["request_id"])
    _save_action_receipt(p.catalog, "run", user["request_id"], {**receipt, "state": "completed"})
    starts = []

    async def refused(body, *, port):
        starts.append(body)
        return 503, {"ok": False, "code": "reload_draining"}

    app = {APP_PRAXIS_START_CODE_RUN: refused, APP_LOCAL_PORT: 8898}
    decision = await ap.start_repair(app, p.root, p.catalog, p.cid, why=thomas_project.SENT_BACK, detail=FINDINGS)
    assert decision is not None and decision.action == "repair"
    assert len(starts) == 1
    assert _action_receipt(p.catalog, "run", user["request_id"])["state"] == "after_run_pending"
    saved = forge_code_store.load_conversation(p.root, p.cid)
    assert saved["turns"][-1]["role"] == "agent" and saved["turns"][-1]["outcome"] != "reload_yielded"
    monkeypatch.setattr(_restart(), "_runners_of", lambda _cid: ([], []))
    report = await _restart().resume_interrupted(_app(p.catalog, recovered := []), p.catalog, booted=p.booted)
    assert report["resumed"] == [p.cid] and len(recovered) == 1
    assert FINDINGS in recovered[0]["message"]
    assert _action_receipt(p.catalog, "run", user["request_id"])["state"] == "finished"
    assert (await _restart().resume_interrupted(_app(p.catalog, recovered), p.catalog, booted=p.booted))[
        "resumed"
    ] == []
    assert len(recovered) == 1


@pytest.mark.asyncio
async def test_pending_drain_handoff_survives_a_failed_continuation_attempt(tmp_path: Path, monkeypatch) -> None:
    from thomas.server.routes.evolve_agent_receipts import _action_receipt, _save_action_receipt

    p = _stopped_run(tmp_path, kind="repair", state="completed")
    user = forge_code_store.load_conversation(p.root, p.cid)["turns"][-1]
    forge_code_store.append_agent_turn(p.root, p.cid, **FAILED)
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    conversation["turns"][-1]["ts"] = _iso(p.booted - 10)
    forge_code_store.write_conversation(p.root, conversation)
    receipt = _action_receipt(p.catalog, "run", user["request_id"])
    _save_action_receipt(p.catalog, "run", user["request_id"], {**receipt, "state": "after_run_pending"})
    app = _app(p.catalog, starts := [])
    monkeypatch.setattr(_restart(), "_runners_of", lambda _cid: ([], []))
    original = ap.after_run
    attempts = 0

    async def temporarily_unavailable(*args):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return None
        return await original(*args)

    monkeypatch.setattr(ap, "after_run", temporarily_unavailable)
    first = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)
    assert first["resumed"] == []
    assert _action_receipt(p.catalog, "run", user["request_id"])["state"] == "after_run_pending"
    second = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)
    assert second["resumed"] == [p.cid] and len(starts) == 1
    assert _action_receipt(p.catalog, "run", user["request_id"])["state"] == "finished"


@pytest.mark.asyncio
async def test_a_recorded_reload_yield_carries_on_once_but_a_failed_recording_does_not(tmp_path: Path) -> None:
    p = _stopped_run(tmp_path, kind="repair")
    forge_code_store.append_agent_turn(
        p.root,
        p.cid,
        model="test",
        transcript="Build yielded for reload",
        changed_files=[],
        returncode=75,
        ok=False,
        noop=False,
        reason="Build yielded for reload",
        outcome="reload_yielded",
    )
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    last_user = next(turn for turn in reversed(conversation["turns"]) if turn["role"] == "user")
    _save_action_receipt(
        p.catalog, "run", last_user["request_id"], {"state": "reload_yielded", "response": {"run_id": "run-before"}}
    )
    app = _app(p.catalog, starts := [])

    report = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)
    assert report["resumed"] == [p.cid] and len(starts) == 1
    assert FINDINGS in starts[0]["message"]
    assert (await _restart().resume_interrupted(app, p.catalog, booted=p.booted))["resumed"] == []

    p2 = _stopped_run(tmp_path / "other", kind="repair")
    forge_code_store.append_agent_turn(
        p2.root,
        p2.cid,
        model="test",
        transcript="Build yielded for reload",
        changed_files=[],
        returncode=75,
        ok=False,
        noop=False,
        reason="Build yielded for reload",
        outcome="reload_yielded",
    )
    conversation2 = forge_code_store.load_conversation(p2.root, p2.cid)
    last_user2 = next(turn for turn in reversed(conversation2["turns"]) if turn["role"] == "user")
    _save_action_receipt(p2.catalog, "run", last_user2["request_id"], {"state": "persistence_failed"})
    app2 = _app(p2.catalog, starts2 := [])
    report2 = await _restart().resume_interrupted(app2, p2.catalog, booted=p2.booted)
    assert report2["resumed"] == [] and starts2 == []


@pytest.mark.asyncio
async def test_non_autopilot_reload_yield_carries_on_after_restart(tmp_path: Path) -> None:
    p = _stopped_run(tmp_path, kind="first", autonomy=2)
    forge_code_store.append_agent_turn(
        p.root,
        p.cid,
        model="test",
        transcript="Build yielded for reload",
        changed_files=[],
        returncode=75,
        ok=False,
        noop=False,
        reason="Build yielded for reload",
        outcome="reload_yielded",
    )
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    user = next(turn for turn in reversed(conversation["turns"]) if turn["role"] == "user")
    _save_action_receipt(
        p.catalog, "run", user["request_id"], {"state": "reload_yielded", "response": {"run_id": "run-before"}}
    )
    app = _app(p.catalog, starts := [])
    report = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)
    assert report["resumed"] == [p.cid] and len(starts) == 1
    assert starts[0]["message"].startswith(ap.RESTART_PREFIX)
    assert (await _restart().resume_interrupted(app, p.catalog, booted=p.booted))["resumed"] == []


@pytest.mark.asyncio
async def test_a_stopped_done_check_is_still_the_done_check_once_it_carries_on(tmp_path: Path) -> None:
    p = _stopped_run(tmp_path, kind="review")
    app = _app(p.catalog, starts := [])

    assert (await _restart().resume_interrupted(app, p.catalog, booted=p.booted))["resumed"] == [p.cid]
    forge_code_store.append_agent_turn(p.root, p.cid, **REPLIED)  # it met the bar and changed nothing

    assert ap.review_message(GOAL, FIRST_RUN, "medium") in starts[0]["message"]
    assert ap.decide(_joined(p)).action == "done", "not a second done check"


@pytest.mark.asyncio
async def test_an_ordinary_build_on_autopilot_carries_on_the_same_way(tmp_path: Path) -> None:
    p = _stopped_run(tmp_path, kind="request", thomas=False)
    app = _app(p.catalog, starts := [])

    assert (await _restart().resume_interrupted(app, p.catalog, booted=p.booted))["resumed"] == [p.cid]

    assert starts[0]["message"].startswith(ap.RESTART_PREFIX) and starts[0]["message"].endswith(GOAL)
    assert instructions(forge_code_store.load_conversation(p.root, p.cid)["turns"])[-1] == GOAL


def _handed_in(p: SimpleNamespace, app: dict) -> None:
    forge_code_store.write_conversation(p.catalog, forge_code_store.load_conversation(p.root, p.cid))


def _stopped_by_you(p: SimpleNamespace, app: dict) -> None:
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    conversation["thomas_project"]["stopped_at"] = _iso(p.booted - 60)
    forge_code_store.write_conversation(p.root, conversation)


def _parked(p: SimpleNamespace, app: dict) -> None:
    autopilot_park.park(p.root, p.catalog, p.cid, until=p.booted + 3600, provider="ChatGPT Pro", port=8898)


def _going_again(p: SimpleNamespace, app: dict) -> None:
    app[APP_EVOLVE_AGENT_RUNS] = {p.cid: {"session": {"proc": SimpleNamespace(returncode=None)}}}


def _three_restarts(p: SimpleNamespace, app: dict) -> None:
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    for n in range(3):  # three servers in a row carried it on, and each stopped before any run finished
        text = ap.restart_message(GOAL, ap.repair_message(GOAL, _repair_due()))
        at, request_id = _iso(p.booted - AGO + 60 * (n + 1)), f"request-restart-{n}"
        conversation["turns"].append({"role": "user", "text": text, "ts": at, "request_id": request_id})
        _save_action_receipt(p.catalog, "run", request_id, {"state": "running", "response": {"run_id": f"r{n}"}})
    forge_code_store.write_conversation(p.root, conversation)


def _left_waiting_by_the_restart_before(p: SimpleNamespace, app: dict) -> None:
    """The server before started after this run did, listed it as not carried on, and stopped 5 minutes ago."""
    life = autopilot_silence.Life(p.booted - 600, p.booted - 300, stopped=frozenset({p.cid}))
    autopilot_silence.record_life(p.catalog, life, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "why, arrange, run",
    [
        ("it was handed in to your approval card", _handed_in, {}),
        ("you stopped it", _stopped_by_you, {}),
        ("the pause for your usage limit carries it on", _parked, {}),
        ("a run is going on it again", _going_again, {}),
        ("3 restarts in a row stopped", _three_restarts, {}),
        ("did not carry its Build run on", _left_waiting_by_the_restart_before, {}),
        ("ended in the server before this one", None, {"state": "persistence_failed"}),
        ("started by another Thomas server", None, {"state": None}),  # the checkout is two servers' catalog
    ],
    ids=[
        "handed in",
        "stopped by you",
        "parked",
        "live again",
        "restarts in a row",
        "left waiting by the restart before",
        "ended",
        "another server's",
    ],
)
async def test_what_the_restart_leaves_alone(tmp_path: Path, why: str, arrange: Any, run: dict) -> None:
    p = _stopped_run(tmp_path, **run)
    app = _app(p.catalog, starts := [])
    if arrange is not None:
        arrange(p, app)

    report = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)

    assert starts == [] and report["resumed"] == [], report
    assert why in report["not_resumed"][p.cid], report


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "run",
    [
        {"ago": 37 * 3600},
        {"ago": 37 * 3600, "kind": "request"},
        {"ago": 16 * 3600, "kind": "request"},
    ],
    ids=["silent longer than before", "request silent longer than before", "no prior life record"],
)
async def test_old_unfinished_runs_are_carried_on_once(tmp_path: Path, run: dict) -> None:
    """An unfinished Autopilot run can be carried on regardless of its last word's age."""
    p = _stopped_run(tmp_path, **run)
    app = _app(p.catalog, starts := [])

    report = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)

    assert report["resumed"] == [p.cid] and len(starts) == 1, report


@pytest.mark.asyncio
async def test_a_project_not_on_autopilot_is_listed_as_stopped_by_the_restart_not_carried_on(tmp_path: Path) -> None:
    p = _stopped_run(tmp_path, autonomy=4)
    app = _app(p.catalog, starts := [])

    report = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)

    assert starts == [] and "not on Autopilot" in report["not_resumed"][p.cid]
    state, why = thomas_project.project_phase(p.root, p.catalog, p.cid)
    assert state == "ended" and "stopped when Thomas's server restarted" in why, (state, why)


def test_the_listing_says_carrying_on_until_the_run_starts_then_what_the_run_says(tmp_path: Path) -> None:
    p = _stopped_run(tmp_path)
    before = thomas_project.project_phase(p.root, p.catalog, p.cid)
    _restart().survey(p.catalog, p.booted)  # this server started, and found the run it was doing

    assert before[0] == "waiting", "no restart pass, no change: the old reading"
    assert thomas_project.project_phase(p.root, p.catalog, p.cid) == ("waiting", _restart().CARRYING_ON)
    asyncio.run(_restart().resume_interrupted(_app(p.catalog, []), p.catalog, booted=p.booted))
    assert thomas_project.project_phase(p.root, p.catalog, p.cid) != ("waiting", _restart().CARRYING_ON)


def test_a_carried_on_project_keeps_its_green_past_the_24_hour_sweep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review 2026-10-07: by the morning after, a carried-on project's green can be older than the 24 hours the
    sweeps allow, and the run killed at the shutdown never marked it kept. It is kept as a ratchet repair's is."""
    greens = tmp_path / "greens"
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(greens))
    p = _stopped_run(tmp_path)
    eid = "thomas-0123456789ab"  # the project's green, made the afternoon before
    (greens / "work" / eid).mkdir(parents=True)
    (greens / "git" / eid).mkdir(parents=True)
    made = {"execution_id": eid, "base": "0" * 40, "blue": str(tmp_path), "created_at": p.booted - 30 * 3600}
    (greens / "git" / eid / green_checkout.METADATA_NAME).write_text(json.dumps(made), encoding="utf-8")

    report = asyncio.run(_restart().resume_interrupted(_app(p.catalog, []), p.catalog, booted=p.booted))

    assert report["resumed"] == [p.cid] and (greens / "git" / eid / green_checkout.KEPT_NAME).is_file()
    assert green_checkout.sweep(now=p.booted + 60) == [] and green_checkout.find_green(eid) is not None


def test_a_run_waits_while_the_cages_shell_runner_is_not_answering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review 2026-10-07: with the cage required and its runner silent, every command the carried-on run tried
    would fail. The pass waits for the runner, then says so; meanwhile the server records that it is alive."""
    restart, p = _restart(), _stopped_run(tmp_path)
    for name, value in (("SETTLE_S", 0.0), ("TICK_S", 0.01), ("WAIT_LIMIT_S", 0.3), ("_cage_down", lambda: True)):
        monkeypatch.setattr(restart, name, value)
    monkeypatch.setattr(autopilot_silence, "HEARTBEAT_S", 0.05)
    monkeypatch.setattr(restart._pass, "booted_at", time.time())
    app = _app(p.catalog, starts := [])

    async def scenario() -> list[float]:
        app[restart.APP_AUTOPILOT_RESTART_TASK] = asyncio.create_task(restart.restart_pass(app, catalog_root=p.catalog))
        beats: list[float] = []
        for _ in range(300):
            await asyncio.sleep(0.02)
            life = autopilot_silence.previous_life(p.catalog, time.time() + 3600)
            beats += [life.alive_at] if life is not None and p.cid in restart.report()["not_resumed"] else []
            if len(set(beats)) >= 3:
                break
        await restart.stop_restart_pass(app)
        return beats

    beats = asyncio.run(scenario())

    assert starts == [] and restart.report()["not_resumed"][p.cid] == restart.CAGE_DOWN
    assert len(set(beats)) >= 3 and beats == sorted(beats), "alive, every heartbeat, after the pass is done"


# Orphaned runners end before recovery; a runner whose server is alive stays with that server.
_SLEEPS_AS_A_RUNNER = "import time; time.sleep(120)"
_LAUNCHES_AN_ORPHAN = (  # the runner holds none of the launcher's pipes, or reading its pid would wait for it to end
    "import subprocess, sys; print(subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)',"
    " 'thomas.forge.anvil.forge_code_runner', '--conversation-id', sys.argv[1]], stdin=subprocess.DEVNULL,"
    " stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).pid)"
)


def _alive(pid: int) -> bool:
    import psutil

    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


@pytest.mark.asyncio
async def test_a_runner_whose_server_is_gone_is_ended_before_the_run_carries_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner_scan: Any
) -> None:
    import psutil

    monkeypatch.setattr(_restart(), "_runners_of", runner_scan)

    p = _stopped_run(tmp_path)
    app = _app(p.catalog, starts := [])
    launched = subprocess.run([sys.executable, "-c", _LAUNCHES_AN_ORPHAN, p.cid], capture_output=True, text=True)
    orphan = int(launched.stdout.strip())  # its launcher has exited: nothing can hear this runner any more
    runner_scan.register(orphan)
    try:
        report = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)

        assert report["resumed"] == [p.cid] and len(starts) == 1, report
        deadline = time.time() + 10
        while _alive(orphan) and time.time() < deadline:
            await asyncio.sleep(0.1)
        assert not _alive(orphan), "one team works in the copy"
    finally:
        with contextlib.suppress(psutil.Error):
            psutil.Process(orphan).kill()


@pytest.mark.asyncio
async def test_a_runner_another_live_server_started_is_left_to_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner_scan: Any
) -> None:
    monkeypatch.setattr(_restart(), "_runners_of", runner_scan)
    p = _stopped_run(tmp_path)
    app = _app(p.catalog, starts := [])
    command = [sys.executable, "-c", _SLEEPS_AS_A_RUNNER, "thomas.forge.anvil.forge_code_runner"]
    runner = subprocess.Popen([*command, "--conversation-id", p.cid])  # its server, this test, is alive
    runner_scan.register(runner.pid)
    try:
        report = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)

        assert starts == [] and report["resumed"] == [], report
        assert "still writing, in another server" in report["not_resumed"][p.cid], report
        assert runner.poll() is None, "never ended: its server still hears it"
    finally:
        runner.kill()
        runner.wait(timeout=10)
