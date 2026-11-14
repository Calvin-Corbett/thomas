"""The gateway row cannot take the check of who may call with it, and cannot be on without one.

``gateway_auth_scope = all`` makes the gateway's check refuse any path on the server that has no token. The server installs
that check itself, in ``thomas/server/app_routes_families.py``, because aiohttp fixes its middleware list when the server
starts and a row turned on later could not add one. So this asks as a caller on another machine would, in one process, with
the row off at the start, then on, then off again: a path that is not the gateway's is refused with no token at all three
points, and every route of the gateway is refused with no token while the row is on, apart from the two that report the
policy and hold no secret. The row's own code is ``thomas/server/rows/gateway.py``.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.row_gateway_fixture import ask_with_the_check_covering_the_whole_server
from tests.test_turning_gateway_off_touches_only_its_routes import ROUTES

# Open on purpose: they report the policy with its secrets left out, which is how an operator checks it took effect.
EXEMPT = {"GET /auth/policy", "GET /gateway/auth/policy"}
GUARDED = [route for route in ROUTES.values() if route not in EXEMPT]
# Not the gateway's, and spelled the ways a caller might try to slip past a check that matches on a path.
ELSEWHERE = [
    "GET /",
    "GET /api/health",
    "GET /api/plugins/thomas",
    "GET /nothing-is-here",
    "GET /v1/gateway/state/",
    "GET /V1/GATEWAY/STATE",
    "GET /v1/%67ateway/state",
    "DELETE /v1/gateway/state",
]
REFUSED = [401, "gateway_auth_missing"]


@pytest.fixture(scope="module", params=["remote", "local"])
def seen(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Remote is a caller on another machine. Local lets the server's own guard of changing routes wave a caller on this
    machine through, so the gateway's check is the only thing left to refuse it, and the codes below show it was that."""
    folder = tmp_path_factory.mktemp(f"gateway-check-{request.param}")
    started, found = ask_with_the_check_covering_the_whole_server(
        [*ROUTES.values(), *ELSEWHERE], folder, access_mode=request.param
    )
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return {**found, "mode": request.param}


def _expected_refusals(seen: dict[str, Any], asks: list[str]) -> dict[str, list[Any]]:
    return {ask: REFUSED if seen["mode"] == "local" or ask.startswith("GET ") else [401, None] for ask in asks}


def _refused(seen: dict[str, Any], point: str, asks: list[str]) -> dict[str, list[Any]]:
    """A caller with no token is refused. In remote mode the server's own guard answers first for a route that changes
    something, so only a reading route shows the gateway's code there."""
    answers = {ask: seen[point]["no_token"][ask] for ask in asks}
    return {
        ask: answer if seen["mode"] == "local" or ask.startswith("GET ") else [answer[0], None]
        for ask, answer in answers.items()
    }


def test_the_row_starts_off_and_the_check_is_installed_once(seen: dict[str, Any]) -> None:
    assert seen["start"] == "off"
    assert seen["checks_at_start"] == 1
    assert seen["checks_after_presses"] == 1


@pytest.mark.parametrize("point", ["off", "on", "off_again"])
def test_a_path_that_is_not_the_gateways_is_refused_with_no_token_whatever_the_row_is_doing(
    seen: dict[str, Any], point: str
) -> None:
    assert _refused(seen, point, ELSEWHERE) == _expected_refusals(seen, ELSEWHERE)


@pytest.mark.parametrize("point", ["off", "on", "off_again"])
def test_a_caller_with_the_token_gets_past_the_check_on_a_path_that_is_not_the_gateways(
    seen: dict[str, Any], point: str
) -> None:
    got_through = {ask: seen[point]["with_token"][ask][0] for ask in ELSEWHERE}
    assert 401 not in got_through.values(), got_through
    assert got_through["GET /api/health"] == 200


def test_every_gateway_route_is_refused_with_no_token_while_the_row_is_on(seen: dict[str, Any]) -> None:
    assert seen["pressed_on"] == 200
    assert seen["on_state"] == "active"
    assert _refused(seen, "on", GUARDED) == _expected_refusals(seen, GUARDED)
    assert {ask: seen["on"]["no_token"][ask][0] for ask in EXEMPT} == dict.fromkeys(EXEMPT, 200)


def test_a_caller_with_the_token_reaches_every_gateway_route_while_the_row_is_on(seen: dict[str, Any]) -> None:
    statuses = {ask: seen["on"]["with_token"][ask][0] for ask in ROUTES.values()}
    assert not {401, 403, 404, 429}.intersection(statuses.values()), statuses


@pytest.mark.parametrize("point", ["off", "off_again"])
def test_with_the_row_off_the_gateway_routes_are_refused_with_no_token_and_missing_with_one(
    seen: dict[str, Any], point: str
) -> None:
    """Refused first, so a path that is gone cannot be told from one that is there by a caller with no token."""
    assert _refused(seen, point, GUARDED) == _expected_refusals(seen, GUARDED)
    assert {ask: seen[point]["with_token"][ask][0] for ask in ROUTES.values()} == dict.fromkeys(ROUTES.values(), 404)
    # The two that hold no secret are let through by the check, and there is nothing behind them.
    assert {ask: seen[point]["no_token"][ask][0] for ask in EXEMPT} == dict.fromkeys(EXEMPT, 404)


def test_what_was_saved_in_the_gateway_state_is_still_there_when_the_row_comes_back(seen: dict[str, Any]) -> None:
    assert seen["saved"] == 200
    assert seen["pressed_off"] == 200
    assert seen["off_again_state"] == "off"
    assert seen["pressed_on_again"] == 200
    assert seen["on_again_state"] == "active"
    assert seen["state_back"]["state"] == {"kept": "yes"}, seen["state_back"]
