"""The self_review row, off: its route answers 404, a server started that way never loads it, and the review stops.

``GET /api/self-review`` starts a review of Thomas's own recent work in the background, which is a call to the model
that can sit for 120 seconds, and serves the last report with its age. The row creates the cache that holds the reports
and cancels a review still being written when it stops, so a review cannot go on after the row reads off.

Asking starts a call to the model, so the row runs the server's own access check first. In the shell the route had none,
and a caller on another machine with no token could start a review; one test pins that it is refused now.

Proofs of ``thomas.server.rows.self_review`` and ``thomas.server.routes.self_review``. The cache and its clocks are in
``tests/test_self_review_answers_fast_and_stamps_its_age.py``.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from tests.row_words_fixture import sentences, unnamed_tests
from thomas.server import app_core
from thomas.server.proof.selection import select
from thomas.server.routes import self_review as review
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

ROUTES = {"GET /api/self-review": "GET /api/self-review"}
OWN_CODE = ("thomas.server.rows.self_review", "thomas.server.routes.self_review")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, "HEAD /api/self-review"}
HERE = Path(__file__)
# Run ahead of the server so a request never reaches a real model: no client is built, and the review ends as no_llm.
NO_MODEL = """\
import thomas.server.chat_session_llm as _llm

_llm.announce_llm = lambda app, sid: None


"""
FIRST = "test_the_first_ask_answers_at_once_and_starts_one_call_to_the_model"
NO_PAGE = "test_no_page_in_thomas_asks_for_the_review"
GUARD = "test_a_remote_caller_with_no_token_is_refused_because_the_route_has_a_guard"
STOP = "test_turning_it_off_cancels_a_review_being_written_and_forgets_the_reports"
WORDS = {
    "Lets other programs ask for Thomas's review of its own recent work.": (FIRST,),
    "It reads recent chats, the failure list, the tasks workers finished and the thumbs you gave replies, and writes a "
    "short report of what went wrong and what to fix first.": (
        "test_the_review_is_made_from_chats_failures_tasks_and_thumbs",
    ),
    "The first ask answers at once that the report is being made, and starts it in the background, which costs a "
    "request to the model.": (FIRST,),
    "No page in Thomas shows it.": (NO_PAGE,),
    "Only programs on this computer can ask for it, and programs on other computers only when Thomas is open to them "
    "and they send your access key.": (GUARD,),
    "While this is off, nothing you use changes, because no page in Thomas asks for it.": (NO_PAGE,),
    "Other programs that ask get 404, and no review is started.": (
        "test_with_the_row_off_every_route_answers_404_and_none_is_listed",
        STOP,
    ),
    "A report being written when you turn this off is cancelled, and the reports kept in memory are forgotten, so "
    "turning this on again starts with none.": (STOP,),
    "A request that is still running will fail, and may need sending again.": (
        "test_stop_now_cuts_off_a_request_that_is_still_running",
    ),
}


class _Model:
    """A model that counts the calls it gets and holds each one until the test lets it go."""

    def __init__(self) -> None:
        self.messages: list[list[dict[str, Any]]] = []
        self.release = asyncio.Event()

    async def chat(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        self.messages.append(messages)
        await self.release.wait()
        return {"text": "1. TOP FRICTION - none."}


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _Model:
    held = _Model()
    monkeypatch.setattr("thomas.server.chat_session_llm.announce_llm", lambda app, sid: held)
    monkeypatch.setattr(review, "_repo_root", lambda: tmp_path / "repo")  # the finished report is written under it
    return held


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("self-review-off")
    reading = NO_MODEL + "def reading():\n    return None\n\n\n"
    started, found = start_with_one_row_off("self_review", list(ROUTES.values()), folder, reading=reading)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("self-review-remote")
    started, found = ask_as_a_remote_caller("self_review", list(ROUTES.values()), folder, ahead=NO_MODEL)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "self_review"}
    assert seen["rows"]["self_review"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_the_route_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == {"GET /api/self-review": 200}


def test_turned_off_on_a_running_server_the_route_goes_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_because_the_route_has_a_guard(remote: dict[str, Any]) -> None:
    """Asking starts a review, which is a call to the model, so a caller with no token is turned away before it does."""
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == {"GET /api/self-review": 401}
    # The ask with the token starts a review with no model to call, which ends as an error. Whether it has ended by the
    # time a second ask arrives is a race, so either answer is the handler's own and neither is a refusal.
    assert remote["with_token"]["GET /api/self-review"] in (200, 503)


def test_no_page_in_thomas_asks_for_the_review() -> None:
    callers = []
    for folder in ("thomas/server/web", "extensions", "apps", "desktop", "web"):
        where = ROOT / folder
        for path in where.rglob("*") if where.is_dir() else []:
            if path.suffix in {".js", ".html", ".ts", ".tsx"} and path.is_file():
                if "api/self-review" in path.read_text(encoding="utf-8", errors="replace"):
                    callers.append(path.relative_to(ROOT).as_posix())
    assert callers == []


def test_the_review_is_made_from_chats_failures_tasks_and_thumbs(model: _Model) -> None:
    model.release.set()
    done = asyncio.run(review.generate_self_review(web.Application(), hours=24))
    assert done["ok"] is True
    system, corpus = model.messages[0]
    for part in ("ISSUE / FRICTION LEDGER", "TASK OUTCOMES", "thumbs", "CONVERSATION EXCERPTS"):
        assert part in corpus["content"]
    assert "TOP FRICTION" in system["content"]
    assert "FIX FIRST" in system["content"]


def test_the_first_ask_answers_at_once_and_starts_one_call_to_the_model(
    tmp_path: Path, own_data_dir: Path, model: _Model
) -> None:
    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            first = await asyncio.wait_for(client.get("/api/self-review"), timeout=10)
            assert first.status == 200
            assert await first.json() == {"ok": True, "status": "generating"}
            second = await client.get("/api/self-review")
            assert (await second.json())["status"] == "generating"
            await asyncio.sleep(0.3)
            assert len(model.messages) == 1  # one call however many ask
            model.release.set()
            for _ in range(100):
                answer = await (await client.get("/api/self-review")).json()
                if answer.get("ok") and "report" in answer:
                    break
                await asyncio.sleep(0.1)
            assert answer["report"].startswith("# Thomas self-review")
            assert answer["stale"] is False

    asyncio.run(scenario())


def test_turning_it_off_cancels_a_review_being_written_and_forgets_the_reports(
    tmp_path: Path, own_data_dir: Path, model: _Model
) -> None:
    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            runtime = app[APP_RUNTIME_PLUGINS]
            first_cache = app.get(review.APP_SELF_REVIEW_CACHE)
            assert first_cache is not None
            assert (await client.get("/api/self-review")).status == 200
            await asyncio.sleep(0.3)
            task = first_cache["entries"][24]["task"]
            assert not task.done()

            await runtime.turn_off("self_review")

            assert task.cancelled()
            assert app.get(review.APP_SELF_REVIEW_CACHE) is None
            assert (await client.get("/api/self-review")).status == 404
            assert len(model.messages) == 1  # no second review started by the ask above

            await runtime.turn_on("self_review")
            second_cache = app.get(review.APP_SELF_REVIEW_CACHE)
            assert second_cache is not None
            assert second_cache is not first_cache
            assert second_cache["entries"] == {}
            assert (await client.get("/api/self-review")).status == 200

    asyncio.run(scenario())


def test_stop_now_cuts_off_a_request_that_is_still_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, own_data_dir: Path
) -> None:
    began = asyncio.Event()

    async def held(request: web.Request) -> web.Response:
        began.set()
        await asyncio.sleep(120)
        return web.json_response({})

    monkeypatch.setattr(review, "handle_self_review", held)

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            runtime = app[APP_RUNTIME_PLUGINS]
            asking = asyncio.create_task(client.get("/api/self-review"))
            await asyncio.wait_for(began.wait(), timeout=30)
            stopping = asyncio.create_task(runtime.turn_off("self_review"))
            await asyncio.sleep(0.3)
            assert not stopping.done()

            await runtime.turn_off("self_review", force=True)
            await asyncio.wait_for(stopping, timeout=30)

            assert runtime._report_row(runtime._row("self_review"))["state"] == "off"
            answer = (await asyncio.gather(asking, return_exceptions=True))[0]
            assert isinstance(answer, BaseException) or answer.status != 200, answer

    asyncio.run(scenario())


def test_every_sentence_of_the_words_names_the_test_that_shows_it() -> None:
    written = sentences("self_review", "about", "off_means", "stop_now")
    assert written == list(WORDS)
    assert unnamed_tests(WORDS, HERE) == []


@pytest.mark.parametrize("changed", ["thomas/server/rows/self_review.py", "thomas/server/routes/self_review.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_self_review_off_touches_only_its_routes.py" in chosen
    assert "tests/test_self_review_answers_fast_and_stamps_its_age.py" in chosen
