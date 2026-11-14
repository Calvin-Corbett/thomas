"""The project_change row, off: ``GET /api/self/projects/{conversation_id}/change`` answers 404, nothing else moves.

The route reads what a Thomas project changed in its private copy, and no page calls it. The words of the row live in
``thomas/server/rows/default.toml``, and each sentence of them names the test that shows it, in this file or in
``tests/test_a_stopped_project_shows_its_change.py``, which builds its own app and calls the registrar directly.

The row is ``thomas.server.rows.project_change`` and its code is ``thomas.server.routes.self_project_change_routes``,
and those names are how a check finds this file when either changes.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import ast
import re
from typing import Any

import pytest
import tomllib

from tests.row_off_fixture import ask_as_a_remote_caller, ask_from_another_machine, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

ROW = "project_change"
PATH = "/api/self/projects/{conversation_id}/change"
# An id the route refuses by its first character. On a row that is off the same address is no route at all, so the two
# answers differ: 400 from the handler when it is on and 404 when it is off. A well-formed id gives 404 either way.
ASK = "GET /api/self/projects/-bad/change"
OWN_CODE = ("thomas.server.rows.project_change", "thomas.server.routes.self_project_change_routes")
# aiohttp lists a HEAD beside each GET.
LISTED = {f"GET {PATH}", f"HEAD {PATH}"}


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("change-off")
    started, found = start_with_one_row_off(ROW, [ASK], folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("change-remote")
    started, found = ask_as_a_remote_caller(ROW, [ASK], folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture(scope="module")
def elsewhere(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("change-elsewhere")
    started, found = ask_from_another_machine(ROW, [ASK], folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_the_route_answers_404_and_is_not_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == {ASK: 404}
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_the_project_routes_that_stay_in_the_server_are_there_with_the_row_off(seen: dict[str, Any]) -> None:
    """The change route reads through their module, which is loaded and answering whether this is on or off."""
    assert {
        "GET /api/self/projects",
        "POST /api/self/projects",
        "POST /api/self/projects/{conversation_id}/send-back",
        "POST /api/self/projects/{conversation_id}/hand-in-again",
        "POST /api/self/projects/{conversation_id}/stop",
    } <= set(seen["listed_off"])
    assert "thomas.server.routes.self_project_routes" in seen["loaded"]


def test_turning_it_on_brings_the_route_back_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == {ASK: 400}


def test_turned_off_on_a_running_server_the_route_goes_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its route goes and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == {ASK: 404}
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_the_route_asks_for_this_machine_and_not_for_the_token(remote: dict[str, Any]) -> None:
    """It was guarded by the machine alone and still is, so a caller on this machine is let in with no token at all.

    The test client is on this machine, and the handler refuses the id, which is the route answering. The caller on
    another machine, with the token, is the next test.
    """
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == {ASK: 400}
    assert remote["with_token"] == {ASK: 400}


def test_a_caller_on_another_machine_is_refused_even_with_the_token(elsewhere: dict[str, Any]) -> None:
    """The token is sent each time, so it lets a request past the server and only the machine guard can give the 403.

    Asked from this machine with the same token the route answers 400 to the id, so the 403 is not a server that
    refuses everyone.
    """
    assert elsewhere["row"]["state"] == "active", elsewhere["row"]
    assert elsewhere["elsewhere"] == {ASK: 403}
    assert elsewhere["here"] == {ASK: 400}


def test_the_row_stops_nothing_and_writes_nothing() -> None:
    """The route only reads, and the row has no stop step to touch a project's copy."""
    source = (ROOT / "thomas" / "server" / "rows" / "project_change.py").read_text(encoding="utf-8")
    code = ast.unparse(ast.parse(source))
    for word in ("on_stopped", "on_ready", "open(", "write", "unlink", "Thread", "create_task"):
        assert word not in code, word


def test_no_page_in_thomas_asks_for_a_projects_change() -> None:
    """Nothing in the web layer, the extensions, the desktop shell or the scripts names the address."""
    asked = [
        str(path.relative_to(ROOT))
        for folder in ("thomas/server/web", "extensions", "desktop", "apps", "scripts")
        if (ROOT / folder).is_dir()
        for path in (ROOT / folder).rglob("*")
        if path.is_file()
        and path.suffix in {".js", ".html", ".mjs", ".ts", ".tsx", ".py", ".ps1"}
        and re.search(r"api/self/projects[^\n]*/change|/change\b[^\n]*api/self/projects", _text(path))
    ]
    assert asked == []


def _text(path: Any) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def test_a_change_to_the_row_or_its_routes_runs_their_proofs() -> None:
    own = "tests/test_turning_project_change_off_touches_only_its_routes.py"
    feature = "tests/test_a_stopped_project_shows_its_change.py"
    for changed in ("thomas/server/rows/project_change.py", "thomas/server/routes/self_project_change_routes.py"):
        chosen = select(ROOT, [changed]).files
        assert own in chosen, changed
        assert feature in chosen, changed


# The words, a sentence at a time. Each is shown by the test named beside it, in this file or in the route tests. A new,
# changed or dropped sentence fails here until the list has it with a test that shows it.
PATCH_TEST = "test_stopped_project_exposes_the_exact_applicable_patch_without_changing_its_green"
WORDS = {
    "about": {
        "Lets other programs read the whole change a Thomas project made in its private copy: the files it changed and "
        "the patch.": (PATCH_TEST, "test_turning_it_on_brings_the_route_back_without_a_restart"),
        "It does not hand the project in or change the copy, and it also works for a project you stopped.": (
            PATCH_TEST,
            "test_reading_change_does_not_rewrite_the_green_base_after_dev_was_merged",
        ),
        "Only a program on this computer can ask.": (
            "test_a_caller_on_another_machine_is_refused_even_with_the_token",
            "test_non_loopback_caller_is_refused_by_the_same_guard",
        ),
        "No page in Thomas shows it.": ("test_no_page_in_thomas_asks_for_a_projects_change",),
    },
    "off_means": {
        "While this is off, nothing you use changes, because no page in Thomas reads a project's change.": (
            "test_no_page_in_thomas_asks_for_a_projects_change",
        ),
        "A program that asks is told there is no such address.": (
            "test_with_the_row_off_the_route_answers_404_and_is_not_listed",
        ),
        "Projects, their private copies and their changes are not touched.": (
            "test_the_row_stops_nothing_and_writes_nothing",
        ),
        "The list of Thomas projects, and starting, sending back, handing in again and stopping a project, are separate "
        "and carry on.": ("test_the_project_routes_that_stay_in_the_server_are_there_with_the_row_off",),
        "Turning this on again brings it back with no restart.": (
            "test_turning_it_on_brings_the_route_back_without_a_restart",
        ),
    },
    "stop_now": {
        "A request for a project's change that is still being read will fail, and may need sending again.": (
            "test_turned_off_on_a_running_server_the_route_goes_and_the_code_stays_loaded",
        ),
    },
}
FILES = (
    "test_turning_project_change_off_touches_only_its_routes.py",
    "test_a_stopped_project_shows_its_change.py",
)


def _row() -> dict[str, Any]:
    rows = tomllib.loads((ROOT / "thomas/server/rows/default.toml").read_text("utf-8"))["row"]
    return next(row for row in rows if row["id"] == ROW)


@pytest.mark.parametrize("field", ["about", "off_means", "stop_now"])
def test_every_sentence_of_the_words_names_the_test_that_shows_it(field: str) -> None:
    text = "".join((ROOT / "tests" / name).read_text("utf-8") for name in FILES)
    assert re.split(r"(?<=\.)\s+", _row()[field]) == list(WORDS[field])
    named = {name for names in WORDS[field].values() for name in names}
    assert {name for name in named if f"def {name}(" not in text} == set()
