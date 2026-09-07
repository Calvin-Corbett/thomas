"""Compaction reconstruction honesty: "exact" vs "lossy-fallback" (Task 4 re-review).

Split out of test_model_visible_means_logged_shadow_derivation.py to stay
under the monolith guard's unbaselined soft limit -- this is a fourth
logically distinct honesty-spine test file, not a `*_part*.py` module split
(its own coherent set of contracts on the `reconstruction` field added to
`thomas/marketplace/observability/session_log_events.py`'s
`compaction_payload`, the detection wired into
`thomas/agent/context_compaction.py`, and the decline-to-compare handling in
`thomas/marketplace/observability/derive_messages.py`).

Contradiction resolution this file pins: `derive_messages`' compaction
splice model (one recorded range replaced by one message) is only valid
when the real compactor did exactly that. `ContextCompactor`'s progressive
heuristic-trim fallback (`_apply_heuristic_compaction`) does NOT always do
that -- when no real splice happened (`summaries` empty) or Pass 3 dropped
messages beyond one clean splice, replaying the naive model deletes real,
still-present content. `compaction_payload`'s `reconstruction` field
("exact" default, "lossy-fallback" when detected) lets a reader tell the
difference; `derive_messages` raises `NonComparableDerivation` on
"lossy-fallback" rather than guess, and `shadow_diff_if_enabled` turns that
into a classified `shadow/skip` event -- never a false match, never a false
divergence.

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
    """Mirrors the sibling honesty-spine test files' fixture of the same shape."""
    monkeypatch.setattr(capture_context, "_ambient_run_id", None)
    monkeypatch.setattr(capture_context, "_next_seq_by_run", {})
    monkeypatch.setattr(dm, "shadow_diff_failures", 0)


def _seed_baseline_request(run_id: str, messages: list[dict]) -> None:
    """Seed via the SAME seq counter the compaction event will draw from."""
    payload = sle.model_request_payload(
        messages=messages, model="m", provider="p", tools_digest=None, correlation="contextvar"
    )
    capture_context.append_capture_event(run_id, payload)


# ---------------------------------------------------------------------------
# compaction_payload's `reconstruction` field: validated, defaulted
# ---------------------------------------------------------------------------


def test_compaction_payload_defaults_reconstruction_to_exact() -> None:
    payload = sle.compaction_payload(
        summary_text="s", replaced_from=0, replaced_to=1, by="heuristic", spliced_role="assistant", spliced_content="x"
    )
    assert payload["reconstruction"] == sle.RECONSTRUCTION_EXACT == "exact"


def test_compaction_payload_rejects_an_unrecognized_reconstruction_value() -> None:
    with pytest.raises(ValueError, match="reconstruction"):
        sle.compaction_payload(
            summary_text="s",
            replaced_from=0,
            replaced_to=1,
            by="heuristic",
            spliced_role="assistant",
            spliced_content="x",
            reconstruction="somehow-fine-probably",
        )


# ---------------------------------------------------------------------------
# derive_messages declines to reconstruct a lossy-fallback compaction
# ---------------------------------------------------------------------------


def test_derive_messages_raises_non_comparable_on_a_fabricated_lossy_fallback_event() -> None:
    """Unit-level: a hand-crafted event carrying reconstruction="lossy-fallback"

    is enough on its own -- derive_messages must decline before it ever
    looks at replaced_from/replaced_to, regardless of what real compactor
    behavior produced it.
    """
    events = [
        {"type": sle.MODEL_REQUEST, "seq": 0, "messages": [{"role": "user", "content": "a"}]},
        {
            "type": sle.HISTORY_COMPACTION,
            "seq": 1,
            "replaced_from": 0,
            "replaced_to": 1,
            "spliced_role": "assistant",
            "spliced_content": "whatever",
            "reconstruction": "lossy-fallback",
        },
    ]
    with pytest.raises(dm.NonComparableDerivation, match="lossy-fallback"):
        dm.derive_messages(events)


def test_non_comparable_derivation_is_not_a_value_error_and_not_swallowed_by_shadow_exceptions() -> None:
    """It must NOT subclass ValueError -- SHADOW_EXCEPTIONS' generic failure

    path must never accidentally catch this as an ordinary capture failure;
    shadow_diff_if_enabled has to handle it explicitly, on purpose.
    """
    assert not issubclass(dm.NonComparableDerivation, ValueError)
    assert not issubclass(dm.NonComparableDerivation, dm.SHADOW_EXCEPTIONS)


# ---------------------------------------------------------------------------
# THE TEST THAT MATTERS: the real compactor's partial-drop fallback,
# reproduced end-to-end, declared non-comparable, and skipped honestly.
# ---------------------------------------------------------------------------


def test_derive_messages_reproduces_the_real_compactors_splice_on_the_heuristic_fallback_path(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Coordinator re-review, CRITICAL: the fallback's PARTIAL-drop sub-case.

    Repro recipe (as specified): a compactable region entirely of blank-
    content assistant turns -- per-segment heuristic summarization then
    produces nothing (`_heuristic_segment_summary` returns "" with no
    tool_calls/file_paths/text to report), so `summaries` stays empty and
    `compact()` never builds a clean single-message splice at all. It falls
    straight to `_apply_heuristic_compaction`, whose Pass 3 drops SOME but
    not all of the blank turns to meet budget -- exactly the shape that
    used to make `derive_messages` collapse the whole recorded range into
    one message and delete real, still-present content (the reviewer's
    reproduction: built 12, derived 8).

    Asserts, in order: (1) the recorded event carries
    reconstruction="lossy-fallback"; (2) derive_messages declines to guess
    -- raises NonComparableDerivation rather than silently reconstructing
    something wrong; (3) shadow_diff_if_enabled appends a classified
    shadow/skip event (reason="lossy-compaction-fallback"), never a false
    match and never a false divergence; (4) no shadow/divergence event
    exists anywhere on the run.
    """
    from thomas.agent.context_compaction import ContextCompactor

    run_id = run_store.create_run({"session_id": "s1"})
    messages = [{"role": "system", "content": "sys"}]
    messages += [{"role": "assistant", "content": ""} for _ in range(10)]
    messages += [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"preserved turn {i}: " + ("y" * 40)}
        for i in range(4)
    ]
    _seed_baseline_request(run_id, messages)

    compactor = ContextCompactor(llm=None, segment_size=4)
    token = capture_context.set_capture_run(run_id)
    try:
        result = asyncio.run(compactor.compact(messages, target_budget=100, preserve_recent=4, use_llm=False))
    finally:
        capture_context.reset(token)

    events = list(run_store.stream_replay(run_id))
    compaction_event = next(e for e in events if e["type"] == sle.HISTORY_COMPACTION)

    # Sanity: this really is the partial-drop shape -- SOME but not all of
    # the 10 blank compactable turns survived (a marker was inserted, some
    # blanks remain, none of the 4 preserved-recent turns were touched).
    assert compaction_event["replaced_from"] == 1
    assert compaction_event["replaced_to"] == 11
    assert 6 <= result.compacted_message_count <= 14  # somewhere between "all dropped" and "none dropped"
    assert any(m.get("content", "").startswith("preserved turn") for m in messages)

    assert compaction_event["reconstruction"] == "lossy-fallback"

    with pytest.raises(dm.NonComparableDerivation, match="lossy-fallback"):
        dm.derive_messages(events)

    monkeypatch.setattr(dm, "SHADOW_ENABLED", True)
    dm.shadow_diff_if_enabled(run_id, messages)

    after = list(run_store.stream_replay(run_id))
    skip = next(e for e in after if e["type"] == dm.SHADOW_SKIP)
    assert skip["reason"] == dm.SKIP_REASON_LOSSY_COMPACTION_FALLBACK == "lossy-compaction-fallback"
    assert skip["comparison_scope"] == dm.COMPARISON_SCOPE
    assert not any(e["type"] == dm.SHADOW_DIVERGENCE for e in after)
    assert dm.shadow_diff_failures == 0


# ---------------------------------------------------------------------------
# The report tool's skip count
# ---------------------------------------------------------------------------


def test_report_tool_prints_the_skipped_as_non_comparable_count_even_at_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.forge import honesty_shadow_report as report

    db_path = tmp_path / "report-runs.sqlite3"
    exit_code = report.main(["--db", str(db_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "0 skipped as non-comparable" in captured.out


def test_report_tool_counts_a_real_skip_event(
    store: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.forge import honesty_shadow_report as report

    monkeypatch.setattr(dm, "SHADOW_ENABLED", True)
    run_id = run_store.create_run({"session_id": "s1"})
    messages = [{"role": "user", "content": "hi"}]
    _seed_baseline_request(run_id, messages)
    compaction_payload = sle.compaction_payload(
        summary_text="s",
        replaced_from=0,
        replaced_to=1,
        by="heuristic-trim",
        spliced_role="assistant",
        spliced_content="x",
        reconstruction="lossy-fallback",
    )
    capture_context.append_capture_event(run_id, compaction_payload)

    dm.shadow_diff_if_enabled(run_id, messages)

    exit_code = report.main(["--db", str(store)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "1 skipped as non-comparable" in captured.out
    assert not any(e["type"] == dm.SHADOW_DIVERGENCE for e in run_store.stream_replay(run_id))
