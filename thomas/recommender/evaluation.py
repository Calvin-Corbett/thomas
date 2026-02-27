"""
Evaluation metrics for recommendation systems.

Includes ranking metrics (Precision, Recall, NDCG, MAP),
rating prediction metrics (RMSE, MAE), and coverage/diversity.
"""

import math
from collections import defaultdict

from thomas.recommender._types import Rating, Recommendation


class PrecisionRecall:
    """Precision and Recall metrics."""

    @staticmethod
    def precision_at_k(recommended_items: list[str], relevant_items: set[str], k: int) -> float:
        """Compute Precision@K.

        Precision@K = |{relevant items in top-K}| / K

        Args:
            recommended_items: Ordered list of recommended item IDs.
            relevant_items: Set of relevant/ideal item IDs.
            k: Cutoff rank.

        Returns:
            Precision@K score (0-1).
        """
        if k <= 0:
            return 0.0

        top_k = recommended_items[:k]
        hits = len(set(top_k) & relevant_items)
        return hits / k

    @staticmethod
    def recall_at_k(recommended_items: list[str], relevant_items: set[str], k: int) -> float:
        """Compute Recall@K.

        Recall@K = |{relevant items in top-K}| / |relevant items|

        Args:
            recommended_items: Ordered list of recommended item IDs.
            relevant_items: Set of relevant/ideal item IDs.
            k: Cutoff rank.

        Returns:
            Recall@K score (0-1).
        """
        if not relevant_items:
            return 0.0

        top_k = recommended_items[:k]
        hits = len(set(top_k) & relevant_items)
        return hits / len(relevant_items)

    @staticmethod
    def f1_at_k(recommended_items: list[str], relevant_items: set[str], k: int) -> float:
        """Compute F1@K.

        F1@K = 2 * (Precision@K * Recall@K) / (Precision@K + Recall@K)

        Args:
            recommended_items: Ordered list of recommended item IDs.
            relevant_items: Set of relevant/ideal item IDs.
            k: Cutoff rank.

        Returns:
            F1@K score (0-1).
        """
        precision = PrecisionRecall.precision_at_k(recommended_items, relevant_items, k)
        recall = PrecisionRecall.recall_at_k(recommended_items, relevant_items, k)

        if precision + recall == 0:
            return 0.0

        return 2 * (precision * recall) / (precision + recall)

    @staticmethod
    def avg_precision(recommended_items: list[str], relevant_items: set[str]) -> float:
        """Compute Average Precision (AP).

        AP = sum of (Precision@k * rel(k)) / |relevant items|

        Args:
            recommended_items: Ordered list of recommended item IDs.
            relevant_items: Set of relevant/ideal item IDs.

        Returns:
            Average Precision (0-1).
        """
        if not relevant_items:
            return 0.0

        score = 0.0
        hits = 0

        for k, item in enumerate(recommended_items, 1):
            if item in relevant_items:
                hits += 1
                score += hits / k

        return score / len(relevant_items)

    @staticmethod
    def hit_rate(recommended_items: list[str], relevant_items: set[str], k: int) -> float:
        """Compute hit rate (whether any relevant items in top-K).

        Args:
            recommended_items: Ordered list of recommended item IDs.
            relevant_items: Set of relevant/ideal item IDs.
            k: Cutoff rank.

        Returns:
            1.0 if any relevant item in top-K, else 0.0.
        """
        top_k = recommended_items[:k]
        return 1.0 if any(item in relevant_items for item in top_k) else 0.0


class RankingMetrics:
    """Ranking-based evaluation metrics."""

    @staticmethod
    def ndcg(recommended_items: list[str], relevant_items: set[str], k: int) -> float:
        """Compute Normalized Discounted Cumulative Gain (NDCG).

        NDCG = DCG / IDCG
        DCG = sum of (rel(i) / log2(i+1))
        IDCG = DCG with ideal ranking (all relevant items first)

        Args:
            recommended_items: Ordered list of recommended item IDs.
            relevant_items: Set of relevant/ideal item IDs.
            k: Cutoff rank.

        Returns:
            NDCG@K score (0-1).
        """
        # Compute DCG
        dcg = 0.0
        for i, item in enumerate(recommended_items[:k], 1):
            if item in relevant_items:
                dcg += 1.0 / math.log2(i + 1)

        # Compute IDCG (ideal DCG)
        idcg = 0.0
        for i in range(1, min(k, len(relevant_items)) + 1):
            idcg += 1.0 / math.log2(i + 1)

        if idcg == 0:
            return 0.0

        return dcg / idcg

    @staticmethod
    def map_at_k(recommendations: list[list[str]], relevant_sets: list[set[str]], k: int) -> float:
        """Compute Mean Average Precision (MAP).

        MAP = mean of AP values across all queries.

        Args:
            recommendations: List of recommendation lists (one per query).
            relevant_sets: List of relevant item sets (one per query).
            k: Cutoff rank.

        Returns:
            Mean Average Precision (0-1).
        """
        if not recommendations:
            return 0.0

        ap_values = [
            PrecisionRecall.avg_precision(recs[:k], relevant) for recs, relevant in zip(recommendations, relevant_sets)
        ]

        return sum(ap_values) / len(ap_values)

    @staticmethod
    def mean_ndcg(recommendations: list[list[str]], relevant_sets: list[set[str]], k: int) -> float:
        """Compute mean NDCG across multiple queries.

        Args:
            recommendations: List of recommendation lists.
            relevant_sets: List of relevant item sets.
            k: Cutoff rank.

        Returns:
            Mean NDCG (0-1).
        """
        if not recommendations:
            return 0.0

        ndcg_values = [RankingMetrics.ndcg(recs, relevant, k) for recs, relevant in zip(recommendations, relevant_sets)]

        return sum(ndcg_values) / len(ndcg_values)


class RatingMetrics:
    """Metrics for rating prediction tasks."""

    @staticmethod
    def rmse(actual: list[float], predicted: list[float]) -> float:
        """Compute Root Mean Squared Error (RMSE).

        RMSE = sqrt(sum((actual - pred)^2) / n)

        Args:
            actual: Actual rating values.
            predicted: Predicted rating values.

        Returns:
            RMSE value.
        """
        if not actual:
            return 0.0

        mse = sum((a - p) ** 2 for a, p in zip(actual, predicted)) / len(actual)
        return math.sqrt(mse)

    @staticmethod
    def mae(actual: list[float], predicted: list[float]) -> float:
        """Compute Mean Absolute Error (MAE).

        MAE = sum(|actual - pred|) / n

        Args:
            actual: Actual rating values.
            predicted: Predicted rating values.

        Returns:
            MAE value.
        """
        if not actual:
            return 0.0

        return sum(abs(a - p) for a, p in zip(actual, predicted)) / len(actual)

    @staticmethod
    def mape(actual: list[float], predicted: list[float]) -> float:
        """Compute Mean Absolute Percentage Error (MAPE).

        Args:
            actual: Actual rating values.
            predicted: Predicted rating values.

        Returns:
            MAPE value.
        """
        if not actual:
            return 0.0

        errors = []
        for a, p in zip(actual, predicted):
            if a != 0:
                errors.append(abs((a - p) / a))

        return sum(errors) / len(errors) if errors else 0.0


class CoverageMetrics:
    """Coverage and diversity metrics."""

    @staticmethod
    def catalog_coverage(recommendations: list[list[str]], all_items: set[str]) -> float:
        """Compute catalog coverage.

        Fraction of items that are recommended at least once.

        Args:
            recommendations: List of recommendation lists.
            all_items: Set of all available items.

        Returns:
            Coverage ratio (0-1).
        """
        recommended = set()
        for recs in recommendations:
            recommended.update(recs)

        if not all_items:
            return 0.0

        return len(recommended) / len(all_items)

    @staticmethod
    def novelty(recommendations: list[list[str]], item_popularity: dict[str, int]) -> float:
        """Compute novelty (inverse popularity).

        Measures how often unpopular items are recommended.

        Args:
            recommendations: List of recommendation lists.
            item_popularity: Popularity count for each item.

        Returns:
            Novelty score (0-1, higher is more novel).
        """
        if not recommendations:
            return 0.0

        total_items = sum(len(recs) for recs in recommendations)
        if total_items == 0:
            return 0.0

        max_popularity = max(item_popularity.values()) if item_popularity else 1

        novelty_sum = 0.0
        for recs in recommendations:
            for item in recs:
                popularity = item_popularity.get(item, 0)
                novelty_sum += 1.0 - (popularity / max_popularity)

        return novelty_sum / total_items

    @staticmethod
    def diversity(recommendations: list[str], item_similarity: dict[tuple[str, str], float]) -> float:
        """Compute diversity (average pairwise distance).

        Args:
            recommendations: List of recommended item IDs.
            item_similarity: Pre-computed similarity matrix.

        Returns:
            Diversity score (0-1, higher is more diverse).
        """
        if len(recommendations) <= 1:
            return 1.0

        distances = []
        for i, item1 in enumerate(recommendations):
            for item2 in recommendations[i + 1 :]:
                key = tuple(sorted([item1, item2]))
                sim = item_similarity.get(key, 0.0)
                distance = 1.0 - sim
                distances.append(distance)

        return sum(distances) / len(distances) if distances else 1.0


class RecommenderEvaluator:
    """Comprehensive evaluation framework."""

    def __init__(self) -> None:
        """Initialize evaluator."""
        self.test_ratings: list[Rating] = []
        self.recommendations: list[list[Recommendation]] = []

    def add_test_ratings(self, ratings: list[Rating]) -> None:
        """Add test ratings for evaluation.

        Args:
            ratings: Test ratings.
        """
        self.test_ratings.extend(ratings)

    def add_recommendations(self, recommendations: list[Recommendation]) -> None:
        """Add recommendations for evaluation.

        Args:
            recommendations: List of recommendations.
        """
        self.recommendations.append(recommendations)

    def evaluate_ranking(self, k: int = 10) -> dict[str, float]:
        """Evaluate ranking metrics.

        Args:
            k: Cutoff rank for metrics.

        Returns:
            Dictionary of metric names to values.
        """
        # Group test ratings by user
        user_items: dict[str, set[str]] = defaultdict(set)
        for rating in self.test_ratings:
            if rating.score >= 4.0:  # Consider 4+ as relevant
                user_items[rating.user_id].add(rating.item_id)

        # Extract recommended items
        rec_lists = [[rec.item_id for rec in recs] for recs in self.recommendations]

        # Compute metrics
        precisions = [
            PrecisionRecall.precision_at_k(recs, user_items.get(str(i), set()), k) for i, recs in enumerate(rec_lists)
        ]
        recalls = [
            PrecisionRecall.recall_at_k(recs, user_items.get(str(i), set()), k) for i, recs in enumerate(rec_lists)
        ]
        ndcgs = [RankingMetrics.ndcg(recs, user_items.get(str(i), set()), k) for i, recs in enumerate(rec_lists)]

        return {
            "precision@k": sum(precisions) / len(precisions) if precisions else 0.0,
            "recall@k": sum(recalls) / len(recalls) if recalls else 0.0,
            "ndcg@k": sum(ndcgs) / len(ndcgs) if ndcgs else 0.0,
        }

    def train_test_split(self, ratings: list[Rating], test_size: float = 0.2) -> tuple[list[Rating], list[Rating]]:
        """Split ratings into train and test sets.

        Args:
            ratings: All ratings.
            test_size: Fraction of data to use for testing.

        Returns:
            Tuple of (train_ratings, test_ratings).
        """
        split_point = int(len(ratings) * (1 - test_size))
        return ratings[:split_point], ratings[split_point:]
