"""The gateway row, off: its 28 routes answer 404, a server started that way loads none of their modules, and the check stays.

The row serves the gateway half of Thomas's gateway: restart, the state other programs save, the log filter, the
OpenAI-style and Responses-style endpoints that hand a request on to an outside service you set up, and the report of the
policy. It does not serve the webhooks, which are a row of their own. Off takes these routes away and runs one stop step,
which closes the session the OpenAI-style proxy keeps to its outside service. The check of who may call is installed by the
server, so ``tests/test_turning_gateway_off_keeps_the_check_of_who_may_call.py`` holds that it stays. The register is
``thomas/server/routes/gateway/__init__.py``, which loads nothing until it registers, and the row is
``thomas.server.rows.gateway``. ``thomas.server.routes.gateway.p136_gateway_auth_policy_enforcement`` is the one module the
server loads whatever the row is doing, so it is not named below.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import aiohttp
import pytest
from aiohttp import web

from tests.plugin_view_fixture import hosted, mount_on, until
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.core.kernel.hotswap import stop
from thomas.server.proof.selection import select

ROW = "gateway"
PACKAGE = "thomas.server.routes.gateway"
# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /auth/policy": "GET /auth/policy",
    "GET /gateway/auth/policy": "GET /gateway/auth/policy",
    "GET /gateway/p140/openai/chat-completions-non-stream/schema": "GET /gateway/p140/openai/chat-completions-non-stream/schema",
    "GET /gateway/p142_openai_tool_call_passthrough_mapping/schema": "GET /gateway/p142_openai_tool_call_passthrough_mapping/schema",
    "GET /gateway/restart/schema": "GET /gateway/restart/schema",
    "GET /openai-compat/health": "GET /openai-compat/health",
    "GET /openai-compat/schema": "GET /openai-compat/schema",
    "GET /v1/gateway/p142_openai_tool_call_passthrough_mapping/schema": "GET /v1/gateway/p142_openai_tool_call_passthrough_mapping/schema",
    "GET /v1/gateway/state": "GET /v1/gateway/state",
    "GET /v1/gateway/state/persistence-model": "GET /v1/gateway/state/persistence-model",
    "GET /v1/responses/schema": "GET /v1/responses/schema",
    "GET /v1/responses/streaming-events/schema": "GET /v1/responses/streaming-events/schema",
    "POST /gateway/logs/filter": "POST /gateway/logs/filter",
    "POST /gateway/openai/chat-completions/stream": "POST /gateway/openai/chat-completions/stream",
    "POST /gateway/openai/chat/completions/stream": "POST /gateway/openai/chat/completions/stream",
    "POST /gateway/openai/chat_completions/stream": "POST /gateway/openai/chat_completions/stream",
    "POST /gateway/p140/openai/chat-completions-non-stream": "POST /gateway/p140/openai/chat-completions-non-stream",
    "POST /gateway/p141/openai-chat-completions-stream": "POST /gateway/p141/openai-chat-completions-stream",
    "POST /gateway/p141/openai_chat_completions_stream": "POST /gateway/p141/openai_chat_completions_stream",
    "POST /gateway/p142_openai_tool_call_passthrough_mapping": "POST /gateway/p142_openai_tool_call_passthrough_mapping",
    "POST /gateway/responses/tool-result-map": "POST /gateway/responses/tool-result-map",
    "POST /gateway/restart": "POST /gateway/restart",
    "POST /openai-compat/v1/chat/completions": "POST /openai-compat/v1/chat/completions",
    "POST /v1/chat/completions": "POST /v1/chat/completions",
    "POST /v1/gateway/p142_openai_tool_call_passthrough_mapping": "POST /v1/gateway/p142_openai_tool_call_passthrough_mapping",
    "POST /v1/gateway/state/persistence-model": "POST /v1/gateway/state/persistence-model",
    "POST /v1/responses": "POST /v1/responses",
    "PUT /v1/gateway/state": "PUT /v1/gateway/state",
}
MODULES = [
    f"{PACKAGE}.{name}"
    for name in (
        "p127_gateway_restart_command",
        "p135_gateway_state_persistence_model",
        "p137_gateway_logs_filter_command",
        "p139_openai_compat_route_scaffold",
        "p140_openai_chat_completions_non_stream",
        "p141_openai_chat_completions_stream",
        "p142_openai_tool_call_passthrough_mapping",
        "p144_responses_compat_route_scaffold",
        "p145_responses_create_non_stream",
        "p146_responses_create_stream_events",
        "p147_responses_tool_result_mapping",
    )
]
OWN_CODE = ("thomas.server.rows.gateway", *MODULES)
# What the server loads whatever the row is doing, because it installs the check of who may call from it.
ALWAYS_LOADED = (PACKAGE, f"{PACKAGE}.p136_gateway_auth_policy_enforcement")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, *(route.replace("GET", "HEAD") for route in ROUTES if route.startswith("GET "))}
# With nothing set up on a fresh data folder, so each of these is the handler answering and not the row.
ON_AN_EMPTY_BODY = {
    "GET /openai-compat/health": 503,  # no outside service address set
    "POST /openai-compat/v1/chat/completions": 503,  # the same
    "POST /gateway/logs/filter": 500,  # no log file set
    "POST /gateway/restart": 500,  # no restart command set
    "POST /gateway/openai/chat-completions/stream": 500,  # no OpenAI key set
    "POST /gateway/openai/chat/completions/stream": 500,
    "POST /gateway/openai/chat_completions/stream": 500,
    "POST /gateway/p141/openai-chat-completions-stream": 500,
    "POST /gateway/p141/openai_chat_completions_stream": 500,
    "POST /v1/chat/completions": 400,  # asks for a model
    "POST /gateway/p140/openai/chat-completions-non-stream": 400,
    "POST /v1/responses": 400,
    "POST /gateway/responses/tool-result-map": 400,
    "POST /gateway/p142_openai_tool_call_passthrough_mapping": 400,
    "POST /v1/gateway/p142_openai_tool_call_passthrough_mapping": 400,
    "POST /v1/gateway/state/persistence-model": 400,
    "PUT /v1/gateway/state": 400,
}
# In remote mode the server refuses any POST, PUT, PATCH or DELETE under /api/ itself, and these answer to nothing of the
# kind. With no gateway token set, which is how Thomas starts, every GET below answers whoever asks. That is how they were
# before this row. Setting a gateway token is what closes them, and whether they should answer without one is for you.
OPEN_UNTIL_A_GATEWAY_TOKEN_IS_SET = {route for route in ROUTES.values() if route.startswith("GET ")}


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("gateway-off")
    with _without_a_real_gateway():
        started, found = start_with_one_row_off(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("gateway-remote")
    with _without_a_real_gateway():
        started, found = ask_as_a_remote_caller(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def _without_a_real_gateway() -> Any:
    """A key or address set on the machine running the tests must not decide what a request here reaches."""
    keep = {
        key: value for key, value in os.environ.items() if not any(w in key for w in ("OPENAI", "GATEWAY", "RESPONSES"))
    }
    return mock.patch.dict(os.environ, keep, clear=True)


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert len(ROUTES) == 28
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded_and_only_the_check_of_who_may_call_has(
    seen: dict[str, Any],
) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []
    assert [module for module in ALWAYS_LOADED if module not in seen["loaded"]] == []


def test_turning_it_on_brings_back_all_28_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert 404 not in seen["on"].values(), seen["on"]
    assert seen["on"] == {**dict.fromkeys(ROUTES.values(), 200), **ON_AN_EMPTY_BODY}


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route_that_changes_something(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    changing = [route for route in ROUTES.values() if route not in OPEN_UNTIL_A_GATEWAY_TOKEN_IS_SET]
    assert {route: remote["no_token"][route] for route in changing} == dict.fromkeys(changing, 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_with_no_gateway_token_set_the_reading_routes_answer_a_remote_caller_who_shows_no_token(
    remote: dict[str, Any],
) -> None:
    """Pinned so that the row's words and this stay true together. A gateway token set in the environment closes them."""
    reading = {route: remote["no_token"][route] for route in OPEN_UNTIL_A_GATEWAY_TOKEN_IS_SET}
    assert set(reading.values()) <= {200, 503}, reading
    assert reading["GET /v1/gateway/state"] == 200


def test_the_session_the_proxy_keeps_is_closed_when_the_row_stops() -> None:
    """The OpenAI-style proxy keeps one session open to its outside service, and a stop closes it."""
    from thomas.server.routes.gateway import p139_openai_compat_route_scaffold as p139

    async def scenario() -> None:
        closed: list[bool] = []

        class Session(aiohttp.ClientSession):
            async def close(self) -> None:
                closed.append(True)
                await super().close()

        app, kernel = hosted()
        kernel.mark_ready()
        fork, view = mount_on(kernel, p139.register)
        assert closed == []
        view[p139._SESSION_KEY]["session"] = Session()
        await stop(fork)
        await until(lambda: closed)
        assert closed == [True]
        assert p139._SESSION_KEY not in app

    asyncio.run(scenario())


def test_the_row_refuses_to_start_with_no_check_of_who_may_call_installed() -> None:
    """Its routes are thrown away with it, so none can be on with nothing in front of them."""
    from thomas.server.rows.gateway import plugin

    service = SimpleNamespace(app=web.Application(), config=None, view=lambda _ctx: web.Application())
    with pytest.raises(RuntimeError, match="no check of who may call"):
        plugin.apply({"web": service}, None)


def test_no_page_or_installed_app_in_thomas_asks_for_these_routes() -> None:
    """The row's words say nothing in Thomas reads these routes. If a page starts to, this fails and they change."""
    paths = (
        "/gateway/",
        "/v1/gateway",
        "/openai-compat/",
        "/v1/chat/completions",
        "/v1/responses",
        "/auth/policy",
    )
    found = []
    for folder in (ROOT / "thomas" / "server" / "web", ROOT / "extensions"):
        for path in folder.rglob("*"):
            if path.suffix in {".js", ".html", ".css", ".json", ".py", ".mjs", ".ts"} and path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
                found += [str(path.relative_to(ROOT)) for word in paths if word in text]
    assert found == []


@pytest.mark.parametrize(
    "changed",
    [
        "thomas/server/rows/gateway.py",
        "thomas/server/routes/gateway/__init__.py",
        "thomas/server/routes/gateway/p139_openai_compat_route_scaffold.py",
    ],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_gateway_off_touches_only_its_routes.py" in chosen
    assert "tests/test_turning_gateway_off_keeps_the_check_of_who_may_call.py" in chosen
