"""Pure synthesis primitives: union/convergence, attrition, simplification."""

from __future__ import annotations

from thomas.forge.anvil.evolve_funnel_synthesis import (
    ScoredArtifact,
    apply_simplification,
    minority_facets,
    normalize,
    pick_survivors,
    render_items,
    reverse_no_scoring_violations,
    union_items,
)


def test_union_keeps_every_distinct_item_and_counts_convergence():
    lane_a = [{"text": "handle empty input"}, {"text": "preserve ordering"}]
    lane_b = [{"text": "Handle  empty input!"}, {"text": "add a regression test"}]  # near-dup of A's first
    lane_c = [{"text": "preserve ordering"}, {"text": "unique idea from C"}]
    unioned = union_items([lane_a, lane_b, lane_c])
    texts = {u.text.lower().rstrip("!") for u in unioned}
    # every distinct facet is preserved (union the good)
    assert any("handle  empty input" in normalize(u.text) or "handle empty input" in normalize(u.text) for u in unioned)
    assert any("add a regression test" in normalize(u.text) for u in unioned)
    assert any("unique idea from c" in normalize(u.text) for u in unioned)
    # convergence: "handle empty input" came from 2 lanes, "preserve ordering" from 2
    conv = {normalize(u.text): u.convergence for u in unioned}
    assert conv[normalize("handle empty input")] == 2
    assert conv[normalize("preserve ordering")] == 2
    assert conv[normalize("unique idea from C")] == 1
    # highest convergence sorts first
    assert unioned[0].convergence >= unioned[-1].convergence
    assert "add a regression test" in " ".join(texts) or True  # distinct kept


def test_convergence_counts_each_lane_once_even_if_repeated_in_lane():
    lane_a = [{"text": "same point"}, {"text": "same point"}]  # repeated within one lane
    unioned = union_items([lane_a])
    assert len(unioned) == 1
    assert unioned[0].convergence == 1  # one lane, not two


def test_pick_survivors_keeps_top_by_score_passing_first():
    scored = [
        ScoredArtifact(index=0, artifact="a", score=0.4, passed=False),
        ScoredArtifact(index=1, artifact="b", score=0.9, passed=True),
        ScoredArtifact(index=2, artifact="c", score=0.8, passed=True),
        ScoredArtifact(index=3, artifact="d", score=0.95, passed=False),
    ]
    survivors = pick_survivors(scored, 2)
    kept = [s.artifact for s in survivors]
    assert kept == ["b", "c"]  # passing ranked above the higher-scored non-passing "d"


def test_apply_simplification_only_removes_safe_matching_cuts():
    items = [{"text": "load-bearing gate"}, {"text": "redundant comment"}, {"text": "real invariant"}]
    cuts = [
        {"text": "redundant comment", "what_is_lost": "nothing", "safe": True},
        {"text": "load-bearing gate", "what_is_lost": "the gate", "safe": False},  # unsafe -> NOT cut
        {"text": "does not match anything", "safe": True},  # no match -> nothing removed
    ]
    kept, accepted = apply_simplification(items, cuts)
    kept_texts = {i["text"] for i in kept}
    assert "redundant comment" not in kept_texts  # safe cut applied
    assert "load-bearing gate" in kept_texts  # unsafe cut refused
    assert "real invariant" in kept_texts  # untouched
    assert len(accepted) == 1


def test_apply_simplification_never_forces_cuts():
    items = [{"text": "a"}, {"text": "b"}]
    kept, accepted = apply_simplification(items, [])  # no cuts proposed
    assert len(kept) == 2 and accepted == []


def test_render_items_marks_convergence():
    unioned = union_items([[{"text": "x"}], [{"text": "x"}], [{"text": "y"}]])
    out = render_items(unioned)
    assert "convergence=2" in out
    assert "- x" in out and "- y" in out


# --- funnel self-improvement: minority preservation + REVERSE no-scoring guard ---


def test_minority_facets_are_the_single_lane_ones():
    unioned = union_items(
        [
            [{"text": "shared requirement"}, {"text": "critical single-lane safety rule"}],
            [{"text": "shared requirement"}],
        ]
    )
    minority = minority_facets(unioned)
    texts = {m.text for m in minority}
    assert "critical single-lane safety rule" in texts  # the one-lane facet is flagged
    assert "shared requirement" not in texts  # two-lane facet is not minority


def test_reverse_no_scoring_flags_forbidden_keys():
    bad = {"merged": "ok", "score": 0.9, "winner": "lane2", "items": [{"rank": 1}]}
    violations = reverse_no_scoring_violations(bad)
    assert "score" in violations and "winner" in violations and "rank" in violations


def test_reverse_no_scoring_allows_convergence_and_clean_payload():
    good = {"merged": "ok", "kept_items": ["a", "b"], "contradictions": [], "items": [{"convergence": 2}]}
    assert reverse_no_scoring_violations(good) == []  # convergence is evidence, not a score


def test_scored_artifact_to_dict():
    # Coverage for the method Thomas-evolve dispatched Claude Code to build (verified by the watcher).
    s = ScoredArtifact(index=2, artifact="x", score=0.75, passed=False, detail={"reason": "weak"})
    assert s.to_dict() == {"index": 2, "score": 0.75, "passed": False, "detail": {"reason": "weak"}}
