from __future__ import annotations

import math
from datetime import datetime

import pytest

from thomas.marketplace.recommender._types import InteractionType, Rating, Recommendation
from thomas.marketplace.recommender.cold_start import BanditRecommender, ColdStartHandler, HybridWarmupHandler
from thomas.marketplace.recommender.pipeline import A_BTestManager, ExplanationGenerator, RecommendationPipeline


def _rating(user_id: str, item_id: str, score: float = 1.0) -> Rating:
    return Rating(
        user_id=user_id,
        item_id=item_id,
        score=score,
        timestamp=datetime(2026, 1, 1, 0, 0, 0),
        interaction_type=InteractionType.RATE,
    )


def test_pipeline_generate_candidates_tolerates_generator_failure() -> None:
    pipeline = RecommendationPipeline()
    pipeline.register_candidate_generator(
        "ok",
        lambda _user_id, _count: [Recommendation("i1", 0.8)],
    )

    def failing(_user_id: str, _count: int) -> list[Recommendation]:
        raise RuntimeError("boom")

    pipeline.register_candidate_generator("bad", failing)

    candidates = pipeline.generate_candidates("u1", per_generator=5)
    assert candidates["ok"][0].item_id == "i1"
    assert candidates["bad"] == []


def test_pipeline_combine_scores_uses_equal_weights_when_missing() -> None:
    pipeline = RecommendationPipeline()
    combined = pipeline.combine_scores(
        {
            "g1": [Recommendation("item_a", 1.0), Recommendation("item_b", 0.2)],
            "g2": [Recommendation("item_a", 0.4)],
        }
    )
    by_item = {rec.item_id: rec for rec in combined}

    assert by_item["item_a"].score == pytest.approx(0.7)
    assert by_item["item_b"].score == pytest.approx(0.1)
    assert "g1" in by_item["item_a"].explanation
    assert "g2" in by_item["item_a"].explanation


def test_pipeline_uses_custom_ranker_when_set() -> None:
    pipeline = RecommendationPipeline()
    pipeline.register_candidate_generator(
        "base",
        lambda _user_id, _count: [
            Recommendation("i1", 0.9),
            Recommendation("i2", 0.3),
        ],
    )
    pipeline.set_ranker(lambda recs: sorted(recs, key=lambda rec: rec.item_id, reverse=True))

    recommendations = pipeline.recommend("u1", n=2, weights={"base": 1.0})
    assert [rec.item_id for rec in recommendations] == ["i2", "i1"]


def test_explanation_generator_appends_similarity_reason() -> None:
    generator = ExplanationGenerator()
    text = generator.generate_explanation(
        user_id="u1",
        item_id="i1",
        algorithm="ContentBased",
        similarity_reason="genre overlap",
    )
    assert "Matches your preferences" in text
    assert "genre overlap" in text


def test_ab_manager_requires_registered_variants() -> None:
    manager = A_BTestManager()
    with pytest.raises(ValueError):
        manager.select_variant("u1")


def test_ab_manager_tracks_count_and_feedback_average() -> None:
    manager = A_BTestManager()
    manager.register_variant("a", lambda _user_id, n: [Recommendation("i1", 0.8) for _ in range(n)])
    manager.register_variant("b", lambda _user_id, n: [Recommendation("i2", 0.6) for _ in range(n)])

    variant, recs = manager.recommend("user_alpha", n=2)
    manager.record_feedback(variant, 0.5)
    manager.record_feedback(variant, 0.7)
    stats = manager.get_statistics()

    assert len(recs) == 2
    assert stats[variant]["count"] == 1
    assert stats[variant]["total_score"] == pytest.approx(1.2)
    assert stats[variant]["average_score"] == pytest.approx(1.2)


def test_cold_start_random_strategy_never_exceeds_catalog_size() -> None:
    handler = ColdStartHandler()
    handler.add_ratings(
        [
            _rating("u1", "a", 4.0),
            _rating("u2", "b", 5.0),
        ]
    )

    recommendations = handler.new_user_recommendations(n=10, strategy="random")
    assert len(recommendations) == 2
    assert {rec.item_id for rec in recommendations} == {"a", "b"}


def test_bandit_prioritizes_unseen_items_with_infinite_ucb() -> None:
    bandit = BanditRecommender()
    bandit.add_feedback("seen", 0.8)
    bandit.add_feedback("seen", 0.9)

    recommendations = bandit.recommend(["seen", "new"], n=2)

    assert recommendations[0].item_id == "new"
    assert math.isinf(recommendations[0].score)
    assert recommendations[1].item_id == "seen"


def test_hybrid_warmup_neighbors_sorted_by_similarity() -> None:
    handler = HybridWarmupHandler()
    handler.add_item_features("anchor", {"x": 1.0, "y": 1.0})
    handler.add_item_features("near", {"x": 1.0, "y": 0.9})
    handler.add_item_features("far", {"x": -1.0, "y": -1.0})

    neighbors = handler.get_feature_neighbors("anchor", k=2)
    assert [item_id for item_id, _score in neighbors] == ["near"]
    assert all(score > 0 for _item_id, score in neighbors)
