"""
Analytics module for food technology platform.

Tracks eating patterns, nutrition trends, cooking habits, and food analytics
for personal insight and optimization.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from thomas.food_tech._types import Recipe


class FoodAnalytics:
    """Analyzes food consumption and cooking patterns."""

    def __init__(self) -> None:
        """Initialize food analytics."""
        self.meal_log: list[tuple[datetime, str, str]] = []  # (timestamp, meal_type, recipe_id)
        self.nutrition_log: dict[datetime, dict[str, Decimal]] = {}
        self.cooking_frequency: dict[str, int] = {}  # recipe_id -> count
        self.ingredient_usage: dict[str, int] = {}  # ingredient -> count
        self.cuisine_consumption: dict[str, int] = {}  # cuisine -> count
        self.waste_log: list[tuple[datetime, str, Decimal]] = []  # (date, item, qty)

    def log_meal(
        self,
        meal_type: str,
        recipe_id: str,
        recipe: Recipe | None = None,
    ) -> None:
        """Log consumption of a meal.

        Args:
            meal_type: Type of meal (breakfast, lunch, dinner, snack).
            recipe_id: Recipe ID consumed.
            recipe: Optional Recipe object for detailed logging.
        """
        self.meal_log.append((datetime.now(), meal_type, recipe_id))

        # Track cooking frequency
        self.cooking_frequency[recipe_id] = self.cooking_frequency.get(recipe_id, 0) + 1

        # Track ingredients
        if recipe:
            for ingredient in recipe.ingredients:
                key = ingredient.name.lower()
                self.ingredient_usage[key] = self.ingredient_usage.get(key, 0) + 1

            # Track cuisine
            self.cuisine_consumption[recipe.cuisine] = self.cuisine_consumption.get(recipe.cuisine, 0) + 1

    def log_nutrition(
        self,
        calories: Decimal,
        protein: Decimal,
        fat: Decimal,
        carbs: Decimal,
    ) -> None:
        """Log daily nutrition intake.

        Args:
            calories: Calories consumed.
            protein: Protein in grams.
            fat: Fat in grams.
            carbs: Carbohydrates in grams.
        """
        date = datetime.now().date()
        if date not in self.nutrition_log:
            self.nutrition_log[date] = {
                "calories": Decimal(0),
                "protein": Decimal(0),
                "fat": Decimal(0),
                "carbs": Decimal(0),
            }

        self.nutrition_log[date]["calories"] += calories
        self.nutrition_log[date]["protein"] += protein
        self.nutrition_log[date]["fat"] += fat
        self.nutrition_log[date]["carbs"] += carbs

    def log_waste(self, item_name: str, quantity: Decimal) -> None:
        """Log food waste.

        Args:
            item_name: Item wasted.
            quantity: Quantity wasted.
        """
        self.waste_log.append((datetime.now(), item_name, quantity))

    def get_meal_frequency(self, days: int = 30) -> dict[str, int]:
        """Get meal frequency over past N days.

        Args:
            days: Number of days to analyze.

        Returns:
            Dict[str, int]: Recipe ID to count.
        """
        cutoff = datetime.now() - timedelta(days=days)
        frequency = {}

        for timestamp, _, recipe_id in self.meal_log:
            if timestamp >= cutoff:
                frequency[recipe_id] = frequency.get(recipe_id, 0) + 1

        return frequency

    def get_eating_pattern_analysis(self) -> dict[str, any]:
        """Analyze eating patterns and meal timing.

        Returns:
            Dict[str, any]: Pattern analysis including meal timing, frequency.
        """
        meal_types = {}

        for timestamp, meal_type, _ in self.meal_log:
            hour = timestamp.hour
            meal_types[meal_type] = meal_types.get(meal_type, 0) + 1

        return {
            "total_meals_logged": len(self.meal_log),
            "meal_type_distribution": meal_types,
            "average_daily_meals": (len(self.meal_log) / max(1, self._get_days_logged())),
        }

    def _get_days_logged(self) -> int:
        """Get number of unique days with logged meals."""
        if not self.meal_log:
            return 0

        dates = set()
        for timestamp, _, _ in self.meal_log:
            dates.add(timestamp.date())

        return len(dates)

    def get_nutrition_trends(self, days: int = 7) -> dict[str, Decimal]:
        """Get average nutrition over recent days.

        Args:
            days: Number of days to average.

        Returns:
            Dict[str, Decimal]: Average daily values.
        """
        cutoff = datetime.now().date() - timedelta(days=days)
        totals = {"calories": Decimal(0), "protein": Decimal(0), "fat": Decimal(0), "carbs": Decimal(0)}
        count = 0

        for date, nutrition in self.nutrition_log.items():
            if date >= cutoff:
                for key, value in nutrition.items():
                    totals[key] += value
                count += 1

        if count == 0:
            return totals

        return {k: (v / count).quantize(Decimal("0.1")) for k, v in totals.items()}

    def detect_micronutrient_gaps(self) -> list[str]:
        """Identify potential micronutrient deficiencies based on ingredient usage.

        Returns:
            List[str]: List of potentially deficient micronutrients.
        """
        gaps = []

        # Simple heuristic: if certain ingredient categories underrepresented
        ingredient_categories = {
            "leafy greens": ["spinach", "kale", "lettuce"],
            "citrus": ["orange", "lemon", "lime"],
            "berries": ["blueberry", "strawberry", "raspberry"],
            "nuts": ["almond", "walnut", "cashew"],
            "fatty fish": ["salmon", "mackerel", "sardine"],
        }

        for category, ingredients in ingredient_categories.items():
            if not any(ing in self.ingredient_usage for ing in ingredients):
                if category == "leafy greens":
                    gaps.append("Iron, Calcium, Vitamin K")
                elif category == "citrus":
                    gaps.append("Vitamin C")
                elif category == "berries":
                    gaps.append("Antioxidants")
                elif category == "nuts":
                    gaps.append("Vitamin E, Selenium")
                elif category == "fatty fish":
                    gaps.append("Omega-3 Fatty Acids, Vitamin D")

        return gaps

    def get_cooking_frequency_stats(self) -> dict[str, int]:
        """Get cooking frequency statistics.

        Returns:
            Dict[str, int]: Most frequently cooked recipes.
        """
        return dict(
            sorted(
                self.cooking_frequency.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:10]
        )

    def get_popular_ingredients(self, limit: int = 10) -> list[tuple[str, int]]:
        """Get most frequently used ingredients.

        Args:
            limit: Number of ingredients to return.

        Returns:
            List[Tuple[str, int]]: (ingredient, usage_count).
        """
        sorted_ing = sorted(
            self.ingredient_usage.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        return sorted_ing[:limit]

    def get_cuisine_exploration(self) -> dict[str, int]:
        """Analyze cuisine diversity and exploration.

        Returns:
            Dict[str, int]: Cuisine to meal count.
        """
        return dict(
            sorted(
                self.cuisine_consumption.items(),
                key=lambda x: x[1],
                reverse=True,
            )
        )

    def get_variety_score(self, days: int = 30) -> Decimal:
        """Calculate meal variety score (0-100) over recent period.

        Args:
            days: Number of days to analyze.

        Returns:
            Decimal: Variety score percentage.
        """
        cutoff = datetime.now() - timedelta(days=days)
        recent_meals = [recipe_id for timestamp, _, recipe_id in self.meal_log if timestamp >= cutoff]

        if not recent_meals:
            return Decimal(0)

        unique_recipes = len(set(recent_meals))
        possible_unique = len(recent_meals)

        # Score based on unique recipes relative to total meals
        variety = (Decimal(unique_recipes) / Decimal(max(1, possible_unique))) * 100

        return variety.quantize(Decimal("0.1"))

    def get_food_waste_analysis(self, days: int = 30) -> dict[str, any]:
        """Analyze food waste patterns.

        Args:
            days: Number of days to analyze.

        Returns:
            Dict[str, any]: Waste statistics.
        """
        cutoff = datetime.now() - timedelta(days=days)
        total_waste = Decimal(0)
        waste_by_item = {}

        for date, item, quantity in self.waste_log:
            if date >= cutoff:
                total_waste += quantity
                waste_by_item[item] = waste_by_item.get(item, Decimal(0)) + quantity

        return {
            "total_waste_units": total_waste,
            "waste_by_item": dict(
                sorted(
                    waste_by_item.items(),
                    key=lambda x: x[1],
                    reverse=True,
                )
            ),
            "primary_waste_item": (max(waste_by_item, key=waste_by_item.get) if waste_by_item else None),
        }

    def get_spending_summary(self, spending_log: list[tuple[datetime, Decimal]]) -> dict[str, Decimal]:
        """Summarize food spending over time.

        Args:
            spending_log: List of (date, amount) tuples.

        Returns:
            Dict[str, Decimal]: Weekly and monthly spending totals.
        """
        week_ago = datetime.now() - timedelta(days=7)
        month_ago = datetime.now() - timedelta(days=30)

        weekly_total = Decimal(0)
        monthly_total = Decimal(0)

        for date, amount in spending_log:
            if date >= month_ago:
                monthly_total += amount
            if date >= week_ago:
                weekly_total += amount

        return {
            "weekly_spend": weekly_total.quantize(Decimal("0.01")),
            "monthly_spend": monthly_total.quantize(Decimal("0.01")),
            "avg_daily_spend": (monthly_total / Decimal(30)).quantize(Decimal("0.01")),
        }

    def get_comprehensive_analytics(self) -> dict[str, any]:
        """Get comprehensive analytics summary.

        Returns:
            Dict[str, any]: Complete analytics report.
        """
        return {
            "eating_patterns": self.get_eating_pattern_analysis(),
            "nutrition_trends": self.get_nutrition_trends(),
            "variety_score": self.get_variety_score(),
            "most_cooked": self.get_cooking_frequency_stats(),
            "popular_ingredients": self.get_popular_ingredients(5),
            "cuisine_diversity": self.get_cuisine_exploration(),
            "waste_analysis": self.get_food_waste_analysis(),
            "potential_deficiencies": self.detect_micronutrient_gaps(),
        }
