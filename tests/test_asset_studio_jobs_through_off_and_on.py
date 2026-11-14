"""What ``thomas.server.rows.asset_studio`` does to the work its routes started, through off and on, on real processes.

A 404 proves little for this row. Each job is a task the kernel knows nothing of and a child process of its own, and a
ComfyUI is one more process, so the row can read off with every route gone and all of that still running. Only a test that
looks at the process can see it. The one thing that ends them is the cleanup the registrar adds to the view, so each test
here is what that cleanup does or leaves undone. That dotted name, and the route module's,
``thomas.server.routes.asset_studio_aiohttp``, are how a check of the row finds this file.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.asset_studio_fixture import NeverAnswers, comfy_is_up, comfy_script, end_comfy, free_port, job_waiting_on
from thomas.server import app_core
from thomas.server.routes.asset_studio_aiohttp import APP_ASSET_STUDIO_RUNTIME
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

ROW = "asset_studio"
BASE = "/api/asset-studio/v1"
ON = f"/api/plugins/thomas/{ROW}/on"
OFF = f"/api/plugins/thomas/{ROW}/off"
# Longer than any press here should take. Without ``streams=`` a press waits for the stream to run out, and that is far off.
A_PRESS_THAT_ENDS = 60

Scene = Callable[[web.Application, TestClient], Awaitable[None]]


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices and the job store live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("THOMAS_DB_PATH", raising=False)
    monkeypatch.delenv("THOMAS_SQLITE_PATH", raising=False)
    monkeypatch.delenv("THOMAS_COMFYUI_BOOT_CMD", raising=False)
    return tmp_path / "data"


def _run(tmp_path: Path, scene: Scene) -> None:
    async def on_a_server() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            await scene(app, client)

    asyncio.run(on_a_server())


async def _body(answer: aiohttp.ClientResponse) -> Any:
    assert answer.status == 200, await answer.text()
    return await answer.json()


async def _running_job(app: web.Application, client: TestClient, port: int) -> tuple[str, Any]:
    """Start a job and return it once its process is up."""
    job_id = (await _body(await client.post(f"{BASE}/jobs", json=job_waiting_on(port))))["job"]["job_id"]
    runner = app[APP_ASSET_STUDIO_RUNTIME]
    await views.until(lambda: job_id in runner._processes)
    return job_id, runner._processes[job_id]


def _row(app: web.Application) -> dict[str, Any]:
    return next(row for row in app[APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == ROW)


async def _kinds(client: TestClient, job_id: str) -> list[str]:
    return [event["kind"] for event in (await _body(await client.get(f"{BASE}/jobs/{job_id}/events")))["events"]]


def test_a_job_still_running_is_ended_and_kept_as_cancelled(tmp_path: Path, own_data_dir: Path) -> None:
    async def scene(app: web.Application, client: TestClient) -> None:
        with NeverAnswers() as waiting:
            job_id, process = await _running_job(app, client, waiting.port)
            first_runner = app[APP_ASSET_STUDIO_RUNTIME]
            assert process.returncode is None

            assert (await _body(await client.post(OFF)))["state"] == "off"
            await asyncio.wait_for(process.wait(), 15)
            assert APP_ASSET_STUDIO_RUNTIME not in app

            assert (await _body(await client.post(ON)))["state"] == "active"
            assert app[APP_ASSET_STUDIO_RUNTIME] is not first_runner
            job = (await _body(await client.get(f"{BASE}/jobs/{job_id}")))["job"]
            assert (job["status"], job["exit_code"], job["error"]) == ("cancelled", 130, "cancelled")
            assert await _kinds(client, job_id) == ["queued", "running", "cancelled"]
            health = (await _body(await client.get(f"{BASE}/health?detect=0")))["health"]
            assert health["runtime"] == {"active_tasks": 0, "active_processes": 0}

    _run(tmp_path, scene)


def test_a_program_set_to_hear_is_told_and_your_jobs_templates_and_that_setting_stay(
    tmp_path: Path, own_data_dir: Path
) -> None:
    heard: list[str] = []

    async def hear(request: web.Request) -> web.Response:
        heard.append((await request.json())["status"])
        return web.Response()

    listener = web.Application()
    listener.router.add_post("/heard", hear)

    async def scene(app: web.Application, client: TestClient) -> None:
        template = {"name": "keep me", "connector_id": "comfyui", "action_id": "get_history", "payload": {}}
        await _body(await client.post(f"{BASE}/templates", json=template))
        async with TestServer(listener) as hearing:
            told = {"url": str(hearing.make_url("/heard"))}
            await _body(await client.post(f"{BASE}/webhooks/completion", json=told))
            with NeverAnswers() as waiting:
                job_id, _process = await _running_job(app, client, waiting.port)
                await _body(await client.post(OFF))
            assert heard == ["cancelled"]

        await _body(await client.post(ON))
        assert [row["name"] for row in (await _body(await client.get(f"{BASE}/templates")))["templates"]] == ["keep me"]
        assert (await _body(await client.get(f"{BASE}/webhooks/completion")))["configured"] is True
        assert [row["job_id"] for row in (await _body(await client.get(f"{BASE}/jobs")))["jobs"]] == [job_id]

    _run(tmp_path, scene)


def test_a_request_waiting_on_a_job_holds_the_stop_until_stop_now(tmp_path: Path, own_data_dir: Path) -> None:
    async def scene(app: web.Application, client: TestClient) -> None:
        with NeverAnswers() as waiting:
            body = {**job_waiting_on(waiting.port), "wait": True, "wait_timeout_s": 100}
            asked = asyncio.ensure_future(client.post(f"{BASE}/jobs", json=body))
            runner = app[APP_ASSET_STUDIO_RUNTIME]
            await views.until(lambda: runner._processes)
            job_id, process = next(iter(runner._processes.items()))

            pressing = asyncio.ensure_future(client.post(OFF))
            await views.until(lambda: _row(app)["state"] == "unloading" and _row(app)["waiting_for"] == 1)
            await asyncio.sleep(0.5)
            assert process.returncode is None  # the job runs on while the stop waits

            forced = await _body(await client.post(f"{OFF}?force=1"))
            assert forced["stopped_partway"] is True
            await asyncio.wait_for(pressing, 30)
            with pytest.raises(aiohttp.ClientError):
                await asyncio.wait_for(asked, 30)
            await asyncio.wait_for(process.wait(), 15)

            await _body(await client.post(ON))
            assert (await _body(await client.get(f"{BASE}/jobs/{job_id}")))["job"]["status"] == "cancelled"

    _run(tmp_path, scene)


def test_an_open_event_stream_does_not_hold_the_off_switch_and_is_dropped(tmp_path: Path, own_data_dir: Path) -> None:
    async def scene(app: web.Application, client: TestClient) -> None:
        with NeverAnswers() as waiting:
            job_id, _process = await _running_job(app, client, waiting.port)
            opened = await client.get(f"{BASE}/jobs/{job_id}/events/stream?ticks=400")
            assert (opened.status, opened.content_type) == (200, "text/event-stream")
            assert (await opened.content.readline()).startswith(b"data: ")

            pressed = await asyncio.wait_for(client.post(OFF), A_PRESS_THAT_ENDS)
            assert (await _body(pressed))["state"] == "off"
            with pytest.raises(aiohttp.ClientError):
                await asyncio.wait_for(opened.content.read(), 30)

    _run(tmp_path, scene)


def test_a_comfyui_thomas_started_can_keep_running_and_thomas_cannot_stop_it_after(
    tmp_path: Path, own_data_dir: Path
) -> None:
    """The boot command runs in a shell, and only the shell is ended. On Windows ComfyUI is the shell's child."""
    port = free_port()
    command = f'"{sys.executable}" "{comfy_script(tmp_path)}" {port}'
    server_url = f"http://127.0.0.1:{port}"

    async def scene(app: web.Application, client: TestClient) -> None:
        body = {"server_url": server_url, "command": command, "wait_timeout_s": 60}
        boot = (await _body(await client.post(f"{BASE}/comfy/boot", json=body)))["boot"]
        assert (boot["ready"], boot["managed"]) == (True, True)

        assert (await _body(await client.post(OFF)))["state"] == "off"
        await _body(await client.post(ON))

        status = (await _body(await client.get(f"{BASE}/comfy/status?server_url={server_url}")))["status"]
        stopped = (await _body(await client.post(f"{BASE}/comfy/shutdown", json={"server_url": server_url})))[
            "shutdown"
        ]
        assert (status["managed"], stopped["terminated"]) == (False, False)
        if sys.platform == "win32":
            assert (status["running"], comfy_is_up(port)) == (True, True)

    try:
        _run(tmp_path, scene)
    finally:
        end_comfy(port)


def test_a_workflow_on_its_way_to_comfyui_goes_on_after_stop_now(tmp_path: Path, own_data_dir: Path) -> None:
    """The send is on a worker thread, and nothing can end one of those, so ``stop_now`` says so."""

    async def scene(app: web.Application, client: TestClient) -> None:
        with NeverAnswers() as comfy:
            body = {"server_url": f"http://127.0.0.1:{comfy.port}", "workflow_json": '{"1": {}}', "timeout_s": 4}
            asked = asyncio.ensure_future(client.post(f"{BASE}/comfy/queue", json=body))
            await views.until(lambda: b"POST /prompt" in comfy.received())

            pressing = asyncio.ensure_future(client.post(OFF))
            await views.until(lambda: _row(app)["state"] == "unloading" and _row(app)["waiting_for"] == 1)
            assert (await _body(await client.post(f"{OFF}?force=1")))["stopped_partway"] is True
            await asyncio.wait_for(pressing, 30)
            with pytest.raises(aiohttp.ClientError):
                await asyncio.wait_for(asked, 30)
            assert comfy.still_held_open()

    _run(tmp_path, scene)


def test_closing_thomas_ends_a_running_job_too(tmp_path: Path, own_data_dir: Path) -> None:
    """The cleanup used to be the app's. It is the row's now, so it has to run when the server closes as well.

    The port stays held past the close: a job whose port goes away ends by itself, and would pass with no cleanup at all.
    """

    async def on_a_server() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        with NeverAnswers() as waiting:
            async with TestClient(TestServer(app)) as client:
                _job_id, process = await _running_job(app, client, waiting.port)
                assert process.returncode is None
            await asyncio.wait_for(process.wait(), 15)

    asyncio.run(on_a_server())
