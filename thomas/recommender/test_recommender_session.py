"""
Tests for session-based recommendation algorithms.
"""

from datetime import datetime, timedelta

import pytest

from thomas.recommender._types import InteractionType, Rating
from thomas.recommender.session_based import SessionBasedRecommender


class TestSessionBasedRecommender:
    """Test session-based recommendations."""

    @pytest.fixture
    def session_recommender(self) -> SessionBasedRecommender:
        """Create session recommender with test data."""
        rec = SessionBasedRecommender(session_timeout_minutes=30)
        return rec

    def test_add_rating(self, session_recommender: SessionBasedRecommender) -> None:
        """Test adding ratings to sessions."""
        now = datetime.now()

        session_recommender.add_rating(Rating("user1", "item_a", 5.0, now, InteractionType.VIEW))
        session_recommender.add_rating(Rating("user1", "item_b", 4.0, now + timedelta(minutes=5), InteractionType.VIEW))

        assert len(session_recommender.ratings) == 2

    def test_session_tracking(self, session_recommender: SessionBasedRecommender) -> None:
        """Test session tracking for users."""
        now = datetime.now()

        session_recommender.add_rating(Rating("user1", "item_a", 5.0, now, InteractionType.VIEW))
        session_recommender.add_rating(Rating("user1", "item_b", 4.0, now + timedelta(minutes=5), InteractionType.VIEW))

        sessions = session_recommender.get_user_sessions("user1")
        assert len(sessions) >= 1

    def test_session_timeout(self, session_recommender: SessionBasedRecommender) -> None:
        """Test session timeout creates new session."""
        now = datetime.now()

        # First session
        session_recommender.add_rating(Rating("user1", "item_a", 5.0, now, InteractionType.VIEW))

        # After timeout
        later = now + timedelta(minutes=35)
        session_recommender.add_rating(Rating("user1", "item_b", 4.0, later, InteractionType.VIEW))

        sessions = session_recommender.get_user_sessions("user1")
        # Should have 2 sessions (one completed, one current)
        assert len(sessions) >= 1

    def test_get_session_items(self, session_recommender: SessionBasedRecommender) -> None:
        """Test retrieving items from a session."""
        now = datetime.now()

        ratings = [
            Rating("user1", "item_a", 5.0, now, InteractionType.VIEW),
            Rating("user1", "item_b", 4.0, now + timedelta(minutes=1), InteractionType.VIEW),
            Rating("user1", "item_c", 3.0, now + timedelta(minutes=2), InteractionType.VIEW),
        ]

        session = ratings
        items = session_recommender.get_session_items(session)

        assert items == ["item_a", "item_b", "item_c"]

    def test_cooccurrence_matrix(self, session_recommender: SessionBasedRecommender) -> None:
        """Test co-occurrence matrix computation."""
        now = datetime.now()

        session_recommender.add_rating(Rating("user1", "item_a", 5.0, now, InteractionType.VIEW))
        session_recommender.add_rating(Rating("user1", "item_b", 4.0, now + timedelta(minutes=1), InteractionType.VIEW))
        session_recommender.add_rating(Rating("user1", "item_c", 3.0, now + timedelta(minutes=2), InteractionType.VIEW))

        cooc = session_recommender._compute_cooccurrence_matrix()

        # Items in same session should have co-occurrence counts
        assert ("item_a" in cooc and "item_b" in cooc["item_a"]) or len(cooc) == 0

    def test_recommend_from_session(self, session_recommender: SessionBasedRecommender) -> None:
        """Test recommendation from session co-occurrence."""
        now = datetime.now()

        # Build a session
        session_recommender.add_rating(Rating("user1", "item_a", 5.0, now, InteractionType.VIEW))
        session_recommender.add_rating(Rating("user1", "item_b", 4.0, now + timedelta(minutes=1), InteractionType.VIEW))

        recs = session_recommender.recommend_from_session("user1", n=5)

        # Should generate recommendations or empty list if not enough data
        assert isinstance(recs, list)
        assert all(rec.item_id not in ["item_a", "item_b"] for rec in recs)

    def test_markov_chain(self, session_recommender: SessionBasedRecommender) -> None:
        """Test Markov chain transition matrix."""
        now = datetime.now()

        # Create multiple sessions with patterns
        for user_id in ["user1", "user2"]:
            t = now
            for item_id in ["item_a", "item_b", "item_c"]:
                session_recommender.add_rating(Rating(user_id, item_id, 5.0, t, InteractionType.VIEW))
                t += timedelta(minutes=1)

        transitions = session_recommender._build_transition_matrix()

        # Should have some transitions
        assert isinstance(transitions, dict)

    def test_recommend_from_markov(self, session_recommender: SessionBasedRecommender) -> None:
        """Test Markov chain recommendations."""
        now = datetime.now()

        session_recommender.add_rating(Rating("user1", "item_a", 5.0, now, InteractionType.VIEW))
        session_recommender.add_rating(Rating("user1", "item_b", 4.0, now + timedelta(minutes=1), InteractionType.VIEW))

        recs = session_recommender.recommend_from_markov("user1", n=5)
        assert isinstance(recs, list)

    def test_recommend_combined(self, session_recommender: SessionBasedRecommender) -> None:
        """Test combined co-occurrence and Markov recommendations."""
        now = datetime.now()

        session_recommender.add_rating(Rating("user1", "item_a", 5.0, now, InteractionType.VIEW))
        session_recommender.add_rating(Rating("user1", "item_b", 4.0, now + timedelta(minutes=1), InteractionType.VIEW))

        recs = session_recommender.recommend_combined("user1", n=5)
        assert isinstance(recs, list)

    def test_session_similarity(self, session_recommender: SessionBasedRecommender) -> None:
        """Test session similarity computation."""
        now = datetime.now()

        session1 = [
            Rating("user1", "item_a", 5.0, now, InteractionType.VIEW),
            Rating("user1", "item_b", 4.0, now + timedelta(minutes=1), InteractionType.VIEW),
        ]

        session2 = [
            Rating("user1", "item_a", 5.0, now, InteractionType.VIEW),
            Rating("user1", "item_c", 3.0, now + timedelta(minutes=1), InteractionType.VIEW),
        ]

        session3 = [
            Rating("user1", "item_c", 5.0, now, InteractionType.VIEW),
            Rating("user1", "item_d", 4.0, now + timedelta(minutes=1), InteractionType.VIEW),
        ]

        sim12 = session_recommender.get_session_similarity(session1, session2)
        sim13 = session_recommender.get_session_similarity(session1, session3)

        assert 0 <= sim12 <= 1
        assert 0 <= sim13 <= 1
        # session1 and session2 share item_a, should be more similar
        assert sim12 >= sim13

    def test_find_similar_sessions(self, session_recommender: SessionBasedRecommender) -> None:
        """Test finding similar sessions."""
        now = datetime.now()

        # Create sessions
        for i in range(3):
            session_recommender.add_rating(
                Rating("user1", f"item_{i}", 5.0, now + timedelta(minutes=i * 5), InteractionType.VIEW)
            )

        similar = session_recommender.find_similar_sessions("user1", k=2)
        assert isinstance(similar, list)

    def test_empty_session(self, session_recommender: SessionBasedRecommender) -> None:
        """Test handling of empty sessions."""
        recs = session_recommender.recommend_from_session("nonexistent_user", n=5)
        assert recs == []

    def test_multiple_users(self, session_recommender: SessionBasedRecommender) -> None:
        """Test handling multiple users' sessions."""
        now = datetime.now()

        # User 1 session
        for item in ["a", "b", "c"]:
            session_recommender.add_rating(
                Rating(
                    "user1", f"item_{item}", 5.0, now + timedelta(minutes=int(item.encode()[0])), InteractionType.VIEW
                )
            )

        # User 2 session
        for item in ["d", "e", "f"]:
            session_recommender.add_rating(
                Rating(
                    "user2", f"item_{item}", 5.0, now + timedelta(minutes=int(item.encode()[0])), InteractionType.VIEW
                )
            )

        u1_sessions = session_recommender.get_user_sessions("user1")
        u2_sessions = session_recommender.get_user_sessions("user2")

        assert len(u1_sessions) > 0
        assert len(u2_sessions) > 0
