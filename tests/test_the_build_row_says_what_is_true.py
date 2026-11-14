"""Every sentence the Plugins page shows for the Build row names a test that shows it, and the row stands in for Build.

The words are in ``thomas/server/rows/default.toml`` and the row is ``thomas.server.rows.build``. A new, changed or
dropped sentence fails here until the list below has it with a test that exists. The routes and the shutdown are in
``tests/test_the_build_row.py``, which is read for the names too.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import pytest

from tests.build_row_fixture import AGENT, LOOP, running
from tests.row_proof_fixture import ROOT
from thomas.core.kernel import Profile
from thomas.server import runtime_plugins
from thomas.server.runtime_plugins import PROFILE_PATH

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 uses the declared tomli dependency.
    import tomli as tomllib


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Choices are saved under the data folder, so a test that presses a switch must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


WORDS = {
    "Runs Build, next to Chat and Work: sending a message, the live stream of a run, stopping, steering and approving, "
    "your Build conversations with their files and previews, and keeping or reverting a run's changes.": (
        "test_the_row_is_required_and_on_with_all_its_routes_live",
        "test_every_address_the_build_page_calls_is_one_the_row_serves",
    ),
    "It also serves the upgrade loop's status, plan, start, pause, approve and reject, which the Evolution dashboard "
    "calls, and the orchestration status and plan, which no page calls.": (
        "test_the_evolution_dashboard_calls_the_loop_routes_and_no_page_calls_orchestration",
    ),
    "This cannot be turned off, because Build does not work without it.": (
        "test_turning_it_off_is_refused_with_or_without_force",
        "test_without_the_row_the_build_routes_answer_404",
    ),
    "The Plugins page shows it on and locked, and a request to turn it off is refused.": (
        "test_the_row_is_required_and_on_with_all_its_routes_live",
        "test_turning_it_off_is_refused_with_or_without_force",
    ),
    "If it fails to start, Thomas keeps running, the Plugins page shows it as failed with the reason, and Try again "
    "starts it.": ("test_a_registrar_that_fails_leaves_the_server_up_and_try_again_starts_the_row_once",),
    "When Thomas closes, the upgrade loop and each approval it started are ended.": (
        "test_a_server_that_closes_ends_the_process_the_loop_started",
        "test_the_loop_and_every_approval_it_started_are_ended_and_nothing_else",
    ),
}
WEB = ROOT / "thomas" / "server" / "web"
AGENT_PATHS = {route.split(" ", 1)[1] for route in AGENT}
LOOP_PATHS = {route.split(" ", 1)[1] for route in LOOP}


def _row() -> dict[str, Any]:
    with PROFILE_PATH.open("rb") as handle:
        return next(row for row in tomllib.load(handle)["row"] if row["id"] == "build")


def _literals(pattern: str) -> dict[str, set[str]]:
    """Each script of the web layer that spells an address matching ``pattern``, with the addresses it spells."""
    found: dict[str, set[str]] = {}
    for path in WEB.rglob("*.js"):
        spelled = set(re.findall(pattern, path.read_text(encoding="utf-8", errors="replace")))
        if spelled:
            found[path.name] = spelled
    return found


def test_every_sentence_of_the_build_words_names_a_test_that_shows_it() -> None:
    row = _row()
    here = (ROOT / "tests" / "test_the_build_row_says_what_is_true.py").read_text(encoding="utf-8")
    there = (ROOT / "tests" / "test_the_build_row.py").read_text(encoding="utf-8")

    written = [*re.split(r"(?<=\.)\s+", row["about"]), *re.split(r"(?<=\.)\s+", row["off_means"])]
    assert written == list(WORDS)
    named_tests = {name for names in WORDS.values() for name in names}
    assert {name for name in named_tests if f"def {name}(" not in here + there} == set()


def test_the_row_is_required_and_asks_nothing_to_wait_for() -> None:
    row = _row()
    assert row["required"] is True
    assert row["stop_now"] == ""  # a stop is refused, so Stop now is never shown beside it
    assert row["id"] == "build"  # the same as the plugin manifest (plugins/build.toml), which is allowed when required


def test_every_address_the_build_page_calls_is_one_the_row_serves() -> None:
    spelled = _literals(r"/api/evolve/agent/[A-Za-z0-9_\-/]*")
    assert spelled, "no script spells an agent address, so this proves nothing"
    for script, addresses in spelled.items():
        for address in addresses:
            prefix = address.rstrip("/")
            assert any(path == prefix or path.startswith(prefix + "/") for path in AGENT_PATHS), (script, address)


def test_the_evolution_dashboard_calls_the_loop_routes_and_no_page_calls_orchestration() -> None:
    loop = _literals(r"/api/evolve/loop/[A-Za-z0-9_\-/]*")
    assert set(loop) == {"046_evolution_dashboard.js"}
    # Its header comment spells the family as /api/evolve/loop/*, which is no address.
    called = {address.rstrip("/") for address in loop["046_evolution_dashboard.js"]} - {"/api/evolve/loop"}
    assert called == {
        "/api/evolve/loop/start",
        "/api/evolve/loop/pause",
        "/api/evolve/loop/approve",
        "/api/evolve/loop/reject",
        "/api/evolve/loop/status",
        "/api/evolve/loop/plan",
    }
    assert all(any(path.startswith(address) for path in LOOP_PATHS) for address in called)
    assert _literals(r"/api/evolve/orchestration/[A-Za-z0-9_\-/]*") == {}


def test_without_the_row_the_build_routes_answer_404(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing else in the shell serves them any more, so a server with no rows has no Build."""
    monkeypatch.setattr(runtime_plugins, "read_profile", lambda _path: Profile("no rows"))

    async def scenario() -> None:
        async with running(tmp_path) as (_app, _runtime, client):
            for address in ("/api/evolve/agent/status", "/api/evolve/loop/status", "/api/evolve/agent/conversations"):
                assert (await client.get(address)).status == 404, address

    asyncio.run(scenario())


def test_with_the_row_the_same_addresses_answer(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> None:
        async with running(tmp_path) as (_app, _runtime, client):
            for address in ("/api/evolve/agent/status", "/api/evolve/loop/status", "/api/evolve/agent/conversations"):
                assert (await client.get(address)).status == 200, address

    asyncio.run(scenario())
