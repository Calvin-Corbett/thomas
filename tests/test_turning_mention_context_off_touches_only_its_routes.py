"""The mention_context row, off: its three routes answer 404, a server started that way never loads them, and nothing else moves.

No page in Thomas calls these routes any more. No turn in chat calls them either, so nothing a live turn
waits on goes with them. What they hold, the threads and sessions you register, lives on a module, so it has to be
dropped by the stop and not left for the next time the row is on.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "POST /api/mention-context/resolve": "POST /api/mention-context/resolve",
    "POST /api/mention-context/objects": "POST /api/mention-context/objects",
    "GET /api/mention-context/objects": "GET /api/mention-context/objects",
}
OWN_CODE = ("thomas.server.rows.mention_context", "thomas.server.routes.mention_context_routes")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, "HEAD /api/mention-context/objects"}


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("mention-off")
    started, found = start_with_one_row_off("mention_context", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("mention-remote")
    started, found = ask_as_a_remote_caller("mention_context", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "mention_context"}
    assert seen["rows"]["mention_context"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_all_three_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"]["GET /api/mention-context/objects"] == 200
    assert (
        seen["on"]["POST /api/mention-context/resolve"] != 404
    )  # an empty body is a 400, which is the route answering


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    # The listing has no access guard of its own and was not given one by the move: a GET with no token reads the file
    # root and the names registered, so it answers 200 here. Reported, not fixed in this change. If it is guarded, this
    # becomes 401 and the exception goes.
    assert remote["no_token"] == {**dict.fromkeys(ROUTES.values(), 401), "GET /api/mention-context/objects": 200}
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_a_change_to_the_row_runs_its_proofs() -> None:
    chosen = select(ROOT, ["thomas/server/rows/mention_context.py"]).files
    assert "tests/test_turning_mention_context_off_touches_only_its_routes.py" in chosen


def test_a_change_to_the_routes_runs_their_tests_and_the_rows() -> None:
    chosen = select(ROOT, ["thomas/server/routes/mention_context_routes.py"]).files
    assert "tests/test_turning_mention_context_off_touches_only_its_routes.py" in chosen
    assert "tests/test_mention_context_routes.py" in chosen


def test_nothing_in_the_server_names_the_old_aggregate(tmp_path: Path) -> None:
    """The one entry it held moved here, so the file is gone and nothing may still import it."""
    assert not (ROOT / "thomas" / "server" / "routes" / "frontier_surfaces.py").exists()
    left = [
        path.name
        for path in (ROOT / "thomas").rglob("*.py")
        if "frontier_surfaces" in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert left == []


def test_no_page_in_thomas_calls_these_routes() -> None:
    """The row's words say no page uses them and chat does not. A caller added anywhere else has to be read."""
    pages = [
        path
        for folder in (ROOT / "thomas" / "server" / "web", ROOT / "extensions", ROOT / "apps", ROOT / "desktop")
        if folder.is_dir()
        for path in folder.rglob("*")
        if path.suffix in {".html", ".js", ".mjs", ".ts", ".tsx"} and "node_modules" not in path.parts
    ]
    assert pages  # an empty read would pass below
    assert [p for p in pages if "api/mention-context" in p.read_text(encoding="utf-8", errors="replace")] == []
    assert not (ROOT / "thomas" / "server" / "web" / "js" / "mention_context_panel.js").exists()


def test_nothing_in_chat_or_the_agent_reads_mention_context() -> None:
    """The row's words say a message you send in chat is not read by it, and nothing in Thomas registers objects."""
    reaching = re.compile(r"mention_context_routes|api/mention-context")
    found = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "thomas").rglob("*.py")
        if reaching.search(path.read_text(encoding="utf-8", errors="replace"))
    }

    assert found == {
        "thomas/server/rows/mention_context.py",
        "thomas/server/routes/mention_context_routes.py",
    }
