"""The issues row, off: its two routes answer 404, a server started that way never loads them, and nothing else moves.

The routes take a note from the Chat, Code and Work pages when something goes wrong in them, and give the summary of the
failure list. The list is a file that much of Thomas writes to directly and that Thomas reads back when it reviews its own
work, and none of that goes through these routes, so off cannot stop it.

Neither handler asks the access guard. Only the server's own rule for writes stands in front of the POST, so a caller on
another machine with no token reads the summary today. That is how the routes were in the shell and the move keeps it.

Proofs of ``thomas.server.rows.issues`` and ``thomas.server.routes.issues_aiohttp``. The routes themselves are in
``tests/test_issues_routes.py`` and the pages in ``tests/test_the_pages_that_report_failures_with_their_row_off.py``.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from tests.row_words_fixture import sentences, unnamed_tests
from thomas.server import app_core, issue_ledger
from thomas.server.proof.selection import select
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /api/issues": "GET /api/issues",
    "POST /api/issues": "POST /api/issues",
}
OWN_CODE = ("thomas.server.rows.issues", "thomas.server.routes.issues_aiohttp")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, "HEAD /api/issues"}
HERE = Path(__file__)
ROUTE_TESTS = ROOT / "tests" / "test_issues_routes.py"
PAGE_TESTS = ROOT / "tests" / "test_the_pages_that_report_failures_with_their_row_off.py"
# Run ahead of the server, so a request with the token never writes to the checkout's own ledger.
OWN_LEDGER = """\
import pathlib
import sys

import thomas.server.issue_ledger as _ledger

_ledger._REPO_ROOT = pathlib.Path(sys.argv[2]) / "ledger"
_ledger._is_test_run_writing_to_the_real_ledger = lambda path: False


"""
NOTE = "test_a_reported_failure_is_written_to_the_ledger_and_comes_back_in_the_summary"
WORDS = {
    "Lets the Chat, Code and Work pages send Thomas a note when something goes wrong in them, so it is kept in the "
    "failure list.": ("test_only_the_chat_code_and_work_pages_send_a_note", NOTE),
    "It also lets other programs add a note to that list, or read a summary of it for the last hour up to the last two "
    "weeks.": (NOTE, "test_the_summary_window_is_kept_between_one_hour_and_two_weeks"),
    "No page in the sidebar shows that summary.": ("test_only_the_chat_code_and_work_pages_send_a_note",),
    "While this is off, Chat, Code and Work go on working, because they send these notes without waiting for an "
    "answer.": ("test_the_pages_open_and_go_on_working",),
    "A note they send gets 404 and is lost, and nothing on the screen says so.": (
        "test_a_note_a_page_sends_gets_404_and_nothing_on_the_screen_says_so",
    ),
    "They do not send it again and again, and an open page behaves the same as one you reload.": (
        "test_a_page_does_not_send_it_again_and_again",
    ),
    "Other programs that add a note or ask for the summary get 404.": (
        "test_with_the_row_off_every_route_answers_404_and_none_is_listed",
    ),
    "Everything else in Thomas that records a failure writes to the failure list directly, and Thomas still reads that "
    "list when it reviews its own recent work, so none of that changes.": (
        "test_the_list_is_written_and_read_without_the_routes",
    ),
    "Notes already kept stay.": ("test_stop_now_cuts_off_a_request_that_is_still_running",),
    "A note or a summary request that is still running will fail, and may need sending again.": (
        "test_stop_now_cuts_off_a_request_that_is_still_running",
    ),
}


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("issues-off")
    reading = OWN_LEDGER + "def reading():\n    return None\n\n\n"
    started, found = start_with_one_row_off("issues", list(ROUTES.values()), folder, reading=reading)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("issues-remote")
    started, found = ask_as_a_remote_caller("issues", list(ROUTES.values()), folder, ahead=OWN_LEDGER)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "issues"}
    assert seen["rows"]["issues"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_with_the_row_off_the_ledger_module_the_rest_of_thomas_writes_through_has_loaded(seen: dict[str, Any]) -> None:
    assert "thomas.server.issue_ledger" in seen["loaded"]


def test_turning_it_on_brings_back_both_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == dict.fromkeys(ROUTES.values(), 200)


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_the_write_and_reads_the_summary(remote: dict[str, Any]) -> None:
    """Reported, not changed here: the handler for GET has no access guard and only a write gets the server's own."""
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == {"GET /api/issues": 200, "POST /api/issues": 401}
    assert remote["with_token"] == dict.fromkeys(ROUTES.values(), 200)


def test_only_the_chat_code_and_work_pages_send_a_note() -> None:
    """The row's words name these three pages and say no page shows the summary. A new caller fails this."""
    web = ROOT / "thomas" / "server" / "web"
    callers = {
        path.name: path.read_text(encoding="utf-8")
        for path in web.rglob("*")
        if path.suffix in {".js", ".html"} and "/api/issues" in path.read_text(encoding="utf-8", errors="replace")
    }
    assert sorted(callers) == ["chat_message_view.js", "unified_code_mode.js", "unified_work_mode.js"]
    assert all("method: 'POST'" in text for text in callers.values())


def test_the_list_is_written_and_read_without_the_routes() -> None:
    """The ledger module imports no route, and the review of Thomas's own work reads it from there, not by asking."""
    ledger = (ROOT / "thomas" / "server" / "issue_ledger.py").read_text(encoding="utf-8")
    review = (ROOT / "thomas" / "server" / "routes" / "self_review.py").read_text(encoding="utf-8")
    assert "issues_aiohttp" not in ledger
    assert "from thomas.server.issue_ledger import summarize as summarize_issues" in review
    assert "issues_aiohttp" not in review


def test_stop_now_cuts_off_a_request_that_is_still_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, own_data_dir: Path
) -> None:
    """A stop waits for the request and Stop now drops it. A note kept before that is still in the list afterwards."""
    monkeypatch.setattr(issue_ledger, "_REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(issue_ledger, "_is_test_run_writing_to_the_real_ledger", lambda path: False)
    began = asyncio.Event()

    async def never_ends() -> Any:
        yield b'{"surface":'
        began.set()
        await asyncio.sleep(120)

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            runtime = app[APP_RUNTIME_PLUGINS]
            kept = await client.post("/api/issues", json={"surface": "chat-ui", "message": "kept"})
            assert kept.status == 200
            asking = asyncio.create_task(client.post("/api/issues", data=never_ends()))
            await asyncio.wait_for(began.wait(), timeout=30)
            stopping = asyncio.create_task(runtime.turn_off("issues"))
            await asyncio.sleep(0.3)
            assert not stopping.done()

            await runtime.turn_off("issues", force=True)
            await asyncio.wait_for(stopping, timeout=30)

            assert runtime._report_row(runtime._row("issues"))["state"] == "off"
            answer = (await asyncio.gather(asking, return_exceptions=True))[0]
            assert isinstance(answer, BaseException) or answer.status != 200, answer
            assert (await client.get("/api/issues")).status == 404

    asyncio.run(scenario())
    lines = (tmp_path / "repo" / "runtime" / "logs" / "issues.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["message"] for line in lines] == ["kept"]


def test_every_sentence_of_the_words_names_the_test_that_shows_it() -> None:
    written = sentences("issues", "about", "off_means", "stop_now")
    assert written == list(WORDS)
    assert unnamed_tests(WORDS, HERE, ROUTE_TESTS, PAGE_TESTS) == []


@pytest.mark.parametrize("changed", ["thomas/server/rows/issues.py", "thomas/server/routes/issues_aiohttp.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_issues_off_touches_only_its_routes.py" in chosen
    assert "tests/test_issues_routes.py" in chosen
