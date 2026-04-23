"""
Recommendation pipeline combining multiple strategies.

The pipeline coordinates candidate generation, scoring, filtering,
ranking, and explanation generation.
"""

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from thomas.marketplace.recommender._types import Rating, Recommendation


class RecommendationPipeline:
    """End-to-end recommendation pipeline.

    Stages:
    1. Candidate generation (from multiple models)
    2. Scoring (combine signals)
    3. Filtering (business rules, diversity)
    4. Ranking (final reorder)
    5. Explanation (why recommended)
    """

    def __init__(self) -> None:
        """Initialize recommendation pipeline."""
        self.candidate_generators: dict[str, Callable] = {}
        self.ranker: Callable | None = None
        self.filters: list[Callable] = []
        self.ratings: list[Rating] = []
        self.user_history: dict[str, set[str]] = defaultdict(set)

    def add_ratings(self, ratings: list[Rating]) -> None:
        """Add ratings to pipeline.

        Args:
            ratings: List of ratings.
        """
        self.ratings.extend(ratings)
        for rating in ratings:
            self.user_history[rating.user_id].add(rating.item_id)

    def register_candidate_generator(
        self,
        name: str,
        generator: Callable[[str, int], list[Recommendation]],
    ) -> None:
        """Register a candidate generation strategy.

        Args:
            name: Name of the generator.
            generator: Function(user_id, num_candidates) -> List[Recommendation].
        """
        self.candidate_generators[name] = generator

    def set_ranker(
        self,
        ranker: Callable[[list[Recommendation]], list[Recommendation]],
    ) -> None:
        """Set the final ranking function.

        Args:
            ranker: Function(recommendations) -> ranked_recommendations.
        """
        self.ranker = ranker

    def add_filter(self, filter_fn: Callable[[Recommendation], bool]) -> None:
        """Add a filter function.

        Filter functions return True to keep a recommendation, False to discard.

        Args:
            filter_fn: Function(recommendation) -> bool.
        """
        self.filters.append(filter_fn)

    def generate_candidates(self, user_id: str, per_generator: int = 20) -> dict[str, list[Recommendation]]:
        """Generate candidates from all registered generators.

        Args:
            user_id: User to generate candidates for.
            per_generator: Number of candidates per generator.

        Returns:
            Dictionary mapping generator name to list of recommendations.
        """
        candidates = {}
        for name, generator in self.candidate_generators.items():
            try:
                recs = generator(user_id, per_generator)
                candidates[name] = recs
            except Exception:
                candidates[name] = []

        return candidates

    def combine_scores(
        self,
        candidates: dict[str, list[Recommendation]],
        weights: dict[str, float] | None = None,
    ) -> list[Recommendation]:
        """Combine scores from multiple candidate generators.

        Weighted average: score = sum(weight * score) for all generators.

        Args:
            candidates: Dictionary of generator_name -> recommendations.
            weights: Optional weights for each generator. If None, use equal weights.

        Returns:
            List of recommendations with combined scores.
        """
        if not candidates:
            return []

        # Use equal weights if not provided
        if weights is None:
            weight = 1.0 / len(candidates)
            weights = {name: weight for name in candidates}

        combined: dict[str, list[tuple[float, str]]] = defaultdict(list)

        for gen_name, recs in candidates.items():
            gen_weight = weights.get(gen_name, 0.0)

            for rec in recs:
                combined[rec.item_id].append((gen_weight * rec.score, gen_name))

        result = []
        for item_id, scores in combined.items():
            total_score = sum(s for s, _ in scores)
            sources = [source for _, source in scores]

            rec = Recommendation(
                item_id=item_id,
                score=total_score,
                explanation=f"Combined from {', '.join(set(sources))}",
                algorithm="PipelineEnsemble",
            )
            result.append(rec)

        return result

    def apply_filters(self, recommendations: list[Recommendation]) -> list[Recommendation]:
        """Apply all registered filters.

        Args:
            recommendations: List of recommendations.

        Returns:
            Filtered list of recommendations.
        """
        filtered = recommendations
        for filter_fn in self.filters:
            filtered = [rec for rec in filtered if filter_fn(rec)]

        return filtered

    def rank(self, recommendations: list[Recommendation]) -> list[Recommendation]:
        """Apply final ranking.

        Args:
            recommendations: List of recommendations.

        Returns:
            Ranked list of recommendations.
        """
        if self.ranker is not None:
            return self.ranker(recommendations)

        # Default: sort by score descending
        return sorted(recommendations, key=lambda r: r.score, reverse=True)

    def recommend(
        self,
        user_id: str,
        n: int = 10,
        weights: dict[str, float] | None = None,
        per_generator: int = 20,
    ) -> list[Recommendation]:
        """Get top-N recommendations through full pipeline.

        Args:
            user_id: User to recommend for.
            n: Number of recommendations to return.
            weights: Optional weights for candidate generators.
            per_generator: Number of candidates per generator.

        Returns:
            Top-N ranked recommendations.
        """
        # Stage 1: Candidate generation
        candidates = self.generate_candidates(user_id, per_generator)

        # Stage 2: Scoring
        scored = self.combine_scores(candidates, weights)

        # Stage 3: Filtering
        filtered = self.apply_filters(scored)

        # Stage 4: Ranking
        ranked = self.rank(filtered)

        return ranked[:n]

    def filter_already_seen(self, user_id: str) -> Callable:
        """Create a filter that excludes items user has already seen.

        Args:
            user_id: User to filter for.

        Returns:
            Filter function.
        """
        seen = self.user_history.get(user_id, set())

        def filter_fn(rec: Recommendation) -> bool:
            return rec.item_id not in seen

        return filter_fn

    def filter_by_score_threshold(self, min_score: float) -> Callable:
        """Create a filter for minimum recommendation score.

        Args:
            min_score: Minimum score threshold.

        Returns:
            Filter function.
        """

        def filter_fn(rec: Recommendation) -> bool:
            return rec.score >= min_score

        return filter_fn

    def filter_diversity(
        self,
        max_recommendations: int,
        item_distance: dict[tuple[str, str], float],
        min_diversity: float = 0.3,
    ) -> Callable:
        """Create a filter for diversity (select non-similar items).

        Args:
            max_recommendations: Maximum items to return.
            item_distance: Dictionary of (item_id1, item_id2) -> distance.
            min_diversity: Minimum distance from selected items.

        Returns:
            Filter function that enforces diversity.
        """
        selected: list[str] = []

        def filter_fn(rec: Recommendation) -> bool:
            if len(selected) >= max_recommendations:
                return False

            # Check distance to already selected items
            for sel_item in selected:
                key = tuple(sorted([rec.item_id, sel_item]))
                distance = item_distance.get(key, 1.0)
                if distance < min_diversity:
                    return False

            selected.append(rec.item_id)
            return True

        return filter_fn


class ExplanationGenerator:
    """Generate explanations for recommendations."""

    def __init__(self) -> None:
        """Initialize explanation generator."""
        self.user_profiles: dict[str, dict[str, Any]] = {}
        self.item_details: dict[str, dict[str, Any]] = {}

    def set_user_profile(self, user_id: str, profile: dict[str, Any]) -> None:
        """Set user profile information.

        Args:
            user_id: User identifier.
            profile: User profile dictionary.
        """
        self.user_profiles[user_id] = profile

    def set_item_details(self, item_id: str, details: dict[str, Any]) -> None:
        """Set item details.

        Args:
            item_id: Item identifier.
            details: Item details dictionary.
        """
        self.item_details[item_id] = details

    def generate_explanation(
        self,
        user_id: str,
        item_id: str,
        algorithm: str,
        similarity_reason: str | None = None,
    ) -> str:
        """Generate a human-readable explanation.

        Args:
            user_id: User being recommended to.
            item_id: Item being recommended.
            algorithm: Recommendation algorithm used.
            similarity_reason: Optional reason from similarity computation.

        Returns:
            Explanation string.
        """
        explanations = []

        if algorithm == "UserBasedCF":
            explanations.append("Users like you also enjoyed this")
        elif algorithm == "ItemBasedCF":
            explanations.append("Similar to items you've liked")
        elif algorithm == "ContentBased":
            explanations.append("Matches your preferences")
        elif algorithm == "MatrixFactorization":
            explanations.append("Predicted to be of interest")
        elif algorithm == "SessionBased":
            explanations.append("Trending in your session")
        elif algorithm == "PopularityBased":
            explanations.append("Popular with users")
        else:
            explanations.append(f"Recommended by {algorithm}")

        if similarity_reason:
            explanations.append(f": {similarity_reason}")

        return "".join(explanations)

    def explain_recommendations(
        self,
        user_id: str,
        recommendations: list[Recommendation],
    ) -> list[Recommendation]:
        """Add explanations to recommendations.

        Args:
            user_id: User being recommended to.
            recommendations: List of recommendations.

        Returns:
            Recommendations with enhanced explanations.
        """
        explained = []
        for rec in recommendations:
            explanation = self.generate_explanation(user_id, rec.item_id, rec.algorithm)
            rec.explanation = explanation
            explained.append(rec)

        return explained


class A_BTestManager:
    """Manage A/B tests for multiple recommendation models."""

    def __init__(self) -> None:
        """Initialize A/B test manager."""
        self.variants: dict[str, Callable] = {}
        self.variant_counts: dict[str, int] = {}
        self.variant_scores: dict[str, float] = {}

    def register_variant(
        self,
        name: str,
        recommender: Callable[[str, int], list[Recommendation]],
    ) -> None:
        """Register a variant for A/B testing.

        Args:
            name: Variant name.
            recommender: Recommendation function.
        """
        self.variants[name] = recommender
        self.variant_counts[name] = 0
        self.variant_scores[name] = 0.0

    def select_variant(self, user_id: str) -> str:
        """Select a variant for a user (round-robin for simplicity).

        Args:
            user_id: User identifier.

        Returns:
            Selected variant name.
        """
        if not self.variants:
            raise ValueError("No variants registered")

        # Simple round-robin selection
        variant_names = sorted(self.variants.keys())
        user_hash = hash(user_id)
        return variant_names[user_hash % len(variant_names)]

    def recommend(
        self,
        user_id: str,
        n: int = 10,
    ) -> tuple[str, list[Recommendation]]:
        """Get recommendation from selected variant.

        Args:
            user_id: User to recommend for.
            n: Number of recommendations.

        Returns:
            Tuple of (variant_name, recommendations).
        """
        variant = self.select_variant(user_id)
        recommender = self.variants[variant]
        recs = recommender(user_id, n)

        self.variant_counts[variant] += 1
        return variant, recs

    def record_feedback(
        self,
        variant: str,
        score: float,
    ) -> None:
        """Record feedback for a variant.

        Args:
            variant: Variant name.
            score: Performance score (e.g., click rate, rating).
        """
        self.variant_scores[variant] += score

    def get_statistics(self) -> dict[str, dict[str, float]]:
        """Get performance statistics for all variants.

        Returns:
            Dictionary mapping variant names to stats.
        """
        stats = {}
        for variant in self.variants:
            count = self.variant_counts[variant]
            avg_score = self.variant_scores[variant] / count if count > 0 else 0.0
            stats[variant] = {
                "count": count,
                "total_score": self.variant_scores[variant],
                "average_score": avg_score,
            }

        return stats
