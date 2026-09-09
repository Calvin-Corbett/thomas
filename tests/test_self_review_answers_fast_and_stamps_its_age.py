"""GET /api/self-review must never be mistaken for down because it is slow.

The handler used to run a 15-30s synchronous LLM generation inline, so any
caller with an ordinary timeout saw HTTP_000 -- a working instrument reading
as dead the internal design record Section 4 #5).
The fix serves an app-scoped, TTL-cached, stamped report and refreshes it in
the background, single-flighted. These tests never call a real model --
`generate_self_review` is monkeypatched at the module level.

Fix round 1 (`task-4-review.md`) found two Important issues in the first cut
of this fix and this file grew tests for both: an exception escaping
`generate_self_review` outside its own internal tuple left the cache's
attempt clock unstamped, so the TTL never throttled and the entry never
reached its error path (every caller saw a permanently healthy-looking
"generating"); and a failed refresh stamped the same clock used to compute
`stale`, so an arbitrarily old report could be served with `stale: false`
and no error visible. See `_refresh_self_review_entry`'s two separate clocks
(`built_at` for attempt-throttling, `result_built_at` for report age).
"""

from __future__ import annotations

import asyncio
import json
import warnings
from typing import Any

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from thomas.server.routes import self_review as mod


def _request(app: web.Application, query: str = "") -> web.Request:
    path = "/api/self-review" + (f"?{query}" if query else "")
    return make_mocked_request("GET", path, app=app)


def _body(response: web.Response) -> dict[str, Any]:
    return json.loads(response.text or "{}")


async def _drain(app: web.Application, hours: int = 24) -> None:
    """Let the background refresh task for `hours` run to completion.

    A task that hit an out-of-tuple exception re-raises it (see
    `_refresh_self_review_entry`'s docstring for why that's deliberate, not
    a regression) -- draining only cares that the attempt finished and the
    entry got updated. `asyncio.wait` (unlike `await task` directly) never
    raises the task's exception into the caller; `.exception()` still
    retrieves it afterward so asyncio doesn't separately warn about it going
    unretrieved.
    """
    entry = mod._entry_for(mod._self_review_cache(app), hours)
    task = entry.get("task")
    if task is not None:
        done, _pending = await asyncio.wait([task])
        for finished in done:
            finished.exception()


def test_a_cached_report_answers_fast_with_its_generation_stamp() -> None:
    async def run() -> None:
        app = web.Application()
        cache = mod._self_review_cache(app)
        entry = mod._entry_for(cache, 24)
        entry["result"] = {"ok": True, "report": "# old report", "sessions_reviewed": 3, "issues_in_window": 1}
        entry["generated_at"] = "2026-08-01T00:00:00+00:00"
        now = asyncio.get_running_loop().time()
        entry["built_at"] = now
        entry["result_built_at"] = now

        response = await mod.handle_self_review(_request(app))

        assert response.status == 200
        body = _body(response)
        assert body["ok"] is True
        assert body["report"] == "# old report"
        assert body["generated_at"] == "2026-08-01T00:00:00+00:00"
        assert body["stale"] is False

    asyncio.run(run())


def test_a_cold_start_returns_generating_immediately_instead_of_hanging() -> None:
    calls: list[int] = []

    async def slow_generate(app: web.Application, *, hours: int = 24) -> dict[str, Any]:
        calls.append(hours)
        await asyncio.sleep(3600)  # would fail any real test if the handler ever awaited this
        raise AssertionError("unreachable")

    async def run() -> None:
        app = web.Application()
        orig = mod.generate_self_review
        mod.generate_self_review = slow_generate  # type: ignore[assignment]
        try:
            response = await asyncio.wait_for(mod.handle_self_review(_request(app)), timeout=2.0)
        finally:
            mod.generate_self_review = orig  # type: ignore[assignment]
            task = mod._entry_for(mod._self_review_cache(app), 24).get("task")
            if task is not None:
                task.cancel()

        assert response.status == 200
        body = _body(response)
        assert body == {"ok": True, "status": "generating"}
        assert calls == [], "the slow generation must not have run yet on the request path"

    asyncio.run(run())


def test_two_concurrent_cold_requests_start_only_one_generation() -> None:
    calls: list[int] = []

    async def fake_generate(app: web.Application, *, hours: int = 24) -> dict[str, Any]:
        calls.append(1)
        await asyncio.sleep(0)
        return {"ok": True, "report": "# fresh", "sessions_reviewed": 0, "issues_in_window": 0}

    async def run() -> None:
        app = web.Application()
        orig = mod.generate_self_review
        mod.generate_self_review = fake_generate  # type: ignore[assignment]
        try:
            first, second = await asyncio.gather(
                mod.handle_self_review(_request(app)),
                mod.handle_self_review(_request(app)),
            )
            await _drain(app)
        finally:
            mod.generate_self_review = orig  # type: ignore[assignment]

        assert _body(first) == {"ok": True, "status": "generating"}
        assert _body(second) == {"ok": True, "status": "generating"}
        assert len(calls) == 1, f"expected exactly one generation for two concurrent callers, got {len(calls)}"

    asyncio.run(run())


def test_a_failed_generation_yields_an_honest_error_and_the_next_request_can_retry() -> None:
    attempts: list[int] = []

    async def flaky_generate(app: web.Application, *, hours: int = 24) -> dict[str, Any]:
        attempts.append(1)
        if len(attempts) == 1:
            return {"ok": False, "error": "no_llm"}
        return {"ok": True, "report": "# recovered", "sessions_reviewed": 1, "issues_in_window": 0}

    async def run() -> None:
        app = web.Application()
        orig = mod.generate_self_review
        mod.generate_self_review = flaky_generate  # type: ignore[assignment]
        try:
            # 1) cold start kicks the (failing) generation off.
            first = await mod.handle_self_review(_request(app))
            assert _body(first) == {"ok": True, "status": "generating"}
            await _drain(app)

            # 2) the failure is now recorded; a request arriving before the TTL
            #    elapses must see the honest error, not silently retry-and-hide it.
            second = await mod.handle_self_review(_request(app))
            assert second.status == 503
            body = _body(second)
            assert body["ok"] is False
            assert body["status"] == "error"
            assert body["error"] == "no_llm"
            entry = mod._entry_for(mod._self_review_cache(app), 24)
            assert len(attempts) == 1, "the request that only reads a recent failure must not itself retry"

            # 3) force the entry stale (as if the TTL has now elapsed) and confirm
            #    the next request retries and eventually succeeds.
            entry["built_at"] = 0.0
            third = await mod.handle_self_review(_request(app))
            assert _body(third) == {"ok": True, "status": "generating"}
            await _drain(app)

            fourth = await mod.handle_self_review(_request(app))
            assert fourth.status == 200
            body = _body(fourth)
            assert body["ok"] is True
            assert body["report"] == "# recovered"
            assert "generated_at" in body and body["generated_at"]
            assert len(attempts) == 2
        finally:
            mod.generate_self_review = orig  # type: ignore[assignment]

    asyncio.run(run())


def test_a_stale_cached_report_is_served_with_its_old_stamp_while_refresh_runs() -> None:
    async def slow_generate(app: web.Application, *, hours: int = 24) -> dict[str, Any]:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    async def run() -> None:
        app = web.Application()
        cache = mod._self_review_cache(app)
        entry = mod._entry_for(cache, 24)
        entry["result"] = {"ok": True, "report": "# still the old one", "sessions_reviewed": 2, "issues_in_window": 1}
        entry["generated_at"] = "2026-08-01T00:00:00+00:00"
        entry["built_at"] = 0.0  # attempt clock: far enough in the past to trigger a refresh
        entry["result_built_at"] = 0.0  # report clock: also old -- the report itself is stale

        orig = mod.generate_self_review
        mod.generate_self_review = slow_generate  # type: ignore[assignment]
        try:
            response = await asyncio.wait_for(mod.handle_self_review(_request(app)), timeout=2.0)
        finally:
            mod.generate_self_review = orig  # type: ignore[assignment]
            task = entry.get("task")
            if task is not None:
                task.cancel()

        assert response.status == 200
        body = _body(response)
        assert body["ok"] is True
        assert body["report"] == "# still the old one"
        assert body["generated_at"] == "2026-08-01T00:00:00+00:00"
        assert body["stale"] is True, "staleness must be visible, never a silent stale-forever cache"

    asyncio.run(run())


def test_different_hours_windows_are_cached_separately() -> None:
    """Serving a 24h report to an hours=1 caller would be a fabrication the
    stamp alone couldn't disclose -- each window gets its own cache slot."""

    async def run() -> None:
        app = web.Application()
        cache = mod._self_review_cache(app)
        day_entry = mod._entry_for(cache, 24)
        day_entry["result"] = {"ok": True, "report": "# 24h", "sessions_reviewed": 5, "issues_in_window": 2}
        day_entry["generated_at"] = "2026-08-01T00:00:00+00:00"
        day_entry["built_at"] = asyncio.get_running_loop().time()

        response = await mod.handle_self_review(_request(app, "hours=1"))

        # hours=1 has never been generated -- it must not silently reuse the
        # 24h cache entry, even though a good report exists for a different window.
        assert _body(response) == {"ok": True, "status": "generating"}
        await _drain(app, hours=1)

    asyncio.run(run())


def test_an_out_of_tuple_exception_is_recorded_and_throttled_not_endless_generating() -> None:
    """Fix round 1, Important-1: a KeyError (a real escapee -- e.g.
    `issues[k]` at self_review.py:139, before generate_self_review's own
    internal try) must not leave the entry looking like it was never
    attempted. Before the fix, `built_at` stayed unstamped, so every request
    relaunched a fresh (broken) generation and `entry["error"]` never got
    set -- every caller saw a permanently healthy "generating"."""
    calls: list[int] = []

    async def broken_generate(app: web.Application, *, hours: int = 24) -> dict[str, Any]:
        calls.append(1)
        raise KeyError("total")  # mirrors a real pre-LLM escapee, not the caught tuple

    async def run() -> None:
        app = web.Application()
        orig = mod.generate_self_review
        mod.generate_self_review = broken_generate  # type: ignore[assignment]
        try:
            first = await mod.handle_self_review(_request(app))
            assert _body(first) == {"ok": True, "status": "generating"}
            await _drain(app)

            entry = mod._entry_for(mod._self_review_cache(app), 24)
            assert entry["error"] == "refresh_failed: KeyError", "the crash must be recorded, not silently vanish"
            assert entry["built_at"] is not None, "the attempt clock must stamp even when generation crashes"

            # Still within the TTL: must NOT relaunch (the un-throttled retry
            # storm the review reproduced), and must show the honest error
            # instead of a healthy-looking "generating".
            second = await mod.handle_self_review(_request(app))
            assert len(calls) == 1, "an out-of-tuple exception must still be throttled by the TTL"
            assert second.status == 503
            assert _body(second) == {"ok": False, "status": "error", "error": "refresh_failed: KeyError"}

            # Force the TTL to have elapsed: the next request is allowed to retry.
            entry["built_at"] = 0.0
            third = await mod.handle_self_review(_request(app))
            assert _body(third) == {"ok": True, "status": "generating"}
            await _drain(app)
            assert len(calls) == 2
        finally:
            mod.generate_self_review = orig  # type: ignore[assignment]

    asyncio.run(run())


def test_a_failed_refresh_keeps_serving_the_old_report_with_its_real_age_and_surfaces_the_error() -> None:
    """Fix round 1, Important-2: a failed refresh used to stamp the SAME
    clock the response's `stale` flag was computed from, so an arbitrarily
    old report could be served with `stale: false` and no sign anything
    went wrong. `stale` must reflect when the served REPORT was built, not
    when the last (failed) attempt ran, and a failure must be visible
    alongside the report it didn't replace."""

    async def failing_generate(app: web.Application, *, hours: int = 24) -> dict[str, Any]:
        return {"ok": False, "error": "no_llm"}

    async def run() -> None:
        app = web.Application()
        cache = mod._self_review_cache(app)
        entry = mod._entry_for(cache, 24)
        report_built_at = asyncio.get_running_loop().time()
        entry["result"] = {"ok": True, "report": "# still good", "sessions_reviewed": 1, "issues_in_window": 0}
        entry["generated_at"] = "2026-08-01T00:00:00+00:00"
        entry["result_built_at"] = report_built_at  # the report itself is fresh
        entry["built_at"] = 0.0  # but the entry is due for a refresh attempt

        orig = mod.generate_self_review
        mod.generate_self_review = failing_generate  # type: ignore[assignment]
        try:
            first = await mod.handle_self_review(_request(app))  # kicks the failing refresh
            await _drain(app)
            # Re-fetch: the response returned before the refresh completed,
            # so check the state AFTER it actually finished.
            after = await mod.handle_self_review(_request(app))
        finally:
            mod.generate_self_review = orig  # type: ignore[assignment]

        assert _body(first)["report"] == "# still good"
        body = _body(after)
        assert body["ok"] is True
        assert body["report"] == "# still good"
        assert body["generated_at"] == "2026-08-01T00:00:00+00:00"
        assert body["stale"] is False, "the REPORT is still fresh even though the latest refresh attempt failed"
        assert body["refresh_error"] == "no_llm", "a failed refresh must not silently disappear behind an old report"

    asyncio.run(run())


def test_stale_reflects_report_age_not_attempt_recency_even_after_a_failed_refresh() -> None:
    """Companion to the previous test: an ANCIENT report stays stale even
    right after a failed refresh attempt just ran -- the attempt clock
    (which just updated to "now") must never be mistaken for the report's
    own age."""

    async def failing_generate(app: web.Application, *, hours: int = 24) -> dict[str, Any]:
        return {"ok": False, "error": "no_llm"}

    async def run() -> None:
        app = web.Application()
        cache = mod._self_review_cache(app)
        entry = mod._entry_for(cache, 24)
        entry["result"] = {"ok": True, "report": "# ancient", "sessions_reviewed": 0, "issues_in_window": 0}
        entry["generated_at"] = "2026-01-01T00:00:00+00:00"
        entry["result_built_at"] = 0.0  # the report is genuinely old
        entry["built_at"] = 0.0  # and an attempt is due

        orig = mod.generate_self_review
        mod.generate_self_review = failing_generate  # type: ignore[assignment]
        try:
            await mod.handle_self_review(_request(app))  # kicks the failing refresh
            await _drain(app)
            response = await mod.handle_self_review(_request(app))
        finally:
            mod.generate_self_review = orig  # type: ignore[assignment]

        body = _body(response)
        assert body["stale"] is True, "an ancient report must not read as fresh just because an attempt just ran"
        assert body["refresh_error"] == "no_llm"

    asyncio.run(run())


def test_a_pre_registered_cache_survives_a_frozen_app_without_a_deprecation_warning() -> None:
    """Fix round 1, Minor-1: the lazy `app[APP_SELF_REVIEW_CACHE] = ...`
    fallback mutates the app if the key was never set before the app froze
    -- aiohttp emits a real DeprecationWarning for that on 3.13.5, and a
    unit test that never freezes its app can never see the bug. The live
    server now avoids it entirely by registering the key eagerly in
    `app_core.create_app`, before the app is handed to `AppRunner` (which
    freezes it). This test proves that path: pre-register the key exactly
    like `create_app` does, freeze the app, and confirm the request path
    never has to write into it."""

    async def run() -> None:
        app = web.Application()
        app[mod.APP_SELF_REVIEW_CACHE] = {"lock": asyncio.Lock(), "entries": {}}
        app.freeze()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            entry = mod._entry_for(mod._self_review_cache(app), 24)
            entry["result"] = {"ok": True, "report": "# frozen-safe", "sessions_reviewed": 0, "issues_in_window": 0}
            entry["generated_at"] = "2026-08-01T00:00:00+00:00"
            now = asyncio.get_running_loop().time()
            entry["built_at"] = now
            entry["result_built_at"] = now

            response = await mod.handle_self_review(_request(app))

        assert response.status == 200
        assert _body(response)["report"] == "# frozen-safe"
        deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert not deprecation_warnings, f"pre-registered cache must not touch the frozen app: {deprecation_warnings}"

    asyncio.run(run())
