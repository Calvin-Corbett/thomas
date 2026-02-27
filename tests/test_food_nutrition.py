"""
Tests for nutrition analysis module.
"""

from decimal import Decimal

import pytest

from thomas.food_tech._types import (
    CookingStep,
    FoodCategory,
    Ingredient,
    Nutrient,
    NutritionFacts,
    Recipe,
)
from thomas.food_tech.nutrition import (
    ActivityLevel,
    MacroProfile,
    NutritionAnalyzer,
)


class TestNutritionAnalyzer:
    """Test nutrition analysis operations."""

    @pytest.fixture
    def nutrition_analyzer(self) -> NutritionAnalyzer:
        """Create a nutrition analyzer instance."""
        return NutritionAnalyzer()

    @pytest.fixture
    def sample_recipe(self) -> Recipe:
        """Create a sample recipe for nutrition testing."""
        return Recipe(
            id="nutrition_test_recipe",
            name="Chicken and Rice",
            description="Test",
            ingredients=[
                Ingredient(
                    name="chicken_breast",
                    quantity=Decimal("100"),
                    unit="g",
                    category=FoodCategory.PROTEINS,
                ),
                Ingredient(
                    name="brown_rice",
                    quantity=Decimal("100"),
                    unit="g",
                    category=FoodCategory.GRAINS,
                ),
            ],
            steps=[CookingStep(step_number=1, description="Cook")],
            servings=2,
            prep_time_minutes=5,
            cook_time_minutes=30,
            total_time_minutes=35,
            cuisine="Test",
            meal_type="lunch",
            difficulty="easy",
        )

    def test_analyze_recipe(self, nutrition_analyzer: NutritionAnalyzer, sample_recipe: Recipe) -> None:
        """Test recipe nutrition analysis."""
        nutrition = nutrition_analyzer.analyze_recipe(sample_recipe)

        assert nutrition is not None
        assert nutrition.calories > Decimal(0)
        assert nutrition.protein > Decimal(0)
        assert nutrition.fat >= Decimal(0)
        assert nutrition.carbohydrates > Decimal(0)

    def test_analyze_ingredient(self, nutrition_analyzer: NutritionAnalyzer) -> None:
        """Test ingredient nutrition analysis."""
        ingredient = Ingredient(
            name="chicken_breast",
            quantity=Decimal("200"),
            unit="g",
            category=FoodCategory.PROTEINS,
        )

        nutrition = nutrition_analyzer.analyze_ingredient(ingredient)

        assert nutrition is not None
        assert nutrition.calories > Decimal(0)
        assert nutrition.protein > Decimal(0)

    def test_analyze_ingredient_with_custom_nutrition(self, nutrition_analyzer: NutritionAnalyzer) -> None:
        """Test ingredient with custom nutrition data."""
        custom_nutrition = NutritionFacts(
            calories=Decimal("100"),
            protein=Decimal("10"),
            fat=Decimal("5"),
            carbohydrates=Decimal("5"),
            fiber=Decimal("0"),
            sugar=Decimal("0"),
            sodium=Decimal("500"),
        )

        ingredient = Ingredient(
            name="Custom Item",
            quantity=Decimal("100"),
            unit="g",
            category=FoodCategory.PROTEINS,
            nutrition_per_100g=custom_nutrition,
        )

        nutrition = nutrition_analyzer.analyze_ingredient(ingredient)

        assert nutrition.calories == Decimal("100")
        assert nutrition.protein == Decimal("10")

    def test_calculate_daily_values(self, nutrition_analyzer: NutritionAnalyzer) -> None:
        """Test daily value percentage calculations."""
        nutrition = NutritionFacts(
            calories=Decimal("2000"),
            protein=Decimal("50"),
            fat=Decimal("70"),
            carbohydrates=Decimal("200"),
            fiber=Decimal("25"),
            sugar=Decimal("50"),
            sodium=Decimal("2300"),
            micronutrients={
                "vitamin_c_mg": Nutrient("Vitamin C", Decimal("90"), "mg", Decimal("100")),
            },
        )

        dvs = nutrition_analyzer.calculate_daily_values(nutrition)

        assert "sodium" in dvs
        assert dvs["sodium"] == Decimal("100")

    def test_estimate_bmr_male(self, nutrition_analyzer: NutritionAnalyzer) -> None:
        """Test BMR calculation for male."""
        bmr = nutrition_analyzer.estimate_bmr(
            weight_kg=Decimal("80"),
            height_cm=Decimal("180"),
            age_years=30,
            is_male=True,
        )

        assert bmr > Decimal(0)
        assert bmr < Decimal("3000")

    def test_estimate_bmr_female(self, nutrition_analyzer: NutritionAnalyzer) -> None:
        """Test BMR calculation for female."""
        bmr = nutrition_analyzer.estimate_bmr(
            weight_kg=Decimal("65"),
            height_cm=Decimal("165"),
            age_years=25,
            is_male=False,
        )

        assert bmr > Decimal(0)
        assert bmr < Decimal("3000")

    def test_estimate_tdee(self, nutrition_analyzer: NutritionAnalyzer) -> None:
        """Test TDEE calculation."""
        bmr = Decimal("1700")

        tdee = nutrition_analyzer.estimate_tdee(bmr, ActivityLevel.MODERATELY_ACTIVE)

        assert tdee > bmr
        assert tdee == bmr * ActivityLevel.MODERATELY_ACTIVE.value

    def test_analyze_macro_ratios(self, nutrition_analyzer: NutritionAnalyzer) -> None:
        """Test macro ratio analysis."""
        nutrition = NutritionFacts(
            calories=Decimal("2000"),
            protein=Decimal("200"),  # 200 cal
            fat=Decimal("67"),  # 603 cal
            carbohydrates=Decimal("200"),  # 800 cal
            fiber=Decimal("0"),
            sugar=Decimal("0"),
            sodium=Decimal("0"),
        )

        ratios = nutrition_analyzer.analyze_macro_ratios(nutrition)

        assert "protein" in ratios
        assert "fat" in ratios
        assert "carbs" in ratios
        assert ratios["protein"] + ratios["fat"] + ratios["carbs"] > Decimal(99)

    def test_match_macro_profile(self, nutrition_analyzer: NutritionAnalyzer) -> None:
        """Test matching to macro profiles."""
        # Balanced profile: 30% protein, 30% fat, 40% carbs
        ratios = {
            "protein": Decimal("30"),
            "fat": Decimal("30"),
            "carbs": Decimal("40"),
        }

        matched = nutrition_analyzer.match_macro_profile(ratios)

        assert matched == "BALANCED"

    def test_calculate_calories_for_macros(self, nutrition_analyzer: NutritionAnalyzer) -> None:
        """Test calorie calculation from macros."""
        calories = nutrition_analyzer.calculate_calories_for_macros(
            protein_g=Decimal("50"),
            fat_g=Decimal("65"),
            carbs_g=Decimal("200"),
        )

        # 50*4 + 65*9 + 200*4 = 200 + 585 + 800 = 1585
        expected = Decimal("1585")
        assert abs(calories - expected) < Decimal("1")

    def test_get_macro_targets(self, nutrition_analyzer: NutritionAnalyzer) -> None:
        """Test macro target calculation."""
        tdee = Decimal("2000")

        targets = nutrition_analyzer.get_macro_targets(tdee, MacroProfile.KETO)

        assert "protein" in targets
        assert "fat" in targets
        assert "carbs" in targets
        assert targets["fat"] > targets["protein"]


class TestNutritionFacts:
    """Test nutrition facts operations."""

    @pytest.fixture
    def sample_nutrition(self) -> NutritionFacts:
        """Create sample nutrition facts."""
        return NutritionFacts(
            calories=Decimal("500"),
            protein=Decimal("30"),
            fat=Decimal("20"),
            carbohydrates=Decimal("50"),
            fiber=Decimal("5"),
            sugar=Decimal("10"),
            sodium=Decimal("500"),
        )

    def test_scale_nutrition(self, sample_nutrition: NutritionFacts) -> None:
        """Test scaling nutrition facts."""
        scaled = sample_nutrition.scale(Decimal("2"))

        assert scaled.calories == Decimal("1000")
        assert scaled.protein == Decimal("60")
        assert scaled.fat == Decimal("40")

    def test_nutrition_macro_ratios(self, sample_nutrition: NutritionFacts) -> None:
        """Test macro ratio calculation."""
        ratios = sample_nutrition.macro_ratios()

        assert "protein" in ratios
        assert "fat" in ratios
        assert "carbs" in ratios

        # protein: 30*4 = 120 cal, fat: 20*9 = 180 cal, carbs: 50*4 = 200 cal
        # total = 500 cal
        assert ratios["protein"] > Decimal(0)
        assert ratios["fat"] > Decimal(0)
        assert ratios["carbs"] > Decimal(0)


class TestActivityLevels:
    """Test activity level multipliers."""

    def test_activity_level_values(self) -> None:
        """Test activity level values are reasonable."""
        assert ActivityLevel.SEDENTARY.value == Decimal("1.2")
        assert ActivityLevel.EXTREMELY_ACTIVE.value == Decimal("1.9")
        assert ActivityLevel.SEDENTARY.value < ActivityLevel.EXTREMELY_ACTIVE.value


class TestMacroProfiles:
    """Test macro profile definitions."""

    def test_macro_profile_values(self) -> None:
        """Test macro profile percentages sum to reasonable amounts."""
        for profile in MacroProfile:
            total = sum(profile.value.values())
            # Should be approximately 100
            assert Decimal("99") <= total <= Decimal("101")

    def test_keto_profile(self) -> None:
        """Test keto profile ratios."""
        keto = MacroProfile.KETO.value
        assert keto["fat"] > keto["protein"]
        assert keto["fat"] > keto["carbs"]
        assert keto["carbs"] < Decimal("10")

    def test_high_protein_profile(self) -> None:
        """Test high protein profile ratios."""
        hp = MacroProfile.HIGH_PROTEIN.value
        assert hp["protein"] > hp["fat"]
        assert hp["protein"] > hp["carbs"]
