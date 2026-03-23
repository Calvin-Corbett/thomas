"""
Recommendations module for food technology platform.

Handles recipe recommendations using collaborative filtering, content-based
filtering, health-aware recommendations, and personalization.
"""

from datetime import datetime
from decimal import Decimal

from thomas.marketplace.food_tech._types import Recipe


class RecipeRecommendationEngine:
    """Generates personalized recipe recommendations."""

    def __init__(self) -> None:
        """Initialize recommendation engine."""
        self.user_ratings: dict[str, Decimal] = {}  # recipe_id -> rating
        self.recipe_ratings: dict[str, list[Decimal]] = {}  # recipe_id -> [ratings]
        self.user_history: list[tuple[str, datetime]] = []  # (recipe_id, timestamp)
        self.recipe_views: dict[str, int] = {}  # recipe_id -> view_count
        self.trending_recipes: dict[str, Decimal] = {}  # recipe_id -> popularity_velocity

    def add_user_rating(self, recipe_id: str, rating: Decimal) -> None:
        """Record a user rating for a recipe.

        Args:
            recipe_id: Recipe ID.
            rating: Rating value (0-5).
        """
        if not (Decimal(0) <= rating <= Decimal(5)):
            raise ValueError("Rating must be between 0 and 5")

        self.user_ratings[recipe_id] = rating
        self.user_history.append((recipe_id, datetime.now()))

        if recipe_id not in self.recipe_ratings:
            self.recipe_ratings[recipe_id] = []
        self.recipe_ratings[recipe_id].append(rating)

    def record_view(self, recipe_id: str) -> None:
        """Record a view for a recipe (for popularity tracking).

        Args:
            recipe_id: Recipe ID.
        """
        self.recipe_views[recipe_id] = self.recipe_views.get(recipe_id, 0) + 1

    def get_collaborative_recommendations(
        self,
        recipe_id: str,
        recipes: list[Recipe],
        num_recommendations: int = 5,
    ) -> list[Recipe]:
        """Get recommendations using collaborative filtering.

        Users who liked recipe X also liked Y.

        Args:
            recipe_id: Reference recipe.
            recipes: All available recipes.
            num_recommendations: Number of recommendations to return.

        Returns:
            List[Recipe]: Recommended recipes.
        """
        if recipe_id not in self.user_ratings:
            return []

        # Find recipes with similar rating patterns
        similar_recipes = []

        for recipe in recipes:
            if recipe.id == recipe_id:
                continue

            # Calculate similarity based on rating vectors
            similarity = self._calculate_rating_similarity(recipe_id, recipe.id)

            if similarity > 0:
                similar_recipes.append((recipe, similarity))

        similar_recipes.sort(key=lambda x: x[1], reverse=True)
        return [r[0] for r in similar_recipes[:num_recommendations]]

    def get_content_based_recommendations(
        self,
        recipe_id: str,
        recipes: list[Recipe],
        num_recommendations: int = 5,
    ) -> list[Recipe]:
        """Get recommendations based on recipe similarity (ingredients, cuisine).

        Args:
            recipe_id: Reference recipe.
            recipes: All available recipes.
            num_recommendations: Number of recommendations to return.

        Returns:
            List[Recipe]: Recommended recipes.
        """
        reference = None
        for r in recipes:
            if r.id == recipe_id:
                reference = r
                break

        if not reference:
            return []

        similar_recipes = []
        ref_ingredients = {ing.name.lower() for ing in reference.ingredients}

        for recipe in recipes:
            if recipe.id == recipe_id:
                continue

            recipe_ingredients = {ing.name.lower() for ing in recipe.ingredients}

            # Jaccard similarity on ingredients
            intersection = len(ref_ingredients & recipe_ingredients)
            union = len(ref_ingredients | recipe_ingredients)
            ingredient_similarity = Decimal(intersection) / Decimal(union) if union > 0 else Decimal(0)

            # Cuisine match
            cuisine_match = recipe.cuisine.lower() == reference.cuisine.lower()

            # Combined score
            score = ingredient_similarity * Decimal("0.6") + (Decimal("0.4") if cuisine_match else Decimal(0))

            if score > 0:
                similar_recipes.append((recipe, score))

        similar_recipes.sort(key=lambda x: x[1], reverse=True)
        return [r[0] for r in similar_recipes[:num_recommendations]]

    def get_health_aware_recommendations(
        self,
        recipes: list[Recipe],
        target_calories: Decimal | None = None,
        target_protein_grams: Decimal | None = None,
        avoid_nutrients: set[str] | None = None,
        num_recommendations: int = 5,
    ) -> list[Recipe]:
        """Get recommendations based on nutritional goals.

        Args:
            recipes: All available recipes.
            target_calories: Target calories per serving.
            target_protein_grams: Target protein per serving.
            avoid_nutrients: Nutrients to minimize.
            num_recommendations: Number of recommendations to return.

        Returns:
            List[Recipe]: Recommended recipes meeting nutritional goals.
        """
        scored_recipes = []

        for recipe in recipes:
            if not recipe.nutrition_per_serving:
                continue

            score = Decimal("100")

            # Calorie alignment
            if target_calories:
                calorie_diff = abs(recipe.nutrition_per_serving.calories - target_calories)
                score -= min(calorie_diff / Decimal("100"), Decimal("30"))

            # Protein alignment
            if target_protein_grams:
                protein_diff = abs(recipe.nutrition_per_serving.protein - target_protein_grams)
                score -= min(protein_diff / Decimal("10"), Decimal("20"))

            # Avoid nutrients
            if avoid_nutrients:
                if "sodium" in avoid_nutrients:
                    if recipe.nutrition_per_serving.sodium > Decimal("500"):
                        score -= Decimal("15")

            if score > 0:
                scored_recipes.append((recipe, score))

        scored_recipes.sort(key=lambda x: x[1], reverse=True)
        return [r[0] for r in scored_recipes[:num_recommendations]]

    def get_seasonal_recommendations(
        self,
        recipes: list[Recipe],
        in_season_ingredients: set[str],
        num_recommendations: int = 5,
    ) -> list[Recipe]:
        """Get recommendations based on in-season ingredients.

        Args:
            recipes: All available recipes.
            in_season_ingredients: Set of ingredients currently in season.
            num_recommendations: Number of recommendations to return.

        Returns:
            List[Recipe]: Recommended recipes using seasonal ingredients.
        """
        scored_recipes = []

        for recipe in recipes:
            recipe_ingredients = {ing.name.lower() for ing in recipe.ingredients}
            seasonal_overlap = len(recipe_ingredients & in_season_ingredients)

            if seasonal_overlap > 0:
                score = Decimal(seasonal_overlap) / Decimal(len(recipe_ingredients))
                scored_recipes.append((recipe, score))

        scored_recipes.sort(key=lambda x: x[1], reverse=True)
        return [r[0] for r in scored_recipes[:num_recommendations]]

    def get_trending_recommendations(
        self,
        recipes: list[Recipe],
        num_recommendations: int = 5,
    ) -> list[Recipe]:
        """Get trending recipes based on popularity velocity.

        Args:
            recipes: All available recipes.
            num_recommendations: Number of recommendations to return.

        Returns:
            List[Recipe]: Trending recipes.
        """
        # Calculate popularity velocity (view rate over time)
        self._update_trending_scores()

        scored_recipes = [(r, self.trending_recipes.get(r.id, Decimal(0))) for r in recipes]

        scored_recipes.sort(key=lambda x: x[1], reverse=True)
        return [r[0] for r in scored_recipes[:num_recommendations]]

    def get_personalized_recommendations(
        self,
        recipes: list[Recipe],
        num_recommendations: int = 5,
    ) -> list[Recipe]:
        """Get personalized recommendations based on user history and preferences.

        Args:
            recipes: All available recipes.
            num_recommendations: Number of recommendations to return.

        Returns:
            List[Recipe]: Personalized recommendations.
        """
        if not self.user_history:
            # Return trending recipes if no history
            return self.get_trending_recommendations(recipes, num_recommendations)

        # Get most liked recipe
        most_liked = max(self.user_ratings.items(), key=lambda x: x[1], default=(None, Decimal(0)))

        if most_liked[0]:
            # Use collaborative filtering on most-liked recipe
            collab_recs = self.get_collaborative_recommendations(most_liked[0], recipes, num_recommendations)

            if collab_recs:
                return collab_recs

        # Fall back to content-based
        if self.user_history:
            return self.get_content_based_recommendations(self.user_history[-1][0], recipes, num_recommendations)

        return []

    def _calculate_rating_similarity(self, recipe_id_1: str, recipe_id_2: str) -> Decimal:
        """Calculate similarity between two recipes based on rating patterns."""
        if recipe_id_1 not in self.recipe_ratings or recipe_id_2 not in self.recipe_ratings:
            return Decimal(0)

        ratings_1 = self.recipe_ratings[recipe_id_1]
        ratings_2 = self.recipe_ratings[recipe_id_2]

        if not ratings_1 or not ratings_2:
            return Decimal(0)

        avg_1 = sum(ratings_1) / len(ratings_1)
        avg_2 = sum(ratings_2) / len(ratings_2)

        # Pearson correlation
        numerator = sum(
            (r1 - avg_1) * (r2 - avg_2) for r1, r2 in zip(ratings_1[: len(ratings_2)], ratings_2[: len(ratings_1)])
        )
        denominator = (sum((r - avg_1) ** 2 for r in ratings_1) ** Decimal("0.5")) * (
            sum((r - avg_2) ** 2 for r in ratings_2) ** Decimal("0.5")
        )

        if denominator == 0:
            return Decimal(0)

        return (numerator / denominator).quantize(Decimal("0.01"))

    def _update_trending_scores(self) -> None:
        """Update trending recipe scores based on view velocity."""
        current_time = datetime.now()
        recent_cutoff = current_time.timestamp() - (7 * 24 * 60 * 60)  # 7 days

        for recipe_id, view_count in self.recipe_views.items():
            # Simple velocity: views in last week / 7
            trending_score = Decimal(view_count) / Decimal(7)
            self.trending_recipes[recipe_id] = trending_score

    def get_recommendations_summary(
        self,
        recipes: list[Recipe],
    ) -> dict[str, list[Recipe]]:
        """Get comprehensive recommendation summary using all strategies.

        Args:
            recipes: All available recipes.

        Returns:
            Dict[str, List[Recipe]]: Recommendations by strategy.
        """
        return {
            "personalized": self.get_personalized_recommendations(recipes, 3),
            "trending": self.get_trending_recommendations(recipes, 3),
            "seasonal": self.get_seasonal_recommendations(recipes, {"tomato", "basil", "zucchini"}, 3),
            "health_aware": self.get_health_aware_recommendations(recipes, 3),
        }
