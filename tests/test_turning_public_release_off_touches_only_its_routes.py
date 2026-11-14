"""The Publish to GitHub row, off: its two routes answer 404, a server started that way never loads them, and it comes back.

Proves thomas.server.rows.public_release and thomas.server.routes.public_release_routes. The release tool is replaced by
a stand-in in the server's own process, so no preview of the real checkout is built and nothing is sent anywhere.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.row_off_fixture import ask_as_a_remote_caller, ask_from_another_machine, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

ROUTES = {
    "GET /api/public-release/preview": "GET /api/public-release/preview",
    "POST /api/public-release/publish": "POST /api/public-release/publish",
}
OWN_CODE = ("thomas.server.rows.public_release", "thomas.server.routes.public_release_routes")
# aiohttp lists a HEAD beside a GET unless the registrar says allow_head=False, and this one does, so a HEAD cannot start a build.
LISTED = set(ROUTES)

# Runs in the server's process before it starts: the release tool answers with a preview that sends nothing.
STAND_IN = """\
from scripts.forge.publish import public_release as _release


class _Preview:
    def to_dict(self):
        return {"version": "9.9.9", "digest": "d", "files": 1, "removed": {}, "checks": [], "safe_to_publish": True}

    def digest(self):
        return "d"

    def close(self):
        pass


_release.build = lambda repo, remote=None, **kw: _Preview()


def reading():
    return None


"""


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("public-release-off")
    started, found = start_with_one_row_off("public_release", list(ROUTES.values()), folder, reading=STAND_IN)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    started, found = ask_as_a_remote_caller(
        "public_release", list(ROUTES.values()), tmp_path_factory.mktemp("public-release-remote"), ahead=STAND_IN
    )
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture(scope="module")
def elsewhere(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    started, found = ask_from_another_machine(
        "public_release", list(ROUTES.values()), tmp_path_factory.mktemp("public-release-away"), ahead=STAND_IN
    )
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "public_release"}
    assert seen["rows"]["public_release"] == "off"
    assert others and set(others.values()) == {"active"}, others


def test_with_the_row_off_both_routes_answer_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_both_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200 and seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"]["GET /api/public-release/preview"] == 200
    # An empty body names no preview, so the answer is the handler's, not a missing route.
    assert seen["on"]["POST /api/public-release/publish"] == 409


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [m for m in OWN_CODE if m in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_both_routes(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_a_caller_on_another_machine_with_the_right_token_is_refused_on_both_routes(elsewhere: dict[str, Any]) -> None:
    assert elsewhere["here"]["GET /api/public-release/preview"] == 200
    assert elsewhere["elsewhere"] == dict.fromkeys(ROUTES.values(), 403)


@pytest.mark.parametrize(
    "changed", ["thomas/server/rows/public_release.py", "thomas/server/routes/public_release_routes.py"]
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_public_release_off_touches_only_its_routes.py" in chosen
    assert "tests/test_the_publish_routes_ask_for_a_sign_in.py" in chosen
