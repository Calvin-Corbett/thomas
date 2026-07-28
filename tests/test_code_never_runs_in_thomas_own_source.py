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
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiohttp import CookieJar, web
from aiohttp.test_utils import TestClient, TestServer

from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.forge.anvil.forge_code_git import _run_git
from thomas.server.app_keys import APP_SECRETS
from thomas.server.routes import evolve_agent_http_support
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
