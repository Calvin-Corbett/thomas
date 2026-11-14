"""The Current Task box on the older full page, with the task-ledger row on, off and on again, in a real browser.

The row is ``thomas.server.rows.task_ledger`` and its routes are registered by ``thomas.server.task_ledger_routes``. The
routes, a server started with the row off and a caller with no token are in
``tests/test_turning_task_ledger_off_touches_only_its_routes.py``. The older full page reads these routes from
``thomas/server/web/js/runtime/006_easy_setup_onboarding_04.js``, and the box it fills is the one in Mission Control.

Every sentence of the row's words is in ``SENTENCES`` with the tests that show it, and the last test fails when a
sentence is added, changed or dropped without this list.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

import pytest

from tests.click_past_easy_setup import click_past_easy_setup
from tests.row_page_fixture import serving
from tests.row_proof_fixture import ROOT, ROWS
from tests.web_fixtures.thomas_chat_fixture import browser_ok
from thomas.marketplace.observability.task_ledger import TaskLedgerStore

pytestmark = pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")

WORDS = next(row for row in ROWS if row.id == "task_ledger").config["words"]
WINDOW = {"width": 1400, "height": 900}
LEDGER = ("/api/task-ledger/current", "/api/task-ledger/history")
GOAL = "Ship the quarterly report"
PROGRESS = "Draft written, charts still to do"
LATER = "Charts done, waiting on review"
NO_TASK = "No current task"
# What a person can read in the box, which Mission Control builds from the record.
BOX = """() => {
    const box = document.querySelector('.mission-runtime-panel');
    const at = (role) => box?.querySelector(`[data-role="${role}"]`)?.textContent?.trim() ?? null;
    const shown = box ? box.getBoundingClientRect().height > 0 : false;
    return {shown, title: at('title'), summary: at('summary')};
}"""
PROOFS = (
    "test_the_current_task_record_with_its_row_off.py",
    "test_turning_task_ledger_off_touches_only_its_routes.py",
)
SENTENCES = {
    "Lets other programs read what Thomas has recorded about the task each chat is on: its goal, how far it got, "
    "anything it is waiting for, and its last few steps.": (
        "test_other_programs_read_the_goal_the_progress_and_the_steps",
    ),
    "The older full page, which Classic layout opens, reads it every few seconds.": (
        "test_with_the_row_off_the_older_page_asks_no_faster_and_shows_no_error",
    ),
    "Its Current Task box, in Mission Control on that older page, shows the goal and progress only for a chat that has delegated work "
    "running, and otherwise says No current task.": (
        "test_the_box_in_mission_control_shows_the_goal_and_the_progress_only_with_delegated_work",
    ),
    "While this is off, nothing you normally use changes, and other programs cannot read the record.": (
        "test_with_the_row_off_chat_looks_and_asks_the_same",
        "test_with_the_row_off_every_route_answers_404_and_none_is_listed",
    ),
    "The older full page keeps asking for it every few seconds and gets an error it does not show, so nothing "
    "repeats faster.": ("test_with_the_row_off_the_older_page_asks_no_faster_and_shows_no_error",),
    "Its Current Task box, in Mission Control on that older page, then shows a chat with delegated work running without its goal and "
    "progress.": ("test_with_the_row_off_a_new_box_has_no_goal_and_no_progress",),
    "A page that is already open keeps showing what it last read until you reload it.": (
        "test_a_page_already_open_keeps_what_it_last_read_until_reloaded",
    ),
    "Thomas goes on recording the task for each chat, so turning this on again shows it as it stands.": (
        "test_the_record_is_not_the_rows_and_turning_it_on_shows_it_as_it_stands",
    ),
}


def _get(base: str, path: str) -> Any:
    with urllib.request.urlopen(base + path, timeout=60) as answer:  # noqa: S310 - a server of this test
        return json.loads(answer.read())


def _post(base: str, path: str) -> int:
    request = urllib.request.Request(
        base + path, data=b"{}", method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=60) as answer:  # noqa: S310 - the same
        return int(answer.status)


def _delegated_work(page: Any, session_id: str) -> None:
    """Mission Control as the page sees it with a worker running for the chat, from its stream and from its own asks."""

    def snapshot() -> dict[str, Any]:
        worker = {
            "session_id": session_id,
            "status": "running",
            "name": "Worker",
            "job_id": "j1",
            "source": "autonomy_job",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        return {"agents": [worker]}

    def stream(route: Any) -> None:
        line = json.dumps({"type": "snapshot", "payload": snapshot()}) + "\n"
        route.fulfill(status=200, content_type="application/x-ndjson", body=line)

    page.route("**/api/mission/stream*", stream)
    page.route("**/api/mission/control", lambda route: route.fulfill(status=200, json=snapshot()))


def _open_mission_control(
    browser: Any,
    base: str,
    store: TaskLedgerStore,
    *,
    progress: str = PROGRESS,
    delegated: bool = False,
    routes: bool = True,
) -> Any:
    """The older full page makes a chat of its own, so the record it reads is written for that chat once it exists.

    ``routes`` says whether the page can read it. The page reads while Chat is showing, on its own timer, and Mission
    Control uses what it last read, so this waits for that reading, or for the error that takes its place, before
    it opens Mission Control, and then for the box to say what it will say.
    """
    page = browser.new_page(viewport=WINDOW)
    page.goto(base + "/classic")
    page.wait_for_selector("#app")
    # Its own chat, and not the latest one in the record, which is what its very first ask can come back with.
    page.wait_for_function("() => !!sessionId", timeout=60000)
    chat = page.evaluate("() => sessionId")
    store.update(chat, active_goal=GOAL, last_progress=progress, source="test")
    if delegated:
        _delegated_work(page, chat)
    if routes:
        read = "([chat, goal]) => taskContinuityLatestSessionId === chat && taskContinuityLatestState?.active_goal === goal"
    else:
        read = "() => !!taskContinuityLatestError"
    page.wait_for_function(read, arg=[chat, GOAL], timeout=60000)
    click_past_easy_setup(page, lambda: page.get_by_text("Mission Control").first)
    shown = "Worker" if delegated and not routes else (GOAL if delegated else NO_TASK)
    page.wait_for_function(
        "(title) => document.querySelector('.mission-runtime-panel [data-role=title]')?.textContent?.trim() === title",
        arg=shown,
        timeout=60000,
    )
    page.wait_for_timeout(1000)
    return page


def _asks_in_ten_seconds(browser: Any, base: str, path: str) -> dict[str, Any]:
    page = browser.new_page(viewport=WINDOW)
    asked: list[str] = []
    page.on("request", lambda request: asked.append(request.url.replace(base, "").partition("?")[0]))
    page.goto(base + path)
    page.wait_for_timeout(2500)
    asked.clear()
    page.wait_for_timeout(10000)
    text = page.evaluate("() => document.body.innerText")
    page.close()
    return {"counts": {route: asked.count(route) for route in LEDGER}, "total": len(asked), "text": text}


def _chat_looks(browser: Any, base: str) -> dict[str, Any]:
    page = browser.new_page(viewport=WINDOW)
    asked: list[str] = []
    page.on("request", lambda request: asked.append(request.url.replace(base, "").partition("?")[0]))
    page.goto(base + "/")
    page.wait_for_selector("#tc-shell")
    page.wait_for_timeout(4000)
    text = page.evaluate("() => document.body.innerText")
    page.close()
    return {"text": text, "ledger_asks": [route for route in asked if route in LEDGER]}


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    folder = tmp_path_factory.mktemp("task-ledger-window")
    database = folder / "memory" / ".thomas" / "task_ledger.sqlite3"
    database.parent.mkdir(parents=True)
    store = TaskLedgerStore(database)
    store.update("s1", active_goal=GOAL, last_progress=PROGRESS, missing_inputs=["the sales figures"], source="test")
    store.update("s1", last_progress=PROGRESS, status="in_progress", source="test", force_event=True)
    seen: dict[str, Any] = {}
    with serving(folder) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        seen["current"] = _get(base, "/api/task-ledger/current?session_id=s1")
        seen["history"] = _get(base, "/api/task-ledger/history?session_id=s1")
        seen["twin"] = _get(base, "/api/task_ledger/current?session_id=s1")
        page = _open_mission_control(browser, base, store, delegated=True)
        seen["on_box"] = page.evaluate(BOX)
        idle = _open_mission_control(browser, base, store)
        seen["on_idle_box"] = idle.evaluate(BOX)
        idle.close()
        seen["on_asks"] = _asks_in_ten_seconds(browser, base, "/classic")
        seen["on_chat"] = _chat_looks(browser, base)
        seen["pressed_off"] = _post(base, "/api/plugins/thomas/task_ledger/off")
        page.wait_for_timeout(6000)  # two or more of the page's own asks, each of which now fails
        seen["open_after_off"] = page.evaluate(BOX)
        page.close()
        seen["off_asks"] = _asks_in_ten_seconds(browser, base, "/classic")
        seen["off_chat"] = _chat_looks(browser, base)
        page = _open_mission_control(browser, base, store, delegated=True, routes=False)
        seen["off_box"] = page.evaluate(BOX)
        page.close()
        # The record is the memory folder's, not the row's: a write made now is there when the routes are back.
        store.update("s1", last_progress=LATER, source="test")
        seen["pressed_on"] = _post(base, "/api/plugins/thomas/task_ledger/on")
        time.sleep(1)
        seen["on_again"] = _get(base, "/api/task-ledger/current?session_id=s1")
        page = _open_mission_control(browser, base, store, progress=LATER, delegated=True)
        seen["on_again_box"] = page.evaluate(BOX)
        page.close()
        browser.close()
    return seen


def test_other_programs_read_the_goal_the_progress_and_the_steps(walked: dict[str, Any]) -> None:
    state = walked["current"]["state"]
    assert (state["active_goal"], state["last_progress"], state["missing_inputs"]) == (
        GOAL,
        PROGRESS,
        ["the sales figures"],
    )
    assert len(walked["history"]["events"]) >= 2
    assert walked["twin"]["state"] == state


def test_the_box_in_mission_control_shows_the_goal_and_the_progress_only_with_delegated_work(
    walked: dict[str, Any],
) -> None:
    assert walked["on_box"] == {"shown": True, "title": GOAL, "summary": PROGRESS}
    assert walked["on_idle_box"]["title"] == NO_TASK


def test_with_the_row_off_chat_looks_and_asks_the_same(walked: dict[str, Any]) -> None:
    assert walked["on_chat"]["ledger_asks"] == [] and walked["off_chat"]["ledger_asks"] == []
    assert walked["off_chat"]["text"] == walked["on_chat"]["text"]


def test_with_the_row_off_the_older_page_asks_no_faster_and_shows_no_error(walked: dict[str, Any]) -> None:
    """Its own timer asks every 2.8 seconds, which is three or four asks in ten, and a 404 must not make that more."""
    on, off = walked["on_asks"], walked["off_asks"]
    assert walked["pressed_off"] == 200
    assert 2 <= on["counts"][LEDGER[0]] <= 6, on
    assert 2 <= off["counts"][LEDGER[0]] <= 6 and 2 <= off["counts"][LEDGER[1]] <= 6, off
    assert off["total"] <= on["total"] + 4, (on["total"], off["total"])
    assert not re.search(r"unavailable|sync failed|404|not found", off["text"], re.IGNORECASE), off["text"][:400]


def test_with_the_row_off_a_new_box_has_no_goal_and_no_progress(walked: dict[str, Any]) -> None:
    box = walked["off_box"]
    assert box["shown"] is True
    assert box["title"] == "Worker", box  # the running work is there, under its own name
    assert PROGRESS not in (box["summary"] or "")


def test_a_page_already_open_keeps_what_it_last_read_until_reloaded(walked: dict[str, Any]) -> None:
    assert walked["open_after_off"] == walked["on_box"]


def test_the_record_is_not_the_rows_and_turning_it_on_shows_it_as_it_stands(walked: dict[str, Any]) -> None:
    assert walked["pressed_on"] == 200
    assert walked["on_again"]["state"]["last_progress"] == LATER
    assert walked["on_again_box"] == {"shown": True, "title": GOAL, "summary": LATER}


def test_every_sentence_of_the_words_names_the_test_that_shows_it() -> None:
    """The words are what you are told, so none lands on the strength of having been true once."""
    written = [*re.split(r"(?<=\.)\s+", WORDS["about"]), *re.split(r"(?<=\.)\s+", WORDS["off_means"])]
    assert written == list(SENTENCES)
    proofs = "".join((ROOT / "tests" / name).read_text(encoding="utf-8") for name in PROOFS)
    named = {name for names in SENTENCES.values() for name in names}
    assert {name for name in named if f"def {name}(" not in proofs} == set()


def test_the_older_full_page_is_the_only_page_that_asks_for_the_record() -> None:
    """The words promise nothing in Chat or the sidebar pages changes. A second caller means they must be read again."""
    web = ROOT / "thomas" / "server" / "web"
    callers = sorted(path.name for path in web.rglob("*.js") if "api/task-ledger" in path.read_text(encoding="utf-8"))
    pages = [path.name for path in web.rglob("*.html") if "api/task-ledger" in path.read_text(encoding="utf-8")]
    assert (callers, pages) == (["006_easy_setup_onboarding_04.js"], [])
