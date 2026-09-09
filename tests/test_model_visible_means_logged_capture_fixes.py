"""Reviewer fix-round on the honesty-spine capture hook (Task 2).

Split out of test_model_visible_means_logged.py to keep that file under the
monolith guard's unbaselined soft limit -- this is a second logically
distinct test file, not a `*_part*.py` module split (nothing here is a
fragment of a single module; it is its own coherent set of contracts on the
same capture_context/llm_client behavior).

Three review findings, each reproduced end-to-end before the fix and pinned
here after:

1. (run_id, seq) collision: the default chat route already runs a
   ThreadedRunWriter per turn on the same run_id loop_execution.py
   correlates capture to, and `events` has no (run_id, seq) uniqueness
   constraint -- two independent seq counters on one run_id collided
   silently. capture_context now obtains seqs from the run's registered
   ThreadedRunWriter when one exists, falling back to its own counter only
   when no writer is registered.
2. capture_failures double-count: a single failed request-append was
   counted once in llm_client.py at begin_model_capture, then a SECOND time
   because end_model_capture's early-return path re-surfaced
   `state.failed`. It now returns False on that path (already counted).
3. Failover honesty: a primary that streams partial text then dies,
   followed by a fallback that completes, must never be logged as one clean
   primary response -- the response now carries served_by_model/
   served_by_provider (read at completion time), provider_attempts, and
   merged_partial_output.

Every test here uses its own tmp_path sqlite file via run_store.init_db() --
never the live server's database.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from thomas.core import capture_context
from thomas.core.config import ModelConfig
from thomas.core.llm_client import LLMClient
from thomas.core.llm_shared import LLMError, StreamEvent
from thomas.marketplace.observability import run_store
from thomas.marketplace.observability import session_log_events as sle


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "runs.sqlite3"
    run_store.init_db(db_path)
    monkeypatch.setattr(run_store, "MAX_RUNS", 500)
    monkeypatch.setattr(run_store, "MAX_DB_BYTES", 200 * 1024 * 1024)
    monkeypatch.setattr(run_store, "_PINNED_SKIP_COUNT", 0)
    return db_path


@pytest.fixture(autouse=True)
def _reset_capture_context_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mirrors test_model_visible_means_logged.py's fixture of the same name.

    Capture context keeps a per-process ambient run + seq counters; reset
    both between tests so one test's ambient run or seq numbering never
    bleeds into the next.
    """
    monkeypatch.setattr(capture_context, "_ambient_run_id", None)
    monkeypatch.setattr(capture_context, "_next_seq_by_run", {})


async def _drain(stream) -> list[StreamEvent]:
    return [event async for event in stream]


def _fake_client(monkeypatch: pytest.MonkeyPatch, events: list[StreamEvent]) -> LLMClient:
    cfg = ModelConfig(name="p", provider="anthropic", model="claude-honesty-spine")
    client = LLMClient(cfg)

    async def fake_stream_current_provider(messages, tools=None, **kwargs):  # noqa: ANN001, ARG001
        for event in events:
            yield event

    monkeypatch.setattr(client, "_stream_current_provider", fake_stream_current_provider)
    return client


# ---------------------------------------------------------------------------
# (run_id, seq) collision
# ---------------------------------------------------------------------------


def test_capture_obtains_seqs_from_the_runs_registered_writer_and_never_collides(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduces the exact production wiring: chat_aiohttp_streaming.py

    creates a run and a ThreadedRunWriter for it, then writes some events
    through the writer directly (mirroring chat_request_execution.py's
    send()); loop_execution.py then correlates the SAME run_id via
    set_capture_run before the model call. Both writers must land on one
    seq sequence -- zero duplicate (run_id, seq) pairs across ALL events on
    the run, and request/response correlation must still hold.
    """
    client = _fake_client(monkeypatch, [StreamEvent(type="token", data={"text": "hi"}), StreamEvent(type="done")])

    run_id = "prod-style-run-id"
    run_store.create_run({"run_id": run_id, "session_id": "s1", "mode": "chat"})
    writer = run_store.ThreadedRunWriter(run_id)
    writer.start()
    try:
        # Pre-existing writer traffic on this run_id, exactly like the chat
        # route's own text/tool_call events during the same turn.
        writer.record({"type": "text", "seq": writer.seq, "text": "hello "})
        writer.record({"type": "text", "seq": writer.seq, "text": "world"})

        token = capture_context.set_capture_run(run_id)
        try:
            asyncio.run(_drain(client.stream_chat([{"role": "user", "content": "hi"}], tools=None)))
        finally:
            capture_context.reset(token)
    finally:
        writer.close()

    rows = list(run_store.stream_replay(run_id))
    seqs = [r["seq"] for r in rows]
    assert len(seqs) == len(set(seqs)), f"duplicate (run_id, seq) pairs: {seqs}"

    request = next(r for r in rows if r["type"] == sle.MODEL_REQUEST)
    response = next(r for r in rows if r["type"] == sle.MODEL_RESPONSE)
    assert response["request_seq"] == request["seq"]


def test_capture_falls_back_to_its_own_counter_when_no_writer_is_registered(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ThreadedRunWriter registered for this run_id (the ambient/CLI

    shape) -- capture must still work via its own counter, and still be
    internally seq-consistent.
    """
    client = _fake_client(monkeypatch, [StreamEvent(type="token", data={"text": "hi"}), StreamEvent(type="done")])
    run_id = run_store.create_run({"session_id": "s1"})
    assert run_store.get_active_writer(run_id) is None

    token = capture_context.set_capture_run(run_id)
    try:
        asyncio.run(_drain(client.stream_chat([{"role": "user", "content": "hi"}], tools=None)))
    finally:
        capture_context.reset(token)

    rows = list(run_store.stream_replay(run_id))
    seqs = [r["seq"] for r in rows]
    assert len(seqs) == len(set(seqs))
    request = next(r for r in rows if r["type"] == sle.MODEL_REQUEST)
    response = next(r for r in rows if r["type"] == sle.MODEL_RESPONSE)
    assert response["request_seq"] == request["seq"]


# ---------------------------------------------------------------------------
# Failover honesty
# ---------------------------------------------------------------------------


def test_a_dying_primary_and_a_succeeding_fallback_are_never_logged_as_one_clean_primary_response(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failover-honesty fix: a primary that streams partial text then

    dies, followed by a fallback that completes cleanly, must not read as
    one undifferentiated primary response. The request keeps the config it
    was opened with (what was asked); the response records what actually
    served, how many attempts it took, and that output was merged from more
    than one attempt.
    """
    primary = ModelConfig(name="primary", provider="anthropic", model="claude-primary")
    fallback = ModelConfig(name="fallback", provider="openai", model="gpt-fallback")
    client = LLMClient(primary, fallback_configs=[fallback], failover_enabled=True, failover_cooldown_s=0)

    call_count = {"n": 0}

    async def fake_stream_current_provider(messages, tools=None, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            yield StreamEvent(type="token", data={"text": "PARTIAL-FROM-PRIMARY-"})
            raise LLMError("primary blew up mid-stream", status=500, retryable=True)
        else:
            yield StreamEvent(type="token", data={"text": "FULL-FROM-FALLBACK"})
            yield StreamEvent(type="done")

    monkeypatch.setattr(client, "_stream_current_provider", fake_stream_current_provider)

    run_id = run_store.create_run({"session_id": "s1"})
    token = capture_context.set_capture_run(run_id)
    try:
        asyncio.run(_drain(client.stream_chat([{"role": "user", "content": "hi"}], tools=None)))
    finally:
        capture_context.reset(token)

    logged = list(run_store.stream_replay(run_id))
    assert len([e for e in logged if e["type"] == sle.MODEL_REQUEST]) == 1
    assert len([e for e in logged if e["type"] == sle.MODEL_RESPONSE]) == 1
    request = next(e for e in logged if e["type"] == sle.MODEL_REQUEST)
    response = next(e for e in logged if e["type"] == sle.MODEL_RESPONSE)

    # The request is honest about what was asked: the primary it opened with.
    assert request["model"] == "claude-primary"
    assert request["provider"] == "anthropic"

    # The response is honest about what actually served, and flags that the
    # text is a merge across attempts rather than one clean primary answer.
    assert response["served_by_model"] == "gpt-fallback"
    assert response["served_by_provider"] == "openai"
    assert response["provider_attempts"] == 2
    assert response["merged_partial_output"] is True
    assert response["text"] == "PARTIAL-FROM-PRIMARY-FULL-FROM-FALLBACK"


def test_a_single_provider_response_never_gets_flagged_as_merged(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control case: no failover, one attempt -- merged_partial_output

    must read False and provider_attempts must read 1, not some inflated or
    default value.
    """
    client = _fake_client(monkeypatch, [StreamEvent(type="token", data={"text": "hi"}), StreamEvent(type="done")])
    run_id = run_store.create_run({"session_id": "s1"})

    token = capture_context.set_capture_run(run_id)
    try:
        asyncio.run(_drain(client.stream_chat([{"role": "user", "content": "hi"}], tools=None)))
    finally:
        capture_context.reset(token)

    response = next(e for e in run_store.stream_replay(run_id) if e["type"] == sle.MODEL_RESPONSE)
    assert response["provider_attempts"] == 1
    assert response["merged_partial_output"] is False
    assert response["served_by_model"] == "claude-honesty-spine"
    assert response["served_by_provider"] == "anthropic"


# ---------------------------------------------------------------------------
# Minor: MemoryError joins the named-exception set
# ---------------------------------------------------------------------------


def test_memory_error_during_capture_is_swallowed_like_any_other_capture_failure(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MemoryError is in CAPTURE_EXCEPTIONS: letter of the

    capture-never-breaks-the-call contract covers running out of memory
    while snapshotting or serializing, not just the ordinary named errors.
    """
    client = _fake_client(monkeypatch, [StreamEvent(type="token", data={"text": "hi"}), StreamEvent(type="done")])
    run_id = run_store.create_run({"session_id": "s1"})

    def boom(*_args, **_kwargs):
        raise MemoryError("out of memory")

    monkeypatch.setattr(run_store, "append_event", boom)

    token = capture_context.set_capture_run(run_id)
    try:
        events = asyncio.run(_drain(client.stream_chat([{"role": "user", "content": "hi"}], tools=None)))
    finally:
        capture_context.reset(token)

    assert [e.type for e in events] == ["token", "done"]
    assert client.capture_failures == 1
