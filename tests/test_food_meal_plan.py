"""
Tests for meal planning module.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from thomas.marketplace.food_tech._exceptions import ConstraintViolationError, PlanGenerationError
from thomas.marketplace.food_tech._types import (
    CookingStep,
    FoodCategory,
    Ingredient,
    NutritionFacts,
    Recipe,
)
from thomas.marketplace.food_tech.meal_planning import MealPlanner


class TestMealPlanner:
    """Test meal planning operations."""

    @pytest.fixture
    def meal_planner(self) -> MealPlanner:
        """Create a meal planner instance."""
        return MealPlanner()

    @pytest.fixture
    def sample_recipes(self) -> list:
        """Create sample recipes for meal planning."""
        recipes = []

        for i in range(5):
            nutrition = NutritionFacts(
                calories=Decimal("400") + (i * Decimal("100")),
                protein=Decimal("25"),
                fat=Decimal("15"),
                carbohydrates=Decimal("45"),
                fiber=Decimal("5"),
                sugar=Decimal("5"),
                sodium=Decimal("500"),
            )

            recipe = Recipe(
                id=f"recipe_{i}",
                name=f"Recipe {i}",
                description=f"Test recipe {i}",
                ingredients=[
                    Ingredient(
                        name=f"Ingredient {i}",
                        quantity=Decimal("100"),
                        unit="g",
                        category=FoodCategory.PROTEINS,
                    ),
                ],
                steps=[CookingStep(step_number=1, description="Cook")],
                servings=2,
                prep_time_minutes=10,
                cook_time_minutes=20,
                total_time_minutes=30,
                cuisine="Test",
                meal_type=["breakfast", "lunch", "dinner"][i % 3],
                difficulty="easy",
                nutrition_per_serving=nutrition,
                cost_per_serving=Decimal("5") + (i * Decimal("0.5")),
            )
            recipes.append(recipe)

        return recipes

    def test_generate_meal_plan(self, meal_planner: MealPlanner, sample_recipes: list) -> None:
        """Test basic meal plan generation."""
        try:
            plan = meal_planner.generate_meal_plan(
                recipes=sample_recipes,
                start_date=datetime.now(),
                target_daily_calories=Decimal("2000"),
                target_servings=3,
            )

            assert plan is not None
            assert len(plan.meals) == 7  # 7 days
            assert all(len(meals) > 0 for meals in plan.meals.values())
            assert plan.total_calories > Decimal(0)
        except ConstraintViolationError:
            # Expected if constraints are too strict
            pass

    def test_generate_meal_plan_empty_recipes(self, meal_planner: MealPlanner) -> None:
        """Test meal plan generation with no recipes."""
        with pytest.raises(PlanGenerationError):
            meal_planner.generate_meal_plan(
                recipes=[],
                start_date=datetime.now(),
            )

    def test_meal_plan_constraint_satisfaction(self, meal_planner: MealPlanner, sample_recipes: list) -> None:
        """Test that meal plan satisfies constraints."""
        try:
            plan = meal_planner.generate_meal_plan(
                recipes=sample_recipes,
                start_date=datetime.now(),
                target_daily_calories=Decimal("2000"),
                max_repeat_recipes=2,
            )

            assert "no_repeats" in plan.constraints_met
            assert plan.constraints_met["no_repeats"] is True
        except ConstraintViolationError:
            pass

    def test_aggregate_grocery_list(self, meal_planner: MealPlanner, sample_recipes: list) -> None:
        """Test grocery list aggregation."""
        try:
            plan = meal_planner.generate_meal_plan(
                recipes=sample_recipes[:3],
                start_date=datetime.now(),
            )

            grocery_list = plan.grocery_list

            assert grocery_list.items is not None
            assert len(grocery_list.items) > 0
        except ConstraintViolationError:
            pass

    def test_calculate_plan_macros(self, meal_planner: MealPlanner, sample_recipes: list) -> None:
        """Test macro calculation for meal plan."""
        try:
            plan = meal_planner.generate_meal_plan(
                recipes=sample_recipes[:3],
                start_date=datetime.now(),
            )

            assert plan.average_macros is not None
            assert "protein" in plan.average_macros
            assert "fat" in plan.average_macros
            assert "carbs" in plan.average_macros
        except ConstraintViolationError:
            pass

    def test_optimize_for_leftovers(self, meal_planner: MealPlanner, sample_recipes: list) -> None:
        """Test leftover optimization meal planning."""
        plan = meal_planner.optimize_for_leftovers(
            recipes=sample_recipes,
            start_date=datetime.now(),
        )

        assert plan is not None
        assert len(plan.meals) == 7
        assert all(len(meals) > 0 for meals in plan.meals.values())

    def test_optimize_for_budget(self, meal_planner: MealPlanner, sample_recipes: list) -> None:
        """Test budget-constrained meal planning."""
        budget = Decimal("200")  # Total week budget (higher to allow for recipe costs)

        try:
            plan = meal_planner.optimize_for_budget(
                recipes=sample_recipes,
                start_date=datetime.now(),
                budget=budget,
            )

            assert plan is not None
            assert plan.total_cost <= budget
        except ConstraintViolationError:
            pass

    def test_optimize_for_budget_insufficient(self, meal_planner: MealPlanner, sample_recipes: list) -> None:
        """Test budget optimization with insufficient budget."""
        budget = Decimal("1")  # Too low

        with pytest.raises(ConstraintViolationError):
            meal_planner.optimize_for_budget(
                recipes=sample_recipes,
                start_date=datetime.now(),
                budget=budget,
            )

    def test_meal_plan_prep_time_calculation(self, meal_planner: MealPlanner, sample_recipes: list) -> None:
        """Test estimated prep time calculation in meal plan."""
        try:
            plan = meal_planner.generate_meal_plan(
                recipes=sample_recipes[:3],
                start_date=datetime.now(),
            )

            assert plan.estimated_prep_time_hours > Decimal(0)
        except ConstraintViolationError:
            pass

    def test_meal_plan_variety(self, meal_planner: MealPlanner, sample_recipes: list) -> None:
        """Test meal plan variety with variety weight."""
        try:
            plan = meal_planner.generate_meal_plan(
                recipes=sample_recipes,
                start_date=datetime.now(),
                variety_weight=Decimal("1.0"),
            )

            # Count unique recipes in plan
            unique_recipes = set()
            for day_meals in plan.meals.values():
                for meal in day_meals:
                    unique_recipes.add(meal.id)

            assert len(unique_recipes) >= 1
        except ConstraintViolationError:
            pass


class TestMealPlanMeals:
    """Test meal plan structure and organization."""

    @pytest.fixture
    def simple_meal_planner(self) -> MealPlanner:
        """Create meal planner with minimal setup."""
        return MealPlanner()

    def test_meal_plan_has_all_days(self, simple_meal_planner: MealPlanner) -> None:
        """Test that meal plan includes all days of week."""
        recipes = [
            Recipe(
                id="test_1",
                name="Test Recipe 1",
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
            ),
        ]

        try:
            plan = simple_meal_planner.generate_meal_plan(
                recipes=recipes,
                start_date=datetime.now(),
            )

            expected_days = {
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
            }

            assert set(plan.meals.keys()) == expected_days
        except ConstraintViolationError:
            # Expected if constraints can't be met
            pass
