"""A task started with New chat gets a folder named after its first message.

Measured (w3-parallel-newtask, 2026-08-05): starting a task through the New
chat button produced the folder "Code task 2026-08-05 2020". The button calls
``conversation_new``, which binds a folder BEFORE any message exists, so the
folder is named from an empty title -- while the send-first path names folders
after the task sentence. Two doors into the same feature, two different names,
and the generic one is the one nobody can find again months later.

The fix: when the FIRST message arrives for a conversation whose bound folder
is task-born AND still carries the ``title_source: "empty"`` stamp written at
creation AND holds no user files yet, the folder is renamed to the
message-derived name and the registry is rebound. Any failure keeps the
generic name and never blocks the run. Folders with user files, folders the
user picked, and folders already named from a task sentence are never touched.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from aiohttp.test_utils import TestClient

from tests.test_evolve_agent_routes import _drive, _GateInput, _new_repo
from thomas.forge.anvil import forge_code_projects
from thomas.server.routes import evolve_agent_http_support, evolve_agent_routes


def _redirect_owned_root(monkeypatch: Any, tmp_path: Path) -> Path:
    owned = tmp_path / "dot-thomas"
    owned.mkdir()
    monkeypatch.setattr(forge_code_projects, "thomas_owned_root", lambda: owned)
    # The tmp catalog repo plays the Thomas checkout, so an unpicked new task
    # gets its own folder instead of being honoured as a separate repository.
    monkeypatch.setattr(evolve_agent_routes, "_is_thomas_source", lambda _p: True)

    async def _access_token(_profile: str, *, secret_store: object) -> str:
        return "test-oauth-token"

    monkeypatch.setattr(evolve_agent_http_support, "ensure_openai_codex_access_token", _access_token)
    return owned


def _mock_spawn(monkeypatch: Any) -> None:
    class _EmptyStdout:
        async def readline(self) -> bytes:
            return b""

    class _FinishedProcess:
        pid = 4321
        returncode = 0
        stdout = _EmptyStdout()

        def __init__(self) -> None:
            self.stdin = _GateInput()

        async def wait(self) -> int:
            return 0

    async def _spawn(executable: str, *args: str, **kwargs: Any) -> Any:
        return _FinishedProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)


def _marker(root: Path) -> dict[str, Any]:
    return json.loads((root / ".thomas" / "created-for-one-task.json").read_text(encoding="utf-8"))


def test_the_stamp_records_where_the_name_came_from(tmp_path: Path, monkeypatch: Any) -> None:
    _redirect_owned_root(monkeypatch, tmp_path)
    named = forge_code_projects.project_for_new_task("Build a pacman game")
    unnamed = forge_code_projects.project_for_new_task("")
    assert _marker(named)["title_source"] == "task"
    assert _marker(unnamed)["title_source"] == "empty"


def test_new_chat_folder_is_renamed_by_its_first_message(tmp_path: Path, monkeypatch: Any) -> None:
    catalog = _new_repo(tmp_path)
    _redirect_owned_root(monkeypatch, tmp_path)
    _mock_spawn(monkeypatch)

    async def _body(client: TestClient) -> None:
        created = await (
            await client.post("/api/evolve/agent/conversations/new", json={})
        ).json()
        assert created["ok"] is True, created
        cid = created["conversation"]["id"]
        generic_root = Path(created["conversation"]["project_root"])
        assert generic_root.name.startswith("Code task "), generic_root

        response = await client.post(
            "/api/evolve/agent/send",
            json={"conversation_id": cid, "message": "Build a pacman game with two ghosts", "model": "claude:sonnet"},
        )
        payload = await response.json()
        assert response.status == 200, payload
        bound = Path(payload["project_root"])
        assert bound.name.startswith("Build a pacman game"), (
            f"folder kept its generic New-chat name: {bound}"
        )
        assert not generic_root.exists(), "the generic folder was left behind"

        # The conversation still loads, from its renamed home.
        fetched = await (await client.get(f"/api/evolve/agent/conversations/{cid}")).json()
        assert fetched["ok"] is True, fetched
        assert Path(fetched["conversation"]["project_root"]) == bound

    _drive(catalog, _body)


def test_a_folder_with_user_files_is_never_renamed(tmp_path: Path, monkeypatch: Any) -> None:
    catalog = _new_repo(tmp_path)
    _redirect_owned_root(monkeypatch, tmp_path)
    _mock_spawn(monkeypatch)

    async def _body(client: TestClient) -> None:
        created = await (
            await client.post("/api/evolve/agent/conversations/new", json={})
        ).json()
        cid = created["conversation"]["id"]
        root = Path(created["conversation"]["project_root"])
        (root / "notes.txt").write_text("mine\n", encoding="utf-8")

        response = await client.post(
            "/api/evolve/agent/send",
            json={"conversation_id": cid, "message": "Build a pacman game", "model": "claude:sonnet"},
        )
        payload = await response.json()
        assert response.status == 200, payload
        assert Path(payload["project_root"]) == root.resolve()
        assert (root / "notes.txt").exists()

    _drive(catalog, _body)


def test_a_picked_project_is_never_renamed(tmp_path: Path, monkeypatch: Any) -> None:
    catalog = _new_repo(tmp_path)
    _redirect_owned_root(monkeypatch, tmp_path)
    _mock_spawn(monkeypatch)
    mine = forge_code_projects.create_named_project("my-website")

    async def _body(client: TestClient) -> None:
        created = await (
            await client.post(
                "/api/evolve/agent/conversations/new",
                json={"project_root": str(mine), "project_choice": "picked"},
            )
        ).json()
        cid = created["conversation"]["id"]

        response = await client.post(
            "/api/evolve/agent/send",
            json={"conversation_id": cid, "message": "Build a pacman game", "model": "claude:sonnet"},
        )
        payload = await response.json()
        assert response.status == 200, payload
        assert Path(payload["project_root"]) == mine.resolve()
        assert mine.exists()

    _drive(catalog, _body)
