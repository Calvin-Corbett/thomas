"""The project_queue row, off: its four routes answer 404, a server started that way never loads them, nothing else moves.

The routes back Planned improvements in the Improve Thomas window: the queue of Thomas projects waiting to start, and the
switch for Thomas planning and starting improvements to itself. What starts a queued project and what plans new ones is
the server's own timer, which never calls them. The words of the row live in ``thomas/server/rows/default.toml``, and each
sentence of them names the test that shows it, in this file, in the browser walk of the window, or in the route tests.

The row is ``thomas.server.rows.project_queue`` and its code is ``thomas.server.routes.self_project_queue_routes``, and
those names are how a check finds this file when either changes. The queue tests, ``tests/test_a_self_project_queue.py``
and ``tests/test_self_improvement_planner.py``, build their own app and call the registrar directly.

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

ROW = "project_queue"
# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /api/self/projects/queue": "GET /api/self/projects/queue",
    "POST /api/self/projects/queue": "POST /api/self/projects/queue",
    "GET /api/self/projects/queue/planner": "GET /api/self/projects/queue/planner",
    "PUT /api/self/projects/queue/planner": "PUT /api/self/projects/queue/planner",
}
OWN_CODE = ("thomas.server.rows.project_queue", "thomas.server.routes.self_project_queue_routes")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, "HEAD /api/self/projects/queue", "HEAD /api/self/projects/queue/planner"}
# An empty body is refused by the handler, which is the route answering and writes nothing.
ANSWERS_WITH_AN_EMPTY_BODY = {
    "GET /api/self/projects/queue": 200,
    "POST /api/self/projects/queue": 400,
    "GET /api/self/projects/queue/planner": 200,
    "PUT /api/self/projects/queue/planner": 400,
}


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("queue-off")
    started, found = start_with_one_row_off(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("queue-remote")
    started, found = ask_as_a_remote_caller(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture(scope="module")
def elsewhere(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("queue-elsewhere")
    started, found = ask_from_another_machine(ROW, list(ROUTES.values()), folder)
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


def test_the_project_routes_that_stay_in_the_server_are_there_with_the_row_off(seen: dict[str, Any]) -> None:
    """The queue reads the listing they keep, so the row has to find it whether it is on or off."""
    assert {"GET /api/self/projects", "POST /api/self/projects"} <= set(seen["listed_off"])
    assert "thomas.server.routes.self_project_routes" in seen["loaded"]


def test_turning_it_on_brings_back_all_four_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == ANSWERS_WITH_AN_EMPTY_BODY


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_the_routes_ask_for_this_machine_and_not_for_the_token(remote: dict[str, Any]) -> None:
    """They were guarded by the machine alone and still are, so a caller on this machine is let in with no token.

    The test client is on this machine. The server itself refuses a POST or PUT under ``/api/`` that has no token, before
    any route is reached, so those two read 401 here and say nothing about the route. The caller on another machine, with
    the token, is the next test.
    """
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == {
        "GET /api/self/projects/queue": 200,
        "POST /api/self/projects/queue": 401,
        "GET /api/self/projects/queue/planner": 200,
        "PUT /api/self/projects/queue/planner": 401,
    }
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_a_caller_on_another_machine_is_refused_even_with_the_token(elsewhere: dict[str, Any]) -> None:
    """The token is sent each time, so it lets a request past the server and only the machine guard can give the 403.

    Asked from this machine with the same token, none gives 403, so a refusal below is not a server that refuses everyone.
    The two that change the queue are in this list too: they ask the guard before they read the body.
    """
    assert elsewhere["row"]["state"] == "active", elsewhere["row"]
    assert elsewhere["elsewhere"] == dict.fromkeys(ROUTES.values(), 403)
    assert 403 not in elsewhere["here"].values(), elsewhere["here"]


def test_the_timer_that_starts_and_plans_never_names_the_routes() -> None:
    """What starts a queued project and what plans new ones imports the queue and the planner, never the routes."""
    server = ROOT / "thomas" / "server"
    for name in (
        "self_project_queue_tick.py",
        "self_project_queue.py",
        "self_improvement_planner.py",
        "autopilot_park.py",
        "autopilot_hold_tick.py",
    ):
        tree = ast.parse((server / name).read_text(encoding="utf-8"))
        named = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        } | {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        assert "self_project_queue_routes" not in " ".join(sorted(map(str, named))), name


def test_the_row_stops_nothing_and_writes_nothing() -> None:
    """The queue is a file the row never opens, and the row has no stop step to touch it."""
    source = (ROOT / "thomas" / "server" / "rows" / "project_queue.py").read_text(encoding="utf-8")
    code = ast.unparse(ast.parse(source))
    for word in ("on_stopped", "on_ready", "open(", "write", "unlink", "Thread", "create_task"):
        assert word not in code, word


def test_a_change_to_the_row_or_its_routes_runs_their_proofs() -> None:
    walk = "tests/test_the_improve_thomas_window_with_its_queue_off.py"
    own = "tests/test_turning_project_queue_off_touches_only_its_routes.py"
    for changed, runs in (
        ("thomas/server/rows/project_queue.py", (own, walk, "tests/test_a_self_project_queue_routes.py")),
        ("thomas/server/routes/self_project_queue_routes.py", (own, "tests/test_a_self_project_queue.py")),
    ):
        chosen = select(ROOT, [changed]).files
        for name in runs:
            assert name in chosen, (changed, name)


# The words, a sentence at a time. Each is shown by the test named beside it, in this file, in the browser walk of the
# window or in the route tests. A new, changed or dropped sentence fails here until the list has it with a test.
QUEUE_TESTS = "test_routes_persist_order_and_refusals"
PLANNER_TESTS = "test_planner_switch_route"
WORDS = {
    "about": {
        "Shows and changes the queue of Thomas projects waiting to start, and the switch that lets Thomas plan and start "
        "improvements to itself on its own.": (
            QUEUE_TESTS,
            PLANNER_TESTS,
            "test_turning_it_on_brings_back_all_four_routes_without_a_restart",
        ),
        "You see it in the Improve Thomas window, which opens from the Improve Thomas button in the project menu beside "
        "the message box in Build.": ("test_with_the_row_on_the_window_shows_planned_improvements_and_its_switch",),
        "Under Planned improvements the window shows how many projects are running and queued, and a switch for automatic "
        "improvements.": ("test_with_the_row_on_the_window_shows_planned_improvements_and_its_switch",),
        "Other programs on this computer can queue a project or read the queue the same way.": (QUEUE_TESTS,),
        "Only a program on this computer can ask.": (
            "test_a_caller_on_another_machine_is_refused_even_with_the_token",
        ),
    },
    "off_means": {
        "While this is off, the Planned improvements part of the Improve Thomas window is replaced by a line of technical "
        "text about a problem reading an answer, which does not say this is turned off.": (
            "test_with_the_row_off_the_planned_improvements_part_is_a_line_of_technical_text",
        ),
        "The window asks for the queue once each time you open it, and not again and again.": (
            "test_the_window_asks_for_the_queue_and_the_switch_once_each_time_it_opens",
            "test_with_the_row_off_the_page_asks_nothing_on_its_own",
        ),
        "The rest of the window carries on, because Thomas projects right now and Start a Thomas project do not use the "
        "queue.": (
            "test_with_the_row_off_the_rest_of_the_window_carries_on",
            "test_the_project_routes_that_stay_in_the_server_are_there_with_the_row_off",
        ),
        "You cannot queue a project, read the queue or change the switch, and a program that tries is told there is no "
        "such address.": (
            "test_with_the_row_off_every_route_answers_404_and_none_is_listed",
            "test_with_the_row_off_every_request_for_the_queue_is_told_there_is_no_such_address",
        ),
        "A window that was already open keeps showing what it last read, and its switch flips back and shows the same "
        "technical text.": (
            "test_a_window_open_when_it_goes_off_keeps_what_it_read_until_you_open_it_again",
            "test_the_switch_in_a_window_open_when_it_goes_off_flips_back_with_the_same_technical_text",
        ),
        "The queue stays where it is, and the server's own timer starts queued projects and plans new ones without using "
        "these requests, so both carry on as they were.": (
            "test_the_row_stops_nothing_and_writes_nothing",
            "test_the_timer_that_starts_and_plans_never_names_the_routes",
        ),
        "Turning this on again brings the queue back in the window with no restart.": (
            "test_turned_back_on_the_window_shows_the_queue_again_with_no_restart",
        ),
    },
    "stop_now": {
        "A request to read or change the queue that is still running will fail, and may need sending again.": (
            "test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded",
        ),
        "A request that was queuing a project may not have finished, so look at the queue afterwards.": (
            "test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded",
        ),
    },
}
FILES = (
    "test_turning_project_queue_off_touches_only_its_routes.py",
    "test_the_improve_thomas_window_with_its_queue_off.py",
    "test_a_self_project_queue.py",
    "test_self_improvement_planner.py",
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
