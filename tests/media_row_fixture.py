"""The process the tests of the media row run: a real server, with a stand-in for each step that holds a thread.

Asserts stay in the tests that read what this saw, because pytest rewrites them only in a test module.
"""

from __future__ import annotations

from tests.row_off_fixture import _START_OF_A_SERVER

# Goes ahead of the script ``tests/row_page_fixture.py`` serves. A stand-in for a model that holds its thread until a
# file appears beside the memory folder. Everything else, the page and the lock included, is the real thing.
A_MODEL_THAT_WAITS = """\
import sys
import time
from pathlib import Path

from PIL import Image

from thomas.server.routes import media_generation_routes as media

let_go = Path(sys.argv[1]).parent / "let-go"


def a_model_that_waits(_prompt, output, progress):
    progress(20, "Loading the stand-in model")
    while not let_go.exists():
        time.sleep(0.05)
    Image.new("RGB", (64, 64), "orange").save(output, format="PNG")


media._local_model_ready = lambda _medium: True
media._local_image = a_model_that_waits

"""

THROUGH_OFF_AND_ON = (
    _START_OF_A_SERVER
    + """\

import aiohttp
from PIL import Image

from thomas.core import task_bot_runtime
from thomas.server.routes import media_generation_routes as media

turn_on, turn_off = f"/api/plugins/thomas/{row_id}/on", f"/api/plugins/thomas/{row_id}/off"
data_root = Path(memory)
lanes = data_root / ".thomas" / "media_lanes.json"
let_go, let_the_provider_go, let_the_download_go, let_the_scan_go = (threading.Event() for _ in range(4))
downloading, downloaded, scanning = (threading.Event() for _ in range(3))
began, ended, slow_scan = [], [], []


def held(gate, output):
    began.append(output.parent.name)
    gate.wait(120)
    Image.new("RGB", (8, 8), "orange").save(output, format="PNG")
    ended.append(output.parent.name)


def a_scan(_medium):
    if slow_scan:
        scanning.set()
        let_the_scan_go.wait(120)
    return True


def a_download(_medium):
    downloading.set()
    let_the_download_go.wait(120)
    downloaded.set()


media._local_image = lambda _prompt, output, _progress: held(let_go, output)
media._api_generate = lambda _medium, _prompt, _key, output: held(let_the_provider_go, output)
media._local_model_ready = a_scan
media._ensure_local_model = a_download


async def until(check):
    for _ in range(9000):
        if check():
            return
        await asyncio.sleep(0.01)
    raise TimeoutError("what this was waiting for never came")


def tasks_of_the_row(job):
    names = (task.get_name().replace(f" {job}", "") for task in asyncio.all_tasks())
    return sorted(name for name in names if name.startswith(f"plugin:{row_id}:") and "hooks" not in name)


def record(job):
    found = task_bot_runtime.get_execution(job, data_root)
    return {"state": found["state"], "proof": found.get("proof_status")}


async def create(client, medium="image"):
    body = {"medium": medium, "prompt": "A bus", "session_id": "s1"}
    return await client.post("/api/media/generate", json=body)


async def job_answer(client, job):
    answer = await client.get(f"/api/media/jobs/{job}")
    return (await answer.json())["job"] if answer.status == 200 else answer.status


async def press_off_and_see_it_held(client, app):
    pressing = asyncio.ensure_future(client.post(turn_off))
    report = app[runtime_plugins.APP_RUNTIME_PLUGINS]
    await until(lambda: next(row for row in report.report()["rows"] if row["id"] == row_id)["state"] == "unloading")
    return pressing, await state_of(app)


async def run_the_server():
    lanes.parent.mkdir(parents=True, exist_ok=True)
    lanes.write_text(json.dumps({"image": "local"}), encoding="utf-8")
    app = app_core.create_app(AppConfig(models=models, default_model="local", memory=MemoryConfig(root=memory)))
    seen = {}
    async with TestClient(TestServer(app)) as client:
        first = (await (await create(client)).json())["job_id"]
        await until(lambda: began)
        seen["tasks_of_a_local_job"] = tasks_of_the_row(first)
        seen["running"] = (await job_answer(client, first))["state"]
        seen["start_key_on"] = app.get(media.MEDIA_START) is not None

        off = await asyncio.wait_for(client.post(turn_off), 60)
        seen["off"] = await off.json()
        seen["worker_ended_when_off_answered"] = bool(ended)
        seen["tasks_after_off"] = tasks_of_the_row(first)
        seen["record_after_off"] = record(first)
        seen["asked_while_off"] = await job_answer(client, first)
        seen["start_key_off"] = app.get(media.MEDIA_START) is not None

        await client.post(turn_on)
        seen["asked_once_back_on"] = await job_answer(client, first)
        waiting = (await (await create(client)).json())["job_id"]
        await asyncio.sleep(0.3)
        seen["began_with_one_waiting"] = list(began)
        await asyncio.wait_for(client.post(turn_off), 60)
        seen["waiting_job_record_after_off"] = record(waiting)
        await client.post(turn_on)
        second = (await (await create(client)).json())["job_id"]
        await asyncio.sleep(0.3)
        seen["second_while_the_first_worker_runs"] = (await job_answer(client, second))["state"]
        seen["began_while_the_first_worker_runs"] = list(began)
        seen["lock_held"] = media._LOCAL_LOCK.locked()
        let_go.set()
        await until(lambda: len(ended) == 3)
        while (await job_answer(client, second))["state"] == "running":
            await asyncio.sleep(0.01)
        seen["second"] = await job_answer(client, second)
        seen["the_waiting_job_ran_anyway"] = waiting in began
        seen["waiting_job_once_its_worker_ended"] = record(waiting)
        seen["first_once_its_worker_ended"] = await job_answer(client, first)
        seen["first_record_once_its_worker_ended"] = record(first)
        seen["first_left_a_file"] = (media._WORKSPACES_BASE / first / "generated-image.png").is_file()

        await client.put(f"{media_lanes}/music", json={"provider": "api", "api_key": "not-a-real-key"})
        third = (await (await create(client, "music")).json())["job_id"]
        await until(lambda: len(began) == 4)
        seen["tasks_of_a_provider_job"] = tasks_of_the_row(third)
        off = await asyncio.wait_for(client.post(turn_off), 60)
        seen["off_with_a_provider_job"] = (await off.json())["state"]
        seen["provider_ended_when_off_answered"] = len(ended) == 4
        seen["provider_record"] = record(third)
        seen["finished_file_with_the_row_off"] = (await client.get(f"/deliverable/{second}/generated-image.png")).status
        let_the_provider_go.set()
        await until(lambda: len(ended) == 4)

        await client.post(turn_on)
        download = asyncio.ensure_future(client.put(f"{media_lanes}/video", json={"provider": "local"}))
        await until(downloading.is_set)
        pressing, seen["held_by_a_download"] = await press_off_and_see_it_held(client, app)
        seen["stop_now"] = await (await client.post(f"{turn_off}?force=1")).json()
        await pressing
        seen["after_stop_now"] = await state_of(app)
        try:
            seen["the_download_request"] = (await download).status
        except aiohttp.ClientError:
            seen["the_download_request"] = "dropped"
        seen["download_ended_at_stop_now"] = downloaded.is_set()
        let_the_download_go.set()
        await until(downloaded.is_set)
        seen["saved_after_the_download"] = json.loads(lanes.read_text(encoding="utf-8"))

        await client.post(turn_on)
        seen["lanes_back_on"] = (await (await client.get(media_lanes)).json())["lanes"]
        slow_scan.append(True)
        let_go.clear()
        starting = asyncio.ensure_future(create(client))
        await until(scanning.is_set)
        pressing, seen["held_by_a_start"] = await press_off_and_see_it_held(client, app)
        let_the_scan_go.set()
        started_late = await starting
        await pressing
        seen["started_as_off_was_pressed"] = started_late.status
        seen["its_record"] = record((await started_late.json())["job_id"])
        let_go.set()
    return seen


media_lanes = "/api/media/lanes"
Path(seen_at).write_text(json.dumps(asyncio.run(run_the_server())), encoding="utf-8")
"""
)
