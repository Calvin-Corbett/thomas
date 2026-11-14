"""A stop must not block aiohttp or lose projects when another green is unreadable."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

from tests.test_a_project_can_be_stopped_from_its_api import _file, _stop, isolated
from tests.test_a_thomas_project_starts_without_chat import _client, _start, w
from thomas.server import autopilot_park, thomas_project
from thomas.server.praxis.launch import APP_PRAXIS_STOP_CODE_RUN
from thomas.server.routes import self_project_routes


def test_stop_does_its_file_and_lock_work_outside_aiohttp(w: SimpleNamespace, monkeypatch) -> None:
    async def scenario():
        client = await _client(w)
        try:
            started = await _start(client)
            cid = started["conversation_id"]
            loop_thread = threading.get_ident()
            calls = []
            original_lookup = self_project_routes._in_greens
            original_request = thomas_project.request_stop
            original_clear = autopilot_park.clear
            original_read = Path.read_text

            def outside_loop(name, function):
                def checked(*args, **kwargs):
                    assert threading.get_ident() != loop_thread, name
                    calls.append(name)
                    return function(*args, **kwargs)

                return checked

            def read_text(path, *args, **kwargs):
                if path == _file(started):
                    assert threading.get_ident() != loop_thread, "conversation read"
                    calls.append("read")
                return original_read(path, *args, **kwargs)

            with monkeypatch.context() as patch:
                patch.setattr(self_project_routes, "_in_greens", outside_loop("lookup", original_lookup))
                patch.setattr(thomas_project, "request_stop", outside_loop("stamp", original_request))
                patch.setattr(autopilot_park, "clear", outside_loop("park", original_clear))
                patch.setattr(Path, "read_text", read_text)
                status, body = await _stop(client, cid)
            assert status == 200 and body["stamped"] is True
            assert set(calls) == {"lookup", "stamp", "park", "read"}
        finally:
            await client.close()

    asyncio.run(scenario())


def test_other_unreadable_green_does_not_prevent_stopping_a_listed_project(w: SimpleNamespace, monkeypatch) -> None:
    async def scenario():
        client = await _client(w)
        try:
            started = await _start(client)
            cid = started["conversation_id"]
            original = self_project_routes._conversations
            green = Path(started["project_root"])
            other = w.greens / "work" / "unreadable-neighbor" / "conversations"
            other.mkdir(parents=True)

            def unreadable(folder, *, strict=False, unread=None, warnings=None):
                if folder == other:
                    raise PermissionError("other green cannot be read")
                return original(folder, strict=strict, unread=unread)

            monkeypatch.setattr(self_project_routes, "_conversations", unreadable)
            # The listing can still show the target when the neighbor cannot be read.
            rows = self_project_routes.read_projects(changed_files=False)["projects"]
            assert any(row["conversation_id"] == cid for row in rows)
            assert green != other.parent
            status, body = await _stop(client, cid)
            assert status == 200 and body["stamped"] is True
            assert json.loads(_file(started).read_text())["thomas_project"]["stopped_at"]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_catalog_project_without_submission_is_not_mistaken_for_inbox(w: SimpleNamespace) -> None:
    async def scenario():
        client = await _client(w)
        try:
            started = await _start(client)
            cid = started["conversation_id"]
            catalog_file = thomas_project._live_file(w.catalog, cid)
            catalog_file.parent.mkdir(parents=True, exist_ok=True)
            catalog_file.write_bytes(_file(started).read_bytes())
            (w.tmp / "inbox").mkdir(exist_ok=True)
            calls = []

            async def stop_run(run_id):
                calls.append(run_id)
                return True

            client.app[APP_PRAXIS_STOP_CODE_RUN] = stop_run
            status, body = await _stop(client, cid)
            assert status == 409
            assert "handed in to your card and left the inbox without landing" in body["error"]
            assert "still in the promoter's inbox" not in body["error"]
            assert "nothing of it runs" in body["error"] and "send-back returns it to its team" in body["error"]
            assert not calls and not thomas_project._STOPPED
            assert "stopped_at" not in json.loads(_file(started).read_text())["thomas_project"]
            assert "stopped_at" not in json.loads(catalog_file.read_text())["thomas_project"]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_retirement_submission_is_used_for_handed_in_refusal(w: SimpleNamespace) -> None:
    async def scenario():
        client = await _client(w)
        try:
            started = await _start(client)
            cid = started["conversation_id"]
            catalog_file = thomas_project._live_file(w.catalog, cid)
            catalog_file.parent.mkdir(parents=True, exist_ok=True)
            record = json.loads(_file(started).read_text())
            record["thomas_project"]["retirement"] = {"submission": "self-retired-test"}
            catalog_file.write_text(json.dumps(record), encoding="utf-8")
            (w.tmp / "inbox" / "self-retired-test").mkdir(parents=True)
            status, body = await _stop(client, cid)
            assert status == 409
            assert "self-retired-test is still in the promoter's inbox" in body["error"]
            assert not thomas_project._STOPPED
            assert "stopped_at" not in json.loads(_file(started).read_text())["thomas_project"]
            assert "stopped_at" not in json.loads(catalog_file.read_text())["thomas_project"]
        finally:
            await client.close()

    asyncio.run(scenario())
