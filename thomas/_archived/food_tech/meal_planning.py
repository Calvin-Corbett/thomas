"""
Meal planning module for food technology platform.

Handles weekly meal plan generation with constraint satisfaction,
grocery list aggregation, leftover management, and budget optimization.
"""

from datetime import datetime
from decimal import Decimal

from thomas.food_tech._exceptions import (
    ConstraintViolationError,
    PlanGenerationError,
)
from thomas.food_tech._types import (
    FoodCategory,
    GroceryList,
    MealPlan,
    Recipe,
)
from thomas.food_tech.nutrition import NutritionAnalyzer


class MealPlanner:
    """Generates optimized meal plans with constraint satisfaction."""

    DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    def __init__(self, nutrition_analyzer: NutritionAnalyzer | None = None) -> None:
        """Initialize meal planner.

        Args:
            nutrition_analyzer: Optional NutritionAnalyzer instance.
        """
        self.nutrition_analyzer = nutrition_analyzer or NutritionAnalyzer()

    def generate_meal_plan(
        self,
        recipes: list[Recipe],
        start_date: datetime,
        target_daily_calories: Decimal = Decimal("2000"),
        target_servings: int = 3,  # breakfast, lunch, dinner
        max_repeat_recipes: int = 2,
        variety_weight: Decimal = Decimal("0.5"),
        budget_limit: Decimal | None = None,
    ) -> MealPlan:
        """Generate a weekly meal plan with constraints.

        Args:
            recipes: Available recipes.
            start_date: Start date for meal plan.
            target_daily_calories: Target daily calorie intake.
            target_servings: Number of meals per day.
            max_repeat_recipes: Maximum times a recipe can appear in plan.
            variety_weight: Weight for ingredient variety (0-1).
            budget_limit: Optional budget limit.

        Returns:
            MealPlan: Generated meal plan.

        Raises:
            ConstraintViolationError: If constraints cannot be satisfied.
        """
        if not recipes:
            raise PlanGenerationError("No recipes available for meal planning")

        meals: dict[str, list[Recipe]] = {day: [] for day in self.DAYS_OF_WEEK}
        recipe_count: dict[str, int] = {r.id: 0 for r in recipes}
        total_cost = Decimal(0)
        total_calories = Decimal(0)
        used_ingredients: set[str] = set()

        for day in self.DAYS_OF_WEEK:
            day_calories = Decimal(0)
            day_recipes = []

            for meal_slot in range(target_servings):
                # Find best recipe for this slot
                best_recipe = None
                best_score = Decimal("-999")

                for recipe in recipes:
                    # Check constraints
                    if recipe_count[recipe.id] >= max_repeat_recipes:
                        continue

                    day_calories_after = day_calories + (
                        recipe.nutrition_per_serving.calories if recipe.nutrition_per_serving else Decimal(0)
                    )

                    if day_calories_after > target_daily_calories * Decimal("1.2"):
                        continue

                    # Calculate score
                    score = self._calculate_recipe_score(
                        recipe,
                        target_daily_calories,
                        day_calories,
                        variety_weight,
                        used_ingredients,
                    )

                    if score > best_score:
                        best_score = score
                        best_recipe = recipe

                if best_recipe:
                    day_recipes.append(best_recipe)
                    recipe_count[best_recipe.id] += 1
                    day_calories += (
                        best_recipe.nutrition_per_serving.calories if best_recipe.nutrition_per_serving else Decimal(0)
                    )
                    total_calories += (
                        best_recipe.nutrition_per_serving.calories if best_recipe.nutrition_per_serving else Decimal(0)
                    )
                    if best_recipe.cost_per_serving:
                        total_cost += best_recipe.cost_per_serving

                    for ing in best_recipe.ingredients:
                        used_ingredients.add(ing.name.lower())

            if not day_recipes:
                raise ConstraintViolationError(f"Cannot fill meals for {day}")

            meals[day] = day_recipes

        if budget_limit and total_cost > budget_limit:
            raise ConstraintViolationError(f"Meal plan cost {total_cost} exceeds budget {budget_limit}")

        grocery_list = self._aggregate_grocery_list(meals)
        total_macro_ratios = self._calculate_plan_macros(meals)
        prep_time = sum(r.total_time_minutes for day_meals in meals.values() for r in day_meals)

        return MealPlan(
            start_date=start_date,
            meals=meals,
            total_calories=total_calories,
            average_macros=total_macro_ratios,
            grocery_list=grocery_list,
            total_cost=total_cost,
            estimated_prep_time_hours=Decimal(prep_time) / Decimal(60),
            constraints_met={
                "calorie_target": abs(total_calories - (target_daily_calories * Decimal(7)))
                < (target_daily_calories * Decimal("0.2")),
                "no_repeats": all(count <= max_repeat_recipes for count in recipe_count.values()),
                "budget": budget_limit is None or total_cost <= budget_limit,
            },
        )

    def _calculate_recipe_score(
        self,
        recipe: Recipe,
        target_daily_calories: Decimal,
        current_day_calories: Decimal,
        variety_weight: Decimal,
        used_ingredients: set[str],
    ) -> Decimal:
        """Calculate selection score for a recipe."""
        score = Decimal(0)

        # Calorie balance score
        recipe_cals = recipe.nutrition_per_serving.calories if recipe.nutrition_per_serving else Decimal(0)
        calorie_diff = abs(recipe_cals - (target_daily_calories / Decimal(3)))
        score += max(Decimal(0), Decimal(100) - calorie_diff)

        # Variety score
        new_ingredients = sum(1 for ing in recipe.ingredients if ing.name.lower() not in used_ingredients)
        variety_score = (new_ingredients / len(recipe.ingredients)) if recipe.ingredients else 0
        score += variety_weight * Decimal(variety_score) * 50

        return score

    def _aggregate_grocery_list(self, meals: dict[str, list[Recipe]]) -> GroceryList:
        """Aggregate ingredients from all recipes into a grocery list."""
        items: dict[str, tuple[Decimal, str]] = {}
        organized: dict[FoodCategory, list[str]] = {}
        total_cost = Decimal(0)

        for day_recipes in meals.values():
            for recipe in day_recipes:
                for ingredient in recipe.ingredients:
                    key = ingredient.name.lower()
                    if key in items:
                        qty, unit = items[key]
                        if unit == ingredient.unit:
                            items[key] = (qty + ingredient.quantity, unit)
                    else:
                        items[key] = (ingredient.quantity, ingredient.unit)

                    # Organize by category
                    if ingredient.category not in organized:
                        organized[ingredient.category] = []
                    if ingredient.name not in organized[ingredient.category]:
                        organized[ingredient.category].append(ingredient.name)

        return GroceryList(
            items=items,
            estimated_cost=total_cost if total_cost > 0 else None,
            organized_by_category=organized,
        )

    def _calculate_plan_macros(self, meals: dict[str, list[Recipe]]) -> dict[str, Decimal]:
        """Calculate average macro ratios for the meal plan."""
        all_macros = {"protein": Decimal(0), "fat": Decimal(0), "carbs": Decimal(0)}
        meal_count = 0

        for day_recipes in meals.values():
            for recipe in day_recipes:
                if recipe.nutrition_per_serving:
                    macros = recipe.nutrition_per_serving.macro_ratios()
                    for key in all_macros:
                        all_macros[key] += macros.get(key, Decimal(0))
                    meal_count += 1

        if meal_count > 0:
            for key in all_macros:
                all_macros[key] = (all_macros[key] / meal_count).quantize(Decimal("0.1"))

        return all_macros

    def optimize_for_leftovers(
        self,
        recipes: list[Recipe],
        start_date: datetime,
    ) -> MealPlan:
        """Generate meal plan optimized for leftover usage and ingredient overlap.

        Args:
            recipes: Available recipes.
            start_date: Start date for meal plan.

        Returns:
            MealPlan: Meal plan optimized for leftover management.
        """
        meals: dict[str, list[Recipe]] = {day: [] for day in self.DAYS_OF_WEEK}
        used_ingredients: dict[str, Decimal] = {}

        for day_idx, day in enumerate(self.DAYS_OF_WEEK):
            # Prefer recipes that use ingredients already in the plan
            best_recipes = []

            for recipe in recipes:
                ingredient_overlap = sum(1 for ing in recipe.ingredients if ing.name.lower() in used_ingredients)
                overlap_score = (
                    Decimal(ingredient_overlap) / len(recipe.ingredients) if recipe.ingredients else Decimal(0)
                )

                if day_idx == 0 or overlap_score > Decimal("0.3"):
                    best_recipes.append((recipe, overlap_score))

            best_recipes.sort(key=lambda x: x[1], reverse=True)
            selected = best_recipes[:3] if best_recipes else recipes[:3]

            meals[day] = [r[0] for r in selected]

            for recipe in meals[day]:
                for ing in recipe.ingredients:
                    key = ing.name.lower()
                    used_ingredients[key] = used_ingredients.get(key, Decimal(0)) + ing.quantity

        grocery_list = self._aggregate_grocery_list(meals)
        total_macros = self._calculate_plan_macros(meals)
        total_calories = sum(
            r.nutrition_per_serving.calories
            for day_recipes in meals.values()
            for r in day_recipes
            if r.nutrition_per_serving
        )

        return MealPlan(
            start_date=start_date,
            meals=meals,
            total_calories=total_calories,
            average_macros=total_macros,
            grocery_list=grocery_list,
            total_cost=Decimal(0),
            estimated_prep_time_hours=Decimal(0),
        )

    def optimize_for_budget(
        self,
        recipes: list[Recipe],
        start_date: datetime,
        budget: Decimal,
        target_daily_calories: Decimal = Decimal("2000"),
    ) -> MealPlan:
        """Generate meal plan optimized for budget constraints using greedy selection.

        Args:
            recipes: Available recipes.
            start_date: Start date for meal plan.
            budget: Total budget for the week.
            target_daily_calories: Target daily calorie intake.

        Returns:
            MealPlan: Budget-optimized meal plan.

        Raises:
            ConstraintViolationError: If budget cannot accommodate plan.
        """
        # Filter recipes with cost data
        costed_recipes = [r for r in recipes if r.cost_per_serving]
        if not costed_recipes:
            raise ConstraintViolationError("No recipes with cost data available")

        # Sort by cost-per-calorie ratio
        cost_per_cal = [
            (
                r,
                r.cost_per_serving / r.nutrition_per_serving.calories
                if r.nutrition_per_serving and r.nutrition_per_serving.calories > 0
                else Decimal("999"),
            )
            for r in costed_recipes
        ]
        cost_per_cal.sort(key=lambda x: x[1])

        meals: dict[str, list[Recipe]] = {day: [] for day in self.DAYS_OF_WEEK}
        remaining_budget = budget
        total_cost = Decimal(0)
        total_calories = Decimal(0)

        for day in self.DAYS_OF_WEEK:
            for _ in range(3):  # 3 meals per day
                for recipe, _ in cost_per_cal:
                    if recipe.cost_per_serving and remaining_budget >= recipe.cost_per_serving:
                        meals[day].append(recipe)
                        remaining_budget -= recipe.cost_per_serving
                        total_cost += recipe.cost_per_serving
                        if recipe.nutrition_per_serving:
                            total_calories += recipe.nutrition_per_serving.calories
                        break

        if not all(meals.values()):
            raise ConstraintViolationError(f"Budget {budget} too low for meal plan")

        grocery_list = self._aggregate_grocery_list(meals)
        total_macros = self._calculate_plan_macros(meals)

        return MealPlan(
            start_date=start_date,
            meals=meals,
            total_calories=total_calories,
            average_macros=total_macros,
            grocery_list=grocery_list,
            total_cost=total_cost,
            estimated_prep_time_hours=Decimal(0),
            constraints_met={"budget": remaining_budget >= Decimal(0)},
        )
