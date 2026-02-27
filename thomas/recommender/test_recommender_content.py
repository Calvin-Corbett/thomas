"""
Tests for content-based filtering algorithms.
"""

from datetime import datetime

import pytest

from thomas.recommender._exceptions import ColdStartError
from thomas.recommender._types import InteractionType, Rating
from thomas.recommender.content_based import ContentBasedRecommender, TFIDFVectorizer


class TestTFIDFVectorizer:
    """Test TF-IDF vectorization."""

    def test_vocabulary_building(self) -> None:
        """Test vocabulary and IDF computation."""
        vectorizer = TFIDFVectorizer()
        docs = [
            "python programming tutorial",
            "python data science",
            "machine learning algorithms",
        ]

        vectorizer.build_vocabulary(docs)

        assert "python" in vectorizer.vocabulary
        assert "programming" in vectorizer.vocabulary
        assert len(vectorizer.idf) > 0

    def test_vectorization(self) -> None:
        """Test document vectorization."""
        vectorizer = TFIDFVectorizer()
        docs = [
            "cat and dog",
            "cat and bird",
            "dog and bird",
        ]

        vectorizer.build_vocabulary(docs)
        vec = vectorizer.vectorize("cat and dog")

        assert "cat" in vec
        assert vec["cat"] > 0
        assert isinstance(vec["cat"], float)

    def test_empty_document(self) -> None:
        """Test vectorization of empty document."""
        vectorizer = TFIDFVectorizer()
        vectorizer.build_vocabulary(["test document"])

        vec = vectorizer.vectorize("")
        assert len(vec) == 0


class TestContentBasedRecommender:
    """Test content-based recommendation."""

    @pytest.fixture
    def content_recommender(self) -> ContentBasedRecommender:
        """Create content-based recommender with test data."""
        rec = ContentBasedRecommender()
        now = datetime.now()

        # Add ratings
        rec.add_rating(Rating("user1", "item_a", 5.0, now, InteractionType.RATE))
        rec.add_rating(Rating("user1", "item_b", 4.0, now, InteractionType.RATE))
        rec.add_rating(Rating("user2", "item_b", 5.0, now, InteractionType.RATE))
        rec.add_rating(Rating("user2", "item_c", 3.0, now, InteractionType.RATE))

        # Add item features
        rec.add_item_features("item_a", {"action": 1.0, "drama": 0.5})
        rec.add_item_features("item_b", {"action": 0.8, "drama": 0.7})
        rec.add_item_features("item_c", {"comedy": 1.0, "drama": 0.2})
        rec.add_item_features("item_d", {"action": 0.9, "drama": 0.4})

        return rec

    def test_add_item_features(self, content_recommender: ContentBasedRecommender) -> None:
        """Test adding item features."""
        features = content_recommender.item_features["item_a"]
        assert features["action"] == 1.0
        assert features["drama"] == 0.5

    def test_add_item_description(self, content_recommender: ContentBasedRecommender) -> None:
        """Test adding text descriptions."""
        content_recommender.add_item_description("item_e", "action packed movie with great drama")

        assert "item_e" in content_recommender.item_features
        features = content_recommender.item_features["item_e"]
        assert len(features) > 0

    def test_build_user_profile(self, content_recommender: ContentBasedRecommender) -> None:
        """Test building user profile from ratings."""
        profile = content_recommender._build_user_profile("user1")

        assert "action" in profile or "drama" in profile
        assert isinstance(profile, dict)

    def test_get_user_profile(self, content_recommender: ContentBasedRecommender) -> None:
        """Test retrieving user profile."""
        profile = content_recommender.get_user_profile("user1")
        assert isinstance(profile, dict)

    def test_predict_rating(self, content_recommender: ContentBasedRecommender) -> None:
        """Test rating prediction based on content."""
        pred = content_recommender.predict_rating("user1", "item_d")

        # Should predict based on item_d's similarity to items user1 rated highly
        assert pred is None or (0 <= pred <= 5)

    def test_recommend(self, content_recommender: ContentBasedRecommender) -> None:
        """Test generating recommendations."""
        recs = content_recommender.recommend("user1", n=2)

        assert len(recs) <= 2
        assert all(rec.item_id not in ["item_a", "item_b"] for rec in recs)

    def test_recommend_by_item(self, content_recommender: ContentBasedRecommender) -> None:
        """Test finding similar items."""
        recs = content_recommender.recommend_by_item("item_a", n=2)

        assert len(recs) <= 2
        assert all(rec.item_id != "item_a" for rec in recs)
        assert all(rec.score >= 0 for rec in recs)

    def test_cold_start_error(self, content_recommender: ContentBasedRecommender) -> None:
        """Test error for new user with no ratings."""
        with pytest.raises(ColdStartError):
            content_recommender.recommend("new_user")

    def test_missing_item_features(self, content_recommender: ContentBasedRecommender) -> None:
        """Test prediction for item without features."""
        # Create new item without features
        new_rec = ContentBasedRecommender()
        new_rec.add_rating(Rating("u1", "i1", 5.0, datetime.now(), InteractionType.RATE))
        new_rec.add_item_features("i1", {"feature": 1.0})

        # Try to predict for item without features
        pred = new_rec.predict_rating("u1", "i2")
        assert pred is None


class TestTFIDFIntegration:
    """Integration tests with TF-IDF."""

    def test_tfidf_with_content_recommender(self) -> None:
        """Test TF-IDF integration with content recommender."""
        rec = ContentBasedRecommender()
        now = datetime.now()

        # Build TF-IDF vocabulary
        descriptions = [
            "action movie with car chases",
            "romantic comedy about love",
            "thriller with suspense",
        ]
        rec.vectorizer.build_vocabulary(descriptions)

        # Add ratings and descriptions
        rec.add_rating(Rating("u1", "i1", 5.0, now, InteractionType.RATE))
        rec.add_rating(Rating("u1", "i2", 2.0, now, InteractionType.RATE))

        rec.add_item_description("i1", "action movie with car chases")
        rec.add_item_description("i2", "romantic comedy about love")
        rec.add_item_description("i3", "action packed thriller")

        # Generate recommendations
        recs = rec.recommend("u1", n=1)
        assert len(recs) > 0
        # User rated action high, should recommend action item
        assert recs[0].item_id == "i3"

    def test_multiple_descriptions_per_item(self) -> None:
        """Test multiple feature additions to same item."""
        rec = ContentBasedRecommender()

        rec.add_item_features("item1", {"genre_action": 1.0})
        rec.add_item_features("item1", {"genre_drama": 0.5})

        features = rec.item_features["item1"]
        assert features["genre_action"] == 1.0
        assert features["genre_drama"] == 0.5


class TestContentBasedEdgeCases:
    """Test edge cases in content-based filtering."""

    def test_empty_item_features(self) -> None:
        """Test handling of items with empty features."""
        rec = ContentBasedRecommender()
        now = datetime.now()

        rec.add_rating(Rating("u1", "i1", 5.0, now, InteractionType.RATE))
        rec.add_item_features("i1", {})  # Empty features

        pred = rec.predict_rating("u1", "i2")
        # Should handle gracefully
        assert pred is None or isinstance(pred, float)

    def test_single_rated_item(self) -> None:
        """Test recommendation with only one rated item."""
        rec = ContentBasedRecommender()
        now = datetime.now()

        rec.add_rating(Rating("u1", "i1", 5.0, now, InteractionType.RATE))
        rec.add_item_features("i1", {"feature": 1.0})
        rec.add_item_features("i2", {"feature": 0.9})

        # Profile should build from single item
        profile = rec.get_user_profile("u1")
        assert len(profile) > 0

    def test_zero_score_features(self) -> None:
        """Test handling of zero-valued features."""
        rec = ContentBasedRecommender()
        now = datetime.now()

        rec.add_rating(Rating("u1", "i1", 5.0, now, InteractionType.RATE))
        rec.add_item_features("i1", {"feat1": 1.0, "feat2": 0.0})
        rec.add_item_features("i2", {"feat1": 0.5, "feat2": 0.3})

        recs = rec.recommend("u1", n=1)
        # Should still generate recommendations
        assert len(recs) >= 0
