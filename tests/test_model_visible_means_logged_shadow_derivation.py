"""derive_messages + the shadow soak (Task 4 of the honesty-spine plan).

Split out of test_model_visible_means_logged.py to keep that file under the
monolith guard's unbaselined soft limit -- this is a third logically
distinct test file, not a `*_part*.py` module split (its own coherent set of
contracts on thomas/marketplace/observability/derive_messages.py, the one
call site it adds to thomas/agent/loop_execution.py, the public capture_context
alias Task 3's review required, and scripts/forge/honesty_shadow_report.py).

Five contracts pinned here, matching the Task 4 brief:
1. golden-path fixture: capture -> derive == built, zero divergence.
2. a seeded mismatch (a bogus message the log never recorded) -> a
   shadow/divergence event carrying a compact diff.
3. flag off -> derivation never invoked (module-level monkeypatch counter,
   AND zero run_store I/O -- the off position costs nothing).
4. integrity invariants RAISE on a fabricated duplicate-seq fixture and a
   fabricated orphan-response fixture.
5. the report tool always exits 0 and states its comparison scope in its
   header, even against an empty/fresh run store.

Plus: the loop wiring (thomas/agent/loop_execution.py's one added call site)
actually reaches derive_messages.shadow_diff_if_enabled with the turn's own
run_id and its just-built message list, and the public
capture_context.append_capture_event alias (Task 3's review requirement)
behaves identically to the private name it wraps.

Every test here uses its own tmp_path sqlite file via run_store.init_db() --
never the live server's database.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from thomas.core import capture_context
from thomas.marketplace.observability import derive_messages as dm
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
def _reset_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mirrors the sibling honesty-spine test files' fixture of the same shape.

    Capture context's ambient run + seq counters, and derive_messages'
    shadow-diff failure counter, must never bleed from one test into the
    next.
    """
    monkeypatch.setattr(capture_context, "_ambient_run_id", None)
    monkeypatch.setattr(capture_context, "_next_seq_by_run", {})
    monkeypatch.setattr(dm, "shadow_diff_failures", 0)


def _request_event(run_id: str, messages: list[dict], *, seq: int = 0) -> None:
    payload = sle.model_request_payload(
        messages=messages, model="m", provider="p", tools_digest=None, correlation="contextvar"
    )
    run_store.append_event(run_id, sle.MODEL_REQUEST, payload, t_ms=0, seq=seq)


def _response_event(run_id: str, text: str, *, request_seq: int, seq: int) -> None:
    payload = sle.model_response_payload(
        text=text,
        tool_calls=[],
        usage={},
        interrupted=False,
        request_seq=request_seq,
        served_by_model="m",
        served_by_provider="p",
        provider_attempts=1,
        merged_partial_output=False,
    )
    run_store.append_event(run_id, sle.MODEL_RESPONSE, payload, t_ms=10, seq=seq)


# ---------------------------------------------------------------------------
# Contract 1: golden path -- capture -> derive == built, zero divergence
# ---------------------------------------------------------------------------


def test_derive_messages_reconstructs_the_next_request_from_a_clean_request_response_pair(store: Path) -> None:
    run_id = run_store.create_run({"session_id": "s1"})
    request_messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    _request_event(run_id, request_messages, seq=0)
    _response_event(run_id, "hello there", request_seq=0, seq=1)

    events = list(run_store.stream_replay(run_id))
    derived = dm.derive_messages(events)

    built = [*request_messages, {"role": "assistant", "content": "hello there"}]
    assert derived == built
    assert dm.structural_diff(built, derived) == []


def test_shadow_diff_if_enabled_appends_nothing_on_the_golden_path(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dm, "SHADOW_ENABLED", True)
    run_id = run_store.create_run({"session_id": "s1"})
    request_messages = [{"role": "user", "content": "hi"}]
    _request_event(run_id, request_messages, seq=0)
    _response_event(run_id, "hello", request_seq=0, seq=1)

    built = [*request_messages, {"role": "assistant", "content": "hello"}]
    dm.shadow_diff_if_enabled(run_id, built)

    events_after = list(run_store.stream_replay(run_id))
    assert not any(e["type"] == dm.SHADOW_DIVERGENCE for e in events_after)
    assert dm.shadow_diff_failures == 0


def test_derive_messages_returns_empty_when_the_run_has_no_model_request_yet() -> None:
    """No baseline to derive from -- not an error, just nothing derivable."""
    events = [{"type": sle.HISTORY_TRUNCATE, "seq": 0, "kept": 1, "dropped": 2}]
    assert dm.derive_messages(events) == []


def test_derive_messages_applies_compaction_and_truncate_in_seq_order(store: Path) -> None:
    """Regression: the splice must replay the RECORDED spliced_role/spliced_content

    verbatim, not a re-implemented guess. The real compactor splices an
    "assistant"-role, marker-wrapped message (see
    test_derive_messages_reproduces_the_real_compactors_splice_* below for
    the cross-check against the actual compactor) -- this fixture pins that
    an arbitrary recorded role/content survives the fold unchanged, proving
    derive_messages never hardcodes a role or re-wraps summary_text itself.
    """
    run_id = run_store.create_run({"session_id": "s1"})
    request_messages = [
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},
        {"role": "user", "content": "c"},
    ]
    _request_event(run_id, request_messages, seq=0)
    compaction_payload = sle.compaction_payload(
        summary_text="a+b summarized",
        replaced_from=0,
        replaced_to=2,
        by="heuristic",
        spliced_role="assistant",
        spliced_content="[context-summary]\na+b summarized",
    )
    run_store.append_event(run_id, sle.HISTORY_COMPACTION, compaction_payload, t_ms=5, seq=1)
    truncate_payload = sle.truncate_payload(kept=1, dropped=1)
    run_store.append_event(run_id, sle.HISTORY_TRUNCATE, truncate_payload, t_ms=6, seq=2)

    events = list(run_store.stream_replay(run_id))
    derived = dm.derive_messages(events)

    # compaction: [a,b,c] -> [spliced, c]; truncate(kept=1): -> [spliced]
    assert derived == [{"role": "assistant", "content": "[context-summary]\na+b summarized"}]


# ---------------------------------------------------------------------------
# THE TEST THAT MATTERS: derive_messages reproduces the REAL ContextCompactor's
# splice exactly -- not a re-implementation of its marker/wrapper format.
# Reviewer-flagged critical fix: the derivation used to hardcode
# {"role": "user", "content": summary_text}, but the real compactor splices
# {"role": "assistant", "content": MARKER + wrapped text}. Fixed at the
# source: compaction_payload now carries spliced_role/spliced_content
# verbatim, and derive_messages replays them instead of re-guessing.
# ---------------------------------------------------------------------------


def _compactable_conversation(n: int = 12, size: int = 100) -> list[dict]:
    messages = [{"role": "system", "content": "sys prompt"}]
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append({"role": role, "content": f"turn {i}: " + ("x" * size)})
    return messages


def _seed_baseline_request(run_id: str, messages: list[dict]) -> None:
    """Seed the baseline model/request event via the SAME seq counter

    `_record_compaction_event` uses (`capture_context.append_capture_event`),
    not a hardcoded seq -- so the compaction event that follows cannot
    collide with it. `_request_event`'s hardcoded `seq=0` exists for tests
    that need exact, independently-controlled seq numbers; this fixture
    needs the real counter instead, since a real compaction event is about
    to be appended through it too.
    """
    payload = sle.model_request_payload(
        messages=messages, model="m", provider="p", tools_digest=None, correlation="contextvar"
    )
    capture_context.append_capture_event(run_id, payload)


def _seed_baseline_response(run_id: str, text: str, *, request_seq: int) -> None:
    """Mirrors `_seed_baseline_request` -- also through the real seq counter.

    Any test that calls `shadow_diff_if_enabled` more than once against the
    SAME run needs both its baseline events AND every divergence append to
    share one seq sequence; mixing this with `_request_event`/
    `_response_event`'s hardcoded seqs reproduces the exact (run_id, seq)
    collision the writer-aware counter exists to prevent.
    """
    payload = sle.model_response_payload(
        text=text,
        tool_calls=[],
        usage={},
        interrupted=False,
        request_seq=request_seq,
        served_by_model="m",
        served_by_provider="p",
        provider_attempts=1,
        merged_partial_output=False,
    )
    capture_context.append_capture_event(run_id, payload)


def test_derive_messages_reproduces_the_real_compactors_splice_on_the_llm_mocked_path(store: Path) -> None:
    from thomas.agent.context_compaction import ContextCompactor

    run_id = run_store.create_run({"session_id": "s1"})
    messages = _compactable_conversation()
    original_len = len(messages)
    _seed_baseline_request(run_id, messages)

    class _FakeLLM:
        async def chat(self, messages, tools=None):  # noqa: ANN001, ARG002
            return {"text": "an llm-produced summary of the earlier turns"}

    compactor = ContextCompactor(llm=_FakeLLM(), segment_size=4)
    token = capture_context.set_capture_run(run_id)
    try:
        result = asyncio.run(compactor.compact(messages, target_budget=200, preserve_recent=4, use_llm=True))
    finally:
        capture_context.reset(token)

    events = list(run_store.stream_replay(run_id))
    compaction_event = next(e for e in events if e["type"] == sle.HISTORY_COMPACTION)

    # Sanity: message count matches a CLEAN single splice with no further
    # heuristic-trim drops on top -- proves this run exercised call site 1,
    # the one the critical finding is about. If the fallback trim had also
    # run, len(messages) would be smaller than this.
    replaced_span = compaction_event["replaced_to"] - compaction_event["replaced_from"]
    assert result.compacted_message_count == original_len - replaced_span + 1
    assert len(messages) == original_len - replaced_span + 1
    assert compaction_event["reconstruction"] == "exact"

    derived = dm.derive_messages(events)

    assert derived == messages
    assert dm.structural_diff(messages, derived) == []
    # The spliced message really is assistant-role and marker-wrapped -- the
    # exact shape the reviewer proved derive_messages was getting wrong.
    spliced = derived[compaction_event["replaced_from"]]
    assert spliced["role"] == "assistant"
    assert spliced["content"].startswith("[context-summary]\n")


def test_derive_messages_reproduces_the_real_compactors_splice_on_the_heuristic_path(store: Path) -> None:
    from thomas.agent.context_compaction import ContextCompactor

    run_id = run_store.create_run({"session_id": "s1"})
    messages = _compactable_conversation()
    original_len = len(messages)
    _seed_baseline_request(run_id, messages)

    compactor = ContextCompactor(llm=None, segment_size=4)
    token = capture_context.set_capture_run(run_id)
    try:
        result = asyncio.run(compactor.compact(messages, target_budget=200, preserve_recent=4, use_llm=False))
    finally:
        capture_context.reset(token)

    events = list(run_store.stream_replay(run_id))
    compaction_event = next(e for e in events if e["type"] == sle.HISTORY_COMPACTION)
    replaced_span = compaction_event["replaced_to"] - compaction_event["replaced_from"]
    assert result.compacted_message_count == original_len - replaced_span + 1
    assert len(messages) == original_len - replaced_span + 1
    assert compaction_event["reconstruction"] == "exact"

    derived = dm.derive_messages(events)

    assert derived == messages
    assert dm.structural_diff(messages, derived) == []
    spliced = derived[compaction_event["replaced_from"]]
    assert spliced["role"] == "assistant"
    assert spliced["content"].startswith("[context-summary]\n")


# The lossy-fallback / NonComparableDerivation / shadow/skip contract has
# its own split file: tests/test_model_visible_means_logged_reconstruction.py
# (kept out of here to stay under the monolith guard's unbaselined soft
# limit -- same pattern as the other honesty-spine split files).


# THE TEST THAT CATCHES IT (final-review I3): end-to-end via the REAL
# loop_core._build_messages and the REAL ContextCompactor, proving the
# coordinate-space fix and the correlation-bracket fix together in the
# actual production shape -- moved to its own file to stay under the
# monolith guard's unbaselined soft limit:
# tests/test_model_visible_means_logged_real_build_and_compact.py

# ---------------------------------------------------------------------------
# Contract 2: a seeded mismatch -> a shadow/divergence event with a diff
# ---------------------------------------------------------------------------


def test_shadow_diff_if_enabled_appends_a_divergence_event_carrying_a_compact_diff_on_a_seeded_mismatch(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dm, "SHADOW_ENABLED", True)
    run_id = run_store.create_run({"session_id": "s1"})
    request_messages = [{"role": "user", "content": "hi"}]
    _request_event(run_id, request_messages, seq=0)
    _response_event(run_id, "hello", request_seq=0, seq=1)

    # The fixture appends a bogus inject: a message no captured event
    # predicts, simulating something the loop built that the spine never saw.
    bogus = {"role": "user", "content": "BOGUS INJECT never captured by any event"}
    built = [*request_messages, {"role": "assistant", "content": "hello"}, bogus]

    dm.shadow_diff_if_enabled(run_id, built)

    events = list(run_store.stream_replay(run_id))
    divergence = next(e for e in events if e["type"] == dm.SHADOW_DIVERGENCE)
    assert divergence["comparison_scope"] == dm.COMPARISON_SCOPE == "role+content of non-system messages"
    assert divergence["built_message_count"] == 3
    assert divergence["derived_message_count"] == 2
    assert divergence["diff_count"] == 1
    assert divergence["diffs"][0]["index"] == 2
    assert divergence["diffs"][0]["built"] == {"role": "user", "content": bogus["content"]}
    assert divergence["diffs"][0]["derived"] is None
    # No tool-role message or tool_calls anywhere in this divergence -- the
    # heuristic classifier has nothing to flag it as expected-class noise.
    assert divergence["reason"] == "unclassified"


def test_structural_diff_ignores_system_messages_on_both_sides() -> None:
    built = [{"role": "system", "content": "built-only system noise"}, {"role": "user", "content": "hi"}]
    derived = [{"role": "system", "content": "totally different system noise"}, {"role": "user", "content": "hi"}]
    assert dm.structural_diff(built, derived) == []


# ---------------------------------------------------------------------------
# Important #2 (reviewer): divergence noise classification
# ---------------------------------------------------------------------------


def test_classify_divergence_tags_contains_tool_role_when_built_has_a_tool_message() -> None:
    built = [{"role": "user", "content": "hi"}, {"role": "tool", "content": "tool output"}]
    derived = [{"role": "user", "content": "hi"}]
    assert dm.classify_divergence(built, derived) == "contains-tool-role"


def test_classify_divergence_tags_contains_tool_role_when_derived_has_tool_calls() -> None:
    built = [{"role": "user", "content": "hi"}]
    derived = [{"role": "assistant", "content": "", "tool_calls": [{"id": "1", "name": "fs.read"}]}]
    assert dm.classify_divergence(built, derived) == "contains-tool-role"


def test_classify_divergence_is_unclassified_with_no_tool_signal_on_either_side() -> None:
    built = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    derived = [{"role": "user", "content": "hi"}]
    assert dm.classify_divergence(built, derived) == "unclassified"


def test_shadow_diff_if_enabled_tags_a_tool_bearing_divergence_as_contains_tool_role(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dm, "SHADOW_ENABLED", True)
    run_id = run_store.create_run({"session_id": "s1"})
    request_messages = [{"role": "user", "content": "hi"}]
    _request_event(run_id, request_messages, seq=0)
    _response_event(run_id, "hello", request_seq=0, seq=1)

    # A tool result the loop appended directly to self._conversation -- not
    # yet captured as a spine event, so it's expected, documented noise.
    tool_msg = {"role": "tool", "content": "tool ran ok"}
    built = [*request_messages, {"role": "assistant", "content": "hello"}, tool_msg]

    dm.shadow_diff_if_enabled(run_id, built)

    events = list(run_store.stream_replay(run_id))
    divergence = next(e for e in events if e["type"] == dm.SHADOW_DIVERGENCE)
    assert divergence["reason"] == "contains-tool-role"


# ---------------------------------------------------------------------------
# Contract 3: flag off -> derivation never invoked, zero I/O
# ---------------------------------------------------------------------------


def test_shadow_diff_if_enabled_never_calls_derive_messages_or_touches_run_store_when_the_flag_is_off(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dm, "SHADOW_ENABLED", False)

    derive_calls = {"n": 0}
    real_derive = dm.derive_messages

    def counting_derive(events):
        derive_calls["n"] += 1
        return real_derive(events)

    monkeypatch.setattr(dm, "derive_messages", counting_derive)

    replay_calls = {"n": 0}
    real_replay = run_store.stream_replay

    def counting_replay(run_id):
        replay_calls["n"] += 1
        return real_replay(run_id)

    monkeypatch.setattr(run_store, "stream_replay", counting_replay)

    run_id = run_store.create_run({"session_id": "s1"})
    _request_event(run_id, [{"role": "user", "content": "hi"}], seq=0)

    dm.shadow_diff_if_enabled(run_id, [{"role": "user", "content": "hi"}])

    assert derive_calls["n"] == 0
    assert replay_calls["n"] == 0
    events = list(run_store.stream_replay(run_id))
    assert not any(e["type"] == dm.SHADOW_DIVERGENCE for e in events)


def test_shadow_flag_is_read_once_from_the_environment_at_import_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Documents the restart requirement: the module attribute, not the

    live environment variable, governs behavior after import -- flipping
    the env var mid-process has no effect until the module is reloaded
    (i.e. a process restart in production).
    """
    monkeypatch.setenv("THOMAS_HONESTY_SHADOW", "1")
    assert dm._read_shadow_flag() is True
    # SHADOW_ENABLED was already latched at import time -- setting the env
    # var now does not retroactively change it.
    assert isinstance(dm.SHADOW_ENABLED, bool)


# ---------------------------------------------------------------------------
# Contract 4: integrity invariants RAISE on violation
# ---------------------------------------------------------------------------


def test_derive_messages_raises_on_a_fabricated_duplicate_seq_within_one_run() -> None:
    events = [
        {"type": sle.MODEL_REQUEST, "seq": 0, "messages": [{"role": "user", "content": "a"}]},
        {"type": sle.MODEL_RESPONSE, "seq": 0, "text": "dup-seq", "tool_calls": [], "request_seq": 0},
    ]
    with pytest.raises(dm.DerivationIntegrityError, match="duplicate seq"):
        dm.derive_messages(events)


def test_derive_messages_raises_on_a_fabricated_response_whose_request_seq_matches_no_request() -> None:
    events = [
        {"type": sle.MODEL_REQUEST, "seq": 0, "messages": [{"role": "user", "content": "a"}]},
        {"type": sle.MODEL_RESPONSE, "seq": 1, "text": "orphan", "tool_calls": [], "request_seq": 99},
    ]
    with pytest.raises(dm.DerivationIntegrityError, match="request_seq"):
        dm.derive_messages(events)


def test_derivation_integrity_error_is_a_value_error() -> None:
    assert issubclass(dm.DerivationIntegrityError, ValueError)


def test_shadow_diff_if_enabled_counts_an_integrity_violation_as_a_failure_without_raising(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dm, "SHADOW_ENABLED", True)
    run_id = run_store.create_run({"session_id": "s1"})
    _request_event(run_id, [{"role": "user", "content": "hi"}], seq=0)
    # A second event forged onto the SAME seq -- `events` has no (run_id, seq)
    # uniqueness constraint, so stream_replay hands this straight back,
    # exactly the shape derive_messages' integrity check exists to catch.
    _response_event(run_id, "colliding", request_seq=0, seq=0)

    dm.shadow_diff_if_enabled(run_id, [{"role": "user", "content": "hi"}])

    assert dm.shadow_diff_failures == 1
    events = list(run_store.stream_replay(run_id))
    assert not any(e["type"] == dm.SHADOW_DIVERGENCE for e in events)


def test_shadow_diff_if_enabled_counts_a_raising_append_capture_event_and_the_turn_survives(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Minor (reviewer): the append itself -- not just derivation -- can fail.

    A raising `capture_context.append_capture_event` (the call
    `shadow_diff_if_enabled` makes to actually write the divergence event)
    must be caught by the same `SHADOW_EXCEPTIONS` guard: counted, never
    raised, and the caller (here, the direct call -- loop_execution.py's
    call site is covered separately) proceeds unharmed.
    """
    monkeypatch.setattr(dm, "SHADOW_ENABLED", True)
    run_id = run_store.create_run({"session_id": "s1"})
    request_messages = [{"role": "user", "content": "hi"}]
    _request_event(run_id, request_messages, seq=0)
    _response_event(run_id, "hello", request_seq=0, seq=1)

    def boom(*_args, **_kwargs):
        raise RuntimeError("append_capture_event blew up")

    monkeypatch.setattr(capture_context, "append_capture_event", boom)

    bogus = {"role": "user", "content": "BOGUS INJECT"}
    built = [*request_messages, {"role": "assistant", "content": "hello"}, bogus]

    # Must not raise -- the turn this diagnostic rides alongside survives.
    dm.shadow_diff_if_enabled(run_id, built)

    assert dm.shadow_diff_failures == 1
    events = list(run_store.stream_replay(run_id))
    assert not any(e["type"] == dm.SHADOW_DIVERGENCE for e in events)


# ---------------------------------------------------------------------------
# Contract 5: the report tool always exits 0 and states its comparison scope
# ---------------------------------------------------------------------------


def test_report_tool_exits_zero_and_states_comparison_scope_against_a_fresh_empty_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.forge import honesty_shadow_report as report

    db_path = tmp_path / "report-runs.sqlite3"
    exit_code = report.main(["--db", str(db_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert report.COMPARISON_SCOPE_HEADER in captured.out
    assert "0 divergences across 0 compared turns" in captured.out


def test_report_tool_prints_a_real_divergence_and_still_exits_zero(
    store: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.forge import honesty_shadow_report as report

    monkeypatch.setattr(dm, "SHADOW_ENABLED", True)
    run_id = run_store.create_run({"session_id": "s1"})
    request_messages = [{"role": "user", "content": "hi"}]
    _request_event(run_id, request_messages, seq=0)
    _response_event(run_id, "hello", request_seq=0, seq=1)
    bogus = {"role": "user", "content": "BOGUS INJECT"}
    dm.shadow_diff_if_enabled(run_id, [*request_messages, {"role": "assistant", "content": "hello"}, bogus])

    exit_code = report.main(["--db", str(store)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert report.COMPARISON_SCOPE_HEADER in captured.out
    assert "1 divergences across" in captured.out
    assert run_id in captured.out
    assert "reason=unclassified" in captured.out


def test_report_tool_prints_the_expected_class_vs_unclassified_split_with_a_heuristic_caveat(
    store: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.forge import honesty_shadow_report as report

    monkeypatch.setattr(dm, "SHADOW_ENABLED", True)
    run_id = run_store.create_run({"session_id": "s1"})
    request_messages = [{"role": "user", "content": "hi"}]
    # Counter-consistent seeding: this test calls shadow_diff_if_enabled
    # TWICE against the same run, and each divergence append also draws
    # from the same seq counter -- must not collide with a hardcoded seq.
    _seed_baseline_request(run_id, request_messages)
    _seed_baseline_response(run_id, "hello", request_seq=0)
    # Two divergences: one tool-bearing (expected-class), one plain (unclassified).
    dm.shadow_diff_if_enabled(
        run_id, [*request_messages, {"role": "assistant", "content": "hello"}, {"role": "tool", "content": "x"}]
    )
    dm.shadow_diff_if_enabled(
        run_id, [*request_messages, {"role": "assistant", "content": "hello"}, {"role": "user", "content": "y"}]
    )

    exit_code = report.main(["--db", str(store)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "2 divergences across" in captured.out
    assert "1 expected-class (contains-tool-role) / 1 unclassified" in captured.out
    assert "cheap heuristic" in captured.out


def test_report_tool_never_raises_even_when_the_db_path_is_unreadable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.forge import honesty_shadow_report as report

    # A directory in place of the expected sqlite file: init_db must fail,
    # and the tool must still print the honest zero and exit 0.
    bad_path = tmp_path / "not-a-file"
    bad_path.mkdir()
    exit_code = report.main(["--db", str(bad_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "0 divergences across 0 compared turns" in captured.out


# ---------------------------------------------------------------------------
# The loop wiring: loop_execution.py's one added call site
# ---------------------------------------------------------------------------


def test_agent_loop_calls_shadow_diff_if_enabled_with_its_own_run_id_and_the_just_built_messages() -> None:
    from thomas.agent import loop_execution
    from thomas.agent.loop import AgentLoop
    from thomas.core.config import AppConfig, ModelConfig
    from thomas.core.llm_shared import StreamEvent
    from thomas.tools.registry import ToolRegistry

    calls: list[tuple[str | None, list]] = []

    def fake_shadow_diff_if_enabled(run_id, built_messages):
        calls.append((run_id, list(built_messages)))

    class DummyLLM:
        def __init__(self) -> None:
            self.config = ModelConfig(name="dummy", model="dummy", context_window=2048, max_tokens=64)

        async def stream_chat(self, messages, tools):  # noqa: ANN001, ARG002
            yield StreamEvent(type="token", data={"text": "hi"})
            yield StreamEvent(type="done", data={})

    import pytest as _pytest

    mp = _pytest.MonkeyPatch()
    mp.setattr(loop_execution.honesty_shadow, "shadow_diff_if_enabled", fake_shadow_diff_if_enabled)
    try:
        config = AppConfig(
            models={"frontier": ModelConfig(name="frontier", model="gpt-5.6-sol")}, default_model="frontier"
        )
        loop = AgentLoop(config, DummyLLM(), ToolRegistry(), conversation=[], run_id="shadow-wiring-run-id")

        async def run_once() -> None:
            async for _event in loop.run("hello", tools_policy="never"):
                pass

        asyncio.run(run_once())
    finally:
        mp.undo()

    assert len(calls) == 1
    run_id, built_messages = calls[0]
    assert run_id == "shadow-wiring-run-id"
    assert any(m.get("role") == "user" for m in built_messages)


def test_agent_loop_survives_an_exception_that_escapes_shadow_diff_if_enabled_and_counts_it() -> None:
    """Important #3 (reviewer): defense-in-depth at the call site itself.

    `shadow_diff_if_enabled` already guards its own body, but the call site
    in loop_execution.py additionally wraps the call so a bug OUTSIDE that
    inner try (an unforeseen exception type escaping the diagnostic) still
    cannot kill a live turn. Monkeypatch the module function itself to raise
    directly -- bypassing its own internal guard entirely -- to prove the
    OUTER wrapper is what is actually catching it.
    """
    from thomas.agent import loop_execution
    from thomas.agent.loop import AgentLoop
    from thomas.core.config import AppConfig, ModelConfig
    from thomas.core.llm_shared import StreamEvent
    from thomas.marketplace.observability import derive_messages as dm
    from thomas.tools.registry import ToolRegistry

    def raising_shadow_diff_if_enabled(run_id, built_messages):  # noqa: ARG001
        raise RuntimeError("shadow diff blew up outside its own guard")

    class DummyLLM:
        def __init__(self) -> None:
            self.config = ModelConfig(name="dummy", model="dummy", context_window=2048, max_tokens=64)

        async def stream_chat(self, messages, tools):  # noqa: ANN001, ARG002
            yield StreamEvent(type="token", data={"text": "hi"})
            yield StreamEvent(type="done", data={})

    import pytest as _pytest

    dm.shadow_diff_failures = 0
    mp = _pytest.MonkeyPatch()
    mp.setattr(loop_execution.honesty_shadow, "shadow_diff_if_enabled", raising_shadow_diff_if_enabled)
    try:
        config = AppConfig(
            models={"frontier": ModelConfig(name="frontier", model="gpt-5.6-sol")}, default_model="frontier"
        )
        loop = AgentLoop(config, DummyLLM(), ToolRegistry(), conversation=[], run_id="shadow-defense-run-id")

        async def run_once() -> list:
            events = []
            async for event in loop.run("hello", tools_policy="never"):
                events.append(event)
            return events

        events = asyncio.run(run_once())
        # Read BEFORE mp.undo() -- monkeypatch.setattr on shadow_diff_if_enabled
        # only ever touched that one attribute, so this plain module read is
        # unaffected by the undo below; captured here regardless for clarity.
        failures = dm.shadow_diff_failures
    finally:
        mp.undo()

    # The turn completed normally -- text still came through.
    assert any(getattr(e, "type", None) == "text_delta" for e in events) or any(
        "hi" in str(getattr(e, "data", {})) for e in events
    )
    assert failures == 1


# ---------------------------------------------------------------------------
# The public capture_context.append_capture_event alias (Task 3's review fix)
# ---------------------------------------------------------------------------


def test_append_capture_event_public_alias_behaves_identically_to_the_private_name(store: Path) -> None:
    run_id = run_store.create_run({"session_id": "s1"})
    payload = sle.model_request_payload(
        messages=[{"role": "user", "content": "via the public alias"}],
        model="m",
        provider="p",
        tools_digest=None,
        correlation="contextvar",
    )

    seq = capture_context.append_capture_event(run_id, payload)

    assert seq == 0
    events = list(run_store.stream_replay(run_id))
    assert events[0]["seq"] == 0
    assert events[0]["messages"] == [{"role": "user", "content": "via the public alias"}]


def test_append_capture_event_alias_defers_to_a_registered_writer_same_as_the_private_function(store: Path) -> None:
    run_id = "prod-style-alias-run"
    run_store.create_run({"run_id": run_id, "session_id": "s1", "mode": "chat"})
    writer = run_store.ThreadedRunWriter(run_id)
    writer.start()
    try:
        writer.record({"type": "text", "seq": writer.seq, "text": "hello"})
        payload = sle.model_request_payload(
            messages=[{"role": "user", "content": "hi"}],
            model="m",
            provider="p",
            tools_digest=None,
            correlation="contextvar",
        )
        seq = capture_context.append_capture_event(run_id, payload)
    finally:
        writer.close()

    rows = list(run_store.stream_replay(run_id))
    seqs = [r["seq"] for r in rows]
    assert len(seqs) == len(set(seqs)), f"duplicate (run_id, seq) pairs: {seqs}"
    assert seq == 1
