"""Model-visible means logged: the session-log event vocabulary on run_store.

Task 1 of the honesty-spine plan adds no new ledger -- it adds event type
constants and payload builders (thomas/marketplace/observability/session_log_events.py)
that ride the pre-existing run_store spine, plus a pinned-run retention guard
(thomas/marketplace/observability/run_store.py) so a run marked `pinned` in
its metadata survives eviction while it is still open. This file pins three
contracts: (1) every payload builder round-trips through append_event() and
stream_replay() with its seq intact; (2) a malformed payload raises
ValueError naming the missing field, never silently coerced; (3) a pinned
open run survives retention that deletes its unpinned elders, and the skip
is counted, not silent.

Every test here uses its own tmp_path sqlite file via run_store.init_db() --
never the live server's database.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from thomas.marketplace.observability import run_store
from thomas.marketplace.observability import session_log_events as sle


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "runs.sqlite3"
    run_store.init_db(db_path)
    # Restore module-level retention counters/caps so tests never bleed into
    # each other via shared module state.
    monkeypatch.setattr(run_store, "MAX_RUNS", 500)
    monkeypatch.setattr(run_store, "MAX_DB_BYTES", 200 * 1024 * 1024)
    monkeypatch.setattr(run_store, "_PINNED_SKIP_COUNT", 0)
    return db_path


# ---------------------------------------------------------------------------
# Payload builders round-trip through append_event / stream_replay
# ---------------------------------------------------------------------------


def test_model_request_payload_round_trips_through_append_event_and_stream_replay(store: Path) -> None:
    run_id = run_store.create_run({"session_id": "s1"})
    payload = sle.model_request_payload(
        messages=[{"role": "user", "content": "hi"}],
        model="claude-opus-5",
        provider="anthropic",
        tools_digest="abc123",
        correlation="ctx-1",
    )

    run_store.append_event(run_id, sle.MODEL_REQUEST, payload, t_ms=0, seq=0)

    replayed = list(run_store.stream_replay(run_id))
    assert len(replayed) == 1
    event = replayed[0]
    assert event["type"] == sle.MODEL_REQUEST
    assert event["seq"] == 0
    assert event["messages"] == [{"role": "user", "content": "hi"}]
    assert event["model"] == "claude-opus-5"
    assert event["provider"] == "anthropic"
    assert event["tools_digest"] == "abc123"
    assert event["correlation"] == "ctx-1"


def test_model_response_payload_round_trips_with_seq_intact(store: Path) -> None:
    run_id = run_store.create_run({"session_id": "s1"})
    payload = sle.model_response_payload(
        text="hello there",
        tool_calls=[{"name": "fs.read", "args": {}}],
        usage={"input_tokens": 10, "output_tokens": 5},
        interrupted=False,
        request_seq=0,
        served_by_model="claude-opus-5",
        served_by_provider="anthropic",
        provider_attempts=1,
        merged_partial_output=False,
    )

    run_store.append_event(run_id, sle.MODEL_RESPONSE, payload, t_ms=50, seq=1)

    replayed = list(run_store.stream_replay(run_id))
    event = replayed[0]
    assert event["type"] == sle.MODEL_RESPONSE
    assert event["seq"] == 1
    assert event["text"] == "hello there"
    assert event["tool_calls"] == [{"name": "fs.read", "args": {}}]
    assert event["usage"] == {"input_tokens": 10, "output_tokens": 5}
    assert event["interrupted"] is False
    assert event["request_seq"] == 0
    assert event["served_by_model"] == "claude-opus-5"
    assert event["served_by_provider"] == "anthropic"
    assert event["provider_attempts"] == 1
    assert event["merged_partial_output"] is False


@pytest.mark.parametrize(
    ("builder", "kwargs", "expected_type"),
    [
        pytest.param(
            sle.compaction_payload,
            {
                "summary_text": "summary",
                "replaced_from": 0,
                "replaced_to": 3,
                "by": "compaction",
                "spliced_role": "assistant",
                "spliced_content": "[context-summary]\nsummary",
            },
            sle.HISTORY_COMPACTION,
            id="compaction",
        ),
        pytest.param(
            sle.truncate_payload,
            {"kept": 4, "dropped": 2},
            sle.HISTORY_TRUNCATE,
            id="truncate",
        ),
        pytest.param(
            sle.fork_payload,
            {"parent_session": "parent-1", "boundary_len": 6},
            sle.HISTORY_FORK,
            id="fork",
        ),
        pytest.param(
            sle.imported_payload,
            {"message_count": 12, "source": "legacy-session"},
            sle.HISTORY_IMPORTED,
            id="imported",
        ),
    ],
)
def test_history_mutation_payloads_round_trip_through_the_spine(
    store: Path, builder, kwargs: dict, expected_type: str
) -> None:
    run_id = run_store.create_run({"session_id": "s1"})
    payload = builder(**kwargs)

    run_store.append_event(run_id, expected_type, payload, t_ms=0, seq=7)

    replayed = list(run_store.stream_replay(run_id))
    event = replayed[0]
    assert event["type"] == expected_type
    assert event["seq"] == 7
    for key, value in kwargs.items():
        assert event[key] == value


# ---------------------------------------------------------------------------
# Malformed payloads raise ValueError naming the missing key
# ---------------------------------------------------------------------------


def test_model_request_payload_missing_messages_raises_value_error_naming_it() -> None:
    with pytest.raises(ValueError, match="messages"):
        sle.model_request_payload(
            messages="not-a-list",  # type: ignore[arg-type]
            model="m",
            provider="p",
            tools_digest=None,
            correlation="c",
        )


def test_model_response_payload_missing_usage_raises_value_error_naming_it() -> None:
    with pytest.raises(ValueError, match="usage"):
        sle.model_response_payload(
            text="hi",
            tool_calls=[],
            usage="not-a-dict",  # type: ignore[arg-type]
            interrupted=False,
            request_seq=0,
            served_by_model="m",
            served_by_provider="p",
            provider_attempts=1,
            merged_partial_output=False,
        )


def test_model_response_payload_zero_provider_attempts_raises_value_error_naming_it() -> None:
    with pytest.raises(ValueError, match="provider_attempts"):
        sle.model_response_payload(
            text="hi",
            tool_calls=[],
            usage={},
            interrupted=False,
            request_seq=0,
            served_by_model="m",
            served_by_provider="p",
            provider_attempts=0,
            merged_partial_output=False,
        )


def test_compaction_payload_with_backwards_range_raises_value_error() -> None:
    with pytest.raises(ValueError, match="replaced_to"):
        sle.compaction_payload(
            summary_text="s",
            replaced_from=5,
            replaced_to=1,
            by="compaction",
            spliced_role="assistant",
            spliced_content="x",
        )


def test_compaction_payload_missing_spliced_content_raises_value_error_naming_it() -> None:
    with pytest.raises(ValueError, match="spliced_content"):
        sle.compaction_payload(
            summary_text="s",
            replaced_from=0,
            replaced_to=1,
            by="compaction",
            spliced_role="assistant",
            spliced_content="",
        )


def test_truncate_payload_with_negative_dropped_raises_value_error_naming_it() -> None:
    with pytest.raises(ValueError, match="dropped"):
        sle.truncate_payload(kept=3, dropped=-1)


def test_fork_payload_missing_parent_session_raises_value_error_naming_it() -> None:
    with pytest.raises(ValueError, match="parent_session"):
        sle.fork_payload(parent_session="", boundary_len=2)


def test_imported_payload_wrong_type_message_count_raises_value_error_naming_it() -> None:
    with pytest.raises(ValueError, match="message_count"):
        sle.imported_payload(message_count="twelve", source="legacy")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Pinned-run retention guard
# ---------------------------------------------------------------------------


def _pinned_flag(db_path: Path, run_id: str) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT pinned FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    assert row is not None
    return int(row[0])


def test_a_pinned_open_run_survives_retention_that_deletes_its_unpinned_elders(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_store, "MAX_RUNS", 3)
    monkeypatch.setattr(run_store, "MAX_DB_BYTES", 10**9)

    # The oldest run is pinned and left open (never finalized).
    pinned_id = run_store.create_run({"started_at": "2026-02-10T00:00:00+00:00", "pinned": True})
    run_store.append_event(pinned_id, "text", {"type": "text", "text": "keep me"}, t_ms=0, seq=0)

    created = [pinned_id]
    for i in range(1, 5):
        rid = run_store.create_run({"started_at": f"2026-02-10T00:0{i}:00+00:00"})
        run_store.append_event(rid, "text", {"type": "text", "text": f"hello {i}"}, t_ms=0, seq=0)
        run_store.finalize_run(rid, ok=True, error=None, iterations=i, tool_calls=0, usage=None)
        created.append(rid)

    remaining = {r["run_id"] for r in run_store.list_runs(limit=100, offset=0, filters={})}

    # Retention kept exactly MAX_RUNS non-pinned survivors plus the pinned run.
    assert pinned_id in remaining
    assert len(remaining) == 3
    # The pinned run's own event was not swept away with it.
    assert run_store.get_run(pinned_id)["events"]
    # The skip left a visible trace -- never silently retained without one.
    assert run_store.pinned_skip_count() >= 1


def test_finalize_run_clears_the_pinned_flag_so_the_run_becomes_evictable(store: Path) -> None:
    run_id = run_store.create_run({"pinned": True})
    assert _pinned_flag(store, run_id) == 1

    run_store.finalize_run(run_id, ok=True, error=None, iterations=1, tool_calls=0, usage=None)

    assert _pinned_flag(store, run_id) == 0


def test_an_unpinned_run_is_not_protected_and_retention_behaves_as_before(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_store, "MAX_RUNS", 3)
    monkeypatch.setattr(run_store, "MAX_DB_BYTES", 10**9)

    created = []
    for i in range(5):
        rid = run_store.create_run({"started_at": f"2026-02-10T00:0{i}:00+00:00"})
        run_store.append_event(rid, "text", {"type": "text", "text": f"hello {i}"}, t_ms=0, seq=0)
        run_store.finalize_run(rid, ok=True, error=None, iterations=i, tool_calls=0, usage={"tokens": i})
        created.append(rid)

    remaining = {r["run_id"] for r in run_store.list_runs(limit=100, offset=0, filters={})}
    assert remaining == set(created[-3:])
    assert run_store.pinned_skip_count() == 0


# ---------------------------------------------------------------------------
# Task 2: the capture hook at the narrow waist (LLMClient.stream_chat)
# ---------------------------------------------------------------------------
#
# Every message list handed to the LLM client is captured here at the client
# boundary: stream_chat() builds and appends a model/request event before the
# provider call, accumulates the stream, and appends model/response when the
# stream ends -- naturally or via early aclose(). chat() is built on
# stream_chat() so it is covered for free, without a second capture.
#
# Two hard requirements carried over from Task 1's review, tested explicitly
# below: (A) the captured request must be immune to later in-place mutation
# of the caller's messages list (compaction mutates in place) -- capture
# deep-copies at capture time; (B) model_response_payload's request_seq must
# actually equal the seq the correlated model/request event landed at.

import asyncio
import copy
import time

from thomas.core import capture_context
from thomas.core.config import ModelConfig
from thomas.core.llm_client import LLMClient
from thomas.core.llm_shared import StreamEvent, TokenUsage


@pytest.fixture(autouse=True)
def _reset_capture_context_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Capture context keeps a per-process ambient run + seq counters.

    Reset both between tests so one test's ambient run or seq numbering
    never bleeds into the next -- mirrors the `store` fixture's counter
    reset above.
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


def test_stream_chat_captures_the_exact_message_list_including_multi_part_content(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _fake_client(monkeypatch, [StreamEvent(type="token", data={"text": "hi"}), StreamEvent(type="done")])
    run_id = run_store.create_run({"session_id": "s1"})
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": [{"type": "text", "text": "hello"}, {"type": "image", "url": "x"}]},
    ]

    token = capture_context.set_capture_run(run_id)
    try:
        asyncio.run(_drain(client.stream_chat(messages, tools=None)))
    finally:
        capture_context.reset(token)

    request = next(e for e in run_store.stream_replay(run_id) if e["type"] == sle.MODEL_REQUEST)
    assert request["messages"] == messages
    assert request["correlation"] == "contextvar"
    assert request["model"] == "claude-honesty-spine"
    assert request["provider"] == "anthropic"


def test_captured_request_survives_in_place_mutation_of_the_original_messages_list_afterward(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hard requirement A: compaction mutates the caller's list in place after

    the model call returns. The logged event must keep showing what the model
    actually saw, not whatever the list looks like now.
    """
    client = _fake_client(monkeypatch, [StreamEvent(type="token", data={"text": "hi"}), StreamEvent(type="done")])
    run_id = run_store.create_run({"session_id": "s1"})
    messages = [{"role": "user", "content": "original text"}]

    token = capture_context.set_capture_run(run_id)
    try:
        asyncio.run(_drain(client.stream_chat(messages, tools=None)))
    finally:
        capture_context.reset(token)

    # Mutate the SAME list object in place, exactly as history compaction does.
    messages[0]["content"] = "mutated after capture"
    messages.append({"role": "user", "content": "appended after capture"})

    request = next(e for e in run_store.stream_replay(run_id) if e["type"] == sle.MODEL_REQUEST)
    assert request["messages"] == [{"role": "user", "content": "original text"}]


def test_deepcopy_of_a_hundred_message_multi_part_list_stays_well_under_ten_milliseconds() -> None:
    messages = [
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": [
                {"type": "text", "text": "x" * 200},
                {"type": "tool_use", "id": f"tc{i}", "name": "fs.read", "input": {"path": f"/a/b/{i}.py"}},
            ],
        }
        for i in range(100)
    ]
    iterations = 20
    start = time.perf_counter()
    for _ in range(iterations):
        copy.deepcopy(messages)
    elapsed_ms = (time.perf_counter() - start) / iterations * 1000
    assert elapsed_ms < 10.0


def test_chat_built_on_stream_chat_produces_exactly_one_request_and_one_response(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _fake_client(
        monkeypatch,
        [
            StreamEvent(type="token", data={"text": "hi"}),
            StreamEvent(
                type="usage",
                data={"usage": TokenUsage(prompt_tokens=3, completion_tokens=1, total_tokens=4)},
            ),
            StreamEvent(type="done"),
        ],
    )
    run_id = run_store.create_run({"session_id": "s1"})

    token = capture_context.set_capture_run(run_id)
    try:
        result = asyncio.run(client.chat([{"role": "user", "content": "hi"}]))
    finally:
        capture_context.reset(token)

    assert result["text"] == "hi"
    logged = list(run_store.stream_replay(run_id))
    assert len([e for e in logged if e["type"] == sle.MODEL_REQUEST]) == 1
    assert len([e for e in logged if e["type"] == sle.MODEL_RESPONSE]) == 1
    response = next(e for e in logged if e["type"] == sle.MODEL_RESPONSE)
    assert response["usage"] == {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}


def test_model_response_request_seq_matches_the_landed_request_events_seq(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hard requirement B: request_seq must actually equal the seq the

    correlated model/request event landed at -- not just some counter that
    happens to look plausible.
    """
    client = _fake_client(monkeypatch, [StreamEvent(type="token", data={"text": "hi"}), StreamEvent(type="done")])
    run_id = run_store.create_run({"session_id": "s1"})

    token = capture_context.set_capture_run(run_id)
    try:
        asyncio.run(_drain(client.stream_chat([{"role": "user", "content": "hi"}], tools=None)))
    finally:
        capture_context.reset(token)

    logged = list(run_store.stream_replay(run_id))
    request = next(e for e in logged if e["type"] == sle.MODEL_REQUEST)
    response = next(e for e in logged if e["type"] == sle.MODEL_RESPONSE)
    assert response["request_seq"] == request["seq"]


def test_uncorrelated_call_lands_in_the_ambient_run_and_correlated_lands_in_the_set_run(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _fake_client(monkeypatch, [StreamEvent(type="token", data={"text": "hi"}), StreamEvent(type="done")])

    # No contextvar set -- must land in the lazily-created ambient run.
    asyncio.run(_drain(client.stream_chat([{"role": "user", "content": "uncorrelated"}], tools=None)))
    ambient_id = capture_context.ambient_run_id(create=False)
    assert ambient_id is not None
    ambient_run = run_store.get_run(ambient_id)["run"]
    assert ambient_run["mode"] == "ambient-capture"
    ambient_events = list(run_store.stream_replay(ambient_id))
    assert any(e["type"] == sle.MODEL_REQUEST and e["correlation"] == "ambient" for e in ambient_events)

    # Contextvar set -- must land in that run, not the ambient one.
    run_id = run_store.create_run({"session_id": "s1"})
    token = capture_context.set_capture_run(run_id)
    try:
        asyncio.run(_drain(client.stream_chat([{"role": "user", "content": "correlated"}], tools=None)))
    finally:
        capture_context.reset(token)

    assert run_id != ambient_id
    correlated_events = list(run_store.stream_replay(run_id))
    assert any(e["type"] == sle.MODEL_REQUEST and e["correlation"] == "contextvar" for e in correlated_events)
    # The correlated call did not also land in the ambient run.
    ambient_requests_after = [e for e in run_store.stream_replay(ambient_id) if e["type"] == sle.MODEL_REQUEST]
    assert len(ambient_requests_after) == 1


def test_a_raising_append_event_does_not_break_the_model_call_and_counts_the_failure_once(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single failed append must be counted once, not twice.

    begin_model_capture's request append is the only thing that ever runs
    when the request append itself fails -- end_model_capture short-circuits
    because state.active never became True, and must not re-report that
    same failure as a second one. Instrument the actual append call count
    (not just the counter) so a regression that counts a no-op "failure" a
    second time is caught even if it produces the same final number by
    coincidence.
    """
    client = _fake_client(
        monkeypatch, [StreamEvent(type="token", data={"text": "still works"}), StreamEvent(type="done")]
    )
    run_id = run_store.create_run({"session_id": "s1"})

    append_attempts = {"n": 0}

    def boom(*_args, **_kwargs):
        append_attempts["n"] += 1
        raise RuntimeError("append blew up")

    monkeypatch.setattr(run_store, "append_event", boom)

    assert client.capture_failures == 0
    token = capture_context.set_capture_run(run_id)
    try:
        events = asyncio.run(_drain(client.stream_chat([{"role": "user", "content": "hi"}], tools=None)))
    finally:
        capture_context.reset(token)

    # The model call itself succeeded -- unaffected by the capture failure.
    assert [e.type for e in events] == ["token", "done"]
    # Exactly one append was ever attempted (the request; end_model_capture
    # never tries the response append once the request itself failed)...
    assert append_attempts["n"] == 1
    # ...and it is counted exactly once, not once per capture-hook call site.
    assert client.capture_failures == 1


def test_a_raising_response_append_after_a_successful_request_append_counts_once(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mirror case: the request append succeeds, only the response append

    fails. That is a genuinely distinct failure from the case above and must
    still be counted exactly once.
    """
    client = _fake_client(
        monkeypatch, [StreamEvent(type="token", data={"text": "still works"}), StreamEvent(type="done")]
    )
    run_id = run_store.create_run({"session_id": "s1"})
    real_append = run_store.append_event
    append_attempts = {"n": 0}

    def fail_on_second_call(*args, **kwargs):
        append_attempts["n"] += 1
        if append_attempts["n"] == 1:
            return real_append(*args, **kwargs)
        raise RuntimeError("response append blew up")

    monkeypatch.setattr(run_store, "append_event", fail_on_second_call)

    assert client.capture_failures == 0
    token = capture_context.set_capture_run(run_id)
    try:
        events = asyncio.run(_drain(client.stream_chat([{"role": "user", "content": "hi"}], tools=None)))
    finally:
        capture_context.reset(token)

    assert [e.type for e in events] == ["token", "done"]
    assert append_attempts["n"] == 2
    assert client.capture_failures == 1
    # The request landed; only the response is missing.
    logged = list(run_store.stream_replay(run_id))
    assert len([e for e in logged if e["type"] == sle.MODEL_REQUEST]) == 1
    assert len([e for e in logged if e["type"] == sle.MODEL_RESPONSE]) == 0


def test_partial_consumption_that_closes_the_stream_early_logs_interrupted_true(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _fake_client(
        monkeypatch,
        [
            StreamEvent(type="token", data={"text": "a"}),
            StreamEvent(type="token", data={"text": "b"}),
            StreamEvent(type="token", data={"text": "c"}),
            StreamEvent(type="done"),
        ],
    )
    run_id = run_store.create_run({"session_id": "s1"})

    async def go() -> None:
        gen = client.stream_chat([{"role": "user", "content": "hi"}], tools=None)
        first = await gen.__anext__()
        assert first.type == "token"
        await gen.aclose()

    token = capture_context.set_capture_run(run_id)
    try:
        asyncio.run(go())
    finally:
        capture_context.reset(token)

    logged = list(run_store.stream_replay(run_id))
    response = next(e for e in logged if e["type"] == sle.MODEL_RESPONSE)
    assert response["interrupted"] is True
    assert response["text"] == "a"


def test_agent_loop_correlates_its_model_calls_with_its_own_run_id() -> None:
    """The AgentLoop wiring: set_capture_run(self._run_id)/reset around the

    per-iteration model call in loop_execution.py, so a turn's model calls
    land under the run the turn already owns instead of the ambient run.
    """
    from thomas.agent.loop import AgentLoop
    from thomas.core.config import AppConfig
    from thomas.tools.registry import ToolRegistry

    seen_run_ids: list[str | None] = []

    class DummyLLM:
        def __init__(self) -> None:
            self.config = ModelConfig(name="dummy", model="dummy", context_window=2048, max_tokens=64)

        async def stream_chat(self, messages, tools):  # noqa: ANN001
            seen_run_ids.append(capture_context.current())
            yield StreamEvent(type="token", data={"text": "hi"})
            yield StreamEvent(type="done", data={})

    config = AppConfig(models={"frontier": ModelConfig(name="frontier", model="gpt-5.6-sol")}, default_model="frontier")
    loop = AgentLoop(config, DummyLLM(), ToolRegistry(), conversation=[], run_id="fixed-run-id-123")

    async def run_once() -> None:
        async for _event in loop.run("hello", tools_policy="never"):
            pass

    assert capture_context.current() is None
    asyncio.run(run_once())

    assert seen_run_ids
    assert all(rid == "fixed-run-id-123" for rid in seen_run_ids)
    # The contextvar is reset once the model call finishes -- it does not
    # leak into whatever runs after the turn.
    assert capture_context.current() is None


# Reviewer fix-round tests (seq-collision, capture_failures double-count,
# failover honesty, MemoryError) live in
# test_model_visible_means_logged_capture_fixes.py -- split out to keep this
# file under the monolith guard's unbaselined soft limit.
