"""The workspace row, off: its 35 routes answer 404, none of its code has loaded, and the files it reads stay.

``thomas.server.rows.workspace`` holds three families that were never one feature: the list of workspaces and their
members (``/api/workspaces``), the linked-projects registry that My Stuff, the Chat and Code project pickers and the
Library read (``/api/local``), and the notes left on lines of source (``/api/source-annotations``). They move as one row.

The routes of ``thomas.server.routes.local_projects_aiohttp`` and of ``thomas.server.routes.source_annotation_routes`` are
what a feature test reaches. ``tests/test_server_local_projects_routes.py`` and ``tests/test_source_annotation_routes.py``
are those, and ``tests/test_workspace_rbac_multi_tenant.py`` holds the roles.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import tomllib

from tests.row_off_fixture import ask_as_a_remote_caller, ask_from_another_machine, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

# Written out, because a list worked out from the row would agree with whatever the row did. Every id is one that does not
# exist. A project action launches a program and the folder picker opens a window, so neither may be asked of a real one.
WORKSPACES = {
    "GET /api/workspaces": "GET /api/workspaces",
    "POST /api/workspaces": "POST /api/workspaces",
    "GET /api/workspaces/current": "GET /api/workspaces/current",
    "GET /api/workspaces/current/membership": "GET /api/workspaces/current/membership",
    "POST /api/workspaces/invites/accept": "POST /api/workspaces/invites/accept",
    "GET /api/workspaces/{workspace_id}/members": "GET /api/workspaces/w1/members",
    "POST /api/workspaces/{workspace_id}/invites": "POST /api/workspaces/w1/invites",
    "GET /api/workspaces/{workspace_id}/invites": "GET /api/workspaces/w1/invites",
    "PATCH /api/workspaces/{workspace_id}/members/{user_id}": "PATCH /api/workspaces/w1/members/u1",
    "DELETE /api/workspaces/{workspace_id}/members/{user_id}": "DELETE /api/workspaces/w1/members/u1",
}
PROJECTS = {
    "GET /api/local/projects": "GET /api/local/projects",
    "GET /api/local/projects/boards": "GET /api/local/projects/boards",
    "POST /api/local/projects/import": "POST /api/local/projects/import",
    "POST /api/local/projects/link": "POST /api/local/projects/link",
    "POST /api/local/projects/pick-folder": "POST /api/local/projects/pick-folder",
    "GET /api/local/projects/{project_id}": "GET /api/local/projects/p1",
    "PATCH /api/local/projects/{project_id}/layout": "PATCH /api/local/projects/p1/layout",
    "POST /api/local/projects/{project_id}/action": "POST /api/local/projects/p1/action",
    "POST /api/local/projects/{project_id}/launch": "POST /api/local/projects/p1/launch",
    "PATCH /api/local/projects/{project_id}/context": "PATCH /api/local/projects/p1/context",
    "POST /api/local/projects/{project_id}/chats": "POST /api/local/projects/p1/chats",
    "PATCH /api/local/projects/{project_id}/chats/{session_id}": "PATCH /api/local/projects/p1/chats/s1",
    "DELETE /api/local/projects/{project_id}/chats/{session_id}": "DELETE /api/local/projects/p1/chats/s1",
    "POST /api/local/projects/{project_id}/library": "POST /api/local/projects/p1/library",
    "DELETE /api/local/projects/{project_id}/library/{entry_id}": "DELETE /api/local/projects/p1/library/e1",
    "GET /api/local/projects/{project_id}/resume": "GET /api/local/projects/p1/resume",
    "POST /api/local/projects/{project_id}/shares": "POST /api/local/projects/p1/shares",
    "DELETE /api/local/projects/{project_id}/shares/{share_id}": "DELETE /api/local/projects/p1/shares/sh1",
    "GET /api/local/project-shares/{share_id}": "GET /api/local/project-shares/sh1",
    "DELETE /api/local/projects/{project_id}": "DELETE /api/local/projects/p1",
}
NOTES = {
    "GET /api/source-annotations": "GET /api/source-annotations",
    "POST /api/source-annotations": "POST /api/source-annotations",
    "GET /api/source-annotations/source": "GET /api/source-annotations/source",
    "POST /api/source-annotations/{annotation_id}/conversation": "POST /api/source-annotations/a1/conversation",
    "POST /api/source-annotations/{annotation_id}/diff": "POST /api/source-annotations/a1/diff",
}
ROUTES = {**WORKSPACES, **PROJECTS, **NOTES}
# Open to a caller with no token in remote mode. A share link is given to someone else and answers to its own token, so it
# is open on purpose, and answers 404 for a share it does not know. The two source note reads have no guard at all. That
# is a gap, found while moving this row and left as it was: one of them reads a file under the repository folder for any
# caller. When they get a guard these two must answer 401 and move out of this list.
OPEN = {
    "GET /api/local/project-shares/sh1": 404,
    "GET /api/source-annotations": 200,
    "GET /api/source-annotations/source": 400,
}
OWN_CODE = (
    "thomas.server.rows.workspace",
    "thomas.server.workspace.router",
    "thomas.server.workspace.db",
    "thomas.server.routes.local_projects_aiohttp",
    "thomas.server.routes.local_project_workspace",
    "thomas.server.routes.source_annotation_routes",
)
LISTED = {*ROUTES, "HEAD /api/workspaces", "HEAD /api/workspaces/current", "HEAD /api/local/projects"}

ROW = "workspace"
# The folder picker opens a window on a real desktop and waits for a person. With tkinter missing it answers 409 at once.
NO_WINDOW = 'import sys\n\nsys.modules["tkinter"] = None\n\n'


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("workspace-off")
    started, found = start_with_one_row_off(
        ROW, list(ROUTES.values()), folder, reading=NO_WINDOW + "def reading():\n    return None\n\n\n"
    )
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("workspace-remote")
    started, found = ask_as_a_remote_caller(ROW, list(ROUTES.values()), folder, ahead=NO_WINDOW)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture(scope="module")
def elsewhere(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("workspace-elsewhere")
    started, found = ask_from_another_machine(ROW, list(PROJECTS.values()), folder, ahead=NO_WINDOW)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_all_35_routes_without_a_restart(seen: dict[str, Any]) -> None:
    """Many answer 404 themselves for an id that does not exist, so only ``live_on`` tells those apart."""
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert len(ROUTES) == 35


def test_on_the_real_stores_the_routes_answer_as_the_handlers_do(seen: dict[str, Any]) -> None:
    """Each status below is a handler's, read to its reason, not the row's absence."""
    on = seen["on"]
    assert on["GET /api/workspaces"] == 200
    assert on["GET /api/workspaces/current"] == 403  # you are in no workspace yet
    assert on["POST /api/workspaces"] == 422  # it wants a name
    assert on["GET /api/local/projects"] == 200
    assert on["GET /api/local/projects/boards"] == 200
    assert on["POST /api/local/projects/pick-folder"] == 409  # no window to open here
    assert on["GET /api/source-annotations"] == 200
    assert on["GET /api/source-annotations/source"] == 400  # it wants a file


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    guarded = [ask for ask in ROUTES.values() if ask not in OPEN]
    assert remote["no_token"] == {**dict.fromkeys(guarded, 401), **OPEN}
    assert 401 not in {remote["with_token"][ask] for ask in guarded}, remote["with_token"]


def test_the_20_project_routes_answer_only_a_caller_on_this_machine(elsewhere: dict[str, Any]) -> None:
    """Remote mode lets a token through, but these start a program, open a folder window and delete, so they also want loopback.

    The token is sent every time, so the api guard lets each ask through and only the loopback guard can give the 403. Asked
    from this machine with the same token, none gives 403, so a refusal below is not a server that refuses everyone.
    """
    assert elsewhere["row"]["state"] == "active", elsewhere["row"]
    assert len(PROJECTS) == 20
    assert elsewhere["elsewhere"] == dict.fromkeys(PROJECTS.values(), 403)
    assert 403 not in elsewhere["here"].values(), elsewhere["here"]


def test_the_words_send_you_to_the_project_menu_in_build_where_it_is() -> None:
    """The menu beside the message box is hidden in Chat and shows in Build, so a sentence that sends you to Chat is false."""
    row = next(
        r for r in tomllib.loads((ROOT / "thomas/server/rows/default.toml").read_text("utf-8"))["row"] if r["id"] == ROW
    )
    for field in ("about", "off_means"):
        assert "message box in Chat" not in row[field], row[field]
    assert "message box in Build" in row["about"]
    assert (
        "message box in Build (it does not show in Chat) says Thomas could not read your library just now"
        in row["off_means"]
    )


OFF_TEST = "tests/test_turning_workspace_off_touches_only_its_routes.py"
PROJECT_TESTS = "tests/test_server_local_projects_routes.py"
NOTE_TESTS = "tests/test_source_annotation_routes.py"


@pytest.mark.parametrize(
    ("changed", "runs"),
    [
        ("thomas/server/rows/workspace.py", (OFF_TEST, PROJECT_TESTS, NOTE_TESTS)),
        ("thomas/server/workspace/router.py", (OFF_TEST,)),
        ("thomas/server/routes/local_projects_aiohttp.py", (OFF_TEST, PROJECT_TESTS)),
        ("thomas/server/routes/source_annotation_routes.py", (OFF_TEST, NOTE_TESTS)),
    ],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str, runs: tuple[str, ...]) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    for name in runs:
        assert name in chosen
