"""The Discord row, off: its ten routes answer 404 and the channel's code has not loaded.

Turning it off on a running server also stops the Discord bridge, a program of its own, and
``tests/test_the_discord_row_through_off_and_on.py`` holds that, and what comes back when it is turned on again. The
workspace resident that can read or change the channel is held to the row in ``tests/test_workspace_specialist_actions.py``.

The routes are those of ``thomas.server.rows.discord`` and ``thomas.server.routes.discord_channels_aiohttp``, and
``tests/test_discord_channels.py`` holds what they do with the row on.

The word channel names other things. ``thomas channels send`` and the webhook senders under ``thomas/marketplace/channels``
send to Discord without this row, and off does not reach them.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

# Written out, because a list worked out from the row would agree with whatever the row did. The session is one that does
# not exist, and nothing here is set up, so a start or a voice probe is refused for want of a token and starts nothing.
ROUTES = {
    "GET /api/channels/discord": "GET /api/channels/discord",
    "POST /api/channels/discord/config": "POST /api/channels/discord/config",
    "POST /api/channels/discord/runtime": "POST /api/channels/discord/runtime",
    "POST /api/channels/discord/enabled": "POST /api/channels/discord/enabled",
    "POST /api/channels/discord/start": "POST /api/channels/discord/start",
    "POST /api/channels/discord/stop": "POST /api/channels/discord/stop",
    "POST /api/channels/discord/restart": "POST /api/channels/discord/restart",
    "POST /api/channels/discord/voice-probe": "POST /api/channels/discord/voice-probe",
    "GET /api/channels/discord/history": "GET /api/channels/discord/history",
    "GET /api/channels/discord/history/{session_id}": "GET /api/channels/discord/history/s1",
}
OWN_CODE = (
    "thomas.server.rows.discord",
    "thomas.server.routes.discord_channels_aiohttp",
    "thomas.integrations.discord_bridge_runtime",
)
LISTED = {
    *ROUTES,
    "HEAD /api/channels/discord",
    "HEAD /api/channels/discord/history",
    "HEAD /api/channels/discord/history/{session_id}",
}

ROW = "discord"


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("discord-off")
    started, found = start_with_one_row_off(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("discord-remote")
    started, found = ask_as_a_remote_caller(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_all_ten_routes_without_a_restart(seen: dict[str, Any]) -> None:
    """Nothing is set up on this server, so a start and a voice probe are refused by the handler with a 400."""
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == {
        "GET /api/channels/discord": 200,
        "POST /api/channels/discord/config": 200,
        "POST /api/channels/discord/runtime": 200,
        "POST /api/channels/discord/enabled": 400,  # asks for ``enabled``
        "POST /api/channels/discord/start": 400,  # not set up
        "POST /api/channels/discord/stop": 200,  # nothing to stop
        "POST /api/channels/discord/restart": 400,  # not set up
        "POST /api/channels/discord/voice-probe": 400,  # not set up
        "GET /api/channels/discord/history": 200,
        "GET /api/channels/discord/history/s1": 200,
    }


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_a_change_to_the_row_runs_its_proofs() -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    for changed in ("thomas/server/rows/discord.py", "thomas/server/routes/discord_channels_aiohttp.py"):
        chosen = select(ROOT, [changed]).files
        assert "tests/test_turning_discord_off_touches_only_its_routes.py" in chosen
        assert "tests/test_the_discord_row_through_off_and_on.py" in chosen
        assert "tests/test_discord_channels.py" in chosen


def test_only_the_channels_page_and_the_workspace_resident_use_the_channel() -> None:
    """The row's words describe these. If a second page starts calling the routes, or something else builds the runtime, they must too."""
    found = subprocess.run(
        [
            "git",
            "grep",
            "-l",
            "api/channels/discord",
            "--",
            "thomas",
            "web",
            "extensions",
            "apps",
            "desktop",
            "scripts",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert sorted(found.stdout.split()) == [
        "thomas/server/routes/discord_channels_aiohttp.py",
        "thomas/server/rows/discord.py",
        "thomas/server/web/js/runtime/036_workbench_editors_08.js",
        "thomas/server/web/js/runtime/038_module_rendering_dispatch_01.js",
    ]
    building = subprocess.run(
        ["git", "grep", "-l", " = DiscordBridgeRuntime(", "--", "thomas"], cwd=ROOT, capture_output=True, text=True
    )
    assert building.stdout.split() == ["thomas/server/rows/discord.py"]
