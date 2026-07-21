"""Tests for thomas.agent.subagent_context.

Acceptance line (CAP-027, score 1 -> 2):
    "Prove isolated 50K-context subagents with no sibling-context leakage."

These tests prove, hermetically:
- each spawned subagent gets its OWN 50K-token context (per-subagent budget),
- writes to one sibling's context never appear in another's, and no accessor
  exposes a sibling's private data,
- the 50K budget is enforced deterministically (reject and truncate) with a
  clear structured signal,
- the parent collects each child's result summary without exposing the
  children's full contexts to each other or letting a child reach the parent,
- empty / minimal contexts are handled.
"""

from __future__ import annotations

import pytest

from thomas.agent.subagent_context import (
    DEFAULT_BUDGET_TOKENS,
    ContextBudgetError,
    IsolatedContext,
    OverflowPolicy,
    SubagentContextManager,
    WriteResult,
    create_subagent_context,
    default_token_counter,
)


# Deterministic, exact token counter (1 token per char) so budgets are precise.
def _one_per_char(text: str) -> int:
    return len(text)


def test_default_budget_is_50k():
    assert DEFAULT_BUDGET_TOKENS == 50_000


def test_default_token_counter_is_chars_over_four():
    assert default_token_counter("") == 0
    assert default_token_counter("a" * 4) == 1
    assert default_token_counter("a" * 400) == 100


def test_create_subagent_context_returns_isolated_context():
    parent = IsolatedContext(
        context_id="parent",
        system_prompt="SHARED SYSTEM PROMPT",
        task="parent task",
        budget=DEFAULT_BUDGET_TOKENS,
        token_counter=_one_per_char,
        overflow_policy=OverflowPolicy.REJECT,
    )
    child = create_subagent_context(parent, "child task", DEFAULT_BUDGET_TOKENS)
    assert isinstance(child, IsolatedContext)
    # Child inherits the shared system prompt (by value) plus its own task.
    assert child.system_prompt == "SHARED SYSTEM PROMPT"
    assert child.task == "child task"
    assert child.budget == DEFAULT_BUDGET_TOKENS
    # No back-reference to the parent exists on the child.
    assert not hasattr(child, "parent")
    assert not hasattr(child, "_parent")


# ---------------------------------------------------------------------------
# (2) Sibling isolation
# ---------------------------------------------------------------------------
def test_sibling_contexts_are_isolated_mutation_does_not_leak():
    mgr = SubagentContextManager(default_budget=50_000, token_counter=_one_per_char)
    a = mgr.create_subagent_context("task A", subagent_id="A")
    b = mgr.create_subagent_context("task B", subagent_id="B")

    # Mutate A's private scratch.
    res = a.write_scratch("A-secret-data")
    assert res.accepted and res.signal == "ok"

    # B is completely unchanged by A's write.
    assert a.scratch_text() == "A-secret-data"
    assert b.scratch_text() == ""
    assert b.read_scratch() == []
    assert b.tokens_used() == b._seed_tokens()

    # And mutating B does not retroactively change A.
    b.write_scratch("B-secret-data")
    assert a.scratch_text() == "A-secret-data"
    assert b.scratch_text() == "B-secret-data"


def test_no_accessor_lets_one_sibling_read_another():
    mgr = SubagentContextManager(token_counter=_one_per_char)
    a = mgr.create_subagent_context("task A", subagent_id="A")
    b = mgr.create_subagent_context("task B", subagent_id="B")
    a.write_scratch("A-private")
    b.write_scratch("B-private")

    # A's public surface exposes only A's own data -- B's private string never
    # appears through any accessor on A.
    a_surface = " ".join(
        [
            a.context_id,
            a.system_prompt,
            a.task,
            a.scratch_text(),
            "".join(a.read_scratch()),
            str(a.snapshot()),
            repr(a),
        ]
    )
    assert "B-private" not in a_surface
    # The context object holds no reference to the manager or the sibling.
    assert not hasattr(a, "_children")
    assert not hasattr(a, "_manager")
    # There is no accessor on IsolatedContext that takes/returns another context.
    public = [n for n in dir(a) if not n.startswith("__")]
    for name in public:
        assert "sibling" not in name.lower()
        assert "other" not in name.lower()


def test_sibling_scratch_lists_are_distinct_objects():
    mgr = SubagentContextManager(token_counter=_one_per_char)
    a = mgr.create_subagent_context("task A", subagent_id="A")
    b = mgr.create_subagent_context("task B", subagent_id="B")
    assert a._scratch is not b._scratch
    # read_scratch hands back a copy, so external mutation cannot corrupt state.
    got = a.write_scratch("x")
    assert got.accepted
    copy = a.read_scratch()
    copy.append("tampered")
    assert a.read_scratch() == ["x"]


# ---------------------------------------------------------------------------
# (3) Budget enforcement -- 50K per subagent
# ---------------------------------------------------------------------------
def test_50k_budget_enforced_per_subagent_reject():
    mgr = SubagentContextManager(
        default_budget=50_000,
        token_counter=_one_per_char,
        overflow_policy=OverflowPolicy.REJECT,
    )
    a = mgr.create_subagent_context("task A", subagent_id="A")
    b = mgr.create_subagent_context("task B", subagent_id="B")

    # Each subagent has its own independent 50K budget.
    assert a.budget == 50_000
    assert b.budget == 50_000

    # Fill A almost to the brim (task tokens count too), leaving little room.
    used_before = a.tokens_used()
    room = a.budget - used_before
    ok = a.write_scratch("a" * (room - 5))
    assert ok.accepted and ok.signal == "ok"
    assert a.tokens_remaining() == 5

    # An over-budget write to A is rejected wholesale with a clear signal.
    rej = a.write_scratch("a" * 100)
    assert isinstance(rej, WriteResult)
    assert rej.rejected is True
    assert rej.accepted is False
    assert rej.signal == "rejected"
    assert rej.stored_tokens == 0
    assert rej.dropped_tokens == 100
    # A's state is unchanged by the rejected write.
    assert a.tokens_remaining() == 5

    # B is untouched by A hitting its budget: budgets are per-subagent.
    assert b.tokens_remaining() == b.budget - b.tokens_used()
    assert b.tokens_used() == b._seed_tokens()


def test_50k_budget_enforced_per_subagent_truncate():
    ctx = IsolatedContext(
        context_id="C",
        system_prompt="",
        task="",
        budget=50_000,
        token_counter=_one_per_char,
        overflow_policy=OverflowPolicy.TRUNCATE,
    )
    # Write 60K tokens into a 50K context -> truncated to exactly 50K with signal.
    res = ctx.write_scratch("x" * 60_000)
    assert res.truncated is True
    assert res.signal == "truncated"
    assert res.stored_tokens == 50_000
    assert res.dropped_tokens == 10_000
    assert ctx.tokens_used() == 50_000
    assert ctx.tokens_remaining() == 0
    # Deterministic: the stored prefix is exactly the first 50K characters.
    assert ctx.scratch_text() == "x" * 50_000


def test_budget_uses_default_chars_over_four_counter():
    # With the real default counter, 50K tokens == 200K chars.
    ctx = create_subagent_context(None, task="", budget=50_000, overflow_policy=OverflowPolicy.REJECT)
    ok = ctx.write_scratch("a" * 200_000)  # exactly 50_000 tokens
    assert ok.accepted and ok.tokens_used == 50_000
    rej = ctx.write_scratch("a" * 4)  # 1 more token -> over budget
    assert rej.rejected and rej.signal == "rejected"


def test_seed_larger_than_budget_is_rejected_at_creation():
    with pytest.raises(ContextBudgetError):
        IsolatedContext(
            context_id="C",
            system_prompt="s" * 100,
            task="t" * 100,
            budget=50,  # seed needs 200 tokens with 1-per-char counter
            token_counter=_one_per_char,
            overflow_policy=OverflowPolicy.REJECT,
        )


# ---------------------------------------------------------------------------
# (4) Parent collects results without exposing sibling contexts
# ---------------------------------------------------------------------------
def test_parent_collects_results_without_exposing_sibling_contexts():
    parent_ctx = IsolatedContext(
        context_id="parent",
        system_prompt="SHARED",
        task="orchestrate",
        budget=50_000,
        token_counter=_one_per_char,
        overflow_policy=OverflowPolicy.REJECT,
    )
    # Parent stashes a private note in its OWN context.
    parent_ctx.write_scratch("PARENT-PRIVATE-PLANS")

    mgr = SubagentContextManager(
        parent_context=parent_ctx,
        default_budget=50_000,
        token_counter=_one_per_char,
    )
    a = mgr.create_subagent_context("task A", subagent_id="A")
    b = mgr.create_subagent_context("task B", subagent_id="B")

    # Children do their private work, then publish only a summary.
    a.write_scratch("A internal reasoning that stays private")
    b.write_scratch("B internal reasoning that stays private")
    a.set_result("A: done, result=42")
    b.set_result("B: done, result=99")

    results = mgr.collect_results()
    assert results == {"A": "A: done, result=42", "B": "B: done, result=99"}

    # The collected results contain ONLY the summaries, not the private scratch.
    blob = " ".join(str(v) for v in results.values())
    assert "internal reasoning" not in blob

    # A child cannot reach the parent's private plans: it never received the
    # parent context, only a copy of the shared system prompt.
    assert a.system_prompt == "SHARED"
    assert "PARENT-PRIVATE-PLANS" not in a.system_prompt
    assert "PARENT-PRIVATE-PLANS" not in a.scratch_text()
    assert not hasattr(a, "_parent")
    # Mutating the parent AFTER spawn does not touch the children.
    parent_ctx.write_scratch("MORE-PARENT-SECRETS")
    assert "MORE-PARENT-SECRETS" not in a.scratch_text()
    assert "MORE-PARENT-SECRETS" not in b.scratch_text()


def test_collect_results_reports_none_for_unfinished_children():
    mgr = SubagentContextManager(token_counter=_one_per_char)
    mgr.create_subagent_context("task A", subagent_id="A")
    b = mgr.create_subagent_context("task B", subagent_id="B")
    b.set_result("B done")
    assert mgr.collect_results() == {"A": None, "B": "B done"}


def test_duplicate_subagent_id_rejected():
    mgr = SubagentContextManager(token_counter=_one_per_char)
    mgr.create_subagent_context("task", subagent_id="dup")
    with pytest.raises(ValueError):
        mgr.create_subagent_context("task", subagent_id="dup")


# ---------------------------------------------------------------------------
# Empty / minimal context handling
# ---------------------------------------------------------------------------
def test_empty_minimal_context_handled():
    # Minimal: no parent, empty system prompt, empty task.
    ctx = create_subagent_context(None, task="", overflow_policy=OverflowPolicy.REJECT)
    assert ctx.system_prompt == ""
    assert ctx.task == ""
    assert ctx.budget == DEFAULT_BUDGET_TOKENS
    assert ctx.tokens_used() == 0
    assert ctx.tokens_remaining() == DEFAULT_BUDGET_TOKENS
    assert ctx.read_scratch() == []
    assert ctx.result is None

    # Writing empty text is a no-op accepted write.
    res = ctx.write_scratch("")
    assert res.accepted and res.stored_tokens == 0 and res.signal == "ok"
    assert ctx.tokens_used() == 0

    # Manager with no parent still spawns usable minimal children.
    mgr = SubagentContextManager(token_counter=_one_per_char)
    child = mgr.create_subagent_context("")
    assert child.system_prompt == ""
    assert child.tokens_used() == 0
    assert mgr.collect_results() == {child.context_id: None}


def test_invalid_budget_rejected():
    with pytest.raises(ContextBudgetError):
        SubagentContextManager(default_budget=0)
    with pytest.raises(ContextBudgetError):
        create_subagent_context(None, task="x", budget=0)


def test_token_counter_must_return_non_negative_int():
    ctx = create_subagent_context(None, task="", overflow_policy=OverflowPolicy.REJECT)
    ctx._token_counter = lambda _t: -1  # type: ignore[assignment]
    with pytest.raises(ValueError):
        ctx.write_scratch("boom")
