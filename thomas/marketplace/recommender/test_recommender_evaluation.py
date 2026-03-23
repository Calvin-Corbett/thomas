"""
Tests for evaluation metrics.
"""

import math

import pytest

from thomas.marketplace.recommender.evaluation import (
    CoverageMetrics,
    PrecisionRecall,
    RankingMetrics,
    RatingMetrics,
    RecommenderEvaluator,
)


class TestPrecisionRecall:
    """Test precision and recall metrics."""

    def test_precision_at_k(self) -> None:
        """Test Precision@K computation."""
        recommended = ["i1", "i2", "i3", "i4"]
        relevant = {"i1", "i3"}

        p5 = PrecisionRecall.precision_at_k(recommended, relevant, 5)
        assert p5 == pytest.approx(0.5, rel=1e-5)  # 2 out of 4

        p2 = PrecisionRecall.precision_at_k(recommended, relevant, 2)
        assert p2 == 0.5  # 1 out of 2

    def test_recall_at_k(self) -> None:
        """Test Recall@K computation."""
        recommended = ["i1", "i2", "i3", "i4", "i5"]
        relevant = {"i1", "i3", "i5", "i6"}

        r5 = PrecisionRecall.recall_at_k(recommended, relevant, 5)
        assert r5 == pytest.approx(0.75, rel=1e-5)  # 3 out of 4 relevant

    def test_f1_at_k(self) -> None:
        """Test F1@K metric."""
        recommended = ["i1", "i2", "i3"]
        relevant = {"i1", "i2"}

        f1 = PrecisionRecall.f1_at_k(recommended, relevant, 3)
        # Precision = 2/3, Recall = 2/2 = 1.0
        # F1 = 2 * (2/3 * 1.0) / (2/3 + 1.0) = 0.8
        assert f1 == pytest.approx(0.8, rel=1e-5)

    def test_avg_precision(self) -> None:
        """Test Average Precision computation."""
        recommended = ["i1", "i2", "i3", "i4"]
        relevant = {"i1", "i3"}

        ap = PrecisionRecall.avg_precision(recommended, relevant)
        # At position 1: 1/1, at position 3: 2/3
        # AP = (1/1 + 2/3) / 2 = 0.833...
        assert ap == pytest.approx((1.0 + 2 / 3) / 2, rel=1e-5)

    def test_hit_rate(self) -> None:
        """Test hit rate metric."""
        recommended = ["i1", "i2", "i3"]
        relevant = {"i4", "i5"}

        hit = PrecisionRecall.hit_rate(recommended, relevant, 3)
        assert hit == 0.0

        recommended2 = ["i1", "i2", "i4"]
        hit2 = PrecisionRecall.hit_rate(recommended2, relevant, 3)
        assert hit2 == 1.0

    def test_empty_inputs(self) -> None:
        """Test metrics with empty inputs."""
        recommended = []
        relevant = set()

        p = PrecisionRecall.precision_at_k(recommended, relevant, 5)
        r = PrecisionRecall.recall_at_k(recommended, relevant, 5)

        assert p == 0.0
        assert r == 0.0


class TestRankingMetrics:
    """Test ranking-based metrics."""

    def test_ndcg_perfect_ranking(self) -> None:
        """Test NDCG with perfect ranking."""
        recommended = ["i1", "i2", "i3"]
        relevant = {"i1", "i2", "i3"}

        ndcg = RankingMetrics.ndcg(recommended, relevant, 3)
        assert ndcg == pytest.approx(1.0, rel=1e-5)

    def test_ndcg_worst_ranking(self) -> None:
        """Test NDCG with worst ranking."""
        recommended = ["i1", "i2", "i3"]
        relevant = set()

        ndcg = RankingMetrics.ndcg(recommended, relevant, 3)
        assert ndcg == 0.0

    def test_ndcg_partial_ranking(self) -> None:
        """Test NDCG with partial relevance."""
        recommended = ["i1", "i2", "i3", "i4"]
        relevant = {"i1", "i3"}

        ndcg = RankingMetrics.ndcg(recommended, relevant, 4)
        # DCG = 1/log2(2) + 1/log2(4) = 1 + 0.5 = 1.5
        # IDCG = 1/log2(2) + 1/log2(3) = 1 + 0.63... = 1.63...
        assert 0 < ndcg < 1

    def test_map_at_k(self) -> None:
        """Test Mean Average Precision."""
        recommendations = [
            ["i1", "i2", "i3"],
            ["i4", "i5", "i6"],
        ]
        relevant_sets = [
            {"i1", "i3"},
            {"i4", "i5"},
        ]

        map_score = RankingMetrics.map_at_k(recommendations, relevant_sets, 3)
        assert 0 <= map_score <= 1

    def test_mean_ndcg(self) -> None:
        """Test mean NDCG across queries."""
        recommendations = [
            ["i1", "i2", "i3"],
            ["i4", "i5", "i6"],
        ]
        relevant_sets = [
            {"i1", "i2", "i3"},
            {"i4", "i5", "i6"},
        ]

        mean_ndcg = RankingMetrics.mean_ndcg(recommendations, relevant_sets, 3)
        assert mean_ndcg == pytest.approx(1.0, rel=1e-5)


class TestRatingMetrics:
    """Test rating prediction metrics."""

    def test_rmse(self) -> None:
        """Test RMSE computation."""
        actual = [5.0, 4.0, 3.0]
        predicted = [5.0, 4.0, 3.0]

        rmse = RatingMetrics.rmse(actual, predicted)
        assert rmse == pytest.approx(0.0, rel=1e-5)

    def test_rmse_with_errors(self) -> None:
        """Test RMSE with prediction errors."""
        actual = [5.0, 4.0, 3.0]
        predicted = [4.0, 4.0, 2.0]

        rmse = RatingMetrics.rmse(actual, predicted)
        # MSE = (1^2 + 0^2 + 1^2) / 3 = 2/3
        # RMSE = sqrt(2/3) = 0.816...
        assert rmse == pytest.approx(math.sqrt(2 / 3), rel=1e-5)

    def test_mae(self) -> None:
        """Test Mean Absolute Error."""
        actual = [5.0, 4.0, 3.0]
        predicted = [5.0, 4.0, 3.0]

        mae = RatingMetrics.mae(actual, predicted)
        assert mae == pytest.approx(0.0, rel=1e-5)

    def test_mae_with_errors(self) -> None:
        """Test MAE with prediction errors."""
        actual = [5.0, 4.0, 3.0]
        predicted = [4.0, 4.0, 2.0]

        mae = RatingMetrics.mae(actual, predicted)
        # MAE = (1 + 0 + 1) / 3 = 2/3
        assert mae == pytest.approx(2 / 3, rel=1e-5)

    def test_mape(self) -> None:
        """Test Mean Absolute Percentage Error."""
        actual = [4.0, 5.0]
        predicted = [4.0, 5.0]

        mape = RatingMetrics.mape(actual, predicted)
        assert mape == pytest.approx(0.0, rel=1e-5)

    def test_mape_with_errors(self) -> None:
        """Test MAPE with errors."""
        actual = [4.0, 5.0]
        predicted = [2.0, 5.0]

        mape = RatingMetrics.mape(actual, predicted)
        # APE1 = |4-2|/4 = 0.5, APE2 = |5-5|/5 = 0
        # MAPE = (0.5 + 0) / 2 = 0.25
        assert mape == pytest.approx(0.25, rel=1e-5)


class TestCoverageMetrics:
    """Test coverage and diversity metrics."""

    def test_catalog_coverage(self) -> None:
        """Test catalog coverage metric."""
        recommendations = [
            ["i1", "i2", "i3"],
            ["i2", "i4", "i5"],
        ]
        all_items = {"i1", "i2", "i3", "i4", "i5", "i6"}

        coverage = CoverageMetrics.catalog_coverage(recommendations, all_items)
        # 5 items recommended out of 6 total
        assert coverage == pytest.approx(5 / 6, rel=1e-5)

    def test_coverage_100_percent(self) -> None:
        """Test full coverage."""
        recommendations = [
            ["i1", "i2"],
            ["i3", "i4"],
        ]
        all_items = {"i1", "i2", "i3", "i4"}

        coverage = CoverageMetrics.catalog_coverage(recommendations, all_items)
        assert coverage == pytest.approx(1.0, rel=1e-5)

    def test_novelty(self) -> None:
        """Test novelty metric."""
        recommendations = [["i1", "i2"]]
        popularity = {"i1": 100, "i2": 1}  # i2 is novel (less popular)

        novelty = CoverageMetrics.novelty(recommendations, popularity)
        # Novelty for i1: 1 - 100/100 = 0
        # Novelty for i2: 1 - 1/100 = 0.99
        # Average: 0.495
        assert novelty == pytest.approx(0.495, rel=1e-5)

    def test_diversity(self) -> None:
        """Test diversity metric."""
        recommendations = ["i1", "i2", "i3"]
        similarity = {
            ("i1", "i2"): 0.5,  # 50% similar
            ("i1", "i3"): 0.2,  # 20% similar
            ("i2", "i3"): 0.3,  # 30% similar
        }

        diversity = CoverageMetrics.diversity(recommendations, similarity)
        # Distances: 0.5, 0.8, 0.7
        # Average: (0.5 + 0.8 + 0.7) / 3 = 0.667
        assert diversity == pytest.approx(2.0 / 3, rel=1e-5)


class TestRecommenderEvaluator:
    """Test comprehensive evaluator."""

    def test_train_test_split(self) -> None:
        """Test train/test split."""
        from datetime import datetime

        from thomas.marketplace.recommender._types import InteractionType, Rating

        ratings = [
            Rating(f"u{i}", f"i{j}", float(i + j), datetime.now(), InteractionType.RATE)
            for i in range(5)
            for j in range(5)
        ]

        evaluator = RecommenderEvaluator()
        train, test = evaluator.train_test_split(ratings, test_size=0.2)

        assert len(train) + len(test) == len(ratings)
        assert len(test) == pytest.approx(5, abs=1)
        assert len(train) == pytest.approx(20, abs=1)

    def test_evaluate_ranking(self) -> None:
        """Test ranking evaluation."""
        from thomas.marketplace.recommender._types import Recommendation

        evaluator = RecommenderEvaluator()

        recs = [
            Recommendation("i1", 0.9),
            Recommendation("i2", 0.8),
            Recommendation("i3", 0.7),
        ]
        evaluator.add_recommendations(recs)

        metrics = evaluator.evaluate_ranking(k=10)
        assert "precision@k" in metrics
        assert "recall@k" in metrics
        assert "ndcg@k" in metrics
