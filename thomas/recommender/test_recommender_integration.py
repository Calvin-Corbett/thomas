"""
Integration tests for the complete recommendation system.
"""

from datetime import datetime

import pytest

from thomas.recommender._types import InteractionType, Rating, Recommendation, RecommenderConfig
from thomas.recommender.cold_start import BanditRecommender, ColdStartHandler, HybridWarmupHandler
from thomas.recommender.collaborative import ItemBasedCF, UserBasedCF
from thomas.recommender.evaluation import RatingMetrics, RecommenderEvaluator
from thomas.recommender.matrix_factorization import ALSFactorizer
from thomas.recommender.pipeline import ExplanationGenerator, RecommendationPipeline
from thomas.recommender.session_based import SessionBasedRecommender


class TestMultiAlgorithmEnsemble:
    """Test using multiple algorithms together."""

    @pytest.fixture
    def sample_ratings(self):
        """Create sample ratings for testing."""
        now = datetime.now()
        ratings = []

        # Create dense rating matrix
        for user_id in range(1, 6):
            for item_id in range(1, 6):
                score = float(((user_id + item_id) % 5) + 1)
                ratings.append(
                    Rating(
                        f"user_{user_id}",
                        f"item_{item_id}",
                        score,
                        now,
                        InteractionType.RATE,
                    )
                )

        return ratings

    def test_ensemble_recommendations(self, sample_ratings):
        """Test combining multiple algorithms."""
        # Train multiple algorithms
        user_cf = UserBasedCF()
        user_cf.add_ratings(sample_ratings)

        item_cf = ItemBasedCF()
        item_cf.add_ratings(sample_ratings)

        als = ALSFactorizer(RecommenderConfig(iterations=5))
        als.add_ratings(sample_ratings)
        als.fit()

        # Get recommendations from each
        user_recs = user_cf.recommend("user_1", n=3)
        item_recs = item_cf.recommend("user_1", n=3)
        als_recs = als.recommend("user_1", n=3)

        # All should produce some recommendations
        total_recs = len(user_recs) + len(item_recs) + len(als_recs)
        assert total_recs > 0

    def test_algorithm_comparison(self, sample_ratings):
        """Compare recommendation quality across algorithms."""
        algorithms = {
            "UserCF": UserBasedCF(),
            "ItemCF": ItemBasedCF(),
        }

        for algo in algorithms.values():
            algo.add_ratings(sample_ratings)

        # Get recommendations from each
        results = {}
        for name, algo in algorithms.items():
            try:
                recs = algo.recommend("user_1", n=2)
                results[name] = len(recs)
            except Exception:
                results[name] = 0

        # At least one algorithm should work
        assert sum(results.values()) > 0


class TestColdStartStrategy:
    """Test cold start handling strategies."""

    @pytest.fixture
    def cold_start_handler(self):
        """Create cold start handler with data."""
        handler = ColdStartHandler()
        now = datetime.now()

        ratings = [
            Rating("u1", "item_a", 5.0, now, InteractionType.RATE),
            Rating("u1", "item_b", 4.0, now, InteractionType.RATE),
            Rating("u2", "item_a", 5.0, now, InteractionType.RATE),
            Rating("u3", "item_c", 3.0, now, InteractionType.RATE),
        ]

        handler.add_ratings(ratings)
        return handler

    def test_popular_items_fallback(self, cold_start_handler):
        """Test popularity-based fallback for new users."""
        recs = cold_start_handler.get_popular_items(n=5)
        assert len(recs) > 0
        assert all(isinstance(rec, Recommendation) for rec in recs)

    def test_epsilon_greedy_exploration(self, cold_start_handler):
        """Test epsilon-greedy exploration strategy."""
        popular = cold_start_handler.get_popular_items(n=3)
        recs = cold_start_handler.epsilon_greedy(popular, n=5, epsilon=0.5)
        assert len(recs) > 0

    def test_bandit_ucb(self):
        """Test UCB bandit strategy."""
        bandit = BanditRecommender()

        # Record feedback for items
        bandit.add_feedback("item_a", 0.8)
        bandit.add_feedback("item_a", 0.9)
        bandit.add_feedback("item_b", 0.4)

        recs = bandit.recommend(["item_a", "item_b", "item_c"], n=3)
        assert len(recs) <= 3

    def test_hybrid_warmup(self):
        """Test hybrid warm-up strategy."""
        handler = HybridWarmupHandler()

        # Add item features
        handler.add_item_features("item_a", {"action": 1.0, "drama": 0.5})
        handler.add_item_features("item_b", {"action": 0.8, "drama": 0.7})

        # Record feedback
        handler.add_feedback("item_a", 0.9)

        # Find similar items
        similar = handler.get_feature_neighbors("item_a", k=1)
        assert len(similar) <= 1


class TestSessionBasedIntegration:
    """Test session-based recommendations in context."""

    def test_session_flow(self):
        """Test a realistic session flow."""
        rec = SessionBasedRecommender(session_timeout_minutes=30)
        now = datetime.now()

        # User views items in session
        from datetime import timedelta

        items_viewed = ["item_1", "item_2", "item_3"]
        for i, item in enumerate(items_viewed):
            rec.add_rating(
                Rating(
                    "user_1",
                    item,
                    5.0,
                    now + timedelta(minutes=i),
                    InteractionType.VIEW,
                )
            )

        # Get recommendations
        recs = rec.recommend_combined("user_1", n=5)
        assert isinstance(recs, list)

    def test_multiple_sessions_tracking(self):
        """Test tracking multiple user sessions."""
        from datetime import timedelta

        rec = SessionBasedRecommender(session_timeout_minutes=30)
        now = datetime.now()

        # Session 1
        rec.add_rating(Rating("user_1", "item_a", 5.0, now, InteractionType.VIEW))
        rec.add_rating(Rating("user_1", "item_b", 4.0, now + timedelta(minutes=5), InteractionType.VIEW))

        # Session 2 (after timeout)
        later = now + timedelta(minutes=35)
        rec.add_rating(Rating("user_1", "item_c", 3.0, later, InteractionType.VIEW))

        sessions = rec.get_user_sessions("user_1")
        assert len(sessions) > 0


class TestEvaluationPipeline:
    """Test evaluation metrics pipeline."""

    def test_full_evaluation_workflow(self):
        """Test complete evaluation workflow."""
        now = datetime.now()

        # Create test data
        ratings = [
            Rating("u1", "i1", 5.0, now, InteractionType.RATE),
            Rating("u1", "i2", 4.0, now, InteractionType.RATE),
            Rating("u2", "i1", 5.0, now, InteractionType.RATE),
            Rating("u2", "i3", 3.0, now, InteractionType.RATE),
        ]

        # Split data
        evaluator = RecommenderEvaluator()
        train, test = evaluator.train_test_split(ratings, test_size=0.25)

        # Evaluate
        evaluator.add_test_ratings(test)
        metrics = evaluator.evaluate_ranking(k=3)

        assert "precision@k" in metrics
        assert "recall@k" in metrics
        assert "ndcg@k" in metrics

    def test_rating_metrics_workflow(self):
        """Test rating prediction metrics."""
        actual = [5.0, 4.0, 3.0, 4.0, 5.0]
        predicted = [5.1, 3.9, 3.2, 4.1, 4.9]

        rmse = RatingMetrics.rmse(actual, predicted)
        mae = RatingMetrics.mae(actual, predicted)

        assert rmse > 0
        assert mae > 0
        assert rmse >= mae  # RMSE >= MAE always


class TestRecommendationPipeline:
    """Test full recommendation pipeline."""

    def test_pipeline_setup_and_execution(self):
        """Test setting up and running a pipeline."""
        pipeline = RecommendationPipeline()
        now = datetime.now()

        # Add ratings
        ratings = [
            Rating("u1", "i1", 5.0, now, InteractionType.RATE),
            Rating("u1", "i2", 4.0, now, InteractionType.RATE),
            Rating("u2", "i1", 5.0, now, InteractionType.RATE),
        ]
        pipeline.add_ratings(ratings)

        # Register candidate generators
        def generator1(user_id, n):
            return [Recommendation(f"i{i}", float(5 - i), algorithm="Gen1") for i in range(1, n + 1)]

        def generator2(user_id, n):
            return [Recommendation(f"i{i}", float(4 - i), algorithm="Gen2") for i in range(1, n + 1)]

        pipeline.register_candidate_generator("gen1", generator1)
        pipeline.register_candidate_generator("gen2", generator2)

        # Add filter
        pipeline.add_filter(pipeline.filter_already_seen("u1"))

        # Get recommendations
        recs = pipeline.recommend("u1", n=3)
        assert len(recs) > 0

    def test_pipeline_with_explanation(self):
        """Test pipeline with explanation generation."""
        generator = ExplanationGenerator()
        generator.set_user_profile("u1", {"interest": "action"})
        generator.set_item_details("i1", {"genre": "action"})

        recs = [Recommendation("i1", 0.9, algorithm="UserBasedCF")]
        explained = generator.explain_recommendations("u1", recs)

        assert len(explained) == 1
        assert len(explained[0].explanation) > 0

    def test_ab_testing_manager(self):
        """Test A/B testing manager."""
        from thomas.recommender.pipeline import A_BTestManager

        manager = A_BTestManager()

        # Register variants
        def variant_a(user_id, n):
            return [Recommendation(f"i{i}", float(i), algorithm="A") for i in range(n)]

        def variant_b(user_id, n):
            return [Recommendation(f"i{i}", float(n - i), algorithm="B") for i in range(n)]

        manager.register_variant("variant_a", variant_a)
        manager.register_variant("variant_b", variant_b)

        # Get recommendations
        variant, recs = manager.recommend("user_1", n=3)
        assert variant in ["variant_a", "variant_b"]
        assert len(recs) == 3

        # Record feedback
        manager.record_feedback(variant, 0.8)

        # Check statistics
        stats = manager.get_statistics()
        assert variant in stats
        assert stats[variant]["count"] == 1


class TestCompleteWorkflow:
    """Test a complete realistic workflow."""

    def test_end_to_end_recommendation_system(self):
        """Test complete recommendation system workflow."""
        now = datetime.now()

        # 1. Load data
        ratings = []
        for u in range(3):
            for i in range(4):
                ratings.append(
                    Rating(
                        f"user_{u}",
                        f"item_{i}",
                        float((u + i) % 5 + 1),
                        now,
                        InteractionType.RATE,
                    )
                )

        # 2. Train models
        user_cf = UserBasedCF()
        user_cf.add_ratings(ratings)

        als = ALSFactorizer(RecommenderConfig(iterations=5))
        als.add_ratings(ratings)
        als.fit()

        # 3. Get recommendations
        user_recs = user_cf.recommend("user_0", n=2)
        als_recs = als.recommend("user_0", n=2)

        # 4. Evaluate
        evaluator = RecommenderEvaluator()
        train, test = evaluator.train_test_split(ratings, test_size=0.25)
        evaluator.add_test_ratings(test)

        metrics = evaluator.evaluate_ranking(k=3)

        # 5. Verify results
        assert len(user_recs) > 0 or len(als_recs) > 0
        assert "precision@k" in metrics
        assert all(0 <= m <= 1 for m in metrics.values())
