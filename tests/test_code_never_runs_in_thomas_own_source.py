"""Code must never run against Thomas's own source checkout.

``send`` already calls this a HARD SAFETY NET and applies it twice: once for a
conversation id with nothing behind it, once for a brand-new conversation. The
third branch -- an id that DOES resolve, i.e. every "continue this task" -- takes
its project root straight from the stored conversation and never checks it.

That branch is reachable today, not hypothetically. Measured against the running
server on this workspace: 20 Code conversations resolve to ``C:\\Users\\corbe\\Thomas``,
three of them with real turns, and the changes endpoint offers one of them
``notes.txt`` -- a file sitting in the repository root because a Code task wrote
it there. Revert is ``git checkout -- <file>``, and for an untracked file it is a
delete, so continuing one of those tasks edits the product source and the Revert
button removes files from it.

Refusing is the right answer rather than silently substituting a different
folder: the handler immediately above already returns 409
``project_change_requires_new_conversation`` because a conversation's project is
not allowed to move underneath it. Quietly moving it here would contradict that
rule while claiming to enforce a safety one.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiohttp import CookieJar, web
from aiohttp.test_utils import TestClient, TestServer

from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.forge.anvil.forge_code_git import _run_git
from thomas.server.app_keys import APP_SECRETS
from thomas.server.routes import evolve_agent_http_support, evolve_agent_routes
from thomas.server.routes.deliverable_aiohttp import register_deliverable_routes
from thomas.server.routes.evolve_agent_routes import register_evolve_agent_routes


def _init_repo(root: Path) -> None:
    _run_git(root, ["init"])
    _run_git(root, ["config", "user.email", "test@example.com"])
    _run_git(root, ["config", "user.name", "Forge Test"])
    _run_git(root, ["config", "commit.gpgsign", "false"])
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    _run_git(root, ["add", "-A"])
    _run_git(root, ["commit", "-m", "init"])


def _drive(catalog: Path, body: Callable[[TestClient], Awaitable[Any]]) -> Any:
    async def _runner() -> Any:
        app = web.Application()
        preview = register_deliverable_routes(app, require_api_access=lambda _request: None)
        register_evolve_agent_routes(
            app,
            require_api_access=lambda _request: None,
            root_resolver=lambda: catalog,
        )
        app[APP_SECRETS] = object()  # type: ignore[assignment]
        client = TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True))
        await client.start_server()
        preview.configure(main_origin=str(client.make_url("/")).rstrip("/"))
        try:
            return await body(client)
        finally:
            await client.close()
            await preview.stop()

    prior = os.environ.get("THOMAS_DATA_DIR")
    os.environ["THOMAS_DATA_DIR"] = str(catalog.parent / "thomas-test-data")
    try:
        return asyncio.run(_runner())
    finally:
        if prior is None:
            os.environ.pop("THOMAS_DATA_DIR", None)
        else:
            os.environ["THOMAS_DATA_DIR"] = prior


def test_continuing_a_conversation_bound_to_the_source_repo_never_launches(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    catalog = tmp_path / "thomas-source"
    catalog.mkdir()
    _init_repo(catalog)

    # This fixture repo IS "Thomas's own checkout" for the duration of the test.
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: catalog.resolve())

    spawns: list[dict[str, Any]] = []

    async def _spawn(_executable: str, *_args: str, **kwargs: Any) -> Any:
        spawns.append({"cwd": kwargs.get("cwd")})
        raise AssertionError(f"Code launched against {kwargs.get('cwd')} -- Thomas's own source tree")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)

    async def _access_token(_profile: str, *, secret_store: object) -> str:
        return "live-oauth-token"

    monkeypatch.setattr(evolve_agent_http_support, "ensure_openai_codex_access_token", _access_token)

    # A conversation that already lives in the source checkout, exactly as the
    # 20 on this workspace do: a real file plus a registry row pointing at it.
    conv = forge_code_store.new_conversation(catalog, title="create notes.txt")
    cid = conv["id"]
    forge_code_projects.bind_conversation(catalog, cid, catalog)

    async def _body(client: TestClient) -> None:
        response = await client.post(
            "/api/evolve/agent/send",
            json={
                "conversation_id": cid,
                "message": "add another bullet to notes.txt",
                "model": "codex:gpt",
                "model_id": "gpt-5.6-codex",
                "request_id": "source-repo-guard",
            },
        )
        assert not spawns, f"Code must not launch in its own source tree (cwd={spawns})"
        assert response.status == 409, f"expected a refusal, got {response.status}"
        payload = await response.json()
        assert payload["ok"] is False
        assert payload["code"] == "project_is_thomas_source"
        # Nothing was recorded as having run.
        assert "run_id" not in payload

    _drive(catalog, _body)


def test_send_refuses_when_source_inspection_times_out_on_each_branch(tmp_path: Path, monkeypatch: Any) -> None:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    _init_repo(catalog)
    conv = forge_code_store.new_conversation(catalog, title="build")
    forge_code_projects.bind_conversation(catalog, conv["id"], catalog)
    other = tmp_path / "other"
    other.mkdir()
    _init_repo(other)
    calls: list[int] = []

    def unknown() -> Path:
        calls.append(threading.get_ident())
        raise forge_code_projects.ForgeCodeInspectionUnavailable("Thomas source root could not be inspected")

    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", unknown)
    monkeypatch.setattr(evolve_agent_routes, "_new_task_project_root", lambda _root, _message: other)
    monkeypatch.setattr(evolve_agent_routes, "_chosen_project", lambda *_args, **_kwargs: other)

    async def _body(client: TestClient) -> None:
        loop_thread = threading.get_ident()
        for conversation_id in ("", conv["id"], "missing-conversation"):
            response = await client.post(
                "/api/evolve/agent/send",
                json={"conversation_id": conversation_id, "message": "build", "model": "codex:gpt"},
            )
            assert response.status == 400
            assert (await response.json())["code"] == "invalid_project_root"
        assert len(calls) == 3
        assert all(thread != loop_thread for thread in calls)

    _drive(catalog, _body)


def test_installed_copy_can_set_up_history_on_new_conversation(tmp_path: Path, monkeypatch: Any) -> None:
    catalog = tmp_path / "site-packages"
    catalog.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: None)

    async def _body(client: TestClient) -> None:
        response = await client.post(
            "/api/evolve/agent/conversations/new",
            json={"project_root": str(project), "history_choice": "setup"},
        )
        assert response.status == 200, await response.text()
        payload = await response.json()
        assert payload["conversation"]["project_root"] == str(project.resolve())
        assert (project / ".git").is_dir()
        assert payload["conversation"]["id"]

    _drive(catalog, _body)


def test_send_sets_up_history_off_the_event_loop(tmp_path: Path, monkeypatch: Any) -> None:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    loop_thread: list[int] = []
    setup_threads: list[int] = []
    finished_setup = False
    original = forge_code_projects.initialize_history

    def initialize(path: Path) -> Path:
        nonlocal finished_setup
        setup_threads.append(threading.get_ident())
        result = original(path)
        finished_setup = True
        return result

    def source_root() -> Path | None:
        if finished_setup:
            raise forge_code_projects.ForgeCodeInspectionUnavailable("Thomas source root could not be inspected")
        return None

    monkeypatch.setattr(forge_code_projects, "initialize_history", initialize)
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", source_root)

    async def _body(client: TestClient) -> None:
        loop_thread.append(threading.get_ident())
        response = await client.post(
            "/api/evolve/agent/send",
            json={"project_root": str(project), "history_choice": "setup", "message": "build"},
        )
        assert response.status == 400, await response.text()
        assert (await response.json())["code"] == "invalid_project_root"

    _drive(catalog, _body)
    assert (project / ".git").is_dir()
    assert len(setup_threads) == 1
    assert setup_threads[0] != loop_thread[0]


def test_a_normal_project_still_runs(tmp_path: Path, monkeypatch: Any) -> None:
    """The other direction: the guard must not refuse ordinary work.

    Same setup, same continue-an-existing-conversation branch -- the only
    difference is that the conversation lives in a project that is not the
    source checkout. It has to launch.
    """

    catalog = tmp_path / "thomas-source"
    catalog.mkdir()
    _init_repo(catalog)
    project = tmp_path / "a-real-project"
    project.mkdir()
    _init_repo(project)

    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: catalog.resolve())

    launched: dict[str, Any] = {}

    class _EmptyStdout:
        async def read(self, _n: int = -1) -> bytes:
            return await self.readline()

        async def readline(self) -> bytes:
            return b""

    class _GateInput:
        def __init__(self) -> None:
            self.data = b""

        def write(self, data: bytes) -> None:
            self.data += data

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

    class _FinishedProcess:
        pid = 4321
        returncode = 0
        stdout = _EmptyStdout()

        def __init__(self) -> None:
            self.stdin = _GateInput()

        async def wait(self) -> int:
            return 0

    async def _spawn(_executable: str, *_args: str, **kwargs: Any) -> Any:
        launched["cwd"] = kwargs.get("cwd")
        proc = _FinishedProcess()
        proc.start_token = kwargs["env"]["THOMAS_CODE_START_TOKEN"]
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)

    async def _access_token(_profile: str, *, secret_store: object) -> str:
        return "live-oauth-token"

    monkeypatch.setattr(evolve_agent_http_support, "ensure_openai_codex_access_token", _access_token)

    conv = forge_code_store.new_conversation(project, title="a real task")
    cid = conv["id"]
    forge_code_projects.bind_conversation(catalog, cid, project)

    async def _body(client: TestClient) -> None:
        response = await client.post(
            "/api/evolve/agent/send",
            json={
                "conversation_id": cid,
                "message": "keep going",
                "model": "codex:gpt",
                "model_id": "gpt-5.6-codex",
                "request_id": "normal-project",
            },
        )
        assert response.status == 200, await response.text()
        payload = await response.json()
        assert payload["project_root"] == str(project.resolve())
        assert launched["cwd"] == str(project.resolve())

    _drive(catalog, _body)


def test_a_self_edit_thread_from_redesign_is_let_through_the_guard(tmp_path: Path, monkeypatch: Any) -> None:
    """Redesign is "edit this thing however I say" (the owner, 2026-09-06): "thomas
    must be able to change every single thing about him and it work". The guard
    above stays for every accidental way into the checkout; a thread the person
    opened on purpose through Redesign is marked ``self_edit`` and runs there."""
    catalog = tmp_path / "thomas-source"
    catalog.mkdir()
    _init_repo(catalog)
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: catalog.resolve())

    spawns: list[dict[str, Any]] = []

    async def _spawn(_executable: str, *_args: str, **kwargs: Any) -> Any:
        spawns.append({"cwd": kwargs.get("cwd")})
        raise RuntimeError("stop here: the launch itself is the proof")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)

    async def _access_token(_profile: str, *, secret_store: object) -> str:
        return "live-oauth-token"

    monkeypatch.setattr(evolve_agent_http_support, "ensure_openai_codex_access_token", _access_token)

    # Since 07bdda37 a self-edit names the exact files it may change and is checked
    # against the source's own protected-file policy, so the source carries both.
    (catalog / "thomas").mkdir()
    (catalog / "thomas" / "menu.py").write_text("PLUS = True\n", encoding="utf-8")
    (catalog / "agent_safety.toml").write_text('[protected]\npolicy_files=["agent_safety.toml"]\n', encoding="utf-8")
    (catalog / "plans" / "thomas").mkdir(parents=True)
    (catalog / "plans" / "thomas" / "WORKBOARD.md").write_text("## Agent Claims\n", encoding="utf-8")

    async def _body(client: TestClient) -> None:
        created = await client.post(
            "/api/evolve/agent/conversations/new",
            json={"self_edit": True, "project_identity": "thomas-source", "self_edit_scope": ["thomas/menu.py"]},
        )
        conv = (await created.json())["conversation"]
        assert conv.get("self_edit") is True
        cid = conv["id"]
        response = await client.post(
            "/api/evolve/agent/send",
            json={
                "conversation_id": cid,
                "message": "turn the plus into a menu",
                "model": "codex:gpt",
                "model_id": "gpt-5.6-codex",
                "request_id": "self-edit-allowed",
            },
        )
        # The stub raises once Code is launched, so the run itself ends in an
        # error; the launch, in the checkout, is the proof.
        assert response.status != 409, await response.text()
        # Since the self-edit isolation landed (2026-09-07) a self-edit run does not
        # start IN the checkout: it starts in its own candidate copy under the data
        # dir and the checkout stays untouched until Apply. The launch itself, no
        # 409, is the proof the guard let it through.
        assert spawns, spawns
        cwd = Path(str(spawns[0]["cwd"])).resolve()
        assert cwd != catalog.resolve(), spawns
        assert "self-edit" in cwd.as_posix(), spawns

    _drive(catalog, _body)
