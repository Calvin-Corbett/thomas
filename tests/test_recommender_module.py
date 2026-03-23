from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from thomas.marketplace.recommender._types import InteractionType, Rating, Recommendation
from thomas.marketplace.recommender.pipeline import RecommendationPipeline
from thomas.marketplace.recommender.session_based import SessionBasedRecommender
from thomas.marketplace.recommender.similarity import (
    SimilarityComputer,
    cosine_similarity,
    euclidean_similarity,
    hamming_similarity,
    jaccard_similarity,
    pearson_correlation,
)

BASE_TIME = datetime(2026, 1, 1, 12, 0, 0)


def _rating(user_id: str, item_id: str, minute_offset: int) -> Rating:
    return Rating(
        user_id=user_id,
        item_id=item_id,
        score=1.0,
        timestamp=BASE_TIME + timedelta(minutes=minute_offset),
        interaction_type=InteractionType.VIEW,
    )


def _session(user_id: str, items: list[str]) -> list[Rating]:
    return [_rating(user_id, item_id, idx) for idx, item_id in enumerate(items)]


def test_similarity_metric_helpers_known_values() -> None:
    assert cosine_similarity({"a": 1.0, "b": 0.0}, {"a": 1.0, "b": 0.0}) == pytest.approx(1.0)
    assert pearson_correlation({"a": 1.0, "b": 2.0, "c": 3.0}, {"a": 2.0, "b": 4.0, "c": 6.0}) == pytest.approx(1.0)
    assert jaccard_similarity(set(), set()) == pytest.approx(1.0)
    assert euclidean_similarity({"a": 0.0}, {"a": 3.0}) == pytest.approx(0.25)
    assert hamming_similarity({"x": 1.0, "y": 0.0}, {"x": 1.0, "y": 1.0}) == pytest.approx(0.5)


def test_similarity_computer_cache_is_symmetric_and_reused() -> None:
    computer = SimilarityComputer(metric="cosine")
    left = {"x": 1.0}
    right = {"x": 1.0}

    first = computer.compute("item_a", "item_b", left, right)
    right["x"] = -1.0
    second = computer.compute("item_b", "item_a", right, left)

    assert first == pytest.approx(1.0)
    assert second == pytest.approx(first)
    assert len(computer.cache) == 1


def test_similarity_computer_pairwise_and_top_similar_ordering() -> None:
    entities = {
        "anchor": {"x": 1.0, "y": 1.0},
        "near": {"x": 1.0, "y": 0.9},
        "far": {"x": -1.0, "y": -1.0},
    }
    computer = SimilarityComputer(metric="cosine")

    pairwise = computer.pairwise_similarity(entities)
    assert pairwise[("anchor", "near")] == pytest.approx(pairwise[("near", "anchor")])

    ordered = computer.get_top_similar("anchor", entities, k=2)
    assert [item_id for item_id, _score in ordered] == ["near", "far"]


def test_pipeline_filters_enforce_score_and_diversity() -> None:
    pipeline = RecommendationPipeline()

    def generator(_user_id: str, _count: int) -> list[Recommendation]:
        return [
            Recommendation("i1", 0.90, algorithm="UnitGen"),
            Recommendation("i2", 0.70, algorithm="UnitGen"),
            Recommendation("i3", 0.60, algorithm="UnitGen"),
            Recommendation("i4", 0.55, algorithm="UnitGen"),
        ]

    pipeline.register_candidate_generator("unit", generator)
    pipeline.add_filter(pipeline.filter_by_score_threshold(0.60))
    pipeline.add_filter(
        pipeline.filter_diversity(
            max_recommendations=2,
            item_distance={
                ("i1", "i2"): 0.10,
                ("i1", "i3"): 0.80,
                ("i2", "i3"): 0.80,
            },
            min_diversity=0.30,
        )
    )

    recommendations = pipeline.recommend("user_a", n=5, weights={"unit": 1.0}, per_generator=10)
    assert [rec.item_id for rec in recommendations] == ["i1", "i3"]
    assert all(rec.score >= 0.60 for rec in recommendations)


def test_pipeline_filter_already_seen_excludes_history() -> None:
    pipeline = RecommendationPipeline()
    pipeline.add_ratings([_rating("user_seen", "already_seen", 0)])
    pipeline.register_candidate_generator(
        "unit",
        lambda _user_id, _count: [
            Recommendation("already_seen", 0.9),
            Recommendation("new_item", 0.8),
        ],
    )
    pipeline.add_filter(pipeline.filter_already_seen("user_seen"))

    recommendations = pipeline.recommend("user_seen", n=5, weights={"unit": 1.0})
    assert [rec.item_id for rec in recommendations] == ["new_item"]


def test_markov_recommendations_follow_transition_probabilities() -> None:
    recommender = SessionBasedRecommender(session_timeout_minutes=30)
    recommender.add_ratings(
        [
            _rating("target", "a", 0),
            _rating("target", "b", 1),
            _rating("u1", "b", 0),
            _rating("u1", "c", 1),
            _rating("u2", "b", 0),
            _rating("u2", "c", 1),
            _rating("u3", "b", 0),
            _rating("u3", "d", 1),
        ]
    )

    recommendations = recommender.recommend_from_markov("target", n=2)
    assert [rec.item_id for rec in recommendations] == ["c", "d"]
    assert recommendations[0].score == pytest.approx(2.0 / 3.0)
    assert recommendations[1].score == pytest.approx(1.0 / 3.0)


def test_combined_recommendations_blend_markov_and_cooccurrence() -> None:
    recommender = SessionBasedRecommender(session_timeout_minutes=30)
    recommender.add_ratings(
        [
            _rating("target", "a", 0),
            _rating("target", "b", 1),
            _rating("u1", "a", 0),
            _rating("u1", "c", 1),
            _rating("u2", "a", 0),
            _rating("u2", "c", 1),
            _rating("u3", "b", 0),
            _rating("u3", "d", 1),
        ]
    )

    recommendations = recommender.recommend_combined(
        "target",
        n=3,
        cooccurrence_weight=0.6,
        markov_weight=0.4,
    )
    item_ids = [rec.item_id for rec in recommendations]

    assert item_ids[0] == "d"
    assert "c" in item_ids


def test_find_similar_sessions_returns_sorted_positive_matches() -> None:
    recommender = SessionBasedRecommender(session_timeout_minutes=30)
    recommender.current_session["target"] = _session("target", ["i1", "i2"])
    recommender.sessions = {
        "s_high": _session("u1", ["i1", "i2", "i3"]),
        "s_mid": _session("u2", ["i1", "x"]),
        "s_zero": _session("u3", ["x", "y"]),
    }

    matches = recommender.find_similar_sessions("target", k=5)
    match_ids = [session_id for session_id, _session_rows, _sim in matches]

    assert match_ids == ["s_high", "s_mid"]
    assert matches[0][2] > matches[1][2] > 0.0
