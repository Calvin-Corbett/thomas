"""A new Code task never lands in the previous task's folder uninvited.

Measured live on 2026-08-05, driving the real UI with two back-to-back tasks:
task A got its own folder (named after its request), and task B -- started with
the "New chat" button, nothing picked -- was bound to A's folder. A's finished
run then listed B's ``goodbye.html`` under "THOMAS MADE 2 THINGS". The
per-task-folder isolation only ever held for the FIRST task of a session: the
client keeps the last root it was handed and sends it back as ``project_root``
on the next new task, where it is indistinguishable from a deliberate pick.
This is the shared-drawer defect reborn, with the first task's folder playing
the drawer -- and the same cure applies.

The server now stamps folders minted by ``project_for_new_task`` and treats a
stamped folder arriving WITHOUT ``project_choice: "picked"`` as the absence of
a choice: the new task gets a folder of its own. An explicit pick -- the folder
dialog, a project card, a typed project name, all of which now send the flag --
is honoured exactly as before, and so is every folder the user made or chose
themselves (those carry no stamp).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiohttp.test_utils import TestClient

from tests.test_evolve_agent_routes import _drive, _new_repo
from thomas.forge.anvil import forge_code_projects


def _redirect_owned_root(monkeypatch: Any, tmp_path: Path) -> Path:
    owned = tmp_path / "dot-thomas"
    owned.mkdir()
    monkeypatch.setattr(forge_code_projects, "thomas_owned_root", lambda: owned)
    return owned


def test_a_task_born_folder_is_stamped_and_a_user_named_one_is_not(
    tmp_path: Path, monkeypatch: Any
) -> None:
    _redirect_owned_root(monkeypatch, tmp_path)
    task_folder = forge_code_projects.project_for_new_task("Build hello.html with one button")
    named_folder = forge_code_projects.create_named_project("my-website")
    assert forge_code_projects.is_task_born_project(task_folder) is True
    assert forge_code_projects.is_task_born_project(named_folder) is False


def test_a_leftover_task_folder_is_not_a_choice(tmp_path: Path, monkeypatch: Any) -> None:
    catalog = _new_repo(tmp_path)
    _redirect_owned_root(monkeypatch, tmp_path)
    stale = forge_code_projects.project_for_new_task("Build hello.html with one button")
    forge_code_projects.ensure_git_repo(stale)

    async def _body(client: TestClient) -> None:
        # The old client's replay: the previous task's folder arrives dressed as
        # an explicit project_root, with no evidence anyone picked it.
        response = await client.post(
            "/api/evolve/agent/conversations/new",
            json={"title": "Second task", "project_root": str(stale)},
        )
        payload = await response.json()
        assert response.status == 200, payload
        bound = Path(payload["conversation"]["project_root"]).resolve()
        assert bound != stale.resolve(), (
            "a leftover task-born folder was honoured as if somebody chose it"
        )

    _drive(catalog, _body)


def test_an_explicit_pick_of_a_task_born_folder_is_honoured(
    tmp_path: Path, monkeypatch: Any
) -> None:
    # The control that keeps this from becoming a gate: the same folder, sent
    # WITH the pick flag a real click now carries, binds exactly as requested.
    catalog = _new_repo(tmp_path)
    _redirect_owned_root(monkeypatch, tmp_path)
    stale = forge_code_projects.project_for_new_task("Build hello.html with one button")
    forge_code_projects.ensure_git_repo(stale)

    async def _body(client: TestClient) -> None:
        response = await client.post(
            "/api/evolve/agent/conversations/new",
            json={"title": "On purpose", "project_root": str(stale), "project_choice": "picked"},
        )
        payload = await response.json()
        assert response.status == 200, payload
        assert Path(payload["conversation"]["project_root"]).resolve() == stale.resolve()

    _drive(catalog, _body)


def test_a_folder_the_user_made_themselves_still_sticks(tmp_path: Path, monkeypatch: Any) -> None:
    # A user-named project carries no stamp, so the sticky-default behaviour
    # people rely on -- keep working in MY project -- is untouched even when the
    # client sends it without the flag (old localStorage, old client).
    catalog = _new_repo(tmp_path)
    _redirect_owned_root(monkeypatch, tmp_path)
    mine = forge_code_projects.create_named_project("my-website")
    forge_code_projects.ensure_git_repo(mine)

    async def _body(client: TestClient) -> None:
        response = await client.post(
            "/api/evolve/agent/conversations/new",
            json={"title": "In my project", "project_root": str(mine)},
        )
        payload = await response.json()
        assert response.status == 200, payload
        assert Path(payload["conversation"]["project_root"]).resolve() == mine.resolve()

    _drive(catalog, _body)
