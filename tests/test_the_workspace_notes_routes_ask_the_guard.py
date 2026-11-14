"""A caller with no token is refused on every source-notes route, and one with the token is let in.

``thomas.server.rows.workspace`` hands ``register_source_annotation_routes`` the access guard the server gives rows.
The proof of a row sends no request, so only this shows that the two reads kept it: the server itself refuses a POST
under ``/api/`` with no token before a row is reached, so a read that lost its guard shows only here.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.row_off_fixture import ask_as_a_remote_caller

# Written out, because a list worked out from the row would agree with whatever the row did.
READS = (
    "GET /api/source-annotations",
    "GET /api/source-annotations/source?file=README.md",
)
WRITES = (
    "POST /api/source-annotations",
    "POST /api/source-annotations/none/conversation",
    "POST /api/source-annotations/none/diff",
)
ASKS = READS + WRITES

# With the token the routes answer as themselves: the reads 200, an empty create 400, and an unknown note 404.
WITH_TOKEN = {
    READS[0]: 200,
    READS[1]: 200,
    WRITES[0]: 400,
    WRITES[1]: 404,
    WRITES[2]: 404,
}


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("workspace-notes-remote")
    started, found = ask_as_a_remote_caller("workspace", list(ASKS), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_the_row_is_up_for_a_remote_caller(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["no_token"] == dict.fromkeys(ASKS, 401)


def test_the_token_lets_a_remote_caller_through_to_each_route(remote: dict[str, Any]) -> None:
    assert remote["with_token"] == WITH_TOKEN
