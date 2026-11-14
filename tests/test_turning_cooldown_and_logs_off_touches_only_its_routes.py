"""The rate limit line and log export, off: three routes answer 404, and a server started that way never loads them.

The routes only read. ``GET /api/chat/cooldowns`` reads what the LLM client keeps about models it is resting, so off
cannot change which model answers. ``/api/logs/export`` packs the logs folder, so off cannot stop anything being written
there. What goes is what the page learns from them, and these tests hold the row's words to that.

``/api/logs/export`` answers 404 by itself on a server with no logs folder, so ``seen`` is given one. A 404 there with the
row off then cannot be the handler's, and ``remote``, which has none, holds the handler's own answer.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT, ROWS, module_of, named
from thomas.core import llm_client
from thomas.server import app_core
from thomas.server.proof.selection import select

ROW = "cooldown_and_logs"
# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /api/chat/cooldowns": "GET /api/chat/cooldowns",
    "GET /api/logs/export": "GET /api/logs/export",
    "HEAD /api/logs/export": "HEAD /api/logs/export",
}
OWN_CODE = (
    "thomas.server.rows.cooldown_and_logs",
    "thomas.server.routes.cooldown_routes",
    "thomas.server.routes.logs_export_routes",
)
# aiohttp lists a HEAD beside each GET. The export asks it not to and registers its own, so the probe builds no archive.
LISTED = {*ROUTES, "HEAD /api/chat/cooldowns"}


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("cooldown-and-logs-off")
    (folder / "memory" / "logs").mkdir(parents=True)
    started, found = start_with_one_row_off(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("cooldown-and-logs-remote")
    started, found = ask_as_a_remote_caller(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a server started here must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def _write_log(folder: Path, name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text("a line\n", encoding="utf-8", newline="\n")


def _what_a_real_server_answers(tmp_path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    """The names in the export, then the rows the line is told, from a server built the way a real one is."""

    async def scenario() -> tuple[list[str], list[dict[str, Any]]]:
        app = app_core.create_app(plugin_view_fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            export = await client.get("/api/logs/export")
            assert export.status == 200
            resting = await client.get("/api/chat/cooldowns")
            assert resting.status == 200
            names = sorted(zipfile.ZipFile(io.BytesIO(await export.read())).namelist())
            return names, (await resting.json())["cooldowns"]

    return asyncio.run(scenario())


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


def test_the_row_names_both_its_route_modules() -> None:
    """A press on imports what a row names in a thread, and the proof of every row watches only what it names.

    A module left out still works, because ``apply`` imports it, so nothing else here would show that it now loads on the
    event loop and has dropped out of that proof.
    """
    entry = next(row for row in ROWS if row.id == ROW)
    assert sorted(named(entry)) == sorted(set(OWN_CODE) - {module_of(entry)})


def test_with_the_row_off_what_rests_a_model_is_still_loaded(seen: dict[str, Any]) -> None:
    """The row's words say Thomas goes on resting models. That is the client's work, and these routes only read it."""
    assert "thomas.core.llm_client" in seen["loaded"]


def test_turning_it_on_brings_back_all_three_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == dict.fromkeys(ROUTES.values(), 200)


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_with_no_logs_folder_the_export_answers_404_itself_so_the_button_stays_grey(remote: dict[str, Any]) -> None:
    """This server has never had a logs folder. With the row on and the token shown, the probe still fails."""
    assert remote["with_token"] == {
        "GET /api/chat/cooldowns": 200,
        "GET /api/logs/export": 404,
        "HEAD /api/logs/export": 404,
    }


def test_the_export_packs_the_logs_folder_under_the_data_root(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("THOMAS_LOG_FILE", raising=False)
    _write_log(tmp_path / "memory" / "logs", "thomas.log")

    names, _ = _what_a_real_server_answers(tmp_path)

    assert names == ["thomas.log"]


def test_the_export_packs_the_folder_of_the_log_thomas_was_told_to_write(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A server started the usual way is told where its log goes, and that folder is the one to pack."""
    _write_log(tmp_path / "memory" / "logs", "thomas.log")
    _write_log(tmp_path / "elsewhere", "thomas.log.1")
    monkeypatch.setenv("THOMAS_LOG_FILE", str(tmp_path / "elsewhere" / "thomas.log"))

    names, _ = _what_a_real_server_answers(tmp_path)

    assert names == ["thomas.log.1"]


def test_the_line_is_told_about_a_model_the_client_is_resting(
    tmp_path: Path, own_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through the live table, on the client's own record of what it is resting.

    Ten minutes, the longest a park lasts, because the server starts after this one is set. A start took 12 seconds alone
    and longer on a busy machine, and a 20 second park had ended by the time the route was asked.
    """
    monkeypatch.setattr(llm_client, "_PROVIDER_COOLDOWNS", {})
    _write_log(tmp_path / "memory" / "logs", "thomas.log")
    llm_client._get_cooldown("gpt-test").mark("rate_limit", base_s=600.0)

    _, rows = _what_a_real_server_answers(tmp_path)

    assert [row["profile"] for row in rows] == ["gpt-test"]
    assert rows[0]["failure_type"] == "rate_limit"


def test_only_the_chat_line_and_the_export_button_call_these_routes() -> None:
    """The row's words name these two. If a page gets a new caller, this fails and those words have to change.

    A landing runs this only for a change to this row or its routes. A caller added anywhere else is found by the full
    suite.
    """
    web = ROOT / "thomas" / "server" / "web"
    pages = [*web.rglob("*.js"), *web.rglob("*.html")]
    texts = {path: path.read_text(encoding="utf-8", errors="replace") for path in pages}

    assert [path.name for path, text in texts.items() if "/api/chat/cooldowns" in text] == ["rate_limit_banner.js"]
    assert [path.name for path, text in texts.items() if "/api/logs/export" in text] == ["settings.maintenance.js"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_words_name_every_way_a_line_already_showing_ends(seen: dict[str, Any]) -> None:
    """With the route gone, only the stream can change the line, and the plan and reset come from nowhere else.

    The words listed two ways a line ends. A message into a resting model is a third, and it swaps a line that named a
    limit for a countdown of ten minutes at most, which then ends with the limit still out. A message another model
    answers does not, so the words cannot say any new message does. Reloading empties the line as well.
    """
    limit = "ChatGPT Pro has reached its usage limit · resets Monday 2 November at 18:48 · another model is needed until then"
    countdown = "local is rate-limited · back in 9:42 · Thomas will try again when it clears"
    out = subprocess.run(
        [
            "node",
            str(ROOT / "tests" / "web_node" / "rate_limit_line_route_gone.mjs"),
            str(ROOT / "thomas" / "server" / "web" / "js" / "rate_limit_banner.js"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert out.returncode == 0, out.stderr

    assert json.loads(out.stdout.strip().splitlines()[-1]) == {
        "opened": limit,
        "turned_off": limit,
        "another_model_answered": limit,
        "a_message_ran_into_a_resting_model": countdown,
        "that_countdown_ended": "",
        "a_resting_model_refused_the_message": countdown,
        "that_model_answered": "",
        "its_time_was_up": "",
        "reloaded": "",
    }
    assert (
        "A line already showing stays until you reload Chat, its time is up, that model answers, or a message runs into "
        "a resting model, which puts a countdown in its place and takes away any plan and reset it named."
    ) in seen["row_on"]["off_means"]


@pytest.mark.parametrize(
    ("changed", "feature_test"),
    [
        ("thomas/server/rows/cooldown_and_logs.py", "tests/test_provider_cooldowns.py"),
        ("thomas/server/rows/cooldown_and_logs.py", "tests/test_the_settings_page_can_export_the_logs.py"),
        ("thomas/server/routes/cooldown_routes.py", "tests/test_provider_cooldowns.py"),
        ("thomas/server/routes/logs_export_routes.py", "tests/test_the_settings_page_can_export_the_logs.py"),
    ],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str, feature_test: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_cooldown_and_logs_off_touches_only_its_routes.py" in chosen
    assert feature_test in chosen
