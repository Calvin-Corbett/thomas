"""With the default scope, a gateway that is off answers 401 on /gateway and /v1/gateway and 404 on its other addresses.

The Plugins page says what a caller sees while the Gateway row is off. With a gateway token set and the scope left
unset, the check of who may call covers only ``/gateway``, ``/ws`` and ``/v1/gateway``. So an address outside those
that has gone answers 404 to a caller who shows no token, and the words on the page must say so. This asks a remote
caller on a real server, then reads the words.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import tomllib

from tests.row_gateway_fixture import ask_with_the_check_covering_the_whole_server
from tests.test_turning_gateway_off_touches_only_its_routes import ROUTES

COVERED = [r for r in ROUTES.values() if r.split()[1].startswith(("/gateway/", "/v1/gateway/"))]
OUTSIDE = [r for r in ROUTES.values() if r not in COVERED]
ROW_FILE = Path(__file__).resolve().parents[1] / "thomas" / "server" / "rows" / "default.toml"


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    started, found = ask_with_the_check_covering_the_whole_server(
        list(ROUTES.values()), tmp_path_factory.mktemp("gateway-default-scope"), access_mode="remote", scope="unset"
    )
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_an_address_under_gateway_answers_401_with_no_token_while_off(seen: dict[str, Any]) -> None:
    got = {ask: seen["off"]["no_token"][ask][0] for ask in COVERED if ask != "GET /gateway/auth/policy"}
    assert set(got.values()) == {401}, got


def test_an_address_outside_gateway_answers_404_with_no_token_while_off(seen: dict[str, Any]) -> None:
    got = {ask: seen["off"]["no_token"][ask][0] for ask in OUTSIDE if ask.startswith("GET ")}
    assert set(got.values()) == {404}, got


def _off_means() -> str:
    rows = tomllib.loads(ROW_FILE.read_text(encoding="utf-8"))["row"]
    return next(row["off_means"] for row in rows if row["id"] == "gateway")


def test_the_words_do_not_promise_401_on_every_address_while_the_scope_is_the_default() -> None:
    words = _off_means()
    assert "whatever they ask for" not in words
    assert "an address that has gone answers 401 and not 404" not in words
    # The words may not hold a slash, so they name the gateway's own addresses, and the other ones, in plain words.
    assert "every address of the gateway itself" in words
    assert "the other addresses" in words
    assert "404" in words
