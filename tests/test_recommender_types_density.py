from __future__ import annotations

from datetime import datetime

import pytest

from thomas.marketplace.recommender._exceptions import ColdStartError, InsufficientDataError, RecommenderError
from thomas.marketplace.recommender._types import (
    FeatureVector,
    InteractionType,
    ItemProfile,
    Rating,
    Recommendation,
    RecommenderConfig,
    SimilarityMetric,
    UserProfile,
)


def _rating(user_id: str, item_id: str, score: float) -> Rating:
    return Rating(
        user_id=user_id,
        item_id=item_id,
        score=score,
        timestamp=datetime(2026, 1, 1, 0, 0, 0),
        interaction_type=InteractionType.RATE,
    )


def test_enums_expose_expected_wire_values() -> None:
    assert InteractionType.VIEW.value == "view"
    assert InteractionType.CLICK.value == "click"
    assert SimilarityMetric.COSINE.value == "cosine"
    assert SimilarityMetric.ADJUSTED_COSINE.value == "adjusted_cosine"


def test_rating_rejects_negative_scores() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _rating("u1", "i1", -0.01)


def test_feature_vector_norm_cache_is_invalidated_on_update() -> None:
    vector = FeatureVector(features={"a": 3.0, "b": 4.0})
    assert vector.compute_norm() == pytest.approx(5.0)
    assert vector.norm == pytest.approx(5.0)

    vector.add_feature("c", 12.0)
    assert vector.norm is None
    assert vector.compute_norm() == pytest.approx(13.0)
    assert vector.get_feature("missing", default=9.0) == pytest.approx(9.0)
    assert vector.dimension() == 3


def test_user_profile_helpers_use_all_ratings() -> None:
    profile = UserProfile(user_id="user-1")
    profile.ratings = [_rating("user-1", "a", 4.0), _rating("user-1", "b", 2.0)]

    assert profile.rating_count() == 2
    assert profile.average_rating() == pytest.approx(3.0)
    assert profile.get_rated_items() == {"a": 4.0, "b": 2.0}


def test_item_profile_helpers_use_all_ratings() -> None:
    profile = ItemProfile(item_id="item-1")
    profile.ratings = [_rating("u1", "item-1", 5.0), _rating("u2", "item-1", 3.0)]

    assert profile.rating_count() == 2
    assert profile.average_rating() == pytest.approx(4.0)
    assert profile.popularity() == 2


def test_recommendation_comparison_uses_score_order() -> None:
    low = Recommendation("i-low", 0.1)
    high = Recommendation("i-high", 0.9)

    assert low < high
    assert low <= high
    assert sorted([high, low]) == [low, high]


@pytest.mark.parametrize(
    "field, value, msg",
    [
        ("k", 0, "k must be >= 1"),
        ("min_ratings", -1, "min_ratings must be >= 0"),
        ("latent_factors", 0, "latent_factors must be >= 1"),
        ("learning_rate", 1.0, r"learning_rate must be in \(0, 1\)"),
        ("regularization", -0.1, "regularization must be >= 0"),
        ("iterations", 0, "iterations must be >= 1"),
        ("convergence_threshold", -0.0001, "convergence_threshold must be >= 0"),
    ],
)
def test_recommender_config_validate_rejects_invalid_values(field: str, value: float, msg: str) -> None:
    config = RecommenderConfig()
    setattr(config, field, value)

    with pytest.raises(ValueError, match=msg):
        config.validate()


def test_custom_recommender_exceptions_include_context() -> None:
    cold_start = ColdStartError("user", "u-new", "no history")
    insufficient = InsufficientDataError(minimum=5, actual=2, resource_type="interactions")

    assert isinstance(cold_start, RecommenderError)
    assert "Cold start problem for user 'u-new'" in str(cold_start)
    assert "no history" in str(cold_start)
    assert isinstance(insufficient, RecommenderError)
    assert "need 5, got 2" in str(insufficient)
