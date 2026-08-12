"""HTTP-surface tests for the in-flow PR review routes (CAP-149, Level 2).

Drives the real aiohttp handlers through an in-process TestServer -- no network,
no full app boot, no temp dirs. Every acceptance-line behavior is proved through
the HTTP layer:

* hunks come back risk-ranked (highest-risk-first) with their score;
* comments thread (add / reply / resolve);
* approval is blocked with a stated reason while a high-risk hunk carries an
  unresolved blocking comment, and permitted once resolved;
* a fix handoff returns a structured task bound to its hunk.

Each test injects a fresh :class:`PrReviewStore` so state never leaks between
tests or from the process-wide singleton.
"""

from __future__ import annotations

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.pr_review_routes import (
    PR_REVIEW_STORE_KEY,
    PrReviewStore,
    register_pr_review_routes,
)

# ---------------------------------------------------------------------------
# Fixtures: a fixed diff with a low-risk doc hunk, a high-risk auth hunk, and a
# test-file hunk. Deterministic -- the core scores it the same way every run.
# ---------------------------------------------------------------------------

DIFF = """\
diff --git a/docs/README.md b/docs/README.md
--- a/docs/README.md
+++ b/docs/README.md
@@ -1,3 +1,3 @@
-Thomas
+Thomas workspace
 second line
 third line
diff --git a/app/auth/session_login.py b/app/auth/session_login.py
--- a/app/auth/session_login.py
+++ b/app/auth/session_login.py
@@ -10,8 +10,9 @@ def login(user):
-    token = make_token(user)
-    if not verify_password(user.password):
-        return None
+    token = make_token(user, ttl=None)
+    secret = load_api_key()
+    if not verify_password(user.password, secret):
+        return None
+    grant_permission(user, "admin")
 return token
diff --git a/tests/test_ttl.py b/tests/test_ttl.py
--- a/tests/test_ttl.py
+++ b/tests/test_ttl.py
@@ -1,4 +1,5 @@
 import pytest
+
+def test_ttl_default():
+    assert compute_ttl() == 900
 # end
"""

NOT_A_DIFF = "this text contains no hunk headers at all\njust prose\n"


def _make_app() -> web.Application:
    app = web.Application()
    app[PR_REVIEW_STORE_KEY] = PrReviewStore()
    register_pr_review_routes(app, None)
    return app


async def _drive(scenario):
    server = TestServer(_make_app())
    client = TestClient(server)
    await client.start_server()
    try:
        return await scenario(client)
    finally:
        await client.close()


def _run(scenario):
    return asyncio.run(_drive(scenario))


async def _open(client, diff: str = DIFF, title: str = "CAP-149") -> dict:
    resp = await client.post("/api/pr-review/reviews", json={"diff": diff, "title": title})
    assert resp.status == 201, await resp.text()
    body = await resp.json()
    return body["review"]


def _high_risk_hunk(review: dict) -> dict:
    for hunk in review["hunks"]:
        if hunk["risk_band"] == "high":
            return hunk
    raise AssertionError("fixture diff produced no high-risk hunk")


# ---------------------------------------------------------------------------
# Ingest + risk ranking
# ---------------------------------------------------------------------------


def test_open_review_returns_hunks_risk_ranked_highest_first():
    async def scenario(client):
        review = await _open(client)
        assert review["review_id"]
        assert review["title"] == "CAP-149"
        hunks = review["hunks"]
        assert len(hunks) == 3

        scores = [h["risk_score"] for h in hunks]
        assert scores == sorted(scores, reverse=True), scores
        # every hunk exposes its score and band to the UI
        for hunk in hunks:
            assert isinstance(hunk["risk_score"], int)
            assert hunk["risk_band"] in ("high", "medium", "low")
            assert hunk["file_path"]
            assert hunk["header"].startswith("@@")

        top = hunks[0]
        assert top["risk_band"] == "high"
        assert top["touches_security"] is True
        assert "auth" in top["file_path"]
        return review

    _run(scenario)


def test_get_review_snapshot_matches_open_ranking():
    async def scenario(client):
        opened = await _open(client)
        resp = await client.get(f"/api/pr-review/reviews/{opened['review_id']}")
        assert resp.status == 200
        fetched = (await resp.json())["review"]
        assert [h["hunk_id"] for h in fetched["hunks"]] == [h["hunk_id"] for h in opened["hunks"]]
        assert fetched["can_approve"] is True
        assert fetched["blocking_reasons"] == []

    _run(scenario)


def test_list_reviews_reports_open_reviews():
    async def scenario(client):
        review = await _open(client)
        resp = await client.get("/api/pr-review/reviews")
        assert resp.status == 200
        body = await resp.json()
        assert len(body["reviews"]) == 1
        summary = body["reviews"][0]
        assert summary["review_id"] == review["review_id"]
        assert summary["hunk_count"] == 3
        assert summary["approved"] is False

    _run(scenario)


# ---------------------------------------------------------------------------
# Threaded comments
# ---------------------------------------------------------------------------


def test_comment_reply_and_resolve_thread_over_http():
    async def scenario(client):
        review = await _open(client)
        rid = review["review_id"]
        hunk_id = _high_risk_hunk(review)["hunk_id"]

        add = await client.post(
            f"/api/pr-review/reviews/{rid}/comments",
            json={"hunk_id": hunk_id, "author": "calvin", "body": "ttl=None disables expiry"},
        )
        assert add.status == 201
        root = (await add.json())["comment"]
        assert root["hunk_id"] == hunk_id
        assert root["parent_id"] is None
        assert root["resolved"] is False

        reply = await client.post(
            f"/api/pr-review/reviews/{rid}/comments/{root['comment_id']}/replies",
            json={"author": "agent", "body": "restoring the default ttl"},
        )
        assert reply.status == 201
        reply_body = (await reply.json())["comment"]
        assert reply_body["parent_id"] == root["comment_id"]
        assert reply_body["hunk_id"] == hunk_id

        resolve = await client.post(
            f"/api/pr-review/reviews/{rid}/comments/{root['comment_id']}/resolve",
            json={},
        )
        assert resolve.status == 200
        resolved_payload = await resolve.json()
        resolved_ids = {c["comment_id"] for c in resolved_payload["resolved"]}
        assert {root["comment_id"], reply_body["comment_id"]} <= resolved_ids
        for comment in resolved_payload["review"]["comments"]:
            assert comment["resolved"] is True

    _run(scenario)


# ---------------------------------------------------------------------------
# Approval gate: blocked, then permitted
# ---------------------------------------------------------------------------


def test_approval_blocked_by_high_risk_blocking_comment_then_permitted():
    async def scenario(client):
        review = await _open(client)
        rid = review["review_id"]
        hunk = _high_risk_hunk(review)

        add = await client.post(
            f"/api/pr-review/reviews/{rid}/comments",
            json={
                "hunk_id": hunk["hunk_id"],
                "author": "calvin",
                "body": "grant_permission(admin) is unreviewed",
                "blocking": True,
            },
        )
        assert add.status == 201
        add_body = await add.json()
        comment = add_body["comment"]
        # the snapshot returned with the comment already shows the gate closed
        assert add_body["review"]["can_approve"] is False

        snap = await client.get(f"/api/pr-review/reviews/{rid}")
        gated_review = (await snap.json())["review"]
        assert gated_review["can_approve"] is False
        assert gated_review["blocking_reasons"], "expected a stated blocking reason"
        assert comment["comment_id"] in gated_review["blocking_reasons"][0]
        assert hunk["hunk_id"] in gated_review["blocking_reasons"][0]

        blocked = await client.post(f"/api/pr-review/reviews/{rid}/approve", json={"approver": "calvin"})
        assert blocked.status == 409
        blocked_body = await blocked.json()
        assert blocked_body["error"] == "approval_blocked"
        assert blocked_body["blocking_reasons"]
        assert blocked_body["review"]["approved"] is False

        resolve = await client.post(
            f"/api/pr-review/reviews/{rid}/comments/{comment['comment_id']}/resolve",
            json={},
        )
        assert resolve.status == 200
        assert (await resolve.json())["review"]["can_approve"] is True

        approved = await client.post(f"/api/pr-review/reviews/{rid}/approve", json={"approver": "calvin"})
        assert approved.status == 200
        approved_body = await approved.json()
        assert approved_body["approved"] is True
        assert approved_body["approved_by"] == "calvin"
        assert approved_body["review"]["blocking_reasons"] == []

    _run(scenario)


def test_blocking_comment_on_low_risk_hunk_does_not_gate_approval():
    async def scenario(client):
        review = await _open(client)
        rid = review["review_id"]
        low = [h for h in review["hunks"] if h["risk_band"] != "high"][-1]

        add = await client.post(
            f"/api/pr-review/reviews/{rid}/comments",
            json={"hunk_id": low["hunk_id"], "body": "nit", "blocking": True},
        )
        assert add.status == 201
        assert (await add.json())["review"]["can_approve"] is True

        approved = await client.post(f"/api/pr-review/reviews/{rid}/approve", json={})
        assert approved.status == 200

    _run(scenario)


# ---------------------------------------------------------------------------
# Fix handoff
# ---------------------------------------------------------------------------


def test_fix_handoff_returns_structured_task_bound_to_its_hunk():
    async def scenario(client):
        review = await _open(client)
        rid = review["review_id"]
        hunk = _high_risk_hunk(review)

        add = await client.post(
            f"/api/pr-review/reviews/{rid}/comments",
            json={"hunk_id": hunk["hunk_id"], "body": "drop the admin grant", "blocking": True},
        )
        comment = (await add.json())["comment"]

        handoff = await client.post(
            f"/api/pr-review/reviews/{rid}/comments/{comment['comment_id']}/fix-task",
            json={},
        )
        assert handoff.status == 201
        payload = await handoff.json()
        task = payload["fix_task"]
        assert task["task_id"]
        assert task["comment_id"] == comment["comment_id"]
        assert task["hunk_id"] == hunk["hunk_id"]
        assert task["file_path"] == hunk["file_path"]
        assert task["hunk_header"] == hunk["header"]
        assert task["instruction"] == "drop the admin grant"
        assert task["risk_score"] == hunk["risk_score"]
        assert task["risk_band"] == "high"
        assert task["blocking"] is True

        # the task is carried on the review snapshot the panel renders
        assert payload["review"]["fix_tasks"][0]["task_id"] == task["task_id"]

    _run(scenario)


def test_fix_handoff_accepts_instruction_override():
    async def scenario(client):
        review = await _open(client)
        rid = review["review_id"]
        hunk = _high_risk_hunk(review)
        add = await client.post(
            f"/api/pr-review/reviews/{rid}/comments",
            json={"hunk_id": hunk["hunk_id"], "body": "see thread"},
        )
        comment = (await add.json())["comment"]

        handoff = await client.post(
            f"/api/pr-review/reviews/{rid}/comments/{comment['comment_id']}/fix-task",
            json={"instruction": "restore ttl default and drop the admin grant"},
        )
        assert handoff.status == 201
        task = (await handoff.json())["fix_task"]
        assert task["instruction"] == "restore ttl default and drop the admin grant"

    _run(scenario)


def test_fix_handoff_on_resolved_comment_is_rejected_with_409():
    async def scenario(client):
        review = await _open(client)
        rid = review["review_id"]
        hunk = _high_risk_hunk(review)
        add = await client.post(
            f"/api/pr-review/reviews/{rid}/comments",
            json={"hunk_id": hunk["hunk_id"], "body": "nothing left to fix"},
        )
        comment = (await add.json())["comment"]
        await client.post(f"/api/pr-review/reviews/{rid}/comments/{comment['comment_id']}/resolve", json={})

        handoff = await client.post(
            f"/api/pr-review/reviews/{rid}/comments/{comment['comment_id']}/fix-task",
            json={},
        )
        assert handoff.status == 409
        assert (await handoff.json())["error"] == "fix_handoff_rejected"

    _run(scenario)


# ---------------------------------------------------------------------------
# Input validation: user error is 4xx, never a 500
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload,expected_error",
    [
        ({}, "missing_diff"),
        ({"diff": ""}, "missing_diff"),
        ({"diff": "   "}, "missing_diff"),
        ({"diff": 17}, "missing_diff"),
        ({"diff": NOT_A_DIFF}, "invalid_diff"),
        ({"diff": DIFF, "security_markers": "auth"}, "invalid_field"),
        ({"diff": DIFF, "security_markers": [""]}, "invalid_field"),
        ({"diff": DIFF, "title": 5}, "invalid_field"),
    ],
)
def test_open_review_rejects_bad_input_with_400(payload, expected_error):
    async def scenario(client):
        resp = await client.post("/api/pr-review/reviews", json=payload)
        assert resp.status == 400, await resp.text()
        body = await resp.json()
        assert body["ok"] is False
        assert body["error"] == expected_error

    _run(scenario)


def test_open_review_rejects_non_json_body_with_400():
    async def scenario(client):
        resp = await client.post(
            "/api/pr-review/reviews",
            data="not json at all",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400
        assert (await resp.json())["error"] == "invalid_json"

        resp2 = await client.post(
            "/api/pr-review/reviews",
            data="[1, 2, 3]",
            headers={"Content-Type": "application/json"},
        )
        assert resp2.status == 400
        assert (await resp2.json())["error"] == "invalid_json"

    _run(scenario)


def test_unknown_review_and_hunk_and_comment_return_404():
    async def scenario(client):
        missing = await client.get("/api/pr-review/reviews/nope")
        assert missing.status == 404
        assert (await missing.json())["error"] == "unknown_review"

        review = await _open(client)
        rid = review["review_id"]

        bad_hunk = await client.post(
            f"/api/pr-review/reviews/{rid}/comments",
            json={"hunk_id": "h999", "body": "ghost"},
        )
        assert bad_hunk.status == 404
        assert (await bad_hunk.json())["error"] == "unknown_hunk"

        bad_reply = await client.post(
            f"/api/pr-review/reviews/{rid}/comments/c999/replies",
            json={"body": "ghost"},
        )
        assert bad_reply.status == 404
        assert (await bad_reply.json())["error"] == "unknown_comment"

        bad_resolve = await client.post(f"/api/pr-review/reviews/{rid}/comments/c999/resolve", json={})
        assert bad_resolve.status == 404

        bad_fix = await client.post(f"/api/pr-review/reviews/{rid}/comments/c999/fix-task", json={})
        assert bad_fix.status == 404

    _run(scenario)


def test_comment_requires_hunk_id_and_body():
    async def scenario(client):
        review = await _open(client)
        rid = review["review_id"]
        hunk_id = review["hunks"][0]["hunk_id"]

        no_hunk = await client.post(f"/api/pr-review/reviews/{rid}/comments", json={"body": "x"})
        assert no_hunk.status == 400
        assert (await no_hunk.json())["error"] == "missing_hunk_id"

        no_body = await client.post(f"/api/pr-review/reviews/{rid}/comments", json={"hunk_id": hunk_id})
        assert no_body.status == 400
        assert (await no_body.json())["error"] == "missing_body"

        bad_blocking = await client.post(
            f"/api/pr-review/reviews/{rid}/comments",
            json={"hunk_id": hunk_id, "body": "x", "blocking": 12},
        )
        assert bad_blocking.status == 400
        assert (await bad_blocking.json())["error"] == "invalid_field"

    _run(scenario)


def test_registered_store_is_isolated_per_app():
    """Each app gets the store it was handed -- no leakage into the singleton."""

    async def scenario(client):
        await _open(client)
        resp = await client.get("/api/pr-review/reviews")
        assert len((await resp.json())["reviews"]) == 1

    _run(scenario)
    # a second, independent app starts empty
    _run(scenario)
