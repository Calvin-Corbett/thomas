"""THE TEST THAT CATCHES IT -- final whole-branch review, finding I3.

Split out of test_model_visible_means_logged_shadow_derivation.py to keep
that file under the monolith guard's unbaselined soft limit -- a fourth
logically distinct honesty-spine test file, not a `*_part*.py` module split
(same pattern the other four honesty-spine test files already use).

The two "reproduces the real compactor's splice" tests in the shadow
derivation file build their fixture by compacting the SAME list object they
also record as the model/request's `messages` -- a conversation that already
carries its own leading system message, because the fixture put one there.
That is not how production looks: `AgentLoop._build_messages` synthesizes
and prepends the system message SEPARATELY from `self._conversation` (which
the compactor mutates and has no leading system message at all), and may
additionally trim the request. Those two tests are therefore
coordinate-space-fictional -- they cannot exercise the offset bug the final
review found (I2), because in their fixture there is no offset to get wrong.

This test builds via the REAL `loop_core._build_messages` (system message
prepended, real trim) and compacts via the REAL `ContextCompactor`, then
derives from the captured events -- proving `_resolve_verified_splice_range`
(the I2/I3 fix in `derive_messages.py`) and the correlation-bracket fix (I1,
`loop_execution.py` wrapping auto-compact in its own `set_capture_run`)
together, in the shape production actually uses: `derived == built`, OR the
run carries a classified skip -- never a silent, unclassified divergence.

Uses its own tmp_path sqlite file via run_store.init_db() -- never the live
server's database.
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
    """Seed the baseline model/request event via the real writer-aware seq counter."""
    payload = sle.model_request_payload(
        messages=messages, model="m", provider="p", tools_digest=None, correlation="contextvar"
    )
    capture_context.append_capture_event(run_id, payload)


def test_derive_messages_matches_or_classifies_skip_against_the_real_build_messages_and_real_compactor(
    store: Path,
) -> None:
    from thomas.agent.context_compaction import ContextCompactor
    from thomas.agent.loop import AgentLoop
    from thomas.agent.loop_core import LoopState
    from thomas.core.config import AppConfig, ModelConfig
    from thomas.tools.registry import ToolRegistry

    run_id = run_store.create_run({"session_id": "e2e-real-build"})

    class DummyLLM:
        def __init__(self) -> None:
            self.config = ModelConfig(name="dummy", model="dummy", context_window=20000, max_tokens=500)

    config = AppConfig(
        models={"frontier": ModelConfig(name="frontier", model="gpt-5.6-sol")}, default_model="frontier"
    )
    loop = AgentLoop(config, DummyLLM(), ToolRegistry(), conversation=[], run_id=run_id)

    # Enough compactable turns to force a real compaction well under target_budget.
    for i in range(14):
        role = "user" if i % 2 == 0 else "assistant"
        loop._conversation.append({"role": role, "content": f"turn {i} " + "z" * 700})

    build_kwargs = {
        "memory_text": "",
        "tool_specs": [],
        "include_purpose": False,
        "preserve_first": 1,
        "preserve_last": 4,
        "history_token_cap": None,
        "route_path": "",
        "skills_context": "",
        "include_autonomy_profile": False,
        "include_editing_policy": False,
        "include_project_instructions": False,
    }
    # Turn 1's request: [synthesized system message] + the real trim of
    # self._conversation -- exactly what loop_execution.py hands the LLM.
    built_before = loop._build_messages(LoopState(), **build_kwargs)
    _seed_baseline_request(run_id, built_before)

    # Compaction runs on self._conversation (conversation-space, no system
    # prefix) -- correlated the same way the I1 fix now correlates it in the
    # real loop: set_capture_run wraps this call, not just the model call.
    compactor = ContextCompactor(llm=None)
    token = capture_context.set_capture_run(run_id)
    try:
        asyncio.run(compactor.compact(loop._conversation, target_budget=900, preserve_recent=4, use_llm=False))
    finally:
        capture_context.reset(token)

    # Turn 2's request: what the loop would ACTUALLY send next.
    built_after = loop._build_messages(LoopState(), **build_kwargs)

    events = list(run_store.stream_replay(run_id))
    assert any(e["type"] == sle.HISTORY_COMPACTION for e in events), "fixture must actually compact"

    try:
        derived = dm.derive_messages(events)
    except dm.NonComparableDerivation as e:
        # A classified skip is an honest outcome -- a silent, unclassified
        # divergence (or a wrongly "exact" splice) is not.
        assert e.reason in {dm.SKIP_REASON_LOSSY_COMPACTION_FALLBACK, dm.SKIP_REASON_COMPACTION_RANGE_UNVERIFIABLE}
        return

    assert derived == built_after
    assert dm.structural_diff(built_after, derived) == []
