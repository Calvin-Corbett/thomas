"""
Session-based recommendation algorithms.

Session-based methods track sequences of user interactions within a session
and recommend items based on co-occurrence patterns and Markov chains.
"""

from collections import defaultdict
from datetime import timedelta

from thomas.marketplace.recommender._types import Rating, Recommendation


class SessionBasedRecommender:
    """Session-based recommendations using interaction sequences.

    Tracks user sessions and recommends items based on:
    1. Co-occurrence (items viewed together)
    2. Sequential patterns (item A then item B)
    3. Markov chains (transition probabilities)
    """

    def __init__(self, session_timeout_minutes: int = 30) -> None:
        """Initialize session-based recommender.

        Args:
            session_timeout_minutes: Duration before session ends.
        """
        self.session_timeout = timedelta(minutes=session_timeout_minutes)
        self.ratings: list[Rating] = []
        self.sessions: dict[str, list[Rating]] = {}
        self.current_session: dict[str, list[Rating]] = {}

    def add_rating(self, rating: Rating) -> None:
        """Add a rating and track it as part of user's session.

        Args:
            rating: Rating to add.
        """
        self.ratings.append(rating)
        self._track_session(rating)

    def add_ratings(self, ratings: list[Rating]) -> None:
        """Add multiple ratings.

        Args:
            ratings: List of ratings to add.
        """
        self.ratings.extend(ratings)
        for rating in ratings:
            self._track_session(rating)

    def _track_session(self, rating: Rating) -> None:
        """Track a rating as part of a user's session.

        Args:
            rating: Rating to track.
        """
        user_id = rating.user_id

        # Initialize session if needed
        if user_id not in self.current_session:
            self.current_session[user_id] = []

        # Check if session should end (timeout)
        if self.current_session[user_id]:
            last_time = self.current_session[user_id][-1].timestamp
            if rating.timestamp - last_time > self.session_timeout:
                # End current session and start new one
                session_id = f"{user_id}_{len(self.sessions)}"
                self.sessions[session_id] = self.current_session[user_id]
                self.current_session[user_id] = []

        self.current_session[user_id].append(rating)

    def get_user_sessions(self, user_id: str) -> list[list[Rating]]:
        """Get all completed sessions for a user.

        Args:
            user_id: User identifier.

        Returns:
            List of sessions (each session is a list of ratings).
        """
        sessions = []
        for session_id, session in self.sessions.items():
            if session_id.startswith(user_id):
                sessions.append(session)

        # Add current session if it exists
        if user_id in self.current_session and self.current_session[user_id]:
            sessions.append(self.current_session[user_id])

        return sessions

    def get_session_items(self, session: list[Rating]) -> list[str]:
        """Get items viewed in a session.

        Args:
            session: Session (list of ratings).

        Returns:
            Ordered list of item IDs viewed in session.
        """
        return [r.item_id for r in session]

    def _compute_cooccurrence_matrix(self) -> dict[str, dict[str, int]]:
        """Compute item co-occurrence from all sessions.

        Args:
            sessions: List of sessions.

        Returns:
            Dict mapping item_id to dict of co-occurring items and counts.
        """
        all_sessions = list(self.sessions.values())
        for session in self.current_session.values():
            if session:
                all_sessions.append(session)

        cooccurrence: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

        for session in all_sessions:
            items = self.get_session_items(session)
            # Count co-occurrences within session
            for i, item1 in enumerate(items):
                for item2 in items[i + 1 :]:
                    cooccurrence[item1][item2] += 1
                    cooccurrence[item2][item1] += 1

        return cooccurrence

    def recommend_from_session(
        self,
        user_id: str,
        n: int = 10,
        exclude_viewed: bool = True,
    ) -> list[Recommendation]:
        """Recommend items based on user's current session.

        Items are ranked by co-occurrence with viewed items.

        Args:
            user_id: User identifier.
            n: Number of recommendations.
            exclude_viewed: If True, don't recommend already viewed items.

        Returns:
            List of recommendations.
        """
        if user_id not in self.current_session:
            return []

        session = self.current_session[user_id]
        if not session:
            return []

        viewed_items = set(self.get_session_items(session))
        cooccurrence = self._compute_cooccurrence_matrix()

        # Score items by total co-occurrence with viewed items
        scores: dict[str, float] = defaultdict(float)

        for viewed_item in viewed_items:
            if viewed_item in cooccurrence:
                for cooc_item, count in cooccurrence[viewed_item].items():
                    if exclude_viewed and cooc_item in viewed_items:
                        continue
                    scores[cooc_item] += count

        # Sort by score
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        recommendations = [
            Recommendation(
                item_id=item_id,
                score=float(count),
                explanation="Co-occurrence in session",
                algorithm="SessionBased",
            )
            for item_id, count in ranked[:n]
        ]

        return recommendations

    def _build_transition_matrix(self) -> dict[str, dict[str, float]]:
        """Build Markov chain transition probabilities.

        Transition probability = count(A -> B) / count(A).

        Returns:
            Dict mapping item_id to dict of next items and probabilities.
        """
        all_sessions = list(self.sessions.values())
        for session in self.current_session.values():
            if session:
                all_sessions.append(session)

        transitions: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        item_counts: dict[str, int] = defaultdict(int)

        for session in all_sessions:
            items = self.get_session_items(session)
            for i in range(len(items) - 1):
                current = items[i]
                next_item = items[i + 1]
                transitions[current][next_item] += 1
                item_counts[current] += 1

        # Convert to probabilities
        probabilities: dict[str, dict[str, float]] = {}
        for item, next_items in transitions.items():
            count = item_counts[item]
            probabilities[item] = {next_item: cnt / count for next_item, cnt in next_items.items()}

        return probabilities

    def recommend_from_markov(
        self,
        user_id: str,
        n: int = 10,
    ) -> list[Recommendation]:
        """Recommend using Markov chain transition probabilities.

        Recommends items likely to follow recently viewed item.

        Args:
            user_id: User identifier.
            n: Number of recommendations.

        Returns:
            List of recommendations.
        """
        if user_id not in self.current_session:
            return []

        session = self.current_session[user_id]
        if not session:
            return []

        transition_matrix = self._build_transition_matrix()
        last_item = session[-1].item_id

        if last_item not in transition_matrix:
            return []

        next_items = transition_matrix[last_item]

        # Sort by transition probability
        ranked = sorted(next_items.items(), key=lambda x: x[1], reverse=True)

        recommendations = [
            Recommendation(
                item_id=item_id,
                score=prob,
                explanation="Sequential pattern from Markov chain",
                algorithm="MarkovChain",
            )
            for item_id, prob in ranked[:n]
        ]

        return recommendations

    def recommend_combined(
        self,
        user_id: str,
        n: int = 10,
        cooccurrence_weight: float = 0.6,
        markov_weight: float = 0.4,
    ) -> list[Recommendation]:
        """Combine co-occurrence and Markov recommendations.

        Args:
            user_id: User identifier.
            n: Number of recommendations.
            cooccurrence_weight: Weight for co-occurrence scores.
            markov_weight: Weight for Markov scores.

        Returns:
            List of combined recommendations.
        """
        cooc_recs = self.recommend_from_session(user_id, n * 2, exclude_viewed=True)
        markov_recs = self.recommend_from_markov(user_id, n * 2)

        # Create score dictionary
        scores: dict[str, float] = {}
        for rec in cooc_recs:
            # Normalize to 0-1 scale
            norm_score = min(1.0, rec.score / max(1.0, max((r.score for r in cooc_recs), default=1.0)))
            scores[rec.item_id] = cooccurrence_weight * norm_score

        for rec in markov_recs:
            norm_score = rec.score  # Already 0-1
            scores[rec.item_id] = scores.get(rec.item_id, 0) + markov_weight * norm_score

        # Rank by combined score
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        recommendations = [
            Recommendation(
                item_id=item_id,
                score=score,
                explanation="Session-based recommendation",
                algorithm="SessionBased",
            )
            for item_id, score in ranked[:n]
        ]

        return recommendations

    def get_session_similarity(self, session1: list[Rating], session2: list[Rating]) -> float:
        """Compute Jaccard similarity between two sessions.

        Args:
            session1: First session.
            session2: Second session.

        Returns:
            Similarity between 0 and 1.
        """
        items1 = set(self.get_session_items(session1))
        items2 = set(self.get_session_items(session2))

        if not items1 and not items2:
            return 1.0
        if not items1 or not items2:
            return 0.0

        intersection = len(items1 & items2)
        union = len(items1 | items2)

        return intersection / union if union > 0 else 0.0

    def find_similar_sessions(self, user_id: str, k: int = 5) -> list[tuple[str, list[Rating], float]]:
        """Find sessions similar to user's current session.

        Args:
            user_id: User identifier.
            k: Number of similar sessions to find.

        Returns:
            List of (session_id, session, similarity) tuples.
        """
        if user_id not in self.current_session:
            return []

        current = self.current_session[user_id]
        list(self.sessions.values())

        similarities: list[tuple[str, list[Rating], float]] = []

        for session_id, session in self.sessions.items():
            sim = self.get_session_similarity(current, session)
            if sim > 0:
                similarities.append((session_id, session, sim))

        similarities.sort(key=lambda x: x[2], reverse=True)
        return similarities[:k]
