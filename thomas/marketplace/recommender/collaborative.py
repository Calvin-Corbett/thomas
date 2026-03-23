"""
Collaborative filtering recommendation algorithms.

This module implements both user-based and item-based collaborative filtering.
These methods find similar users/items and recommend based on their preferences.
"""

from thomas.marketplace.recommender._exceptions import ColdStartError, InsufficientDataError
from thomas.marketplace.recommender._types import Rating, Recommendation, RecommenderConfig
from thomas.marketplace.recommender.similarity import SimilarityComputer


class CollaborativeFilter:
    """Base class for collaborative filtering recommenders."""

    def __init__(self, config: RecommenderConfig | None = None) -> None:
        """Initialize collaborative filter.

        Args:
            config: Recommender configuration.
        """
        self.config = config or RecommenderConfig()
        self.config.validate()
        self.ratings: list[Rating] = []

    def add_rating(self, rating: Rating) -> None:
        """Add a rating to the system.

        Args:
            rating: Rating to add.
        """
        self.ratings.append(rating)

    def add_ratings(self, ratings: list[Rating]) -> None:
        """Add multiple ratings.

        Args:
            ratings: List of ratings to add.
        """
        self.ratings.extend(ratings)

    def _get_user_ratings(self, user_id: str) -> dict[str, float]:
        """Get all ratings for a user.

        Args:
            user_id: User identifier.

        Returns:
            Dictionary mapping item_id to rating score.
        """
        return {r.item_id: r.score for r in self.ratings if r.user_id == user_id}

    def _get_item_ratings(self, item_id: str) -> dict[str, float]:
        """Get all ratings for an item.

        Args:
            item_id: Item identifier.

        Returns:
            Dictionary mapping user_id to rating score.
        """
        return {r.user_id: r.score for r in self.ratings if r.item_id == item_id}

    def _get_all_users(self) -> set[str]:
        """Get all users in the system.

        Returns:
            Set of user IDs.
        """
        return {r.user_id for r in self.ratings}

    def _get_all_items(self) -> set[str]:
        """Get all items in the system.

        Returns:
            Set of item IDs.
        """
        return {r.item_id for r in self.ratings}


class UserBasedCF(CollaborativeFilter):
    """User-based collaborative filtering.

    Finds users similar to the target user based on their rating patterns,
    then recommends items that similar users rated highly.
    """

    def __init__(self, config: RecommenderConfig | None = None) -> None:
        """Initialize user-based CF.

        Args:
            config: Recommender configuration.
        """
        super().__init__(config)
        self.similarity_computer = SimilarityComputer(metric="cosine")

    def _get_user_vector(self, user_id: str) -> dict[str, float]:
        """Get rating vector for a user.

        Args:
            user_id: User identifier.

        Returns:
            Dictionary mapping item_id to rating score.
        """
        return self._get_user_ratings(user_id)

    def _compute_user_similarity(self, user1_id: str, user2_id: str) -> float:
        """Compute similarity between two users.

        Args:
            user1_id: First user ID.
            user2_id: Second user ID.

        Returns:
            Similarity score between -1 and 1.
        """
        vec1 = self._get_user_vector(user1_id)
        vec2 = self._get_user_vector(user2_id)
        return self.similarity_computer.compute(user1_id, user2_id, vec1, vec2)

    def find_similar_users(self, user_id: str, k: int | None = None) -> list[tuple[str, float]]:
        """Find k users most similar to given user.

        Args:
            user_id: Reference user ID.
            k: Number of similar users to find.

        Returns:
            List of (user_id, similarity) tuples sorted by similarity.

        Raises:
            InsufficientDataError: If user has too few ratings.
        """
        k = k or self.config.k

        user_ratings = self._get_user_ratings(user_id)
        if len(user_ratings) < self.config.min_ratings:
            raise InsufficientDataError(self.config.min_ratings, len(user_ratings), "user ratings")

        all_users = self._get_all_users()
        similarities: list[tuple[str, float]] = []

        for other_user in all_users:
            if other_user == user_id:
                continue
            if len(self._get_user_ratings(other_user)) < self.config.min_ratings:
                continue

            sim = self._compute_user_similarity(user_id, other_user)
            similarities.append((other_user, sim))

        # Sort by similarity descending
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:k]

    def predict_rating(self, user_id: str, item_id: str) -> float | None:
        """Predict a rating using weighted average of similar users' ratings.

        Args:
            user_id: User to predict for.
            item_id: Item to predict rating for.

        Returns:
            Predicted rating or None if prediction not possible.
        """
        try:
            similar_users = self.find_similar_users(user_id)
        except InsufficientDataError:
            return None

        if not similar_users:
            return None

        # Get ratings from similar users
        weighted_sum = 0.0
        weight_sum = 0.0

        for sim_user_id, similarity in similar_users:
            sim_user_ratings = self._get_user_ratings(sim_user_id)
            if item_id in sim_user_ratings:
                weight = max(0.0, similarity)  # Only positive similarity
                weighted_sum += weight * sim_user_ratings[item_id]
                weight_sum += weight

        if weight_sum == 0:
            return None

        return weighted_sum / weight_sum

    def recommend(
        self,
        user_id: str,
        n: int = 10,
        exclude_rated: bool = True,
    ) -> list[Recommendation]:
        """Get top-N recommendations for a user.

        Args:
            user_id: User to recommend for.
            n: Number of recommendations.
            exclude_rated: If True, don't recommend already-rated items.

        Returns:
            List of recommendations sorted by score.

        Raises:
            ColdStartError: If user has no rating history.
        """
        user_ratings = self._get_user_ratings(user_id)
        if not user_ratings:
            raise ColdStartError("user", user_id, "No rating history")

        all_items = self._get_all_items()
        if exclude_rated:
            all_items = all_items - set(user_ratings.keys())

        # Score all items
        recommendations: list[Recommendation] = []
        for item_id in all_items:
            pred_rating = self.predict_rating(user_id, item_id)
            if pred_rating is not None and pred_rating > 0:
                rec = Recommendation(
                    item_id=item_id,
                    score=pred_rating,
                    explanation="Predicted from similar users",
                    algorithm="UserBasedCF",
                )
                recommendations.append(rec)

        # Sort by score descending
        recommendations.sort(key=lambda r: r.score, reverse=True)
        return recommendations[:n]


class ItemBasedCF(CollaborativeFilter):
    """Item-based collaborative filtering.

    Computes item-item similarity based on user rating patterns,
    then recommends items similar to those the user rated highly.
    """

    def __init__(self, config: RecommenderConfig | None = None) -> None:
        """Initialize item-based CF.

        Args:
            config: Recommender configuration.
        """
        super().__init__(config)
        self.similarity_computer = SimilarityComputer(metric="cosine")
        self.item_similarity_matrix: dict[tuple[str, str], float] = {}

    def _get_item_vector(self, item_id: str) -> dict[str, float]:
        """Get rating vector for an item.

        Args:
            item_id: Item identifier.

        Returns:
            Dictionary mapping user_id to rating score.
        """
        return self._get_item_ratings(item_id)

    def _compute_item_similarity(self, item1_id: str, item2_id: str) -> float:
        """Compute similarity between two items.

        Args:
            item1_id: First item ID.
            item2_id: Second item ID.

        Returns:
            Similarity score between -1 and 1.
        """
        # Check cache
        cache_key = tuple(sorted([item1_id, item2_id]))
        if cache_key in self.item_similarity_matrix:
            return self.item_similarity_matrix[cache_key]

        vec1 = self._get_item_vector(item1_id)
        vec2 = self._get_item_vector(item2_id)
        sim = self.similarity_computer.compute(item1_id, item2_id, vec1, vec2)

        self.item_similarity_matrix[cache_key] = sim
        return sim

    def compute_similarity_matrix(self) -> None:
        """Precompute item-item similarity matrix."""
        all_items = self._get_all_items()
        items_list = list(all_items)

        for i, item1 in enumerate(items_list):
            for item2 in items_list[i + 1 :]:
                self._compute_item_similarity(item1, item2)

    def find_similar_items(self, item_id: str, k: int | None = None) -> list[tuple[str, float]]:
        """Find k items most similar to given item.

        Args:
            item_id: Reference item ID.
            k: Number of similar items to find.

        Returns:
            List of (item_id, similarity) tuples sorted by similarity.

        Raises:
            InsufficientDataError: If item has too few ratings.
        """
        k = k or self.config.k

        item_ratings = self._get_item_ratings(item_id)
        if len(item_ratings) < self.config.min_ratings:
            raise InsufficientDataError(self.config.min_ratings, len(item_ratings), "item ratings")

        all_items = self._get_all_items()
        similarities: list[tuple[str, float]] = []

        for other_item in all_items:
            if other_item == item_id:
                continue
            if len(self._get_item_ratings(other_item)) < self.config.min_ratings:
                continue

            sim = self._compute_item_similarity(item_id, other_item)
            similarities.append((other_item, sim))

        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:k]

    def predict_rating(self, user_id: str, item_id: str) -> float | None:
        """Predict a rating using weighted average of similar items' ratings.

        Args:
            user_id: User to predict for.
            item_id: Item to predict rating for.

        Returns:
            Predicted rating or None if prediction not possible.
        """
        user_ratings = self._get_user_ratings(user_id)
        if not user_ratings:
            return None

        try:
            similar_items = self.find_similar_items(item_id)
        except InsufficientDataError:
            return None

        if not similar_items:
            return None

        # Weight by similarity of items user has rated
        weighted_sum = 0.0
        weight_sum = 0.0

        for sim_item_id, similarity in similar_items:
            if sim_item_id in user_ratings:
                weight = max(0.0, similarity)
                weighted_sum += weight * user_ratings[sim_item_id]
                weight_sum += weight

        if weight_sum == 0:
            return None

        return weighted_sum / weight_sum

    def recommend(
        self,
        user_id: str,
        n: int = 10,
        exclude_rated: bool = True,
    ) -> list[Recommendation]:
        """Get top-N recommendations for a user.

        Args:
            user_id: User to recommend for.
            n: Number of recommendations.
            exclude_rated: If True, don't recommend already-rated items.

        Returns:
            List of recommendations sorted by score.

        Raises:
            ColdStartError: If user has no rating history.
        """
        user_ratings = self._get_user_ratings(user_id)
        if not user_ratings:
            raise ColdStartError("user", user_id, "No rating history")

        all_items = self._get_all_items()
        if exclude_rated:
            all_items = all_items - set(user_ratings.keys())

        recommendations: list[Recommendation] = []
        for item_id in all_items:
            pred_rating = self.predict_rating(user_id, item_id)
            if pred_rating is not None and pred_rating > 0:
                rec = Recommendation(
                    item_id=item_id,
                    score=pred_rating,
                    explanation="Predicted from similar items",
                    algorithm="ItemBasedCF",
                )
                recommendations.append(rec)

        recommendations.sort(key=lambda r: r.score, reverse=True)
        return recommendations[:n]
