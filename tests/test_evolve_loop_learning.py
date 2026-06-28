"""Tests for the evolve loop's cross-iteration learning layer."""

from __future__ import annotations

from thomas.forge.anvil.evolve_loop_learning import rerank_by_history, summarize_history
from thomas.forge.anvil.evolve_planner import EvolveGoal


def _goal(goal_id: str, category: str = "refactor") -> EvolveGoal:
    return EvolveGoal(
        id=goal_id,
        title=f"goal {goal_id}",
        category=category,
        rationale="because",
        goal_prompt="do the thing",
        target_paths=["thomas/x.py"],
        risk_tier="low",
        leverage=1.0,
    )


def _hist(goal_id, category, action, reason="", promoted=False):
    return {
        "goal_id": goal_id,
        "category": category,
        "decision": {"action": action, "reason": reason},
        "promoted": promoted,
    }


def test_summarize_counts_only_real_failures():
    history = [
        _hist("g1", "refactor", "reject", "verification failed"),
        _hist("g1", "refactor", "reject", "verification failed"),
        _hist("g2", "tests", "reject", "no changes produced"),
        _hist("g3", "security", "promote", "promoting", promoted=True),
        _hist("g4", "refactor", "approve", "held for approval"),
    ]
    stats = summarize_history(history)
    assert stats.fails_by_goal["g1"] == 2
    assert stats.fails_by_goal["g2"] == 0
    assert stats.fails_by_category["refactor"] == 2
    assert stats.promotions_by_category["security"] == 1
    assert stats.category_score("security") == 1
    assert stats.category_score("refactor") == -2


def test_rerank_drops_tarpit_goals():
    history = [
        _hist("g1", "refactor", "reject", "verification failed"),
        _hist("g1", "refactor", "reject", "verification failed"),
    ]
    goals = [_goal("g1"), _goal("g2")]
    kept, dropped = rerank_by_history(goals, history)
    assert [g.id for g in dropped] == ["g1"]
    assert [g.id for g in kept] == ["g2"]


def test_rerank_prefers_categories_with_track_record():
    history = [
        _hist("old1", "security", "promote", "promoting", promoted=True),
        _hist("old2", "refactor", "reject", "verification failed"),
        _hist("old3", "refactor", "reject", "verification failed"),
    ]
    goals = [_goal("r1", "refactor"), _goal("s1", "security"), _goal("r2", "refactor")]
    kept, dropped = rerank_by_history(goals, history)
    assert dropped == []
    assert kept[0].id == "s1"
    assert [g.id for g in kept if g.category == "refactor"] == ["r1", "r2"]


def test_rerank_no_history_is_identity():
    goals = [_goal("a"), _goal("b"), _goal("c")]
    kept, dropped = rerank_by_history(goals, [])
    assert dropped == []
    assert [g.id for g in kept] == ["a", "b", "c"]


def test_rerank_threshold_is_configurable():
    history = [_hist("g1", "refactor", "reject", "verification failed")]
    goals = [_goal("g1")]

    kept, dropped = rerank_by_history(goals, history)
    assert dropped == []
    assert [g.id for g in kept] == ["g1"]

    kept, dropped = rerank_by_history(goals, history, fail_threshold=1)
    assert kept == []
    assert [g.id for g in dropped] == ["g1"]
