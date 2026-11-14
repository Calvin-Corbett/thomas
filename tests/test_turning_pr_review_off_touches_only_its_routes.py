"""The pull request review row, off: its eight routes answer 404, a server started that way never loads them, and reviews stay.

No page in Thomas calls these routes any more, and nothing else in Thomas does either. What they
hold sits in memory in ``thomas.server.routes.pr_review_routes``, in one ``PrReviewStore`` for the whole process, and
each review is a ``thomas.tools.pr_review.PrReview``. So off takes the routes and leaves the store, and a page left open
carries on from where it was when the row comes back. Resetting the store on off would lose your reviews, and the
numbers would start again at pr1, so a page left open on the old pr1 would write into a different review.

The row writes two app keys, which is why it is written with the view and tested here for what the view takes back.

Each server in this file that a test builds itself is built in the test, never in a module-scoped fixture: a home of
its own for each test comes from a function-scoped fixture in ``tests/conftest_factories.py``.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.plugin_page_fixture import report_of
from tests.plugin_view_fixture import state_of, until
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT, choose
from thomas.server import app_core
from thomas.server.proof.selection import select
from thomas.server.routes import pr_review_routes
from thomas.server.routes.pr_review_routes import PR_REVIEW_CONFIG_KEY, PR_REVIEW_STORE_KEY
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

ROW = "pr_review"
API = "/api/pr-review/reviews"
SWITCH = f"/api/plugins/thomas/{ROW}"
# One change, high risk because it touches a token.
DIFF = """\
diff --git a/app/auth.py b/app/auth.py
--- a/app/auth.py
+++ b/app/auth.py
@@ -1,2 +1,3 @@
-token = old()
+token = new()
+secret = load()
 keep
"""
# Written out, because a list worked out from the row would agree with whatever the row did.
GUARDED = {
    "POST /api/pr-review/reviews": "POST /api/pr-review/reviews",
    "POST /api/pr-review/reviews/{review_id}/comments": "POST /api/pr-review/reviews/r1/comments",
    "POST /api/pr-review/reviews/{review_id}/comments/{comment_id}/replies": (
        "POST /api/pr-review/reviews/r1/comments/c1/replies"
    ),
    "POST /api/pr-review/reviews/{review_id}/comments/{comment_id}/resolve": (
        "POST /api/pr-review/reviews/r1/comments/c1/resolve"
    ),
    "POST /api/pr-review/reviews/{review_id}/comments/{comment_id}/fix-task": (
        "POST /api/pr-review/reviews/r1/comments/c1/fix-task"
    ),
    "POST /api/pr-review/reviews/{review_id}/approve": "POST /api/pr-review/reviews/r1/approve",
}
# Open, and not on purpose. register_pr_review_routes takes no access guard, and the server's own check covers only what
# changes something. So in remote mode a caller with no token can read these two. Reported, and left as it was by the move.
OPEN = {
    "GET /api/pr-review/reviews": "GET /api/pr-review/reviews",
    "GET /api/pr-review/reviews/{review_id}": "GET /api/pr-review/reviews/r1",
}
ROUTES = {**GUARDED, **OPEN}
OWN_CODE = ("thomas.server.rows.pr_review", "thomas.server.routes.pr_review_routes", "thomas.tools.pr_review")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, "HEAD /api/pr-review/reviews", "HEAD /api/pr-review/reviews/{review_id}"}


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("pr-review-off")
    started, found = start_with_one_row_off(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("pr-review-remote")
    started, found = ask_as_a_remote_caller(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Saved choices live in the data dir, so a test that turns something off must not share it.

    The store is the process's own, so each test here starts from an empty one, and leaves one.
    """
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    choose(tmp_path / "data", on={ROW})
    pr_review_routes.reset_review_store()
    yield tmp_path / "data"
    pr_review_routes.reset_review_store()


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


def test_turning_it_on_brings_back_all_eight_routes_without_a_restart(seen: dict[str, Any]) -> None:
    """A handler answers 404 itself for a review it does not have, so ``live_on`` is what shows those routes are there."""
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == {
        "POST /api/pr-review/reviews": 400,  # asked with no diff
        "GET /api/pr-review/reviews": 200,
        **dict.fromkeys([ask for ask in ROUTES.values() if "/r1" in ask], 404),
    }


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so the row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_guarded_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == {
        **dict.fromkeys(GUARDED.values(), 401),
        "GET /api/pr-review/reviews": 200,
        "GET /api/pr-review/reviews/r1": 404,  # there is no such review, and a real number answers 200
    }
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_a_whole_review_works_through_the_row_on_a_real_server(tmp_path: Path, own_data_dir: Path) -> None:
    """Every route with a real body, in the order the page uses them, because a route file's own test uses a bare app."""

    async def scenario() -> dict[str, int]:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            opened = await client.post(API, json={"diff": DIFF, "title": "Through the row"})
            review = (await opened.json())["review"]
            at = f"{API}/{review['review_id']}"
            hunk = next(hunk["hunk_id"] for hunk in review["hunks"] if hunk["risk_band"] == "high")
            comment = await client.post(f"{at}/comments", json={"hunk_id": hunk, "body": "Fix this.", "blocking": True})
            on_it = f"{at}/comments/{(await comment.json())['comment']['comment_id']}"
            return {
                "opened": opened.status,
                "comment": comment.status,
                "reply": (await client.post(f"{on_it}/replies", json={"body": "Looking."})).status,
                "fix": (await client.post(f"{on_it}/fix-task", json={})).status,
                "held back": (await client.post(f"{at}/approve", json={})).status,
                "resolved": (await client.post(f"{on_it}/resolve", json={})).status,
                "approved": (await client.post(f"{at}/approve", json={})).status,
                "read": (await client.get(at)).status,
                "listed": (await client.get(API)).status,
            }

    assert asyncio.run(scenario()) == {
        "opened": 201,
        "comment": 201,
        "reply": 201,
        "fix": 201,
        "held back": 409,
        "resolved": 200,
        "approved": 200,
        "read": 200,
        "listed": 200,
    }


def test_reviews_outlive_off_and_on_and_their_numbers_go_on(tmp_path: Path, own_data_dir: Path) -> None:
    """The row's words say so. A stop that reset the store would hand the next review the number a page left open has.

    The config is the server's, and not the row's own empty settings, because that is what the shell handed these routes.
    """

    async def scenario() -> dict[str, Any]:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            first = (await (await client.post(API, json={"diff": DIFF})).json())["review"]["review_id"]
            store = app[PR_REVIEW_STORE_KEY]
            config = app[PR_REVIEW_CONFIG_KEY]
            await client.post(f"{SWITCH}/off")
            seen = {
                "first": first,
                "off": (await client.get(f"{API}/{first}")).status,
                "keys_off": [key in app for key in (PR_REVIEW_STORE_KEY, PR_REVIEW_CONFIG_KEY)],
            }
            await client.post(f"{SWITCH}/on")
            await until(lambda: state_of(app[APP_RUNTIME_PLUGINS], ROW) == "active")
            seen["back"] = (await client.get(f"{API}/{first}")).status
            seen["same_store"] = app[PR_REVIEW_STORE_KEY] is store
            seen["same_config"] = app[PR_REVIEW_CONFIG_KEY] is config is app[APP_RUNTIME_PLUGINS].web.config
            seen["next"] = (await (await client.post(API, json={"diff": DIFF})).json())["review"]["review_id"]
            return seen

    assert asyncio.run(scenario()) == {
        "first": "pr1",
        "off": 404,
        "keys_off": [False, False],
        "back": 200,
        "same_store": True,
        "same_config": True,
        "next": "pr2",
    }


def test_nothing_a_review_holds_reaches_the_disk(tmp_path: Path, own_data_dir: Path) -> None:
    """So a restart loses every review, on or off, as the row's words say."""
    marker = "a-comment-only-a-saved-review-would-hold"

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            review = (await (await client.post(API, json={"diff": DIFF, "title": marker})).json())["review"]
            hunk = review["hunks"][0]["hunk_id"]
            at = f"{API}/{review['review_id']}/comments"
            assert (await client.post(at, json={"hunk_id": hunk, "body": marker})).status == 201
            await client.post(f"{SWITCH}/off")

    asyncio.run(scenario())

    written = [path for path in tmp_path.rglob("*") if path.is_file() and marker.encode() in path.read_bytes()]
    assert any(tmp_path.rglob("*"))  # an empty folder would pass
    assert written == []


def test_stop_now_cuts_off_a_review_still_arriving_and_keeps_nothing_of_it(tmp_path: Path, own_data_dir: Path) -> None:
    """A handler still reading its body is the one thing that can hold a stop here. The row's stop_now words say this."""
    body = b'{"diff": "@@ -1 +1 @@'
    head = f"POST {API} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: 500\r\n\r\n"

    async def scenario() -> dict[str, Any]:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            runtime = app[APP_RUNTIME_PLUGINS]
            held_already = (await (await client.post(API, json={"diff": DIFF})).json())["review"]["review_id"]
            reader, writer = await asyncio.open_connection(client.host, client.port)
            writer.write(head.encode() + body)
            await writer.drain()
            await until(lambda: report_of(runtime, ROW)["waiting_for"] == 1)
            stopping = asyncio.ensure_future(runtime.turn_off(ROW))
            await until(lambda: state_of(runtime, ROW) == "unloading")
            await asyncio.sleep(0.2)
            waited = not stopping.done()
            await runtime.turn_off(ROW, force=True)
            await stopping
            answer = await asyncio.wait_for(reader.read(), timeout=30)
            writer.close()
            reviews = [review["review_id"] for review in pr_review_routes.get_review_store().summaries()]
            return {
                "waited": waited,
                "state": state_of(runtime, ROW),
                "answer": answer,
                "kept": reviews == [held_already],
            }

    assert asyncio.run(scenario()) == {"waited": True, "state": "off", "answer": b"", "kept": True}


@pytest.mark.parametrize("changed", ["thomas/server/rows/pr_review.py", "thomas/server/routes/pr_review_routes.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """A check finds these because each spells out the dotted names, and a change to the row must run them."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_pr_review_off_touches_only_its_routes.py" in chosen
    assert "tests/test_pr_review_routes.py" in chosen
