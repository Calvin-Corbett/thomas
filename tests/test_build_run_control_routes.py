"""Route tests for a live Build run's controls: pause, resume, message, messages, answer, live diff, status fields.

Same harness as the other Build route tests (evolve_agent_route_support): the evolve-agent routes on a bare aiohttp
app, auth stubbed, a throwaway git repo as the catalog, and a running run seeded into the registry.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestClient

from tests.evolve_agent_route_support import _commit_all, _drive, _GateInput, _init_repo, _new_repo
from thomas.forge.anvil import forge_code_git, forge_code_store, run_control
from thomas.forge.anvil.run_control import RunControl
from thomas.server.app_keys import APP_SECRETS
from thomas.server.routes import evolve_agent_http_support
from thomas.server.routes.evolve_agent_run_state import runs

RUN = "run-live"


class _Proc:
    pid = 4242

    def __init__(self, agent: str) -> None:
        self.returncode: int | None = None
        self.thomas_agent = agent


def _seed(app: web.Application, repo: Path, *, agent: str = "thomas") -> _Proc:
    proc = _Proc(agent)
    session = {
        "run_id": RUN,
        "conversation_id": "c-live",
        "project_root": str(repo),
        "settings": {"effective": {"agent": agent}},
        "proc": proc,
        "started_at": 1.0,
    }
    runs(app)["c-live"] = {"session": session, "drain": None}
    return proc


def _folder(repo: Path) -> Path:
    return run_control.control_dir(repo, RUN)


def test_pause_and_resume_set_the_flag_the_runner_holds_on(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)

    async def _body(client: TestClient) -> None:
        missing = await client.post("/api/evolve/agent/pause", json={})
        assert missing.status == 400 and (await missing.json())["code"] == "run_id_required"
        stale = await client.post("/api/evolve/agent/pause", json={"run_id": "run-gone"})
        assert stale.status == 409 and (await stale.json())["code"] == "run_not_active"

        paused = await client.post("/api/evolve/agent/pause", json={"run_id": RUN})
        assert paused.status == 200
        assert await paused.json() == {"ok": True, "run_id": RUN, "paused": True}
        assert run_control.is_paused(_folder(repo))
        status = await (await client.get(f"/api/evolve/agent/status?run_id={RUN}")).json()
        assert status["paused"] is True
        assert status["controls"] == {"pause": True, "message": True, "ask": True}

        resumed = await client.post("/api/evolve/agent/resume", json={"run_id": RUN})
        assert resumed.status == 200 and (await resumed.json())["paused"] is False
        assert not run_control.is_paused(_folder(repo))
        assert (await (await client.get(f"/api/evolve/agent/status?run_id={RUN}")).json())["paused"] is False

    _drive(repo, _body, configure=lambda app: _seed(app, repo))


def test_a_claude_code_run_says_it_cannot_be_paused_or_messaged(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)

    async def _body(client: TestClient) -> None:
        pause = await client.post("/api/evolve/agent/pause", json={"run_id": RUN})
        assert pause.status == 409 and (await pause.json())["code"] == "pause_unsupported"
        assert not run_control.is_paused(_folder(repo))
        message = await client.post(
            "/api/evolve/agent/message", json={"run_id": RUN, "agent_id": "lead", "text": "make it blue"}
        )
        body = await message.json()
        assert message.status == 409 and body["code"] == "agent_not_listening" and "Claude Code" in body["error"]
        status = await (await client.get(f"/api/evolve/agent/status?run_id={RUN}")).json()
        assert status["controls"] == {"pause": False, "message": False, "ask": False}

    _drive(repo, _body, configure=lambda app: _seed(app, repo, agent="claude_code"))


def test_a_message_reaches_only_a_listening_agent_and_reads_back_with_its_state(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)
    procs: list[_Proc] = []

    async def _body(client: TestClient) -> None:
        async def send(**body: Any) -> Any:
            return await client.post("/api/evolve/agent/message", json={"run_id": RUN, **body})

        empty = await send(agent_id="lead", text="   ")
        assert empty.status == 400 and (await empty.json())["code"] == "empty_message"
        long = await send(agent_id="lead", text="x" * (run_control.MAX_MESSAGE_CHARS + 1))
        assert long.status == 400 and (await long.json())["code"] == "message_too_long"
        bad = await send(agent_id="../lead", text="hi")
        assert bad.status == 400
        deaf = await send(agent_id="lead", text="make it blue")
        assert deaf.status == 409 and (await deaf.json())["code"] == "agent_not_listening"

        runner = RunControl(_folder(repo), emit=lambda _e: None)
        runner.listen("lead", "Thomas")
        sent = await send(agent_id="lead", text="  make it blue ")
        assert sent.status == 202
        receipt = (await sent.json())["receipt"]
        assert (receipt["agent_id"], receipt["text"], receipt["state"]) == ("lead", "make it blue", "queued")

        listing = await (await client.get(f"/api/evolve/agent/messages?run_id={RUN}")).json()
        assert listing["running"] is True and listing["paused"] is False and listing["listening"] == ["lead"]
        assert [row["state"] for row in listing["messages"]] == ["queued"]

        assert runner.inbox("lead").get_nowait() == "make it blue"  # the lead reads it between steps
        listing = await (await client.get(f"/api/evolve/agent/messages?run_id={RUN}")).json()
        [acked] = listing["messages"]
        assert acked["state"] == "acked" and isinstance(acked["acked_at"], int)

        second = (await (await send(agent_id="lead", text="and bigger")).json())["receipt"]
        procs[0].returncode = 0  # the run ended before the lead read it
        ended = await (await client.get(f"/api/evolve/agent/messages?run_id={RUN}")).json()
        assert ended["running"] is False and ended["listening"] == []
        states = {row["id"]: row["state"] for row in ended["messages"]}
        assert states == {receipt["id"]: "acked", second["id"]: "undelivered"}
        too_late = await send(agent_id="lead", text="hello?")
        assert too_late.status == 409 and (await too_late.json())["code"] == "run_not_active"

        unknown = await client.get("/api/evolve/agent/messages?run_id=run-never")
        assert unknown.status == 404 and (await unknown.json())["code"] == "run_not_found"
        assert (await client.get("/api/evolve/agent/messages")).status == 400

    _drive(repo, _body, configure=lambda app: procs.append(_seed(app, repo)))


def test_your_answer_reaches_the_question_once(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)

    async def _body(client: TestClient) -> None:
        folder = _folder(repo)
        (folder / "questions").mkdir(parents=True)
        question = {
            "question_id": "q-1",
            "question": "Dark or light?",
            "options": [{"label": "Dark", "description": "", "recommended": True}],
            "allow_free_text": False,
            "asked_at": 10,
            "state": "open",
        }
        (folder / "questions" / "q-1.json").write_text(json.dumps(question), encoding="utf-8")
        listing = await (await client.get(f"/api/evolve/agent/messages?run_id={RUN}")).json()
        assert [q["state"] for q in listing["questions"]] == ["open"]

        async def answer(**body: Any) -> Any:
            return await client.post("/api/evolve/agent/answer", json={"run_id": RUN, **body})

        assert (await answer(question_id="q-1", answer=" ")).status == 400
        missing = await answer(question_id="q-9", answer="Dark")
        assert missing.status == 404 and (await missing.json())["code"] == "question_not_found"
        ok = await answer(question_id="q-1", answer="Dark")
        assert ok.status == 200 and (await ok.json())["ok"] is True
        again = await answer(question_id="q-1", answer="Light")
        assert again.status == 409 and (await again.json())["code"] == "question_not_open"
        listing = await (await client.get(f"/api/evolve/agent/messages?run_id={RUN}")).json()
        [answered] = listing["questions"]
        assert (answered["state"], answered["answer"]) == ("answered", "Dark")

    _drive(repo, _body, configure=lambda app: _seed(app, repo))


def test_the_live_diff_shows_the_working_tree_against_head_and_new_files(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)
    (repo / "app.js").write_text("one\ntwo\nthree\n", encoding="utf-8")
    (repo / "keep.txt").write_text("unchanged\n", encoding="utf-8")
    _commit_all(repo)
    (repo / "app.js").write_text("one\nTWO\nthree\nfour\n", encoding="utf-8")
    (repo / "new page.html").write_text("<h1>hi</h1>\n<p>x</p>\n", encoding="utf-8")
    (repo / ".thomas" / "scratch").mkdir(parents=True)
    (repo / ".thomas" / "scratch" / "probe.js").write_text("scratch\n", encoding="utf-8")
    (repo / "big.bin").write_bytes(b"x" * (300 * 1024))

    async def _body(client: TestClient) -> None:
        response = await client.get(f"/api/evolve/agent/live-diff?run_id={RUN}")
        assert response.status == 200
        payload = await response.json()
        assert payload["ok"] is True and payload["project_root"] == str(repo) and payload["history"] is True
        files = {row["file"]: row for row in payload["files"]}
        assert set(files) == {"app.js", "new page.html", "big.bin"}  # Thomas's own scratch is left out
        app_js = files["app.js"]
        assert (app_js["added"], app_js["removed"], app_js["untracked"]) == (2, 1, False)
        assert "+TWO" in app_js["diff"] and "-two" in app_js["diff"] and "+four" in app_js["diff"]
        page = files["new page.html"]
        assert (page["added"], page["removed"], page["untracked"]) == (2, 0, True)
        assert "+<h1>hi</h1>" in page["diff"]
        assert files["big.bin"]["diff"] == "" and files["big.bin"].get("too_large") is True
        assert all(isinstance(row["mtime"], int) for row in payload["files"])

        by_conversation = await client.get("/api/evolve/agent/live-diff?conversation_id=c-live")
        assert by_conversation.status == 200
        assert {row["file"] for row in (await by_conversation.json())["files"]} == set(files)
        assert (await client.get("/api/evolve/agent/live-diff")).status == 400
        assert (await client.get("/api/evolve/agent/live-diff?run_id=run-gone")).status == 404
        assert (await client.get("/api/evolve/agent/live-diff?conversation_id=c-none")).status == 404

    _drive(repo, _body, configure=lambda app: _seed(app, repo))


def test_status_without_a_live_run_offers_no_controls(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)

    async def _body(client: TestClient) -> None:
        status = await (await client.get("/api/evolve/agent/status")).json()
        assert status["running"] is False and status["paused"] is False
        assert status["controls"] == {"pause": False, "message": False, "ask": False}

    _drive(repo, _body)


def test_a_conversation_names_the_branch_its_project_is_on(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _commit_all(repo)
    _rc, branch, _err = forge_code_git._run_git(repo, ["symbolic-ref", "--short", "HEAD"])
    conv = forge_code_store.new_conversation(repo, title="Branch check")

    async def _body(client: TestClient) -> None:
        payload = await (await client.get(f"/api/evolve/agent/conversations/{conv['id']}")).json()
        assert payload["conversation"]["branch"] == branch.strip() and branch.strip()

    _drive(repo, _body)


def test_send_names_the_control_folder_and_says_what_the_lead_can_take(tmp_path: Path, monkeypatch: Any) -> None:
    catalog = _new_repo(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    _init_repo(project)
    spawned: dict[str, Any] = {}

    class _EmptyStdout:
        async def readline(self) -> bytes:
            return b""

    class _FinishedProcess:
        pid = 1234
        returncode = 0
        stdout = _EmptyStdout()

        def __init__(self) -> None:
            self.stdin = _GateInput()

        async def wait(self) -> int:
            return 0

    async def _spawn(executable: str, *args: str, **kwargs: Any) -> _FinishedProcess:
        spawned.update({"env": kwargs["env"]})
        return _FinishedProcess()

    async def _access_token(_profile: str, *, secret_store: object) -> str:
        return "live-oauth-token"

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)
    monkeypatch.setattr(evolve_agent_http_support, "ensure_openai_codex_access_token", _access_token)

    async def _body(client: TestClient) -> None:
        response = await client.post(
            "/api/evolve/agent/send",
            json={"project_root": str(project), "project_choice": "picked", "message": "Build a page"},
        )
        assert response.status == 200
        payload = await response.json()
        assert payload["controls"] == {"pause": True, "message": True, "ask": True}
        expected = run_control.control_dir(catalog, payload["run_id"])
        assert spawned["env"][run_control.CONTROL_DIR_ENV] == str(expected)

    def _configure(app: web.Application) -> None:
        app[APP_SECRETS] = object()  # type: ignore[assignment]

    _drive(catalog, _body, configure=_configure)
