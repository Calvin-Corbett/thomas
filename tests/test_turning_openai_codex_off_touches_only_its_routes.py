"""The ChatGPT sign-in row, off: its six routes answer 404, a server started that way never loads them, chat still answers.

``thomas.server.rows.openai_codex`` registers the routes in ``thomas.server.routes.openai_codex_aiohttp``, and
``thomas/server/routes/openai_codex_aiohttp_helpers.py`` is what they hand their work to. No test imports a row, and a check
follows one import, so naming all three here is how a change to any of them finds this file.

A sign-in opens a listener on a fixed port of this machine, and the existing route tests used to open the real one. Nothing
here does: each process below swaps the sign-in start for one that ends at once, so ``/login`` does not wait five minutes and
no port is bound. ``tests/test_the_chatgpt_sign_in_through_off_and_on.py`` runs the real listener on a scratch port.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /api/openai-codex/status": "GET /api/openai-codex/status",
    "POST /api/openai-codex/login": "POST /api/openai-codex/login",
    "POST /api/openai-codex/login/start": "POST /api/openai-codex/login/start",
    "POST /api/openai-codex/login/complete": "POST /api/openai-codex/login/complete",
    "POST /api/openai-codex/logout": "POST /api/openai-codex/logout",
    "GET /api/openai-codex/models": "GET /api/openai-codex/models",
}
OWN_CODE = (
    "thomas.server.rows.openai_codex",
    "thomas.server.routes.openai_codex_aiohttp",
    "thomas.server.routes.openai_codex_aiohttp_helpers",
)
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, "HEAD /api/openai-codex/status", "HEAD /api/openai-codex/models"}
# With the row on, on a server nobody has signed in to. The sign-in start is the stand-in below, which ends at once with an
# error, so login answers 500 from that and not from the route. The real start is tried in the other test file.
ON = {
    "GET /api/openai-codex/status": 200,
    "POST /api/openai-codex/login": 500,
    "POST /api/openai-codex/login/start": 200,
    "POST /api/openai-codex/login/complete": 400,
    "POST /api/openai-codex/logout": 200,
    "GET /api/openai-codex/models": 200,
}

# Source run in the process before the server starts, so nothing in it opens a browser, binds a port or reads the Codex
# app's own sign-in from a real folder. The sign-in start is swapped as its module loads, because the module must not load
# before then: a server started with the row off is meant never to import it.
_NO_REAL_SIGN_IN = """\
import importlib.abc
import importlib.util
import os
import sys
import webbrowser

os.environ["CODEX_HOME"] = sys.argv[2] + "-codex"
os.environ["THOMAS_IMPORT_LOCAL_CODEX_AUTH"] = "0"
webbrowser.open = lambda *args, **kwargs: True


class _SwapTheSignInStart(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name != "thomas.server.routes.openai_codex_aiohttp":
            return None
        sys.meta_path.remove(self)
        spec = importlib.util.find_spec(name)
        run = spec.loader.exec_module

        def exec_module(module):
            run(module)

            async def ends_at_once(self, profile):
                import asyncio

                flow = module.start_oauth_flow(profile=profile, redirect_uri=module.OPENAI_CODEX_REDIRECT_URI)
                pending = module._PendingLogin(
                    flow=flow, callback_bound=False, event=asyncio.Event(), error="no sign-in in a test"
                )
                pending.event.set()
                return pending

            module._OAuthCallbackServer.start_flow = ends_at_once

        spec.loader.exec_module = exec_module
        return spec


sys.meta_path.insert(0, _SwapTheSignInStart())

"""
_READS_NOTHING = """\
def reading():
    return None


"""


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("openai-codex-off")
    started, found = start_with_one_row_off(
        "openai_codex", list(ROUTES.values()), folder, reading=_NO_REAL_SIGN_IN + _READS_NOTHING
    )
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("openai-codex-remote")
    started, found = ask_as_a_remote_caller("openai_codex", list(ROUTES.values()), folder, ahead=_NO_REAL_SIGN_IN)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "openai_codex"}
    assert seen["rows"]["openai_codex"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_with_the_row_off_the_code_chat_reads_the_signed_in_token_with_is_still_loaded(seen: dict[str, Any]) -> None:
    """The row's words say a model already signed in goes on answering. That is this module and not the routes."""
    assert "thomas.server.openai_codex_oauth" in seen["loaded"]


def test_turning_it_on_brings_back_all_six_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == ON


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]
    assert remote["with_token"] == ON


@pytest.mark.parametrize(
    ("changed", "feature_test"),
    [
        ("thomas/server/rows/openai_codex.py", "tests/test_openai_codex_oauth.py"),
        ("thomas/server/routes/openai_codex_aiohttp.py", "tests/test_openai_codex_oauth.py"),
        ("thomas/server/routes/openai_codex_aiohttp.py", "tests/test_model_catalog_routes.py"),
        ("thomas/server/routes/openai_codex_aiohttp_helpers.py", "tests/test_model_catalog_routes.py"),
    ],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str, feature_test: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_openai_codex_off_touches_only_its_routes.py" in chosen
    assert feature_test in chosen
