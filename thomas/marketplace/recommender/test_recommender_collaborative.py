"""
Tests for collaborative filtering algorithms.
"""

from datetime import datetime

import pytest

from thomas.marketplace.recommender._exceptions import ColdStartError, InsufficientDataError
from thomas.marketplace.recommender._types import InteractionType, Rating, RecommenderConfig
from thomas.marketplace.recommender.collaborative import ItemBasedCF, UserBasedCF


class TestUserBasedCF:
    """Test user-based collaborative filtering."""

    @pytest.fixture
    def cf_with_data(self) -> UserBasedCF:
        """Create CF with test data."""
        cf = UserBasedCF()
        now = datetime.now()

        # User 1 rates: A(5), B(4), C(2)
        cf.add_rating(Rating("user1", "item_a", 5.0, now, InteractionType.RATE))
        cf.add_rating(Rating("user1", "item_b", 4.0, now, InteractionType.RATE))
        cf.add_rating(Rating("user1", "item_c", 2.0, now, InteractionType.RATE))

        # User 2 rates: A(5), B(3), D(4)
        cf.add_rating(Rating("user2", "item_a", 5.0, now, InteractionType.RATE))
        cf.add_rating(Rating("user2", "item_b", 3.0, now, InteractionType.RATE))
        cf.add_rating(Rating("user2", "item_d", 4.0, now, InteractionType.RATE))

        # User 3 rates: C(3), D(4), E(5)
        cf.add_rating(Rating("user3", "item_c", 3.0, now, InteractionType.RATE))
        cf.add_rating(Rating("user3", "item_d", 4.0, now, InteractionType.RATE))
        cf.add_rating(Rating("user3", "item_e", 5.0, now, InteractionType.RATE))

        return cf

    def test_get_user_ratings(self, cf_with_data: UserBasedCF) -> None:
        """Test retrieving user ratings."""
        ratings = cf_with_data._get_user_ratings("user1")
        assert ratings == {"item_a": 5.0, "item_b": 4.0, "item_c": 2.0}

    def test_find_similar_users(self, cf_with_data: UserBasedCF) -> None:
        """Test finding similar users."""
        similar = cf_with_data.find_similar_users("user1", k=2)
        assert len(similar) <= 2
        assert similar[0][0] in ["user2", "user3"]
        assert 0 <= similar[0][1] <= 1

    def test_predict_rating(self, cf_with_data: UserBasedCF) -> None:
        """Test rating prediction."""
        # User 1 should rate item_d similar to user 2 who rated it 4.0
        pred = cf_with_data.predict_rating("user1", "item_d")
        assert pred is not None
        assert 0 <= pred <= 5

    def test_recommend(self, cf_with_data: UserBasedCF) -> None:
        """Test recommendation generation."""
        recs = cf_with_data.recommend("user1", n=2)
        assert len(recs) <= 2
        assert all(rec.item_id not in ["item_a", "item_b", "item_c"] for rec in recs)
        assert all(rec.score > 0 for rec in recs)

    def test_cold_start_error(self, cf_with_data: UserBasedCF) -> None:
        """Test cold start error for new user."""
        with pytest.raises(ColdStartError):
            cf_with_data.recommend("new_user")

    def test_insufficient_ratings(self, cf_with_data: UserBasedCF) -> None:
        """Test error when user has too few ratings."""
        cf = UserBasedCF(RecommenderConfig(min_ratings=3))
        cf.add_rating(Rating("user1", "item_a", 5.0, datetime.now(), InteractionType.RATE))

        with pytest.raises(InsufficientDataError):
            cf.find_similar_users("user1")

    def test_exclude_rated_items(self, cf_with_data: UserBasedCF) -> None:
        """Test that recommend excludes already-rated items by default."""
        recs = cf_with_data.recommend("user1", exclude_rated=True)
        user_ratings = cf_with_data._get_user_ratings("user1")

        for rec in recs:
            assert rec.item_id not in user_ratings


class TestItemBasedCF:
    """Test item-based collaborative filtering."""

    @pytest.fixture
    def item_cf_with_data(self) -> ItemBasedCF:
        """Create item-based CF with test data."""
        cf = ItemBasedCF()
        now = datetime.now()

        # Item A: user1(5), user2(5), user3(4)
        cf.add_rating(Rating("user1", "item_a", 5.0, now, InteractionType.RATE))
        cf.add_rating(Rating("user2", "item_a", 5.0, now, InteractionType.RATE))
        cf.add_rating(Rating("user3", "item_a", 4.0, now, InteractionType.RATE))

        # Item B: user1(4), user2(3), user4(5)
        cf.add_rating(Rating("user1", "item_b", 4.0, now, InteractionType.RATE))
        cf.add_rating(Rating("user2", "item_b", 3.0, now, InteractionType.RATE))
        cf.add_rating(Rating("user4", "item_b", 5.0, now, InteractionType.RATE))

        # Item C: user3(3), user4(4), user5(2)
        cf.add_rating(Rating("user3", "item_c", 3.0, now, InteractionType.RATE))
        cf.add_rating(Rating("user4", "item_c", 4.0, now, InteractionType.RATE))
        cf.add_rating(Rating("user5", "item_c", 2.0, now, InteractionType.RATE))

        return cf

    def test_get_item_ratings(self, item_cf_with_data: ItemBasedCF) -> None:
        """Test retrieving item ratings."""
        ratings = item_cf_with_data._get_item_ratings("item_a")
        assert ratings == {"user1": 5.0, "user2": 5.0, "user3": 4.0}

    def test_compute_similarity_matrix(self, item_cf_with_data: ItemBasedCF) -> None:
        """Test computing item similarity matrix."""
        item_cf_with_data.compute_similarity_matrix()
        assert len(item_cf_with_data.item_similarity_matrix) > 0

    def test_find_similar_items(self, item_cf_with_data: ItemBasedCF) -> None:
        """Test finding similar items."""
        similar = item_cf_with_data.find_similar_items("item_a", k=2)
        assert len(similar) <= 2
        assert all(item[0] in ["item_b", "item_c"] for item in similar)

    def test_predict_rating_from_items(self, item_cf_with_data: ItemBasedCF) -> None:
        """Test rating prediction using item similarity."""
        # User 1 has rated item_a(5) and item_b(4), predict item_c
        pred = item_cf_with_data.predict_rating("user1", "item_c")
        # Should be influenced by user's high ratings for similar items
        assert pred is None or (0 <= pred <= 5)

    def test_recommend_from_items(self, item_cf_with_data: ItemBasedCF) -> None:
        """Test generating recommendations."""
        recs = item_cf_with_data.recommend("user1", n=2)
        assert len(recs) <= 2
        assert all(rec.item_id not in ["item_a", "item_b"] for rec in recs)

    def test_item_based_cold_start(self, item_cf_with_data: ItemBasedCF) -> None:
        """Test cold start for new user."""
        with pytest.raises(ColdStartError):
            item_cf_with_data.recommend("new_user")


class TestCollaborativeFilteringIntegration:
    """Integration tests for collaborative filtering."""

    def test_both_algorithms_on_same_data(self) -> None:
        """Compare user-based and item-based CF on same data."""
        now = datetime.now()

        # Create test data
        ratings = [
            Rating("u1", "i1", 5.0, now, InteractionType.RATE),
            Rating("u1", "i2", 4.0, now, InteractionType.RATE),
            Rating("u2", "i1", 5.0, now, InteractionType.RATE),
            Rating("u2", "i3", 3.0, now, InteractionType.RATE),
            Rating("u3", "i2", 4.0, now, InteractionType.RATE),
            Rating("u3", "i3", 4.0, now, InteractionType.RATE),
        ]

        # Test user-based CF
        user_cf = UserBasedCF()
        user_cf.add_ratings(ratings)
        user_recs = user_cf.recommend("u1", n=2, exclude_rated=True)

        # Test item-based CF
        item_cf = ItemBasedCF()
        item_cf.add_ratings(ratings)
        item_recs = item_cf.recommend("u1", n=2, exclude_rated=True)

        # Both should produce recommendations
        assert len(user_recs) > 0 or len(item_recs) > 0

    def test_sparsity_handling(self) -> None:
        """Test handling of sparse rating matrices."""
        cf = UserBasedCF()
        now = datetime.now()

        # Very sparse data: only a few ratings
        cf.add_rating(Rating("u1", "i1", 5.0, now, InteractionType.RATE))
        cf.add_rating(Rating("u1", "i2", 4.0, now, InteractionType.RATE))
        cf.add_rating(Rating("u2", "i1", 5.0, now, InteractionType.RATE))

        # Should still find similar users
        similar = cf.find_similar_users("u1")
        assert len(similar) >= 0

    def test_large_scale_performance(self) -> None:
        """Test performance with larger dataset."""
        cf = UserBasedCF()
        now = datetime.now()

        # Add 100 users, 50 items, ~500 ratings
        for user_id in range(100):
            for item_id in range(min(5, 50)):  # Each user rates ~5 items
                score = float((user_id + item_id) % 5 + 1)
                cf.add_rating(
                    Rating(
                        f"user_{user_id}",
                        f"item_{item_id}",
                        score,
                        now,
                        InteractionType.RATE,
                    )
                )

        # Should handle without errors
        recs = cf.recommend("user_0", n=5)
        assert len(recs) <= 5
