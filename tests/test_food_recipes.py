"""
Tests for recipe management module.
"""

from decimal import Decimal

import pytest

from thomas.marketplace.food_tech._exceptions import (
    InvalidRecipeError,
    RecipeNotFoundError,
    RecipeParsingError,
)
from thomas.marketplace.food_tech._types import (
    CookingStep,
    FoodCategory,
    Ingredient,
    Recipe,
)
from thomas.marketplace.food_tech.recipes import IngredientParser, RecipeManager


class TestRecipeManager:
    """Test recipe management operations."""

    @pytest.fixture
    def recipe_manager(self) -> RecipeManager:
        """Create a recipe manager instance."""
        return RecipeManager()

    @pytest.fixture
    def sample_ingredients(self) -> list:
        """Create sample ingredients."""
        return [
            Ingredient(
                name="Chicken Breast",
                quantity=Decimal("500"),
                unit="g",
                category=FoodCategory.PROTEINS,
            ),
            Ingredient(
                name="Brown Rice",
                quantity=Decimal("2"),
                unit="cup",
                category=FoodCategory.GRAINS,
            ),
            Ingredient(
                name="Broccoli",
                quantity=Decimal("1"),
                unit="lb",
                category=FoodCategory.VEGETABLES,
            ),
        ]

    @pytest.fixture
    def sample_steps(self) -> list:
        """Create sample cooking steps."""
        return [
            CookingStep(
                step_number=1,
                description="Preheat oven to 375°F",
                temperature_celsius=190,
            ),
            CookingStep(
                step_number=2,
                description="Season chicken with salt and pepper",
                duration_minutes=5,
            ),
            CookingStep(
                step_number=3,
                description="Bake chicken for 25 minutes",
                duration_minutes=25,
            ),
        ]

    def test_create_recipe(self, recipe_manager: RecipeManager, sample_ingredients, sample_steps) -> None:
        """Test recipe creation."""
        recipe = recipe_manager.create_recipe(
            name="Baked Chicken with Rice",
            description="Healthy baked chicken served with brown rice",
            ingredients=sample_ingredients,
            steps=sample_steps,
            servings=4,
            prep_time_minutes=10,
            cook_time_minutes=30,
            cuisine="American",
            meal_type="dinner",
            difficulty="easy",
            tags={"healthy", "quick"},
        )

        assert recipe.name == "Baked Chicken with Rice"
        assert recipe.servings == 4
        assert len(recipe.ingredients) == 3
        assert recipe.version == 1
        assert "healthy" in recipe.tags

    def test_create_invalid_recipe(self, recipe_manager: RecipeManager, sample_steps) -> None:
        """Test creation of invalid recipe."""
        with pytest.raises(InvalidRecipeError):
            recipe_manager.create_recipe(
                name="",
                description="Test",
                ingredients=[],
                steps=sample_steps,
                servings=1,
                prep_time_minutes=10,
                cook_time_minutes=10,
                cuisine="Test",
                meal_type="dinner",
                difficulty="easy",
            )

    def test_get_recipe(self, recipe_manager: RecipeManager, sample_ingredients, sample_steps) -> None:
        """Test recipe retrieval."""
        created = recipe_manager.create_recipe(
            name="Test Recipe",
            description="Test",
            ingredients=sample_ingredients,
            steps=sample_steps,
            servings=2,
            prep_time_minutes=10,
            cook_time_minutes=20,
            cuisine="Test",
            meal_type="lunch",
            difficulty="medium",
        )

        retrieved = recipe_manager.get_recipe(created.id)
        assert retrieved.name == "Test Recipe"
        assert retrieved.id == created.id

    def test_get_nonexistent_recipe(self, recipe_manager: RecipeManager) -> None:
        """Test retrieval of nonexistent recipe."""
        with pytest.raises(RecipeNotFoundError):
            recipe_manager.get_recipe("nonexistent_id")

    def test_update_recipe(self, recipe_manager: RecipeManager, sample_ingredients, sample_steps) -> None:
        """Test recipe updates create new versions."""
        original = recipe_manager.create_recipe(
            name="Original Name",
            description="Test",
            ingredients=sample_ingredients,
            steps=sample_steps,
            servings=2,
            prep_time_minutes=10,
            cook_time_minutes=20,
            cuisine="Test",
            meal_type="lunch",
            difficulty="easy",
        )

        updated = recipe_manager.update_recipe(
            original.id,
            name="Updated Name",
            servings=4,
        )

        assert updated.name == "Updated Name"
        assert updated.version == 2
        assert updated.servings == 4

        # Original still accessible at version 1
        original_v1 = recipe_manager.get_recipe(original.id, version=1)
        assert original_v1.name == "Original Name"

    def test_delete_recipe(self, recipe_manager: RecipeManager, sample_ingredients, sample_steps) -> None:
        """Test recipe deletion."""
        recipe = recipe_manager.create_recipe(
            name="To Delete",
            description="Test",
            ingredients=sample_ingredients,
            steps=sample_steps,
            servings=1,
            prep_time_minutes=10,
            cook_time_minutes=10,
            cuisine="Test",
            meal_type="breakfast",
            difficulty="easy",
        )

        recipe_manager.delete_recipe(recipe.id)

        with pytest.raises(RecipeNotFoundError):
            recipe_manager.get_recipe(recipe.id)

    def test_search_recipes(self, recipe_manager: RecipeManager, sample_ingredients, sample_steps) -> None:
        """Test recipe search functionality."""
        recipe_manager.create_recipe(
            name="Chicken Stir Fry",
            description="Asian style chicken",
            ingredients=sample_ingredients,
            steps=sample_steps,
            servings=2,
            prep_time_minutes=15,
            cook_time_minutes=15,
            cuisine="Asian",
            meal_type="dinner",
            difficulty="medium",
            tags={"quick", "spicy"},
        )

        recipe_manager.create_recipe(
            name="Chicken Salad",
            description="Fresh salad with chicken",
            ingredients=sample_ingredients[:2],
            steps=sample_steps[:1],
            servings=1,
            prep_time_minutes=10,
            cook_time_minutes=0,
            cuisine="Mediterranean",
            meal_type="lunch",
            difficulty="easy",
            tags={"healthy", "quick"},
        )

        # Search by keyword
        results = recipe_manager.search_recipes(keywords=["chicken"])
        assert len(results) == 2

        # Search by tags
        results = recipe_manager.search_recipes(tags={"quick"})
        assert len(results) == 2

        # Search by cuisine
        results = recipe_manager.search_recipes(cuisine="Asian")
        assert len(results) == 1

        # Search by max prep time
        results = recipe_manager.search_recipes(max_prep_time=10)
        assert len(results) == 1

    def test_recipe_similarity(self, recipe_manager: RecipeManager, sample_ingredients, sample_steps) -> None:
        """Test recipe similarity calculation."""
        recipe1 = recipe_manager.create_recipe(
            name="Recipe 1",
            description="Test",
            ingredients=sample_ingredients,
            steps=sample_steps,
            servings=2,
            prep_time_minutes=10,
            cook_time_minutes=20,
            cuisine="Test",
            meal_type="dinner",
            difficulty="easy",
        )

        recipe2 = recipe_manager.create_recipe(
            name="Recipe 2",
            description="Test",
            ingredients=sample_ingredients[:2],
            steps=sample_steps,
            servings=2,
            prep_time_minutes=10,
            cook_time_minutes=20,
            cuisine="Test",
            meal_type="dinner",
            difficulty="easy",
        )

        similarity = recipe_manager.calculate_recipe_similarity(recipe1.id, recipe2.id)

        assert Decimal("0") <= similarity <= Decimal("1")
        assert similarity > Decimal("0")

    def test_find_similar_recipes(self, recipe_manager: RecipeManager, sample_ingredients, sample_steps) -> None:
        """Test finding similar recipes."""
        recipe1 = recipe_manager.create_recipe(
            name="Main Recipe",
            description="Test",
            ingredients=sample_ingredients,
            steps=sample_steps,
            servings=2,
            prep_time_minutes=10,
            cook_time_minutes=20,
            cuisine="Test",
            meal_type="dinner",
            difficulty="easy",
        )

        recipe2 = recipe_manager.create_recipe(
            name="Similar Recipe",
            description="Test",
            ingredients=sample_ingredients,
            steps=sample_steps,
            servings=2,
            prep_time_minutes=10,
            cook_time_minutes=20,
            cuisine="Test",
            meal_type="dinner",
            difficulty="easy",
        )

        similar = recipe_manager.find_similar_recipes(recipe1.id, min_similarity=Decimal("0.5"))
        assert len(similar) > 0
        assert similar[0][0] == recipe2.id

    def test_rate_recipe(self, recipe_manager: RecipeManager, sample_ingredients, sample_steps) -> None:
        """Test recipe rating."""
        recipe = recipe_manager.create_recipe(
            name="Ratable Recipe",
            description="Test",
            ingredients=sample_ingredients,
            steps=sample_steps,
            servings=2,
            prep_time_minutes=10,
            cook_time_minutes=20,
            cuisine="Test",
            meal_type="dinner",
            difficulty="easy",
        )

        rated = recipe_manager.rate_recipe(recipe.id, Decimal("4.5"))
        assert rated.rating is not None
        assert rated.review_count == 1

        # Add another rating
        rated = recipe_manager.rate_recipe(recipe.id, Decimal("5.0"))
        assert rated.review_count == 2
        # Average of 4.5 and 5.0 is 4.75
        assert abs(rated.rating - Decimal("4.75")) < Decimal("0.01")


class TestIngredientParser:
    """Test ingredient parsing."""

    def test_parse_simple_ingredient(self) -> None:
        """Test parsing simple ingredient."""
        qty, unit, name = IngredientParser.parse_ingredient("2 cups flour")
        assert qty == Decimal("2")
        assert unit == "cups"
        assert name == "flour"

    def test_parse_ingredient_with_decimal(self) -> None:
        """Test parsing ingredient with decimal quantity."""
        qty, unit, name = IngredientParser.parse_ingredient("1.5 tbsp salt")
        assert qty == Decimal("1.5")
        assert unit == "tbsp"
        assert name == "salt"

    def test_parse_ingredient_invalid(self) -> None:
        """Test parsing invalid ingredient."""
        with pytest.raises(RecipeParsingError):
            IngredientParser.parse_ingredient("just flour")

    def test_normalize_unit(self) -> None:
        """Test unit normalization."""
        assert IngredientParser.normalize_unit("cup") == "cup"
        assert IngredientParser.normalize_unit("cups") == "cup"
        assert IngredientParser.normalize_unit("tbsp") == "tablespoon"
        assert IngredientParser.normalize_unit("tsp") == "teaspoon"

    def test_parse_multiple_ingredients(self) -> None:
        """Test parsing multiple ingredients."""
        text = """2 cups flour
        1 egg
        1/2 cup milk"""

        ingredients = IngredientParser.parse_multiple_ingredients(text)
        assert len(ingredients) >= 2


class TestRecipeScaling:
    """Test recipe scaling functionality."""

    @pytest.fixture
    def scalable_recipe(self) -> Recipe:
        """Create a scalable recipe."""
        return Recipe(
            id="test_recipe",
            name="Scalable Recipe",
            description="Test",
            ingredients=[
                Ingredient(
                    name="Flour",
                    quantity=Decimal("2"),
                    unit="cup",
                    category=FoodCategory.GRAINS,
                ),
                Ingredient(
                    name="Sugar",
                    quantity=Decimal("1"),
                    unit="cup",
                    category=FoodCategory.CONDIMENTS,
                ),
            ],
            steps=[CookingStep(step_number=1, description="Mix ingredients")],
            servings=4,
            prep_time_minutes=10,
            cook_time_minutes=20,
            total_time_minutes=30,
            cuisine="Test",
            meal_type="dessert",
            difficulty="easy",
        )

    def test_scale_servings_up(self, scalable_recipe: Recipe) -> None:
        """Test scaling recipe to more servings."""
        scaled = scalable_recipe.scale_servings(8)

        assert scaled.servings == 8
        assert scaled.ingredients[0].quantity == Decimal("4")
        assert scaled.ingredients[1].quantity == Decimal("2")

    def test_scale_servings_down(self, scalable_recipe: Recipe) -> None:
        """Test scaling recipe to fewer servings."""
        scaled = scalable_recipe.scale_servings(2)

        assert scaled.servings == 2
        assert scaled.ingredients[0].quantity == Decimal("1")
        assert scaled.ingredients[1].quantity == Decimal("0.5")
