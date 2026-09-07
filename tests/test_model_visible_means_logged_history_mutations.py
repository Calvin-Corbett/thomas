"""History mutations become events (Task 3 of the honesty-spine plan).

Split out of test_model_visible_means_logged.py to keep that file under the
monolith guard's unbaselined soft limit -- this is a second logically
distinct test file, not a `*_part*.py` module split (nothing here is a
fragment of a single module; it is its own coherent set of contracts on the
four history-mutation sites).

Each of the four sites -- compaction (thomas/agent/context_compaction.py),
truncate (thomas/server/routes/chat_v2_session_routes.py), fork
(thomas/server/routes/sessions_aiohttp.py), and imported
(thomas/chat/session_store.py) -- appends its own event type on a successful
mutation, correlates to whatever run is current() (falling back to the
per-process ambient run when nothing is), and is fail-safe per Task 2's
pattern: a raising append is caught by a fixed, named exception tuple,
counted, and never breaks the caller.

Route-side correlation is honestly weaker than AgentLoop's: truncate and
fork run outside any AgentLoop turn, so no capture_context contextvar is
set there in production either -- their events legitimately land in the
ambient run unless a caller happens to have one current. Session identity
(kept here as an extra "session_id" key on the event payload, since none of
truncate_payload/fork_payload/imported_payload declare one -- those are
Task 1's fixed interfaces) is what lets a future derivation match a
route-side event back to its session; fork additionally gets its OWN new
pinned run (distinct from the parent's and from the shared ambient run),
since a fork creates a new conversation identity.

Every test here uses its own tmp_path sqlite file via run_store.init_db() --
never the live server's database.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request

from thomas.agent.context_compaction import ContextCompactor
from thomas.chat.conversation import ConversationManager
from thomas.chat.session_store import SessionStore
from thomas.core import capture_context
from thomas.core.config import AppConfig, ModelConfig
from thomas.marketplace.observability import run_store
from thomas.marketplace.observability import session_log_events as sle
from thomas.server.app_keys import APP_CONFIG, APP_SESSIONS, ChatSession
from thomas.server.routes import chat_v2_session_routes as truncate_routes
from thomas.server.routes import sessions_aiohttp as fork_routes
from thomas.server.routes.chat_v2_keys import APP_SESSION_STORE


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
    """Mirrors test_model_visible_means_logged.py's fixture of the same name."""
    monkeypatch.setattr(capture_context, "_ambient_run_id", None)
    monkeypatch.setattr(capture_context, "_next_seq_by_run", {})


def _big_conversation(n: int = 20, size: int = 250) -> list[dict]:
    messages = [{"role": "system", "content": "sys prompt"}]
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append({"role": role, "content": f"turn {i}: " + ("x" * size)})
    return messages


# ---------------------------------------------------------------------------
# Compaction: thomas/agent/context_compaction.py
# ---------------------------------------------------------------------------


def test_compact_on_a_fixture_conversation_appends_exactly_one_compaction_event_with_the_replaced_range(
    store: Path,
) -> None:
    compactor = ContextCompactor(llm=None, segment_size=4)
    messages = _big_conversation(n=20, size=250)
    run_id = run_store.create_run({"session_id": "s1"})

    token = capture_context.set_capture_run(run_id)
    try:
        result = asyncio.run(compactor.compact(messages, target_budget=100, preserve_recent=4, use_llm=False))
    finally:
        capture_context.reset(token)

    assert result.compacted_message_count < result.original_message_count
    events = [e for e in run_store.stream_replay(run_id) if e["type"] == sle.HISTORY_COMPACTION]
    assert len(events) == 1
    event = events[0]
    assert event["replaced_from"] == 1  # after the single system prompt
    assert event["replaced_to"] > event["replaced_from"]
    assert len(event["summary_text"]) > 0
    assert event["by"] == "heuristic"


def test_compact_below_budget_does_nothing_and_appends_no_compaction_event(store: Path) -> None:
    compactor = ContextCompactor(llm=None)
    messages = [{"role": "user", "content": "short"}]

    result = asyncio.run(compactor.compact(messages, target_budget=100000))

    assert result.compacted_message_count == len(messages)
    # No run was even created -- a no-op compaction never resolves a run to
    # log to, so it cannot have polluted the ambient run either.
    assert capture_context.ambient_run_id(create=False) is None


def test_compact_lands_in_the_ambient_run_when_no_run_is_current(store: Path) -> None:
    compactor = ContextCompactor(llm=None, segment_size=4)
    messages = _big_conversation(n=20, size=250)

    assert capture_context.current() is None
    asyncio.run(compactor.compact(messages, target_budget=100, preserve_recent=4, use_llm=False))

    ambient_id = capture_context.ambient_run_id(create=False)
    assert ambient_id is not None
    events = [e for e in run_store.stream_replay(ambient_id) if e["type"] == sle.HISTORY_COMPACTION]
    assert len(events) == 1


def test_the_summary_llm_calls_own_capture_correlates_to_the_same_run_as_its_compaction_event(
    store: Path,
) -> None:
    """The summary LLM call is explicitly correlated to the SAME run its

    own history/compaction event lands on -- distinguishing it from
    whatever the caller's contextvar state happened to be, per the Task 3
    brief's requirement.
    """
    seen_run_ids: list[str | None] = []

    class _FakeLLM:
        async def chat(self, messages, tools=None):  # noqa: ANN001, ARG002
            seen_run_ids.append(capture_context.current())
            return {"text": "an llm-produced summary"}

    compactor = ContextCompactor(llm=_FakeLLM(), segment_size=4)
    messages = _big_conversation(n=20, size=250)

    assert capture_context.current() is None
    asyncio.run(compactor.compact(messages, target_budget=100, preserve_recent=4, use_llm=True))

    assert seen_run_ids
    assert all(rid is not None for rid in seen_run_ids)
    ambient_id = capture_context.ambient_run_id(create=False)
    assert all(rid == ambient_id for rid in seen_run_ids)
    events = [e for e in run_store.stream_replay(ambient_id) if e["type"] == sle.HISTORY_COMPACTION]
    assert len(events) == 1
    assert events[0]["by"] == "llm"
    # Reset once compaction finishes -- does not leak into whatever runs next.
    assert capture_context.current() is None


def test_a_raising_history_compaction_append_does_not_break_compact_and_counts_the_failure(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("compaction append blew up")

    monkeypatch.setattr(run_store, "append_event", boom)

    compactor = ContextCompactor(llm=None, segment_size=4)
    messages = _big_conversation(n=20, size=250)
    assert compactor.compaction_event_failures == 0

    result = asyncio.run(compactor.compact(messages, target_budget=100, preserve_recent=4, use_llm=False))

    assert result.compacted_message_count < result.original_message_count
    assert compactor.compaction_event_failures == 1


def test_a_raising_heuristic_summarizer_propagates_but_resets_the_capture_token(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reviewer-flagged leak: an uncaught exception in the (already

    unguarded) heuristic summarizer must not leave capture_context.current()
    pointing at compaction's correlated run. Because compact() is awaited
    in-place, a leaked value would survive into the caller's context and get
    restored by the NEXT set_capture_run/reset bracket (loop_execution.py's
    own), mislabeling later captures. Hits the plain `else` branch (no LLM).
    """
    compactor = ContextCompactor(llm=None, segment_size=4)
    messages = _big_conversation(n=20, size=250)

    def boom(*_args, **_kwargs):
        raise RuntimeError("heuristic summarizer blew up")

    monkeypatch.setattr(compactor, "_summarize_segments_heuristic", boom)

    assert capture_context.current() is None
    with pytest.raises(RuntimeError, match="heuristic summarizer blew up"):
        asyncio.run(compactor.compact(messages, target_budget=100, preserve_recent=4, use_llm=False))

    assert capture_context.current() is None


def test_a_raising_heuristic_fallback_after_a_failed_llm_summary_also_resets_the_capture_token(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same leak, the other unguarded path: the LLM summarizer itself raises

    (caught by the pre-existing except), and its heuristic FALLBACK also
    raises. The token must still come back to None.
    """
    compactor = ContextCompactor(llm=object(), segment_size=4)
    messages = _big_conversation(n=20, size=250)

    async def llm_boom(_segments):
        raise RuntimeError("llm summary path blew up")

    def heuristic_boom(*_args, **_kwargs):
        raise RuntimeError("heuristic fallback blew up")

    monkeypatch.setattr(compactor, "_summarize_segments_with_llm", llm_boom)
    monkeypatch.setattr(compactor, "_summarize_segments_heuristic", heuristic_boom)

    assert capture_context.current() is None
    with pytest.raises(RuntimeError, match="heuristic fallback blew up"):
        asyncio.run(compactor.compact(messages, target_budget=100, preserve_recent=4, use_llm=True))

    assert capture_context.current() is None


# ---------------------------------------------------------------------------
# Truncate: thomas/server/routes/chat_v2_session_routes.py
# ---------------------------------------------------------------------------


class _FakeStoreForTruncate:
    def __init__(self, messages: list[dict]) -> None:
        self._messages = messages
        self.saved: tuple | None = None

    async def load(self, session_id: str):  # noqa: ANN201, ARG002
        return ConversationManager(messages=list(self._messages))

    async def save(self, session_id: str, conversation, meta=None, *, force: bool = False) -> bool:  # noqa: ANN001
        self.saved = (session_id, conversation, force)
        return True


def _truncate_request(session_id: str, messages: list[dict]) -> web.Request:
    app = web.Application()
    app[APP_SESSION_STORE] = _FakeStoreForTruncate(messages)
    return make_mocked_request(
        "POST", f"/api/v2/chat/session/{session_id}/truncate", match_info={"session_id": session_id}, app=app
    )


def test_handle_session_truncate_appends_history_truncate_matching_the_routes_kept_dropped_math(
    store: Path,
) -> None:
    messages = [{"role": "user", "content": f"m{i}"} for i in range(5)]
    request = _truncate_request("sess-1", messages)
    # request.json() has no body -- the route's own (ValueError, TypeError)
    # fallback treats that as keep_messages=0, so the route's real math is
    # kept=0, dropped=len(messages).
    run_id = run_store.create_run({"session_id": "sess-1"})

    token = capture_context.set_capture_run(run_id)
    try:
        response = asyncio.run(truncate_routes.handle_session_truncate(request))
    finally:
        capture_context.reset(token)

    body = json.loads(response.text)
    assert body == {"session_id": "sess-1", "kept": 0, "removed": 5}

    events = [e for e in run_store.stream_replay(run_id) if e["type"] == sle.HISTORY_TRUNCATE]
    assert len(events) == 1
    assert events[0]["kept"] == 0
    assert events[0]["dropped"] == 5
    assert events[0]["session_id"] == "sess-1"


def test_handle_session_truncate_lands_in_the_ambient_run_when_no_run_is_current(store: Path) -> None:
    messages = [{"role": "user", "content": f"m{i}"} for i in range(3)]
    request = _truncate_request("sess-2", messages)

    assert capture_context.current() is None
    asyncio.run(truncate_routes.handle_session_truncate(request))

    ambient_id = capture_context.ambient_run_id(create=False)
    assert ambient_id is not None
    events = [e for e in run_store.stream_replay(ambient_id) if e["type"] == sle.HISTORY_TRUNCATE]
    assert len(events) == 1
    assert events[0]["session_id"] == "sess-2"


def test_a_raising_history_truncate_append_does_not_break_the_route_and_counts_the_failure(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("truncate append blew up")

    monkeypatch.setattr(run_store, "append_event", boom)
    monkeypatch.setattr(truncate_routes, "TRUNCATE_EVENT_FAILURES", 0)

    messages = [{"role": "user", "content": f"m{i}"} for i in range(3)]
    request = _truncate_request("sess-3", messages)

    response = asyncio.run(truncate_routes.handle_session_truncate(request))

    assert response.status == 200
    assert json.loads(response.text)["removed"] == 3
    assert truncate_routes.TRUNCATE_EVENT_FAILURES == 1


def test_handle_session_truncate_no_op_when_keep_covers_everything_appends_no_event(
    store: Path,
) -> None:
    """keep >= len(msgs) is a no-op (no mutation) -- the route returns early

    without ever calling _record_truncate_event, so no event should exist.
    """
    messages = [{"role": "user", "content": f"m{i}"} for i in range(3)]
    request = _truncate_request("sess-5", messages)

    async def fake_json():
        return {"keep_messages": 99}

    request.json = fake_json
    run_id = run_store.create_run({"session_id": "sess-5"})

    token = capture_context.set_capture_run(run_id)
    try:
        response = asyncio.run(truncate_routes.handle_session_truncate(request))
    finally:
        capture_context.reset(token)

    body = json.loads(response.text)
    assert body == {"session_id": "sess-5", "kept": 3, "removed": 0}
    assert [e for e in run_store.stream_replay(run_id) if e["type"] == sle.HISTORY_TRUNCATE] == []


# ---------------------------------------------------------------------------
# Fork: thomas/server/routes/sessions_aiohttp.py
# ---------------------------------------------------------------------------


async def _fork_client(sessions: dict) -> TestClient:
    cfg = AppConfig(models={"local": ModelConfig(name="local", model="dummy")}, default_model="local")
    app = web.Application()
    app[APP_CONFIG] = cfg
    app[APP_SESSIONS] = sessions

    async def _read_json(request: web.Request) -> dict:
        return dict(await request.json())

    fork_routes.register_sessions_routes(
        app,
        require_api_access=lambda request: None,  # noqa: ARG005
        read_json=_read_json,
        task_ledger_update=lambda *args, **kwargs: None,  # noqa: ARG005
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_api_session_fork_appends_history_fork_with_parent_and_boundary_and_the_child_run_is_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "runs.sqlite3"
    run_store.init_db(db_path)
    monkeypatch.setattr(run_store, "MAX_RUNS", 500)
    monkeypatch.setattr(run_store, "MAX_DB_BYTES", 200 * 1024 * 1024)
    monkeypatch.setattr(run_store, "_PINNED_SKIP_COUNT", 0)
    monkeypatch.setattr(capture_context, "_ambient_run_id", None)
    monkeypatch.setattr(capture_context, "_next_seq_by_run", {})

    parent_sid = "parent-1"
    sessions = {
        parent_sid: ChatSession(
            id=parent_sid,
            conversation=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}],
            profile="local",
            model_id=None,
            autonomy_level=3,
        )
    }
    client = await _fork_client(sessions)
    try:
        resp1 = await client.post("/api/session/fork", json={"session_id": parent_sid})
        assert resp1.status == 200
        child1 = (await resp1.json())["session_id"]

        resp2 = await client.post("/api/session/fork", json={"session_id": parent_sid})
        assert resp2.status == 200
        child2 = (await resp2.json())["session_id"]
    finally:
        await client.close()

    assert child1 != child2

    runs1 = run_store.list_runs(limit=10, offset=0, filters={"session_id": child1})
    runs2 = run_store.list_runs(limit=10, offset=0, filters={"session_id": child2})
    assert len(runs1) == 1
    assert len(runs2) == 1
    fork_run_1, fork_run_2 = runs1[0]["run_id"], runs2[0]["run_id"]
    assert fork_run_1 != fork_run_2  # each fork gets its OWN run

    events1 = [e for e in run_store.stream_replay(fork_run_1) if e["type"] == sle.HISTORY_FORK]
    assert len(events1) == 1
    assert events1[0]["parent_session"] == parent_sid
    assert events1[0]["boundary_len"] == 2
    assert events1[0]["session_id"] == child1


@pytest.mark.asyncio
async def test_a_raising_history_fork_append_does_not_break_the_route_and_counts_the_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "runs.sqlite3"
    run_store.init_db(db_path)
    monkeypatch.setattr(run_store, "MAX_RUNS", 500)
    monkeypatch.setattr(run_store, "MAX_DB_BYTES", 200 * 1024 * 1024)
    monkeypatch.setattr(run_store, "_PINNED_SKIP_COUNT", 0)
    monkeypatch.setattr(capture_context, "_ambient_run_id", None)
    monkeypatch.setattr(capture_context, "_next_seq_by_run", {})
    monkeypatch.setattr(fork_routes, "FORK_EVENT_FAILURES", 0)

    def boom(*_args, **_kwargs):
        raise RuntimeError("fork append blew up")

    monkeypatch.setattr(run_store, "append_event", boom)

    parent_sid = "parent-2"
    sessions = {
        parent_sid: ChatSession(
            id=parent_sid, conversation=[{"role": "user", "content": "hi"}], profile="local", model_id=None
        )
    }
    client = await _fork_client(sessions)
    try:
        resp = await client.post("/api/session/fork", json={"session_id": parent_sid})
        assert resp.status == 200
    finally:
        await client.close()

    assert fork_routes.FORK_EVENT_FAILURES == 1


def _pinned_flag(db_path: Path, run_id: str) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT pinned FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return int(row[0])
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_a_forked_run_is_finalized_and_becomes_evictable_by_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reviewer-flagged: fork used to mint a permanently-pinned, never-

    finalized run per call -- retention could never reclaim it, and once
    enough forks happened its scan window would be entirely protected rows.
    finalize_run() now runs right after the single history/fork event
    lands, clearing pinned, so a shrunk retention cap CAN evict it once
    something newer exists.
    """
    db_path = tmp_path / "runs.sqlite3"
    run_store.init_db(db_path)
    monkeypatch.setattr(run_store, "MAX_RUNS", 500)
    monkeypatch.setattr(run_store, "MAX_DB_BYTES", 200 * 1024 * 1024)
    monkeypatch.setattr(run_store, "_PINNED_SKIP_COUNT", 0)
    monkeypatch.setattr(capture_context, "_ambient_run_id", None)
    monkeypatch.setattr(capture_context, "_next_seq_by_run", {})

    parent_sid = "parent-3"
    sessions = {
        parent_sid: ChatSession(
            id=parent_sid, conversation=[{"role": "user", "content": "hi"}], profile="local", model_id=None
        )
    }
    client = await _fork_client(sessions)
    try:
        resp = await client.post("/api/session/fork", json={"session_id": parent_sid})
        assert resp.status == 200
        child_sid = (await resp.json())["session_id"]
    finally:
        await client.close()

    runs = run_store.list_runs(limit=10, offset=0, filters={"session_id": child_sid})
    assert len(runs) == 1
    fork_run_id = runs[0]["run_id"]

    # Finalized immediately: pinned cleared, ended_at set.
    assert _pinned_flag(db_path, fork_run_id) == 0
    assert run_store.get_run(fork_run_id)["run"]["ended_at"]

    # Shrink retention and create one newer run: the fork run, no longer
    # protected, is the oldest and gets evicted.
    monkeypatch.setattr(run_store, "MAX_RUNS", 1)
    run_store.create_run({"session_id": "filler", "started_at": "2099-01-01T00:00:00+00:00"})

    remaining = {r["run_id"] for r in run_store.list_runs(limit=100, offset=0, filters={})}
    assert fork_run_id not in remaining


# ---------------------------------------------------------------------------
# Imported: thomas/chat/session_store.py
# ---------------------------------------------------------------------------


def _write_legacy_session_file(session_store: SessionStore, session_id: str, messages: list[dict]) -> Path:
    """Simulate a session file written by code predating the honesty spine --

    no `session_log` marker key at all.
    """
    target = session_store._session_path(session_id)
    payload = {
        "session_id": session_id,
        "saved_at": 0.0,
        "conversation": {
            "version": 0,
            "messages": messages,
            "total_tokens": 0,
            "message_count": len(messages),
        },
    }
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def test_load_of_a_pre_existing_session_fires_history_imported_exactly_once_and_survives_a_restart(
    tmp_path: Path, store: Path
) -> None:
    session_store = SessionStore(tmp_path / "sessions")
    messages = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "reply"}]
    _write_legacy_session_file(session_store, "legacy-1", messages)

    conversation = asyncio.run(session_store.load("legacy-1"))
    assert conversation is not None
    assert conversation.length == 2

    run_id = capture_context.ambient_run_id(create=False)
    assert run_id is not None
    imported = [e for e in run_store.stream_replay(run_id) if e["type"] == sle.HISTORY_IMPORTED]
    assert len(imported) == 1
    assert imported[0]["message_count"] == 2
    assert imported[0]["source"] == "session_store"
    assert imported[0]["session_id"] == "legacy-1"

    # A second load, same instance: must not fire again.
    asyncio.run(session_store.load("legacy-1"))
    assert len([e for e in run_store.stream_replay(run_id) if e["type"] == sle.HISTORY_IMPORTED]) == 1

    # Restart: a fresh SessionStore instance reading the same file must not
    # re-fire either -- the marker lives on disk, not in process memory.
    fresh_store = SessionStore(tmp_path / "sessions")
    asyncio.run(fresh_store.load("legacy-1"))
    assert len([e for e in run_store.stream_replay(run_id) if e["type"] == sle.HISTORY_IMPORTED]) == 1


def test_log_born_session_never_fires_history_imported(tmp_path: Path, store: Path) -> None:
    session_store = SessionStore(tmp_path / "sessions2")
    conv = ConversationManager(messages=[{"role": "user", "content": "brand new"}])

    asyncio.run(session_store.save("new-1", conv, force=True))
    loaded = asyncio.run(session_store.load("new-1"))
    assert loaded is not None
    assert loaded.length == 1

    # A log-born session never touches the capture path at all.
    assert capture_context.ambient_run_id(create=False) is None


def test_save_of_a_pre_existing_unmarked_session_is_also_a_first_log_touch(tmp_path: Path, store: Path) -> None:
    session_store = SessionStore(tmp_path / "sessions3")
    _write_legacy_session_file(
        session_store,
        "legacy-3",
        [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}, {"role": "user", "content": "c"}],
    )

    new_conv = ConversationManager(messages=[{"role": "user", "content": "d"}])
    asyncio.run(session_store.save("legacy-3", new_conv, force=True))

    run_id = capture_context.ambient_run_id(create=False)
    assert run_id is not None
    imported = [e for e in run_store.stream_replay(run_id) if e["type"] == sle.HISTORY_IMPORTED]
    assert len(imported) == 1
    # The OLD legacy count, not the new content being saved.
    assert imported[0]["message_count"] == 3


def test_a_raising_history_imported_append_does_not_break_load_and_counts_the_failure(
    tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from thomas.chat import session_store as store_mod

    def boom(*_args, **_kwargs):
        raise RuntimeError("imported append blew up")

    monkeypatch.setattr(run_store, "append_event", boom)
    monkeypatch.setattr(store_mod, "IMPORTED_EVENT_FAILURES", 0)

    session_store = store_mod.SessionStore(tmp_path / "sessions4")
    _write_legacy_session_file(session_store, "legacy-4", [{"role": "user", "content": "old"}])

    conversation = asyncio.run(session_store.load("legacy-4"))

    assert conversation is not None
    assert conversation.length == 1
    assert store_mod.IMPORTED_EVENT_FAILURES >= 1

    # The marker is still persisted -- one attempt, not an unbounded retry
    # loop on every future load() of this session.
    raw = json.loads(session_store._session_path("legacy-4").read_text("utf-8"))
    assert raw["session_log"]["imported"] is True
