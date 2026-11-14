"""A caller with no token is refused on every Build route, and one with the token is let in.

``thomas.server.rows.build`` hands the registrars the access guard the server gives rows. The proof of a row sends no
request, so only this shows that a route kept it. The process runs from an empty folder with the loop's two Thomas
commands replaced, because the token lets a start, an approval or a rejection through, and those start real work.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.build_row_fixture import ASKS, ROUTES
from tests.row_off_fixture import ask_as_a_remote_caller
from tests.row_proof_fixture import ROOT

# Run before the server starts. The clone's own folder goes first on the path because the working folder then changes
# to an empty one, so nothing a route writes lands in a checkout.
_AHEAD = f"""\
import os
import sys
import tempfile

sys.path.insert(0, {str(ROOT)!r})
from thomas.server.routes import evolve_loop_routes


class _Over:
    returncode = 0


async def _nothing_ran(root, args):
    return None


async def _nothing_started(root, args):
    return _Over()


evolve_loop_routes._run_evolve_cli = _nothing_ran
evolve_loop_routes._spawn_evolve_cli = _nothing_started
os.chdir(tempfile.mkdtemp())
"""


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("build-remote")
    started, found = ask_as_a_remote_caller("build", list(ASKS.values()), folder, ahead=_AHEAD)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_the_row_is_up_for_a_remote_caller(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert len(ROUTES) == len(ASKS) == 41
    assert remote["no_token"] == dict.fromkeys(ASKS.values(), 401)


def test_with_the_token_no_route_refuses_it(remote: dict[str, Any]) -> None:
    assert 401 not in remote["with_token"].values(), remote["with_token"]
    assert 403 not in remote["with_token"].values(), remote["with_token"]
