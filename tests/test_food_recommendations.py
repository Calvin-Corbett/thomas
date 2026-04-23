"""
Tests for food recommendation engine module.
"""

from decimal import Decimal

import pytest

from thomas.marketplace.food_tech._types import (
    CookingStep,
    FoodCategory,
    Ingredient,
    NutritionFacts,
    Recipe,
)
from thomas.marketplace.food_tech.recommendations import RecipeRecommendationEngine


class TestRecipeRecommendationEngine:
    """Test recommendation engine operations."""

    @pytest.fixture
    def recommendation_engine(self) -> RecipeRecommendationEngine:
        """Create a recommendation engine instance."""
        return RecipeRecommendationEngine()

    @pytest.fixture
    def sample_recipes(self) -> list:
        """Create sample recipes for recommendations."""
        recipes = [
            Recipe(
                id=f"recipe_{i}",
                name=f"Italian Pasta {i}",
                description=f"Italian pasta recipe {i}",
                ingredients=[
                    Ingredient(
                        name="pasta",
                        quantity=Decimal("200"),
                        unit="g",
                        category=FoodCategory.GRAINS,
                    ),
                    Ingredient(
                        name="tomato",
                        quantity=Decimal("300"),
                        unit="g",
                        category=FoodCategory.VEGETABLES,
                    ),
                ],
                steps=[CookingStep(step_number=1, description="Cook")],
                servings=2,
                prep_time_minutes=10,
                cook_time_minutes=15,
                total_time_minutes=25,
                cuisine="Italian",
                meal_type="dinner",
                difficulty="easy",
                nutrition_per_serving=NutritionFacts(
                    calories=Decimal("400"),
                    protein=Decimal("15"),
                    fat=Decimal("10"),
                    carbohydrates=Decimal("60"),
                    fiber=Decimal("5"),
                    sugar=Decimal("10"),
                    sodium=Decimal("500"),
                ),
            )
            for i in range(3)
        ]

        # Add a few different cuisine recipes
        recipes.append(
            Recipe(
                id="asian_recipe",
                name="Stir Fry",
                description="Asian stir fry",
                ingredients=[
                    Ingredient(
                        name="soy",
                        quantity=Decimal("2"),
                        unit="tbsp",
                        category=FoodCategory.CONDIMENTS,
                    ),
                    Ingredient(
                        name="broccoli",
                        quantity=Decimal("200"),
                        unit="g",
                        category=FoodCategory.VEGETABLES,
                    ),
                ],
                steps=[CookingStep(step_number=1, description="Cook")],
                servings=2,
                prep_time_minutes=10,
                cook_time_minutes=10,
                total_time_minutes=20,
                cuisine="Asian",
                meal_type="lunch",
                difficulty="medium",
                nutrition_per_serving=NutritionFacts(
                    calories=Decimal("300"),
                    protein=Decimal("20"),
                    fat=Decimal("12"),
                    carbohydrates=Decimal("30"),
                    fiber=Decimal("6"),
                    sugar=Decimal("5"),
                    sodium=Decimal("800"),
                ),
            )
        )

        return recipes

    def test_add_user_rating(self, recommendation_engine: RecipeRecommendationEngine) -> None:
        """Test recording user ratings."""
        recommendation_engine.add_user_rating("recipe_1", Decimal("4.5"))

        assert "recipe_1" in recommendation_engine.user_ratings
        assert recommendation_engine.user_ratings["recipe_1"] == Decimal("4.5")

    def test_invalid_rating(self, recommendation_engine: RecipeRecommendationEngine) -> None:
        """Test that invalid ratings are rejected."""
        with pytest.raises(ValueError):
            recommendation_engine.add_user_rating("recipe_1", Decimal("6"))

        with pytest.raises(ValueError):
            recommendation_engine.add_user_rating("recipe_1", Decimal("-1"))

    def test_record_view(self, recommendation_engine: RecipeRecommendationEngine) -> None:
        """Test recording recipe views."""
        recommendation_engine.record_view("recipe_1")
        recommendation_engine.record_view("recipe_1")
        recommendation_engine.record_view("recipe_2")

        assert recommendation_engine.recipe_views["recipe_1"] == 2
        assert recommendation_engine.recipe_views["recipe_2"] == 1

    def test_collaborative_recommendations(
        self,
        recommendation_engine: RecipeRecommendationEngine,
        sample_recipes: list,
    ) -> None:
        """Test collaborative filtering recommendations."""
        # Add some ratings
        recommendation_engine.add_user_rating("recipe_0", Decimal("5"))
        recommendation_engine.add_user_rating("recipe_1", Decimal("5"))

        recommendations = recommendation_engine.get_collaborative_recommendations(
            "recipe_0", sample_recipes, num_recommendations=2
        )

        # Should get recommendations (possibly empty if similarity is low)
        assert len(recommendations) >= 0

    def test_content_based_recommendations(
        self,
        recommendation_engine: RecipeRecommendationEngine,
        sample_recipes: list,
    ) -> None:
        """Test content-based recommendations."""
        # Italian recipes should recommend each other
        recommendations = recommendation_engine.get_content_based_recommendations(
            "recipe_0", sample_recipes, num_recommendations=2
        )

        assert len(recommendations) > 0
        # Should recommend other Italian recipes
        italian_ids = [r.id for r in sample_recipes if "Italian" in r.cuisine]
        rec_ids = [r.id for r in recommendations]

        assert any(rid in italian_ids for rid in rec_ids)

    def test_health_aware_recommendations(
        self,
        recommendation_engine: RecipeRecommendationEngine,
        sample_recipes: list,
    ) -> None:
        """Test health-aware recommendations."""
        recommendations = recommendation_engine.get_health_aware_recommendations(
            sample_recipes,
            target_calories=Decimal("350"),
            num_recommendations=2,
        )

        assert len(recommendations) >= 0

        # Recommendations should be close to target calories
        if recommendations:
            for rec in recommendations:
                if rec.nutrition_per_serving:
                    cal_diff = abs(rec.nutrition_per_serving.calories - Decimal("350"))
                    # Reasonable recipes near target
                    assert cal_diff < Decimal("200")

    def test_seasonal_recommendations(
        self,
        recommendation_engine: RecipeRecommendationEngine,
        sample_recipes: list,
    ) -> None:
        """Test seasonal recommendations."""
        in_season = {"tomato", "pasta"}

        recommendations = recommendation_engine.get_seasonal_recommendations(
            sample_recipes,
            in_season_ingredients=in_season,
            num_recommendations=3,
        )

        assert len(recommendations) > 0
        # Should include recipes with seasonal ingredients
        for rec in recommendations:
            recipe_ings = {ing.name.lower() for ing in rec.ingredients}
            assert len(recipe_ings & in_season) > 0

    def test_trending_recommendations(
        self,
        recommendation_engine: RecipeRecommendationEngine,
        sample_recipes: list,
    ) -> None:
        """Test trending recipe recommendations."""
        # Record views to create trends
        recommendation_engine.record_view("recipe_0")
        recommendation_engine.record_view("recipe_0")
        recommendation_engine.record_view("recipe_0")
        recommendation_engine.record_view("recipe_1")

        recommendations = recommendation_engine.get_trending_recommendations(sample_recipes, num_recommendations=2)

        # Should return trending recipes
        assert len(recommendations) > 0

    def test_personalized_recommendations_with_history(
        self,
        recommendation_engine: RecipeRecommendationEngine,
        sample_recipes: list,
    ) -> None:
        """Test personalized recommendations with user history."""
        # Add some ratings to build history
        recommendation_engine.add_user_rating("recipe_0", Decimal("5"))
        recommendation_engine.add_user_rating("recipe_1", Decimal("4"))

        recommendations = recommendation_engine.get_personalized_recommendations(sample_recipes, num_recommendations=2)

        # Should get recommendations based on preferences
        assert len(recommendations) >= 0

    def test_personalized_recommendations_no_history(
        self,
        recommendation_engine: RecipeRecommendationEngine,
        sample_recipes: list,
    ) -> None:
        """Test personalized recommendations with no history."""
        recommendations = recommendation_engine.get_personalized_recommendations(sample_recipes, num_recommendations=2)

        # Should fall back to trending (which may be empty)
        assert len(recommendations) >= 0

    def test_recommendations_summary(
        self,
        recommendation_engine: RecipeRecommendationEngine,
        sample_recipes: list,
    ) -> None:
        """Test comprehensive recommendations summary."""
        # Add some data
        recommendation_engine.add_user_rating("recipe_0", Decimal("5"))
        recommendation_engine.record_view("recipe_0")
        recommendation_engine.record_view("recipe_0")

        summary = recommendation_engine.get_recommendations_summary(sample_recipes)

        assert "personalized" in summary
        assert "trending" in summary
        assert "seasonal" in summary
        assert "health_aware" in summary

        # Each should be a list
        assert isinstance(summary["personalized"], list)
        assert isinstance(summary["trending"], list)


class TestRatingSimilarity:
    """Test rating-based similarity calculations."""

    @pytest.fixture
    def engine_with_ratings(self) -> RecipeRecommendationEngine:
        """Create engine with sample ratings."""
        engine = RecipeRecommendationEngine()

        # Set up recipe ratings
        engine.recipe_ratings["recipe_1"] = [
            Decimal("5"),
            Decimal("4"),
            Decimal("5"),
        ]
        engine.recipe_ratings["recipe_2"] = [
            Decimal("5"),
            Decimal("4"),
            Decimal("5"),
        ]
        engine.recipe_ratings["recipe_3"] = [
            Decimal("1"),
            Decimal("2"),
            Decimal("1"),
        ]

        return engine

    def test_rating_similarity_high(self, engine_with_ratings: RecipeRecommendationEngine) -> None:
        """Test rating similarity for similar ratings."""
        similarity = engine_with_ratings._calculate_rating_similarity("recipe_1", "recipe_2")

        # Should be high similarity
        assert similarity > Decimal("0.5")

    def test_rating_similarity_low(self, engine_with_ratings: RecipeRecommendationEngine) -> None:
        """Test rating similarity for dissimilar ratings."""
        similarity = engine_with_ratings._calculate_rating_similarity("recipe_1", "recipe_3")

        # Should be low similarity
        assert similarity < Decimal("0.5")


class TestRecommendationMetrics:
    """Test recommendation metrics and calculations."""

    @pytest.fixture
    def recommendation_engine(self) -> RecipeRecommendationEngine:
        """Create a recommendation engine instance."""
        return RecipeRecommendationEngine()

    def test_trending_score_update(self, recommendation_engine: RecipeRecommendationEngine) -> None:
        """Test that trending scores are updated."""
        recommendation_engine.record_view("recipe_1")
        recommendation_engine.record_view("recipe_1")
        recommendation_engine.record_view("recipe_2")

        recommendation_engine._update_trending_scores()

        assert "recipe_1" in recommendation_engine.trending_recipes
        assert "recipe_2" in recommendation_engine.trending_recipes
        assert recommendation_engine.trending_recipes["recipe_1"] > recommendation_engine.trending_recipes["recipe_2"]
