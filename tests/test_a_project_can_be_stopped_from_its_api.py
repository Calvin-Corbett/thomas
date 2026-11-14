"""Stopping a Thomas project by API leaves its green and restart pass safely stopped."""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from tests.test_a_thomas_project_starts_without_chat import _client, _finish_and_hand_in, _listed, _start, _verdict, w
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server import autopilot_park, autopilot_restart, thomas_project
from thomas.server.praxis.launch import APP_PRAXIS_STOP_CODE_RUN
from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS

URL = "/api/self/projects"


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(thomas_project, "_STOPPED", {})
    monkeypatch.setattr(autopilot_restart, "_pass", autopilot_restart._Pass())
    keys = ("DATA_DIR", "HOME", "STATE_DIR", "OWNED_ROOT", "MEMORY_ROOT", "SELF_EDIT_HOME", "SHARED_SECRET_STORE_DIR")
    folders = {f"THOMAS_{key}": str(tmp_path / key.lower()) for key in keys}
    folders["THOMAS_DB_PATH"] = str(tmp_path / "data_dir" / "thomas.db")
    with mock.patch.dict(os.environ, folders):
        yield


def _file(started: dict) -> Path:
    return thomas_project._live_file(Path(started["project_root"]), started["conversation_id"])


async def _stop(client, cid: str):
    response = await client.post(f"{URL}/{cid}/stop")
    return response.status, await response.json()


def test_idle_stop_is_stamped_and_listed(w: SimpleNamespace) -> None:
    async def scenario():
        client = await _client(w)
        try:
            started = await _start(client)
            status, body = await _stop(client, started["conversation_id"])
            assert status == 200 and body == {
                "ok": True,
                "conversation_id": started["conversation_id"],
                "execution_id": started["execution_id"],
                "state": "stopped",
                "detail": "you stopped it",
                "stopped": True,
                "run_was_going": False,
                "run_stopped": False,
                "stamped": True,
            }
            assert json.loads(_file(started).read_text())["thomas_project"]["stopped_at"]
            row = (await _listed(client))[started["conversation_id"]]
            assert (row["state"], row["detail"]) == ("stopped", autopilot_restart.YOU_STOPPED)
        finally:
            await client.close()

    asyncio.run(scenario())


def test_restart_words_give_way_to_your_stop(w: SimpleNamespace) -> None:
    async def scenario():
        client = await _client(w)
        try:
            started = await _start(client)
            cid = started["conversation_id"]
            forge_code_store.append_user_turn(Path(started["project_root"]), cid, "run before boot")
            conversation = json.loads(_file(started).read_text())
            conversation["turns"][-1]["ts"] = datetime.fromtimestamp(time.time() - 1200, timezone.utc).isoformat()
            forge_code_store.write_conversation(Path(started["project_root"]), conversation)
            autopilot_restart._pass = autopilot_restart._Pass(
                booted_at=time.time(), scanned=True, stopped={cid: autopilot_restart.UNRECORDED}
            )
            assert (await _listed(client))[cid]["detail"] == autopilot_restart.UNRECORDED
            assert (await _stop(client, cid))[0] == 200
            assert (await _listed(client))[cid]["detail"] == autopilot_restart.YOU_STOPPED
        finally:
            await client.close()

    asyncio.run(scenario())


def test_running_hook_sees_stamp_before_it_is_called(w: SimpleNamespace) -> None:
    async def scenario():
        client = await _client(w)
        try:
            started = await _start(client)
            cid = started["conversation_id"]
            calls = []

            async def stop_run(run_id):
                assert json.loads(_file(started).read_text())["thomas_project"]["stopped_at"]
                calls.append(run_id)
                return True

            client.app[APP_EVOLVE_AGENT_RUNS] = {
                cid: {"session": {"proc": SimpleNamespace(returncode=None), "run_id": "run-for-this-project"}}
            }
            client.app[APP_PRAXIS_STOP_CODE_RUN] = stop_run
            status, body = await _stop(client, cid)
            assert status == 200 and (body["run_was_going"], body["run_stopped"], body["stamped"]) == (True, True, True)
            assert calls == ["run-for-this-project"]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_parked_project_is_cleared(w: SimpleNamespace) -> None:
    async def scenario():
        client = await _client(w)
        try:
            started = await _start(client)
            cid = started["conversation_id"]
            autopilot_park.park(
                Path(started["project_root"]), w.catalog, cid, until=time.time() + 3600, provider="Claude"
            )
            assert (await _stop(client, cid))[0] == 200
            assert autopilot_park.parked(w.catalog, cid) is None
            assert "autopilot" not in json.loads(_file(started).read_text())
        finally:
            await client.close()

    asyncio.run(scenario())


def test_restart_survey_carries_on_before_stop_and_leaves_it_after(w: SimpleNamespace, monkeypatch) -> None:
    from thomas.server.routes.evolve_agent_autopilot import AUTOPILOT
    from thomas.server.routes.evolve_agent_receipts import _save_action_receipt

    async def scenario():
        client = await _client(w)
        try:
            started = await _start(client)
            cid, root = started["conversation_id"], Path(started["project_root"])
            forge_code_store.append_user_turn(root, cid, "continue", request_id="before-boot", request_fingerprint="f")
            conversation = json.loads(_file(started).read_text())
            conversation["turns"][-1]["ts"] = datetime.fromtimestamp(time.time() - 180, timezone.utc).isoformat()
            forge_code_store.write_conversation(root, conversation)
            from thomas.forge.anvil.forge_code_settings import ForgeCodeSettings

            forge_code_projects.bind_conversation(
                w.catalog,
                cid,
                root,
                settings=ForgeCodeSettings.from_payload({"autonomy_level": AUTOPILOT}).capability_report(),
                allow_without_history=True,
            )
            _save_action_receipt(w.catalog, "run", "before-boot", {"state": "running", "response": {"run_id": "old"}})
            monkeypatch.setattr(autopilot_restart, "_runners_of", lambda _cid: ([], []))
            before = autopilot_restart.survey(w.catalog, time.time())
            assert [item.cid for item in before] == [cid]
            assert (await _stop(client, cid))[0] == 200
            assert autopilot_restart.survey(w.catalog, time.time()) == []
            assert autopilot_restart._pass.left[cid] == autopilot_restart.YOU_STOPPED
        finally:
            await client.close()

    asyncio.run(scenario())


def test_your_next_message_lifts_stop(w: SimpleNamespace) -> None:
    async def scenario():
        client = await _client(w)
        try:
            started = await _start(client)
            cid, root = started["conversation_id"], Path(started["project_root"])
            assert (await _stop(client, cid))[0] == 200
            forge_code_store.append_user_turn(root, cid, "Please continue")
            assert not thomas_project.stop_requested(json.loads(_file(started).read_text()))
            assert (await _listed(client))[cid]["detail"] != autopilot_restart.YOU_STOPPED
        finally:
            await client.close()

    asyncio.run(scenario())


def test_unknown_invalid_and_ordinary_build_are_not_stopped(w: SimpleNamespace) -> None:
    async def scenario():
        client = await _client(w)
        try:
            started = await _start(client)
            cid = started["conversation_id"]
            ordinary = forge_code_store.new_conversation(Path(started["project_root"]), title="ordinary")["id"]
            for target in ("fc_0123456789abcdef", f"c:{cid}", ordinary):
                status, body = await _stop(client, target)
                assert status == 404 and "not a Thomas project" in body["error"]
            assert "stopped_at" not in json.loads(_file(started).read_text())["thomas_project"]
            assert not thomas_project._STOPPED
        finally:
            await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "case,words",
    [("landed", "already landed"), ("inbox", "still in the promoter's inbox"), ("withdrawn", "handed in to your card")],
)
def test_handed_in_is_refused_without_stopping(w: SimpleNamespace, case: str, words: str) -> None:
    async def scenario():
        client = await _client(w)
        try:
            started = await _start(client)
            sid = await asyncio.to_thread(_finish_and_hand_in, w, started, "README.md")
            if case == "landed":
                _verdict(w, started, sid, "landed", "landed")
            elif case == "withdrawn":
                (w.tmp / "withdrawn").mkdir(exist_ok=True)
                (w.tmp / "inbox" / sid).rename(w.tmp / "withdrawn" / sid)
            calls = []

            async def stop_run(run_id):
                calls.append(run_id)
                return True

            client.app[APP_PRAXIS_STOP_CODE_RUN] = stop_run
            status, body = await _stop(client, started["conversation_id"])
            assert status == 409 and words in body["error"]
            assert not calls and not thomas_project._STOPPED
            assert "stopped_at" not in json.loads(_file(started).read_text())["thomas_project"]
            assert not json.loads(thomas_project._live_file(w.catalog, started["conversation_id"]).read_text())[
                "thomas_project"
            ].get("stopped_at")
        finally:
            await client.close()

    asyncio.run(scenario())


def test_unreadable_conversation_is_not_stamped(w: SimpleNamespace) -> None:
    async def scenario():
        client = await _client(w)
        try:
            started = await _start(client)
            path = _file(started)
            path.write_bytes(b"not json\xff")
            status, body = await _stop(client, started["conversation_id"])
            assert status == 409 and "not stamped" in body["detail"]
            assert body.get("stamped") is False
            assert path.read_bytes() == b"not json\xff" and not thomas_project._STOPPED
        finally:
            await client.close()

    asyncio.run(scenario())


def test_failed_stamp_still_stops_in_this_server(w: SimpleNamespace, monkeypatch) -> None:
    async def scenario():
        client = await _client(w)
        try:
            started = await _start(client)

            def fail(*args, **kwargs):
                raise OSError("disk full")

            monkeypatch.setattr(forge_code_store, "write_conversation", fail)
            status, body = await _stop(client, started["conversation_id"])
            assert status == 409 and body["stopped"] is True and body["stamped"] is False
            assert "not stamped" in body["detail"] and "until it restarts" in body["detail"]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_remote_caller_cannot_stop(w: SimpleNamespace) -> None:
    async def scenario():
        local = await _client(w)
        started = await _start(local)
        client = await _client(w, remote="192.0.2.8")
        calls = []
        try:

            async def stop_run(run_id):
                calls.append(run_id)
                return True

            client.app[APP_PRAXIS_STOP_CODE_RUN] = stop_run
            response = await client.post(f"{URL}/{started['conversation_id']}/stop")
            assert response.status == 403
            assert not thomas_project._STOPPED and not calls
            assert "stopped_at" not in json.loads(_file(started).read_text())["thomas_project"]
        finally:
            await client.close()
            await local.close()

    asyncio.run(scenario())
