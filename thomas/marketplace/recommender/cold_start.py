"""
Cold start handling strategies for new users and items.

When new users or items lack historical data, alternative strategies are needed.
This module provides popularity-based fallback, exploration/exploitation, and bandit approaches.
"""

import math
import random

from thomas.marketplace.recommender._types import Rating, Recommendation


class ColdStartHandler:
    """Handles recommendations for cold start situations.

    Provides fallback strategies for new users and items.
    """

    def __init__(self) -> None:
        """Initialize cold start handler."""
        self.ratings: list[Rating] = []
        self.item_popularity: dict[str, float] = {}
        self.epsilon: float = 0.1  # For epsilon-greedy exploration

    def add_rating(self, rating: Rating) -> None:
        """Add a rating.

        Args:
            rating: Rating to add.
        """
        self.ratings.append(rating)
        self._update_popularity()

    def add_ratings(self, ratings: list[Rating]) -> None:
        """Add multiple ratings.

        Args:
            ratings: List of ratings to add.
        """
        self.ratings.extend(ratings)
        self._update_popularity()

    def _update_popularity(self) -> None:
        """Update item popularity scores based on ratings."""
        popularity: dict[str, float] = {}

        for rating in self.ratings:
            if rating.item_id not in popularity:
                popularity[rating.item_id] = 0.0
            popularity[rating.item_id] += rating.score

        # Normalize by count
        count: dict[str, int] = {}
        for rating in self.ratings:
            count[rating.item_id] = count.get(rating.item_id, 0) + 1

        for item_id in popularity:
            if count[item_id] > 0:
                popularity[item_id] /= count[item_id]

        self.item_popularity = popularity

    def get_popular_items(self, n: int = 10) -> list[Recommendation]:
        """Get most popular items (by average rating).

        Args:
            n: Number of items to return.

        Returns:
            List of recommendations for popular items.
        """
        items = sorted(self.item_popularity.items(), key=lambda x: x[1], reverse=True)

        recommendations = [
            Recommendation(
                item_id=item_id,
                score=popularity,
                explanation="Popular item",
                algorithm="PopularityBased",
            )
            for item_id, popularity in items[:n]
        ]
        return recommendations

    def get_popular_by_count(self, n: int = 10) -> list[Recommendation]:
        """Get most frequently rated items.

        Args:
            n: Number of items to return.

        Returns:
            List of recommendations for frequently rated items.
        """
        count: dict[str, int] = {}
        for rating in self.ratings:
            count[rating.item_id] = count.get(rating.item_id, 0) + 1

        items = sorted(count.items(), key=lambda x: x[1], reverse=True)

        recommendations = [
            Recommendation(
                item_id=item_id,
                score=float(cnt),
                explanation="Frequently rated",
                algorithm="PopularityBased",
            )
            for item_id, cnt in items[:n]
        ]
        return recommendations

    def new_user_recommendations(
        self,
        n: int = 10,
        strategy: str = "popularity",
    ) -> list[Recommendation]:
        """Get initial recommendations for a new user.

        Args:
            n: Number of recommendations.
            strategy: "popularity" for popular items, "random" for exploration.

        Returns:
            List of recommendations.
        """
        if strategy == "popularity":
            return self.get_popular_items(n)
        elif strategy == "random":
            return self._get_random_items(n)
        else:
            return self.get_popular_items(n)

    def _get_random_items(self, n: int) -> list[Recommendation]:
        """Get random items for exploration.

        Args:
            n: Number of items.

        Returns:
            List of recommendations for random items.
        """
        all_items = list(self.item_popularity.keys())
        if not all_items:
            return []

        sampled = random.sample(all_items, min(n, len(all_items)))
        recommendations = [
            Recommendation(
                item_id=item_id,
                score=random.random(),
                explanation="Exploration item",
                algorithm="Random",
            )
            for item_id in sampled
        ]
        return recommendations

    def epsilon_greedy(
        self,
        exploit_recommendations: list[Recommendation],
        n: int = 10,
        epsilon: float | None = None,
    ) -> list[Recommendation]:
        """Use epsilon-greedy strategy to blend exploitation and exploration.

        With probability epsilon, explore; otherwise exploit (choose from recommendations).

        Args:
            exploit_recommendations: Base recommendations (exploitation options).
            n: Number of recommendations to return.
            epsilon: Exploration probability (0-1). Uses self.epsilon if None.

        Returns:
            Mixed list of exploitation and exploration recommendations.
        """
        if epsilon is None:
            epsilon = self.epsilon

        recommendations: list[Recommendation] = []
        all_items = set(self.item_popularity.keys())

        # Recommended items (exploitation)
        rec_items = {rec.item_id for rec in exploit_recommendations}

        for _ in range(n):
            if random.random() < epsilon:
                # Explore: pick a random item not already recommended
                explore_items = all_items - rec_items
                if explore_items:
                    item_id = random.choice(list(explore_items))
                    recommendations.append(
                        Recommendation(
                            item_id=item_id,
                            score=random.random() * 2,
                            explanation="Exploration",
                            algorithm="EpsilonGreedy",
                        )
                    )
                    rec_items.add(item_id)
            else:
                # Exploit: pick from base recommendations
                if exploit_recommendations:
                    rec = exploit_recommendations.pop(0)
                    recommendations.append(rec)
                    rec_items.add(rec.item_id)

        return recommendations


class BanditRecommender:
    """Multi-armed bandit approach for cold start items.

    Uses Upper Confidence Bound (UCB) strategy to balance exploration
    and exploitation of new items.
    """

    def __init__(self, exploration_bonus: float = 1.25) -> None:
        """Initialize bandit recommender.

        Args:
            exploration_bonus: Confidence bonus for exploration (higher = more exploration).
        """
        self.exploration_bonus = exploration_bonus
        self.item_counts: dict[str, int] = {}
        self.item_rewards: dict[str, float] = {}

    def add_feedback(self, item_id: str, reward: float) -> None:
        """Record feedback (rating/reward) for an item.

        Args:
            item_id: Item identifier.
            reward: Reward/rating value.
        """
        if item_id not in self.item_counts:
            self.item_counts[item_id] = 0
            self.item_rewards[item_id] = 0.0

        self.item_counts[item_id] += 1
        self.item_rewards[item_id] += reward

    def get_ucb_score(self, item_id: str, total_trials: int) -> float:
        """Compute UCB score for an item.

        UCB = average_reward + exploration_bonus * sqrt(ln(n) / count)

        Args:
            item_id: Item identifier.
            total_trials: Total number of trials across all items.

        Returns:
            UCB score.
        """
        if item_id not in self.item_counts or self.item_counts[item_id] == 0:
            return float("inf")  # Unexplored items get infinite UCB

        avg_reward = self.item_rewards[item_id] / self.item_counts[item_id]
        exploration_term = self.exploration_bonus * math.sqrt(math.log(total_trials) / self.item_counts[item_id])

        return avg_reward + exploration_term

    def recommend(self, all_items: list[str], n: int = 10) -> list[Recommendation]:
        """Get recommendations using UCB strategy.

        Args:
            all_items: All available items.
            n: Number of recommendations.

        Returns:
            List of recommendations sorted by UCB score.
        """
        total_trials = sum(self.item_counts.values())
        if total_trials == 0:
            total_trials = 1

        scores: list[tuple[str, float]] = []
        for item_id in all_items:
            ucb_score = self.get_ucb_score(item_id, total_trials)
            scores.append((item_id, ucb_score))

        # Sort by UCB score descending
        scores.sort(key=lambda x: x[1], reverse=True)

        recommendations = [
            Recommendation(
                item_id=item_id,
                score=score,
                explanation="Bandit-based recommendation",
                algorithm="UCBBandit",
            )
            for item_id, score in scores[:n]
        ]
        return recommendations


class HybridWarmupHandler:
    """Warm up new items using content-based features and bandits.

    Bridges cold start for new items by using their features and UCB strategy.
    """

    def __init__(self, bandit: BanditRecommender | None = None) -> None:
        """Initialize hybrid warmup handler.

        Args:
            bandit: BanditRecommender instance for tracking exploration.
        """
        self.bandit = bandit or BanditRecommender()
        self.item_features: dict[str, dict[str, float]] = {}

    def add_item_features(self, item_id: str, features: dict[str, float]) -> None:
        """Add features for an item.

        Args:
            item_id: Item identifier.
            features: Feature vector.
        """
        self.item_features[item_id] = features

    def add_feedback(self, item_id: str, reward: float) -> None:
        """Record feedback for an item.

        Args:
            item_id: Item identifier.
            reward: Reward/rating value.
        """
        self.bandit.add_feedback(item_id, reward)

    def get_feature_similarity(self, item1_id: str, item2_id: str) -> float:
        """Compute feature similarity between two items.

        Args:
            item1_id: First item ID.
            item2_id: Second item ID.

        Returns:
            Similarity score (0-1).
        """
        if item1_id not in self.item_features or item2_id not in self.item_features:
            return 0.0

        feat1 = self.item_features[item1_id]
        feat2 = self.item_features[item2_id]

        # Cosine similarity
        dot_product = sum(feat1.get(k, 0.0) * feat2.get(k, 0.0) for k in set(feat1.keys()) | set(feat2.keys()))

        mag1 = sum(v**2 for v in feat1.values()) ** 0.5
        mag2 = sum(v**2 for v in feat2.values()) ** 0.5

        if mag1 == 0 or mag2 == 0:
            return 0.0

        return dot_product / (mag1 * mag2)

    def get_feature_neighbors(self, item_id: str, k: int = 5) -> list[tuple[str, float]]:
        """Get items with similar features.

        Args:
            item_id: Reference item.
            k: Number of neighbors.

        Returns:
            List of (item_id, similarity) tuples.
        """
        if item_id not in self.item_features:
            return []

        similarities: list[tuple[str, float]] = []
        for other_id, features in self.item_features.items():
            if other_id == item_id:
                continue
            sim = self.get_feature_similarity(item_id, other_id)
            if sim > 0:
                similarities.append((other_id, sim))

        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:k]
