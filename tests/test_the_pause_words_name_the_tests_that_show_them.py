"""The words the Plugins page shows for Pause and Resume are held a sentence at a time, each with the tests that show it.

The row is ``thomas.server.rows.pause`` and its routes are ``thomas.server.routes.pause_routes``. A new, changed or
dropped sentence fails here until the list below has it with a test that shows it. The row is required, so it can fail to
start but never be turned off: that failure and the Try again that follows are shown here, on a real server.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import tomllib
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture
from thomas.server import app_core
from thomas.server.proof.selection import select
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS, PROFILE_PATH

ROOT = Path(__file__).resolve().parents[1]
HERE = "tests/test_the_pause_words_name_the_tests_that_show_them.py"
ROUTES = "tests/test_turning_pause_off_touches_only_its_routes.py"
ENGINES = "tests/test_pause_idles_the_engines.py"
LOOPS = "tests/test_pause_idles_the_servers_own_loops.py"
RUNS = "tests/test_pause_refuses_a_new_build_run.py"
FLAG = "tests/test_pause_flag.py"
STOPS = (
    f"{ENGINES}::test_an_engine_starts_no_cycle_while_paused_and_starts_one_after_resume",
    f"{ENGINES}::test_the_idle_sweep_skips_its_tick_while_paused_and_keeps_its_timer",
    f"{ENGINES}::test_a_scheduled_job_that_falls_due_while_paused_waits_and_runs_after_resume",
    f"{LOOPS}::test_the_daily_ratchet_run_is_skipped_while_paused_and_runs_after_resume",
    f"{LOOPS}::test_the_park_loop_starts_nothing_while_paused_and_carries_on_after_resume",
    f"{RUNS}::test_a_paused_thomas_refuses_a_new_run_in_words_the_page_shows",
)
# Each sentence of what the Plugins page says, and the tests that show it.
WORDS = {
    "Lets you stop everything Thomas starts by himself, and start it again.": (
        f"{ROUTES}::test_the_three_routes_read_pause_and_resume_the_saved_switch",
    ),
    "While paused, the server stays up and Chat still answers you, but the background engines, the daily run that "
    "checks and lands Thomas's own changes, the queue that starts planned Thomas projects, scheduled jobs, the idle "
    "awareness sweep and any new Build or Code run do not start.": (
        f"{ROUTES}::test_chat_still_answers_while_paused",
        *STOPS,
    ),
    "A new Build or Code run is refused with a message saying Thomas is paused.": (
        f"{RUNS}::test_a_paused_thomas_refuses_a_new_run_in_words_the_page_shows",
    ),
    "Work that is already running is not stopped and finishes.": (
        f"{ROUTES}::test_pausing_does_not_end_a_run_and_still_running_counts_it",
    ),
    "The choice is kept in your data folder, so a Thomas that starts while paused starts none of this either.": (
        f"{FLAG}::test_pause_saves_the_flag_in_the_data_folder_and_resume_clears_it",
        f"{ROUTES}::test_the_pause_flag_is_kept_in_the_data_folder_so_a_new_server_starts_paused",
        f"{LOOPS}::test_a_server_that_starts_paused_does_not_retry_held_hand_ins_at_startup",
    ),
    "Other programs can read the state, pause and resume through three addresses, and each says how many runs are "
    "still going.": (
        f"{ROUTES}::test_the_three_routes_read_pause_and_resume_the_saved_switch",
        f"{ROUTES}::test_pausing_does_not_end_a_run_and_still_running_counts_it",
    ),
    "Pause and Resume is part of how Thomas works, so it cannot be turned off.": (
        f"{ROUTES}::test_turning_it_off_is_refused_with_a_sentence_even_when_forced_and_a_saved_off_is_ignored",
    ),
    "The Plugins page shows it as on, with no switch, and anything that tries to turn it off is refused with a message "
    "saying so.": (
        f"{ROUTES}::test_the_row_is_required_and_on",
        f"{ROUTES}::test_turning_it_off_is_refused_with_a_sentence_even_when_forced_and_a_saved_off_is_ignored",
    ),
    "If it fails to start, Thomas goes on running without it, and Try again on this page starts it once the cause is "
    "fixed.": (f"{HERE}::test_a_pause_that_fails_to_start_leaves_thomas_running_and_tries_again",),
}


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("THOMAS_PROFILE", raising=False)
    return tmp_path / "data"


def _row_words() -> dict[str, str]:
    with PROFILE_PATH.open("rb") as handle:
        return next(row for row in tomllib.load(handle)["row"] if row["id"] == "pause")


def test_every_sentence_of_the_pause_words_names_the_test_that_shows_it() -> None:
    row = _row_words()
    written = [*re.split(r"(?<=\.)\s+", row["about"]), *re.split(r"(?<=\.)\s+", row["off_means"])]

    assert written == list(WORDS)
    assert row["stop_now"] == ""  # nothing here starts work a stop would wait for
    for tests in WORDS.values():
        for named in tests:
            path, _, name = named.partition("::")
            assert f"def {name}(" in (ROOT / path).read_text(encoding="utf-8"), named


def test_a_pause_that_fails_to_start_leaves_thomas_running_and_tries_again(tmp_path: Path, own_data_dir: Path) -> None:
    async def scenario() -> dict[str, Any]:
        with patch("thomas.server.routes.pause_routes.register_pause_routes", side_effect=RuntimeError("pause-boom")):
            app = app_core.create_app(plugin_view_fixture.config_in(tmp_path))
        row = next(r for r in app[APP_RUNTIME_PLUGINS].report()["rows"] if r["id"] == "pause")
        seen: dict[str, Any] = {"failed": (row["state"], row["error"])}
        async with TestClient(TestServer(app)) as client:
            seen["down"] = (await client.get("/api/thomas/pause")).status
            seen["health"] = (await client.get("/api/health")).status
            pressed = await client.post("/api/plugins/thomas/pause/on")
            seen["pressed"] = (pressed.status, (await pressed.json())["state"])
            seen["up"] = (await client.get("/api/thomas/pause")).status
        return seen

    seen = asyncio.run(scenario())

    assert seen["failed"] == ("failed", "RuntimeError: pause-boom")
    assert seen["down"] == 404
    assert seen["health"] == 200
    assert seen["pressed"] == (200, "active")
    assert seen["up"] == 200


def test_a_change_to_the_words_runs_this_file() -> None:
    assert HERE in select(ROOT, ["thomas/server/rows/default.toml"]).files
