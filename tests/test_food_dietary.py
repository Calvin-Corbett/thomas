"""
Tests for dietary management module.
"""

from decimal import Decimal

import pytest

from thomas.food_tech._types import (
    Allergen,
    CookingStep,
    DietaryRestriction,
    FoodCategory,
    Ingredient,
    Recipe,
    Substitution,
)
from thomas.food_tech.dietary import DietaryManager


class TestDietaryManager:
    """Test dietary restriction and allergen management."""

    @pytest.fixture
    def dietary_manager(self) -> DietaryManager:
        """Create a dietary manager instance."""
        return DietaryManager()

    @pytest.fixture
    def vegetarian_recipe(self) -> Recipe:
        """Create a vegetarian recipe."""
        return Recipe(
            id="vegetarian_recipe",
            name="Vegetable Stir Fry",
            description="No meat",
            ingredients=[
                Ingredient(
                    name="broccoli",
                    quantity=Decimal("2"),
                    unit="cup",
                    category=FoodCategory.VEGETABLES,
                ),
                Ingredient(
                    name="rice",
                    quantity=Decimal("1"),
                    unit="cup",
                    category=FoodCategory.GRAINS,
                ),
            ],
            steps=[CookingStep(step_number=1, description="Cook")],
            servings=2,
            prep_time_minutes=10,
            cook_time_minutes=10,
            total_time_minutes=20,
            cuisine="Asian",
            meal_type="lunch",
            difficulty="easy",
            dietary_restrictions={DietaryRestriction.VEGETARIAN},
        )

    @pytest.fixture
    def non_vegetarian_recipe(self) -> Recipe:
        """Create a non-vegetarian recipe."""
        return Recipe(
            id="meat_recipe",
            name="Beef Steak",
            description="Contains meat",
            ingredients=[
                Ingredient(
                    name="meat beef",
                    quantity=Decimal("200"),
                    unit="g",
                    category=FoodCategory.PROTEINS,
                    allergens={Allergen.SHELLFISH},
                ),
            ],
            steps=[CookingStep(step_number=1, description="Grill")],
            servings=1,
            prep_time_minutes=5,
            cook_time_minutes=15,
            total_time_minutes=20,
            cuisine="American",
            meal_type="dinner",
            difficulty="easy",
        )

    @pytest.fixture
    def dairy_free_recipe(self) -> Recipe:
        """Create a dairy-free recipe."""
        return Recipe(
            id="dairy_free",
            name="Almond Milk Smoothie",
            description="Dairy free",
            ingredients=[
                Ingredient(
                    name="almond milk",
                    quantity=Decimal("2"),
                    unit="cup",
                    category=FoodCategory.BEVERAGES,
                    allergens={Allergen.TREE_NUTS},
                ),
            ],
            steps=[CookingStep(step_number=1, description="Blend")],
            servings=1,
            prep_time_minutes=2,
            cook_time_minutes=0,
            total_time_minutes=2,
            cuisine="American",
            meal_type="breakfast",
            difficulty="easy",
            dietary_restrictions={DietaryRestriction.DAIRY_FREE},
        )

    def test_set_restrictions(self, dietary_manager: DietaryManager) -> None:
        """Test setting dietary restrictions."""
        restrictions = {DietaryRestriction.VEGETARIAN, DietaryRestriction.GLUTEN_FREE}

        dietary_manager.set_restrictions(restrictions)

        assert dietary_manager.user_restrictions == restrictions

    def test_set_allergens(self, dietary_manager: DietaryManager) -> None:
        """Test setting allergens."""
        allergens = {Allergen.PEANUTS, Allergen.MILK}

        dietary_manager.set_allergens(allergens)

        assert dietary_manager.user_allergens == allergens

    def test_check_recipe_compliance_vegetarian(
        self,
        dietary_manager: DietaryManager,
        vegetarian_recipe: Recipe,
        non_vegetarian_recipe: Recipe,
    ) -> None:
        """Test compliance checking for vegetarian restriction."""
        dietary_manager.set_restrictions({DietaryRestriction.VEGETARIAN})

        veg_compliance = dietary_manager.check_recipe_compliance(vegetarian_recipe)
        assert veg_compliance.get("vegetarian") is True

        meat_compliance = dietary_manager.check_recipe_compliance(non_vegetarian_recipe)
        assert meat_compliance.get("vegetarian") is False

    def test_check_recipe_safety(
        self,
        dietary_manager: DietaryManager,
        dairy_free_recipe: Recipe,
    ) -> None:
        """Test allergen safety checking."""
        dietary_manager.set_allergens({Allergen.TREE_NUTS})

        is_safe = dietary_manager.is_recipe_safe(dairy_free_recipe)
        assert is_safe is False

    def test_detect_allergens(self, dietary_manager: DietaryManager) -> None:
        """Test allergen detection in ingredients."""
        detected = dietary_manager.detect_allergens_in_ingredient("peanut oil")
        assert Allergen.PEANUTS in detected

        detected = dietary_manager.detect_allergens_in_ingredient("wheat flour")
        assert Allergen.WHEAT in detected

    def test_find_substitutions(self, dietary_manager: DietaryManager) -> None:
        """Test finding ingredient substitutions."""
        subs = dietary_manager.find_substitutions("butter")

        assert len(subs) > 0
        assert subs[0].original == "butter"

    def test_add_custom_substitution(self, dietary_manager: DietaryManager) -> None:
        """Test adding custom substitution."""
        sub = Substitution(
            original="milk",
            replacement="oat milk",
            ratio=Decimal("1"),
        )

        dietary_manager.add_substitution(sub)

        found = dietary_manager.find_substitutions("milk", substitution_count=1)
        assert len(found) > 0
        assert found[0].replacement == "oat milk"

    def test_substitute_ingredient_in_recipe(
        self,
        dietary_manager: DietaryManager,
        dairy_free_recipe: Recipe,
    ) -> None:
        """Test substituting ingredients in a recipe."""
        sub = Substitution(
            original="almond milk",
            replacement="oat milk",
            ratio=Decimal("1"),
        )

        substituted = dietary_manager.substitute_ingredient_in_recipe(
            dairy_free_recipe,
            "almond milk",
            sub,
        )

        assert substituted.id == dairy_free_recipe.id
        assert "oat milk" in [i.name for i in substituted.ingredients]

    def test_calculate_compliance_score_compliant(
        self,
        dietary_manager: DietaryManager,
        vegetarian_recipe: Recipe,
    ) -> None:
        """Test compliance score for compliant recipe."""
        dietary_manager.set_restrictions({DietaryRestriction.VEGETARIAN})

        score = dietary_manager.calculate_compliance_score(vegetarian_recipe)

        assert score >= Decimal(0)
        assert score <= Decimal(100)
        assert score > Decimal(50)  # Should be high for compliant recipe

    def test_calculate_compliance_score_non_compliant(
        self,
        dietary_manager: DietaryManager,
        non_vegetarian_recipe: Recipe,
    ) -> None:
        """Test compliance score for non-compliant recipe."""
        dietary_manager.set_restrictions({DietaryRestriction.VEGETARIAN})

        score = dietary_manager.calculate_compliance_score(non_vegetarian_recipe)

        # Should be significantly lower for non-compliant recipe
        assert score <= Decimal(75)

    def test_count_macronutrients_for_diet(self, dietary_manager: DietaryManager) -> None:
        """Test macronutrient counting for recipes."""
        recipe = Recipe(
            id="macro_test",
            name="Test",
            description="Test",
            ingredients=[],
            steps=[CookingStep(step_number=1, description="Cook")],
            servings=1,
            prep_time_minutes=5,
            cook_time_minutes=10,
            total_time_minutes=15,
            cuisine="Test",
            meal_type="lunch",
            difficulty="easy",
        )

        totals = dietary_manager.count_macronutrients_for_diet([recipe])

        assert "protein" in totals
        assert "fat" in totals
        assert "carbs" in totals
        assert "calories" in totals


class TestRestrictionIngredients:
    """Test dietary restriction ingredient mappings."""

    def test_vegetarian_restricted_ingredients(self) -> None:
        """Test vegetarian restriction ingredients."""
        restricted = DietaryManager.RESTRICTION_INGREDIENTS[DietaryRestriction.VEGETARIAN]

        assert "meat" in restricted
        assert "fish" in restricted
        assert "poultry" in restricted

    def test_vegan_restricted_ingredients(self) -> None:
        """Test vegan restriction ingredients."""
        restricted = DietaryManager.RESTRICTION_INGREDIENTS[DietaryRestriction.VEGAN]

        assert "meat" in restricted
        assert "milk" in restricted
        assert "egg" in restricted

    def test_gluten_free_restricted_ingredients(self) -> None:
        """Test gluten-free restriction ingredients."""
        restricted = DietaryManager.RESTRICTION_INGREDIENTS[DietaryRestriction.GLUTEN_FREE]

        assert "wheat" in restricted
        assert "barley" in restricted


class TestAllergenSources:
    """Test allergen source mappings."""

    def test_peanut_allergen_sources(self) -> None:
        """Test peanut allergen sources."""
        sources = DietaryManager.ALLERGEN_SOURCES[Allergen.PEANUTS]

        assert "peanut" in sources
        assert "peanut butter" in sources

    def test_tree_nut_allergen_sources(self) -> None:
        """Test tree nut allergen sources."""
        sources = DietaryManager.ALLERGEN_SOURCES[Allergen.TREE_NUTS]

        assert "almond" in sources
        assert "walnut" in sources
        assert "cashew" in sources

    def test_dairy_allergen_sources(self) -> None:
        """Test dairy allergen sources."""
        sources = DietaryManager.ALLERGEN_SOURCES[Allergen.MILK]

        assert "milk" in sources
        assert "cheese" in sources
        assert "butter" in sources
