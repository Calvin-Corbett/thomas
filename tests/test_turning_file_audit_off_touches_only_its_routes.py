"""The file_audit row, off: its two routes answer 404, a server started that way never loads them, and nothing else moves.

The routes list the file changes that runs note in ``.thomas/file_audit.db``. They read a second copy of the module the
loop writes through (``thomas.observability.file_audit`` is loaded again by the bridge in ``thomas/observability``), so
they list nothing today, and these tests pin that, so the row's words change if it is ever fixed. The record itself is
started by the server and written by the loop, neither of which is the row.

Proofs of ``thomas.server.rows.file_audit`` and ``thomas.server.routes.audit``. The shell side is in
``tests/test_server_app_core.py`` and ``tests/test_server_access_mode.py``.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from tests.row_words_fixture import sentences, unnamed_tests
from thomas.observability import file_audit as alias_of_the_record
from thomas.server import app_core
from thomas.server.proof.selection import select
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /api/audit/files": "GET /api/audit/files",
    "GET /api/audit/runs/{run_id}/files": "GET /api/audit/runs/r1/files",
}
OWN_CODE = ("thomas.server.rows.file_audit", "thomas.server.routes.audit")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, "HEAD /api/audit/files", "HEAD /api/audit/runs/{run_id}/files"}
HERE = Path(__file__)
NOTHING_LISTED = "test_the_routes_list_nothing_today_because_they_read_a_second_copy"
NO_PAGE = "test_no_page_in_thomas_reads_this_record"
WORDS = {
    "Lets other programs ask for the file changes Thomas notes while it works.": (
        "test_turning_it_on_brings_back_both_routes_without_a_restart",
    ),
    "Today the answer is always an empty list, because these routes read a copy of the record that nothing writes to.": (
        NOTHING_LISTED,
    ),
    "No page in Thomas shows it.": (NO_PAGE,),
    "While this is off, nothing you use changes, because no page in Thomas reads this record and the routes list "
    "nothing today.": (NO_PAGE, NOTHING_LISTED),
    "Other programs that ask get 404.": ("test_with_the_row_off_every_route_answers_404_and_none_is_listed",),
    "Thomas goes on noting every file a run writes in the record it keeps, and nothing already noted is deleted.": (
        "test_the_record_goes_on_being_written_and_the_row_is_not_what_writes_it",
    ),
    "A request that is still running will fail, and may need sending again.": (
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
    folder = tmp_path_factory.mktemp("file-audit-off")
    started, found = start_with_one_row_off("file_audit", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("file-audit-remote")
    started, found = ask_as_a_remote_caller("file_audit", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "file_audit"}
    assert seen["rows"]["file_audit"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


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


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_no_page_in_thomas_reads_this_record() -> None:
    """The row's words say so. If a page starts to ask, this fails and those words have to change."""
    callers = []
    for folder in ("thomas/server/web", "extensions", "apps", "desktop", "web"):
        where = ROOT / folder
        for path in where.rglob("*") if where.is_dir() else []:
            if path.suffix in {".js", ".html", ".ts", ".tsx", ".py"} and path.is_file():
                if "api/audit/" in path.read_text(encoding="utf-8", errors="replace"):
                    callers.append(path.relative_to(ROOT).as_posix())
    assert callers == []


def test_the_routes_list_nothing_today_because_they_read_a_second_copy(tmp_path: Path) -> None:
    """A write goes through the module the server starts. The routes read the bridge's copy, which was never started.

    If the two become one module, this fails and the row's words, which say the answer is always an empty list, change.
    """
    from thomas.marketplace.observability import file_audit as the_record

    assert alias_of_the_record is not the_record
    the_record.init_audit(tmp_path / "file_audit.db")
    the_record.record_file_write(run_id="r1", model="m", tool_name="fs.write_file", path="a.txt")
    assert len(the_record.list_file_changes()) == 1
    assert alias_of_the_record.list_file_changes() == []


def test_the_record_goes_on_being_written_and_the_row_is_not_what_writes_it() -> None:
    """The server starts the record in app_core and the loop writes it through its own import: neither is the row."""
    shell = (ROOT / "thomas" / "server" / "app_core.py").read_text(encoding="utf-8")
    loop = (ROOT / "thomas" / "agent" / "loop_tools.py").read_text(encoding="utf-8")
    assert "_file_audit.init_audit(audit_db_path)" in shell
    assert "thomas.server.routes.audit" not in shell
    assert "from thomas.marketplace.observability import file_audit as _file_audit" in loop
    assert "routes.audit" not in loop


def test_stop_now_cuts_off_a_request_that_is_still_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, own_data_dir: Path
) -> None:
    """A stop waits for the request. Stop now drops it, so the program that asked never gets an answer."""
    began = asyncio.Event()

    async def held(request: Any) -> tuple[bytes, int, dict]:
        began.set()
        await asyncio.sleep(120)
        return b"{}", 200, {}

    monkeypatch.setattr("thomas.server.routes.audit.handle_audit_files", held)

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            runtime = app[APP_RUNTIME_PLUGINS]
            asking = asyncio.create_task(client.get("/api/audit/files"))
            await asyncio.wait_for(began.wait(), timeout=30)
            stopping = asyncio.create_task(runtime.turn_off("file_audit"))
            await asyncio.sleep(0.3)
            assert not stopping.done()

            await runtime.turn_off("file_audit", force=True)
            await asyncio.wait_for(stopping, timeout=30)

            assert runtime._report_row(runtime._row("file_audit"))["state"] == "off"
            answer = (await asyncio.gather(asking, return_exceptions=True))[0]
            assert isinstance(answer, BaseException) or answer.status != 200, answer

    asyncio.run(scenario())


def test_every_sentence_of_the_words_names_the_test_that_shows_it() -> None:
    written = sentences("file_audit", "about", "off_means", "stop_now")
    assert written == list(WORDS)
    assert unnamed_tests(WORDS, HERE) == []


@pytest.mark.parametrize("changed", ["thomas/server/rows/file_audit.py", "thomas/server/routes/audit.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_file_audit_off_touches_only_its_routes.py" in chosen
