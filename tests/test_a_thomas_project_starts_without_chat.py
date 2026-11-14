"""A Thomas project starts without Chat (POST /api/self/projects), and GET says where each one stands.

You asked: "so when thomas works on himself make sure their is a task manegrr just for thomas project like he does
with every new build." Only Chat's send_task could start one, and on 2026-09-24 Chat's own model was rate-limited.
Real here: the whole server app with its own loopback guard, git greens made from a small stand-in for Thomas's
source, the conversation store and registry, Chat's own start path, the settle and a repair round. Stubbed: Build's
start hook, and the promoter's verdict files.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core import persistence
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.core.file_access import PROJECT
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server import (
    chat_self_project,
    green_checkout,
    green_handoff,
    repair_ledger,
    self_change_status,
    thomas_project,
)
from thomas.server.app import create_app
from thomas.server.app_keys import APP_LOCAL_PORT
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.routes import self_project_routes

ASK = "Make the Send button blue"
URL = "/api/self/projects"
# The settings a caller passes for a Build run on Claude.
CLAUDE = {"model": "claude:opus", "model_id": "opus", "reasoning_effort": "xhigh", "autonomy_level": 5,
          "file_access": "project", "memory": True, "guardrails": "guarded", "token_economy": "balanced",
          "build_roles": {"builder": None, "reviewer": None}}  # fmt: skip
MOVED = "the change no longer applies to dev: Applied patch to 'AGENTS.md' with conflicts."


def _git(cwd: Path, *args: str) -> None:
    command = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *args]
    subprocess.run(command, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def w(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    blue = tmp_path / "blue"  # stands in for Thomas's own source checkout
    blue.mkdir()
    for name in ("README.md", "AGENTS.md"):
        (blue / name).write_text(f"{name}\n", encoding="utf-8")
    for args in (("init", "-q", "-b", "dev"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        _git(blue, *args)
    greens, catalog, board, outbox = (tmp_path / name for name in ("green", "catalog", "board", "outbox"))
    for folder in (greens / "work", greens / "git", catalog, board, outbox):  # a green root that exists gets no ACLs
        folder.mkdir(parents=True)
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(greens))
    monkeypatch.setenv("THOMAS_PROJECT_ROOT", str(board))  # where a chat's task records live
    monkeypatch.setenv("THOMAS_DB_PATH", str(tmp_path / "preferences.db"))
    monkeypatch.setattr(persistence, "_DEFAULT_STATE_FILE", tmp_path / "state" / "thomas_state.json")
    monkeypatch.setattr(persistence, "_DEFAULT_REPORT_DIR", tmp_path / "state" / "reports")
    monkeypatch.setattr(persistence, "_engine", None)
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: blue)
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: catalog)
    monkeypatch.setattr(green_handoff, "inbox_dir", lambda: tmp_path / "inbox")
    monkeypatch.setattr(repair_ledger, "lessons_note", lambda: "")
    # A separate sibling-listing test covers diff detection; these requests test project lifecycle.
    real_sibling_changes = green_handoff.sibling_changes
    monkeypatch.setattr(green_handoff, "sibling_changes", lambda eid: real_sibling_changes(eid) if eid else {})
    monkeypatch.setattr(green_handoff, "_end_processes", lambda green: None)  # no cage runner in a test
    # The Build hook below never edits a green; do not keep a production polling
    # task alive for every server client when testing project start/list semantics.
    monkeypatch.setattr(green_checkout, "begin_first_edit_watch", lambda green: None)
    monkeypatch.setattr(self_change_status, "outbox_dir", lambda: outbox)
    world = SimpleNamespace(tmp=tmp_path, greens=greens, catalog=catalog, board=board, outbox=outbox, starts=[])

    async def hook(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:  # Build's start, stood in for
        world.starts.append({**body, "port": port})
        return 200, {"ok": True, "conversation_id": body["conversation_id"], "run_id": f"run-{len(world.starts)}"}

    world.hook = hook
    return world


async def _client(w: SimpleNamespace, *, remote: str = "") -> TestClient:
    """The whole server, with its own loopback guard, and Build's start hook stood in for."""
    config = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")}, default_model="local",
        memory=MemoryConfig(root=str(w.tmp / "memory")), server=ServerConfig(access_mode="local"),
    )  # fmt: skip
    app = create_app(config)
    app[APP_PRAXIS_START_CODE_RUN] = w.hook
    if remote:  # a caller on another machine: every request reaches the server from that address

        @web.middleware
        async def elsewhere(request: web.Request, handler: Any) -> web.StreamResponse:
            return await handler(request.clone(remote=remote))

        app.middlewares.insert(0, elsewhere)
    client = TestClient(TestServer(app, host="127.0.0.1"))
    await client.start_server()
    return client


async def _start(client: TestClient, **extra: Any) -> dict[str, Any]:
    response = await client.post(URL, json={"request": ASK, "settings": CLAUDE, **extra})
    assert response.status == 200, await response.text()
    return await response.json()


async def _listed(client: TestClient) -> dict[str, dict[str, Any]]:
    # Advance past the cache window before inspecting changes made directly on disk.
    client.app.get("self_project_listing_slot", {})["updated"] = 0
    response = await client.get(URL)
    assert response.status == 200, await response.text()
    data = await response.json()
    while data.get("refreshing"):
        await asyncio.sleep(0.05)
        response = await client.get(URL)
        data = await response.json()
    return {row["conversation_id"]: row for row in data["projects"]}


def test_a_post_starts_one_thomas_project_with_your_settings_and_chats_own_request(w: SimpleNamespace) -> None:
    async def scenario() -> None:
        client = await _client(w)
        try:
            other = await _start(client)  # another project, already changing a file in its own copy
            await _listed(client)  # cache a complete list before the next start
            (Path(other["project_root"]) / "README.md").write_text("changed\n", encoding="utf-8")
            chat_kwargs = dict(session_id="chat-1", prompt=ASK, autonomy_level=5, file_access=PROJECT,
                               model_id="opus", reasoning_effort="xhigh", guardrails="guarded")  # fmt: skip
            await chat_self_project._start_project(client.app, w.board, chat_kwargs)  # Chat's path, for the words
            from_chat = w.starts[-1]
            started, port = await _start(client, chat_session_id="chat-1"), client.port
            listed = await _listed(client)  # even a scan cached before POST must see the new start
        finally:
            await client.close()
        assert started["conversation_id"] in listed
        assert len(w.starts) == 3 and sorted(started) == ["conversation_id", "execution_id", "ok", "project_root"]
        body = w.starts[-1]
        assert {key: body[key] for key in CLAUDE} == CLAUDE  # your settings reach Build as sent
        assert (body["conversation_id"], body["project_root"]) == (started["conversation_id"], started["project_root"])
        assert body["project_choice"] == "picked" and body["port"] == port  # the port Build runs report back to
        assert Path(started["project_root"]).parent == w.greens / "work"  # a green, never the running checkout
        assert body["message"] == from_chat["message"]  # the same words Chat's own path sends Build
        for convention in (ASK, "TITLE:", "changelog.d/", "monolith_guard", other["execution_id"], "README.md"):
            assert convention in body["message"]
        stored = forge_code_store.load_conversation(Path(started["project_root"]), started["conversation_id"])
        assert stored["thomas_project"]["chat_session_id"] == "chat-1"  # its cards go to that chat

    asyncio.run(scenario())


def test_direct_project_clock_starts_before_request_validation(
    w: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        client = await _client(w)
        try:
            real_checked = self_project_routes._checked
            validation_done: list[float] = []

            def slow_validation(body: dict[str, Any]) -> Any:
                time.sleep(0.12)
                result = real_checked(body)
                validation_done.append(time.time())
                return result

            monkeypatch.setattr(self_project_routes, "_checked", slow_validation)
            before = time.time()
            started = await _start(client)
            green = green_checkout.find_green(started["execution_id"])
            assert green is not None
            metadata = json.loads((green.git_dir / green_checkout.METADATA_NAME).read_text(encoding="utf-8"))
            assert len(validation_done) == 1
            assert before <= metadata["requested_at"] < validation_done[0]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_chat_project_clock_starts_before_look_back(w: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        client = await _client(w)
        try:
            client.app._state[APP_LOCAL_PORT] = client.port
            real_look_back = chat_self_project._look_back
            look_back_done: list[float] = []

            def slow_look_back(*args: Any) -> Any:
                time.sleep(0.12)
                result = real_look_back(*args)
                look_back_done.append(time.time())
                return result

            monkeypatch.setattr(chat_self_project, "_look_back", slow_look_back)
            before = time.time()
            await chat_self_project._start_project(
                client.app, w.board,
                dict(session_id="chat-clock", prompt=ASK, autonomy_level=5, file_access=PROJECT,
                     model_id="opus", reasoning_effort="xhigh", guardrails="guarded"),
                requested_at=before,
            )  # fmt: skip
            greens = [green_checkout.find_green(path.name) for path in (w.greens / "work").iterdir()]
            green = next(g for g in greens if g is not None)
            metadata = json.loads((green.git_dir / green_checkout.METADATA_NAME).read_text(encoding="utf-8"))
            assert len(look_back_done) == 1
            assert before <= metadata["requested_at"] < look_back_done[0]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_queued_project_retains_request_clock_in_greens_metadata(w: SimpleNamespace) -> None:
    async def scenario() -> None:
        from thomas.server import thomas_project

        client = await _client(w)
        try:
            queued_at = time.time() - 10
            started = await thomas_project.start_thomas_project(
                client.app, request=ASK, settings=CLAUDE, port=client.port, meta={"queued_at": queued_at}
            )
            green = green_checkout.find_green(started["execution_id"])
            assert green is not None
            metadata = json.loads((green.git_dir / green_checkout.METADATA_NAME).read_text(encoding="utf-8"))
            assert metadata["requested_at"] == queued_at
        finally:
            await client.close()

    asyncio.run(scenario())


def test_a_start_is_refused_with_builds_own_reason_and_nothing_starts(w: SimpleNamespace) -> None:
    async def scenario() -> list[tuple[int, str]]:
        client = await _client(w)
        answers = []
        try:
            for settings in (
                {**CLAUDE, "model": "qwen2.5-coder:7b", "model_id": "qwen2.5-coder:7b"},  # not a model Build runs
                {**CLAUDE, "autonomy_level": 2},  # below Agent: Build may not edit
                {**CLAUDE, "project_root": "C:/Users"},  # the start picks the folder, never the caller
                {**CLAUDE, "reasoning_effort": "ludicrous"},
            ):
                response = await client.post(URL, json={"request": ASK, "settings": settings})
                answers.append((response.status, (await response.json())["error"]))
            empty = await client.post(URL, json={"request": " ", "settings": CLAUDE})
            answers.append((empty.status, (await empty.json())["error"]))
        finally:
            await client.close()
        return answers

    answers = asyncio.run(scenario())
    assert [status for status, _ in answers] == [400, 409, 400, 400, 400]
    assert "neither a GPT model nor a Claude model" in answers[0][1] and "Autonomy" in answers[1][1]
    assert "project_root" in answers[2][1] and "reasoning_effort" in answers[3][1]
    assert w.starts == [] and not any((w.greens / "work").iterdir())


def test_a_caller_on_another_machine_is_refused(w: SimpleNamespace) -> None:
    async def scenario() -> list[int]:
        client = await _client(w, remote="203.0.113.7")
        try:
            listed = await client.get(URL)
            started = await client.post(URL, json={"request": ASK, "settings": CLAUDE})
            return [listed.status, started.status]
        finally:
            await client.close()

    assert asyncio.run(scenario()) == [403, 403]
    assert w.starts == [] and not any((w.greens / "work").iterdir())


def test_a_page_from_another_origin_is_refused_and_never_gets_cors(w: SimpleNamespace) -> None:
    async def scenario() -> tuple[list[int], list[str | None], int]:
        client = await _client(w)
        statuses, cors = [], []
        try:
            for origin in ("https://evil.example", f"http://127.0.0.1:{client.port + 1}", "null"):
                for method in ("GET", "POST", "OPTIONS"):
                    headers = {"Origin": origin, "Access-Control-Request-Method": "POST"}
                    body = {"request": ASK, "settings": CLAUDE} if method == "POST" else None
                    response = await client.request(method, URL, headers=headers, json=body)
                    statuses.append(response.status)
                    cors.append(response.headers.get("Access-Control-Allow-Origin"))
            own = await client.get(URL, headers={"Origin": f"http://127.0.0.1:{client.port}"})  # the Thomas UI itself
            cors.append(own.headers.get("Access-Control-Allow-Origin"))
            return statuses, cors, own.status
        finally:
            await client.close()

    statuses, cors, own = asyncio.run(scenario())
    assert statuses[0::3] == [403, 403, 403] and statuses[1::3] == [403, 403, 403]  # GET and POST
    assert not any(200 <= status < 300 for status in statuses[2::3])  # a preflight is never answered
    assert cors == [None] * 10 and own == 200
    assert w.starts == [] and not any((w.greens / "work").iterdir())


def _finish_and_hand_in(w: SimpleNamespace, started: dict[str, Any], rel: str) -> str:
    """Its team changes one file and finishes, and the project is handed to your card: the submission id."""
    work, cid = Path(started["project_root"]), started["conversation_id"]
    (work / rel).write_text("changed\n", encoding="utf-8")
    forge_code_store.append_agent_turn(
        work, cid, model="claude", transcript="", changed_files=[rel], returncode=0, ok=True, noop=False,
        reason="1 file(s) changed", outcome="completed",
    )  # fmt: skip
    return thomas_project.settle_if_finished(work, w.catalog, cid).name


def test_a_hand_in_moved_to_withdrawn_was_never_asked(w: SimpleNamespace) -> None:
    async def scenario() -> None:
        client = await _client(w)
        try:
            started = await _start(client, chat_session_id="chat-1")
            sid = await asyncio.to_thread(_finish_and_hand_in, w, started, "README.md")
            submission = w.tmp / "inbox" / sid
            assert submission.is_dir() and not (w.outbox / f"{sid}.verdict.json").exists()
            withdrawn = w.tmp / "withdrawn"
            withdrawn.mkdir()
            submission.rename(withdrawn / sid)
            row = (await _listed(client))[started["conversation_id"]]
            assert row["submission"] == sid
            assert row["state"] == "withdrawn"
            assert "never asked" in row["detail"]
            assert "wait" not in row["detail"].lower()
            assert (self_change_status.read_hand_in_state(sid) or {})["status"] == "withdrawn"
            _verdict(w, started, sid, "declined", "you declined it")
            assert (await _listed(client))[started["conversation_id"]]["state"] == "declined"
            (w.outbox / f"{sid}.verdict.json").unlink()
            assert (await chat_self_project._await_verdict(SimpleNamespace(), sid))["status"] == "withdrawn"
            earlier = {
                "state": "awaiting_proof",
                "last_progress": "Approve or decline it at the Windows sign-in",
                "runtime_profile": {"build_conversation_id": started["conversation_id"]},
            }
            assert chat_self_project._card_hand_in_status(earlier) == "withdrawn"
            carried = chat_self_project._carry("New request", earlier, None)
            assert "you were never asked" in carried
            assert "waiting for your approval" not in carried
            assert "Windows sign-in" not in carried
        finally:
            await client.close()

    asyncio.run(scenario())


def _verdict(w: SimpleNamespace, started: dict[str, Any], sid: str, status: str, detail: str) -> None:
    record = {"id": sid, "submission_id": sid, "execution_id": started["execution_id"], "status": status,
              "detail": detail, "conflicts": [], "ts": time.time()}  # fmt: skip
    (w.outbox / f"{sid}.verdict.json").write_text(json.dumps(record), encoding="utf-8")


def _staged(started: dict[str, Any]) -> str:
    green = green_checkout.find_green(started["execution_id"])
    command = ["git", f"--git-dir={green.git_dir}", f"--work-tree={green.work}", "diff", "--cached", "--name-only"]
    return subprocess.run(command, cwd=green.work, check=True, capture_output=True, text=True).stdout


def test_the_list_follows_each_project_through_landed_refused_and_a_repair_round(
    w: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, dict[str, Any]]]]:
        client = await _client(w)
        try:
            a, b = await _start(client, chat_session_id="chat-1"), await _start(client)
            (Path(a["project_root"]) / "README.md").write_text("half done\n", encoding="utf-8")  # mid-run
            monkeypatch.setattr(green_handoff, "sibling_changes", lambda _eid: {a["execution_id"]: ["README.md"]})
            seen = [await _listed(client)]
            assert _staged(a) == ""  # the list read the change without staging it under the running team
            sid_a = await asyncio.to_thread(_finish_and_hand_in, w, a, "README.md")
            sid_b = await asyncio.to_thread(_finish_and_hand_in, w, b, "AGENTS.md")
            seen.append(await _listed(client))
            _verdict(w, a, sid_a, "landed", "")
            _verdict(w, b, sid_b, "refused", MOVED)
            seen.append(await _listed(client))
            args = (Path(b["project_root"]), w.catalog, b["conversation_id"])
            assert thomas_project.prepare_repair(*args, why=thomas_project.DEV_MOVED, detail=MOVED, sid=sid_b) == 1
            seen.append(await _listed(client))
            return a, b, seen
        finally:
            await client.close()

    a, b, seen = asyncio.run(scenario())
    running, awaiting, decided, repairing = ([s[a["conversation_id"]], s[b["conversation_id"]]] for s in seen)
    assert [row["execution_id"] for row in running] == [a["execution_id"], b["execution_id"]]
    assert [(row["state"], row["chat_session_id"]) for row in running] == [("running", "chat-1"), ("running", "")]
    assert [row["changed_files"] for row in running] == [["README.md"], []]
    assert [(row["state"], row["changed_files"]) for row in awaiting] == [
        ("awaiting verdict", ["README.md"]),
        ("awaiting verdict", ["AGENTS.md"]),
    ]
    assert [(row["state"], row["last_verdict"]["status"]) for row in decided] == [
        ("landed", "landed"),
        ("refused", "refused"),
    ]
    assert decided[1]["last_verdict"]["detail"] == MOVED  # the promoter's words, whole
    assert (repairing[0]["state"], repairing[1]["state"]) == ("landed", "repair round 1")
    assert repairing[1]["last_verdict"]["status"] == "refused" and repairing[1]["changed_files"] == ["AGENTS.md"]
