"""The onboarding row, off: its three routes answer 404, a server started that way never loads them, and setup carries on.

The row holds first-run measurements and nothing first-run setup needs. The page sends its notes without waiting for the
answer, and the choices it saves and the point where it counts as finished go through the preferences routes, which are
in the shell and not in this row. These tests hold the row's words to that: with the row off, those routes still answer.

The desktop routes that share a path prefix with these are the desktop row's, and turning this one off leaves them.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

ROW = "onboarding"
# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "POST /api/onboarding/telemetry": "POST /api/onboarding/telemetry",
    "GET /api/onboarding/outcomes": "GET /api/onboarding/outcomes",
    "GET /api/onboarding/outcomes/gate": "GET /api/onboarding/outcomes/gate",
}
# What first-run setup saves through, and a desktop route that shares the prefix. Neither belongs to this row.
STAYS = {
    "GET /api/preferences": "GET /api/preferences",
    "GET /api/onboarding/desktop/status": "GET /api/onboarding/desktop/status",
}
OWN_CODE = ("thomas.server.rows.onboarding", "thomas.server.routes.onboarding_aiohttp")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, "HEAD /api/onboarding/outcomes", "HEAD /api/onboarding/outcomes/gate"}


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("onboarding-off")
    started, found = start_with_one_row_off(ROW, [*ROUTES.values(), *STAYS.values()], folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("onboarding-remote")
    started, found = ask_as_a_remote_caller(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def _only(answers: dict[str, int], asks: dict[str, str]) -> dict[str, int]:
    return {ask: answers[ask] for ask in asks.values()}


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert _only(seen["off"], ROUTES) == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_what_setup_saves_through_and_the_desktop_routes_still_answer(seen: dict[str, Any]) -> None:
    assert _only(seen["off"], STAYS) == dict.fromkeys(STAYS.values(), 200)


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_all_three_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert _only(seen["on"], ROUTES) == dict.fromkeys(ROUTES.values(), 200)


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert _only(seen["off_again"], ROUTES) == dict.fromkeys(ROUTES.values(), 404)
    assert _only(seen["off_again"], STAYS) == dict.fromkeys(STAYS.values(), 200)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_the_page_sends_its_note_without_waiting_for_the_answer() -> None:
    """The row's words tell you setup carries on when these routes are gone. This is the half of that which is the page's.

    The one script that sends a note ignores what comes back, and catches a failed send. If it starts to wait on the
    answer, or to stop on a failure, those words must change.
    """
    script = (ROOT / "thomas" / "server" / "web" / "js" / "runtime" / "006_easy_setup_onboarding_04.js").read_text(
        encoding="utf-8"
    )
    sending = script.partition("async function emitOnboardingTelemetry")[2].partition(
        "function getOnboardingFromPrefs"
    )[0]

    assert "/api/onboarding/telemetry" in sending
    assert "await fetch(" in sending
    assert "= await fetch(" not in sending  # the answer is not kept, so a 404 changes nothing it does
    assert "catch {" in sending


def test_only_the_debug_dock_and_the_note_sender_call_these_routes() -> None:
    """The words name where a person sees the effect. A caller added anywhere else means they must change."""
    web = ROOT / "thomas" / "server" / "web"
    callers = sorted(
        str(path.relative_to(web)).replace("\\", "/")
        for path in web.rglob("*.*")
        if path.suffix in {".js", ".html"}
        and any(
            f"api/onboarding/{tail}" in path.read_text(encoding="utf-8", errors="replace")
            for tail in ("telemetry", "outcomes")
        )
    )
    assert callers == ["js/runtime/006_easy_setup_onboarding_04.js", "js/runtime/015_debug_dock.js"]


@pytest.mark.parametrize("changed", ["thomas/server/rows/onboarding.py", "thomas/server/routes/onboarding_aiohttp.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_onboarding_off_touches_only_its_routes.py" in chosen
    assert "tests/test_server_onboarding_routes.py" in chosen


def test_nothing_of_the_row_is_left_in_the_shell() -> None:
    shell = (Path(ROOT) / "thomas" / "server" / "app_routes_families.py").read_text(encoding="utf-8")
    assert "onboarding_aiohttp" not in shell
    assert "register_preferences_routes" in shell
