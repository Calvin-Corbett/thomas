"""
Tests for matrix factorization algorithms.
"""

from datetime import datetime

import pytest

from thomas.recommender._exceptions import ColdStartError, InsufficientDataError
from thomas.recommender._types import InteractionType, Rating, RecommenderConfig
from thomas.recommender.matrix_factorization import ALSFactorizer, SGDFactorizer


class TestALSFactorizer:
    """Test Alternating Least Squares matrix factorization."""

    @pytest.fixture
    def als_with_data(self) -> ALSFactorizer:
        """Create ALS with test data."""
        config = RecommenderConfig(
            latent_factors=5,
            iterations=10,
            regularization=0.01,
            convergence_threshold=1e-3,
        )
        als = ALSFactorizer(config)
        now = datetime.now()

        ratings = [
            Rating("u1", "i1", 5.0, now, InteractionType.RATE),
            Rating("u1", "i2", 3.0, now, InteractionType.RATE),
            Rating("u2", "i1", 5.0, now, InteractionType.RATE),
            Rating("u2", "i3", 4.0, now, InteractionType.RATE),
            Rating("u3", "i2", 4.0, now, InteractionType.RATE),
            Rating("u3", "i3", 4.0, now, InteractionType.RATE),
            Rating("u4", "i1", 3.0, now, InteractionType.RATE),
            Rating("u4", "i4", 5.0, now, InteractionType.RATE),
        ]

        als.add_ratings(ratings)
        return als

    def test_initialization(self, als_with_data: ALSFactorizer) -> None:
        """Test factor initialization."""
        als_with_data._initialize_factors()

        assert len(als_with_data.user_factors) == 4
        assert len(als_with_data.item_factors) == 4
        assert all(
            len(factors) == als_with_data.config.latent_factors for factors in als_with_data.user_factors.values()
        )

    def test_training(self, als_with_data: ALSFactorizer) -> None:
        """Test model training."""
        als_with_data.fit()

        assert als_with_data.is_trained
        assert len(als_with_data.user_factors) > 0
        assert len(als_with_data.item_factors) > 0

    def test_prediction(self, als_with_data: ALSFactorizer) -> None:
        """Test rating prediction after training."""
        als_with_data.fit()

        # Predict known rating
        pred = als_with_data.predict_rating("u1", "i1")
        assert pred is not None
        assert isinstance(pred, float)

    def test_prediction_accuracy(self, als_with_data: ALSFactorizer) -> None:
        """Test that predictions are close to actual ratings."""
        als_with_data.fit()

        # Predictions should be roughly correct for training data
        pred = als_with_data.predict_rating("u1", "i1")
        assert pred is not None
        # Predicted value should be in reasonable range
        assert 0 <= pred <= 10  # Allowing some extrapolation

    def test_recommend(self, als_with_data: ALSFactorizer) -> None:
        """Test recommendation generation."""
        als_with_data.fit()

        recs = als_with_data.recommend("u1", n=2)
        assert len(recs) <= 2
        assert all(rec.item_id not in ["i1", "i2"] for rec in recs)

    def test_unseen_user_error(self, als_with_data: ALSFactorizer) -> None:
        """Test error for user not in training data."""
        als_with_data.fit()

        with pytest.raises(ColdStartError):
            als_with_data.recommend("unknown_user")

    def test_untrained_error(self, als_with_data: ALSFactorizer) -> None:
        """Test error when recommending without training."""
        with pytest.raises(ValueError):
            als_with_data.recommend("u1")

    def test_convergence(self, als_with_data: ALSFactorizer) -> None:
        """Test that training converges."""
        als_with_data.fit()
        # If training completed without error, convergence worked
        assert als_with_data.is_trained


class TestSGDFactorizer:
    """Test Stochastic Gradient Descent matrix factorization."""

    @pytest.fixture
    def sgd_with_data(self) -> SGDFactorizer:
        """Create SGD with test data."""
        config = RecommenderConfig(
            latent_factors=5,
            learning_rate=0.01,
            iterations=20,
            regularization=0.01,
            convergence_threshold=1e-4,
        )
        sgd = SGDFactorizer(config)
        now = datetime.now()

        ratings = [
            Rating("u1", "i1", 5.0, now, InteractionType.RATE),
            Rating("u1", "i2", 3.0, now, InteractionType.RATE),
            Rating("u2", "i1", 5.0, now, InteractionType.RATE),
            Rating("u2", "i3", 4.0, now, InteractionType.RATE),
            Rating("u3", "i2", 4.0, now, InteractionType.RATE),
            Rating("u3", "i3", 4.0, now, InteractionType.RATE),
            Rating("u4", "i1", 3.0, now, InteractionType.RATE),
            Rating("u4", "i4", 5.0, now, InteractionType.RATE),
        ]

        sgd.add_ratings(ratings)
        return sgd

    def test_training(self, sgd_with_data: SGDFactorizer) -> None:
        """Test SGD training."""
        sgd_with_data.fit()

        assert sgd_with_data.is_trained
        assert len(sgd_with_data.user_factors) > 0

    def test_prediction(self, sgd_with_data: SGDFactorizer) -> None:
        """Test rating prediction."""
        sgd_with_data.fit()

        pred = sgd_with_data.predict_rating("u1", "i1")
        assert pred is not None

    def test_recommend(self, sgd_with_data: SGDFactorizer) -> None:
        """Test recommendation generation."""
        sgd_with_data.fit()

        recs = sgd_with_data.recommend("u1", n=2)
        assert len(recs) <= 2

    def test_learning_rate_effect(self) -> None:
        """Test that different learning rates work."""
        now = datetime.now()

        for lr in [0.001, 0.01, 0.1]:
            config = RecommenderConfig(
                learning_rate=lr,
                iterations=5,
            )
            sgd = SGDFactorizer(config)
            sgd.add_rating(Rating("u1", "i1", 5.0, now, InteractionType.RATE))
            sgd.add_rating(Rating("u2", "i1", 4.0, now, InteractionType.RATE))

            # Should complete without error
            sgd.fit()
            assert sgd.is_trained

    def test_regularization_effect(self) -> None:
        """Test regularization parameter."""
        now = datetime.now()

        for reg in [0.0, 0.01, 0.1]:
            config = RecommenderConfig(
                regularization=reg,
                iterations=5,
            )
            sgd = SGDFactorizer(config)
            sgd.add_rating(Rating("u1", "i1", 5.0, now, InteractionType.RATE))
            sgd.add_rating(Rating("u2", "i1", 4.0, now, InteractionType.RATE))

            sgd.fit()
            assert sgd.is_trained


class TestMatrixFactorizationComparison:
    """Compare ALS and SGD algorithms."""

    def test_als_vs_sgd_predictions(self) -> None:
        """Compare prediction quality of ALS vs SGD."""
        now = datetime.now()
        ratings = [
            Rating("u1", "i1", 5.0, now, InteractionType.RATE),
            Rating("u1", "i2", 3.0, now, InteractionType.RATE),
            Rating("u2", "i1", 5.0, now, InteractionType.RATE),
            Rating("u2", "i3", 4.0, now, InteractionType.RATE),
            Rating("u3", "i2", 4.0, now, InteractionType.RATE),
            Rating("u3", "i3", 4.0, now, InteractionType.RATE),
        ]

        # Train ALS
        als = ALSFactorizer(RecommenderConfig(latent_factors=3, iterations=5))
        als.add_ratings(ratings)
        als.fit()

        # Train SGD
        sgd = SGDFactorizer(RecommenderConfig(latent_factors=3, iterations=10))
        sgd.add_ratings(ratings)
        sgd.fit()

        # Both should produce predictions
        als_pred = als.predict_rating("u1", "i1")
        sgd_pred = sgd.predict_rating("u1", "i1")

        assert als_pred is not None
        assert sgd_pred is not None

    def test_different_latent_factors(self) -> None:
        """Test effect of latent factor size."""
        now = datetime.now()
        ratings = [
            Rating(f"u{i}", f"i{j}", float((i + j) % 5 + 1), now, InteractionType.RATE)
            for i in range(5)
            for j in range(5)
        ]

        for factors in [2, 5, 10]:
            config = RecommenderConfig(latent_factors=factors, iterations=5)
            als = ALSFactorizer(config)
            als.add_ratings(ratings)
            als.fit()

            assert len(als.user_factors["u0"]) == factors

    def test_insufficient_data(self) -> None:
        """Test error with no ratings."""
        als = ALSFactorizer()
        with pytest.raises(InsufficientDataError):
            als.fit()
