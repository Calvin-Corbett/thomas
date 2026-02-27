"""
Cost analysis module for food technology platform.

Handles recipe cost calculation, price comparison, budget tracking,
and cost optimization strategies.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from thomas.food_tech._types import CostBreakdown, Ingredient, Recipe


class CostAnalyzer:
    """Analyzes costs of recipes and ingredients."""

    def __init__(self) -> None:
        """Initialize cost analyzer."""
        self.ingredient_prices: dict[str, tuple[Decimal, str]] = {}  # name -> (price, unit)
        self.price_history: dict[str, list[tuple[datetime, Decimal]]] = {}
        self.budget_log: list[tuple[datetime, Decimal]] = []

    def set_ingredient_price(
        self,
        ingredient_name: str,
        price: Decimal,
        unit: str = "unit",
    ) -> None:
        """Set current price for an ingredient.

        Args:
            ingredient_name: Ingredient name.
            price: Price per unit.
            unit: Unit of measurement (per gram, per serving, etc.).
        """
        key = ingredient_name.lower()
        self.ingredient_prices[key] = (price, unit)

        # Log in price history
        if key not in self.price_history:
            self.price_history[key] = []
        self.price_history[key].append((datetime.now(), price))

    def get_ingredient_cost(self, ingredient: Ingredient) -> Decimal | None:
        """Calculate cost of an ingredient.

        Args:
            ingredient: Ingredient to price.

        Returns:
            Optional[Decimal]: Cost, or None if price not available.
        """
        key = ingredient.name.lower()

        if key not in self.ingredient_prices:
            return None

        price, unit = self.ingredient_prices[key]

        # Simple quantity-based calculation
        return (price * ingredient.quantity).quantize(Decimal("0.01"))

    def calculate_recipe_cost(self, recipe: Recipe) -> CostBreakdown | None:
        """Calculate total cost and per-serving cost of a recipe.

        Args:
            recipe: Recipe to analyze.

        Returns:
            Optional[CostBreakdown]: Cost breakdown, or None if prices incomplete.

        Raises:
            CostError: If cost calculation fails.
        """
        ingredient_costs: dict[str, Decimal] = {}
        total_cost = Decimal(0)
        missing_prices = []

        for ingredient in recipe.ingredients:
            cost = self.get_ingredient_cost(ingredient)

            if cost is None:
                missing_prices.append(ingredient.name)
                continue

            ingredient_costs[ingredient.name] = cost
            total_cost += cost

        if missing_prices:
            # Continue with partial cost data
            pass

        cost_per_serving = (
            (total_cost / Decimal(recipe.servings)).quantize(Decimal("0.01")) if recipe.servings > 0 else Decimal(0)
        )

        # Calculate normalized unit prices
        price_per_unit = {}
        for ingredient in recipe.ingredients:
            key = ingredient.name.lower()
            if key in self.ingredient_prices:
                price, _ = self.ingredient_prices[key]
                price_per_unit[ingredient.name] = price

        return CostBreakdown(
            recipe_id=recipe.id,
            total_cost=total_cost,
            cost_per_serving=cost_per_serving,
            ingredient_costs=ingredient_costs,
            price_per_unit=price_per_unit,
        )

    def compare_prices(
        self,
        ingredient_name: str,
        prices: list[tuple[str, Decimal]],
    ) -> tuple[str, Decimal]:
        """Compare prices for an ingredient from different sources.

        Args:
            ingredient_name: Ingredient name.
            prices: List of (supplier, price) tuples.

        Returns:
            Tuple[str, Decimal]: (cheapest_supplier, best_price).

        Raises:
            ValueError: If prices list is empty.
        """
        if not prices:
            raise ValueError("No prices provided")

        return min(prices, key=lambda x: x[1])

    def calculate_unit_price(
        self,
        total_price: Decimal,
        quantity: Decimal,
        unit: str,
    ) -> Decimal:
        """Calculate normalized unit price.

        Args:
            total_price: Total price.
            quantity: Quantity value.
            unit: Unit of measurement.

        Returns:
            Decimal: Price per standard unit.
        """
        if quantity <= 0:
            return Decimal(0)

        # Normalize to standard units
        unit_normalizations = {
            "oz": Decimal("28.35"),  # to grams
            "cup": Decimal("240"),
            "tbsp": Decimal("15"),
            "tsp": Decimal("5"),
            "ml": Decimal("1"),
            "lb": Decimal("453.592"),
        }

        normalized_qty = quantity * unit_normalizations.get(unit, Decimal("1"))
        return (total_price / normalized_qty).quantize(Decimal("0.0001"))

    def find_cheaper_substitute(
        self,
        ingredient_name: str,
        alternatives: list[str],
    ) -> str | None:
        """Find the cheapest substitute ingredient.

        Args:
            ingredient_name: Original ingredient.
            alternatives: Alternative ingredients.

        Returns:
            Optional[str]: Cheapest alternative, or None.
        """
        original_price = self.ingredient_prices.get(ingredient_name.lower())

        if not original_price:
            return None

        cheapest = None
        cheapest_price = original_price[0]

        for alt in alternatives:
            alt_price = self.ingredient_prices.get(alt.lower())
            if alt_price and alt_price[0] < cheapest_price:
                cheapest = alt
                cheapest_price = alt_price[0]

        return cheapest

    def track_budget(self, amount_spent: Decimal) -> None:
        """Track food spending.

        Args:
            amount_spent: Amount spent.
        """
        self.budget_log.append((datetime.now(), amount_spent))

    def get_weekly_budget(self) -> Decimal:
        """Get total spending in the past week.

        Returns:
            Decimal: Weekly spending total.
        """
        week_ago = datetime.now() - timedelta(days=7)
        weekly_total = sum(amount for date, amount in self.budget_log if date >= week_ago)
        return weekly_total.quantize(Decimal("0.01"))

    def get_monthly_budget(self) -> Decimal:
        """Get total spending in the past month.

        Returns:
            Decimal: Monthly spending total.
        """
        month_ago = datetime.now() - timedelta(days=30)
        monthly_total = sum(amount for date, amount in self.budget_log if date >= month_ago)
        return monthly_total.quantize(Decimal("0.01"))

    def get_price_trend(self, ingredient_name: str) -> str | None:
        """Analyze price trend for an ingredient.

        Args:
            ingredient_name: Ingredient name.

        Returns:
            Optional[str]: "rising", "falling", or "stable".
        """
        key = ingredient_name.lower()

        if key not in self.price_history or len(self.price_history[key]) < 2:
            return None

        history = self.price_history[key]
        recent_avg = Decimal(sum(p for _, p in history[-5:])) / Decimal(min(5, len(history)))
        older_avg = Decimal(sum(p for _, p in history[:-5])) / Decimal(max(1, len(history) - 5))

        if recent_avg > older_avg * Decimal("1.05"):
            return "rising"
        elif recent_avg < older_avg * Decimal("0.95"):
            return "falling"
        else:
            return "stable"

    def set_price_alert(
        self,
        ingredient_name: str,
        price_threshold: Decimal,
    ) -> None:
        """Create a price alert for an ingredient.

        Args:
            ingredient_name: Ingredient name.
            price_threshold: Alert if price drops below this.
        """
        key = ingredient_name.lower()

        if key in self.ingredient_prices:
            current_price = self.ingredient_prices[key][0]
            if current_price > price_threshold:
                # Alert would be triggered
                pass

    def get_cost_optimization_tips(self, recipe: Recipe) -> list[str]:
        """Get tips to reduce recipe cost.

        Args:
            recipe: Recipe to optimize.

        Returns:
            List[str]: Cost optimization suggestions.
        """
        tips = []

        for ingredient in recipe.ingredients:
            key = ingredient.name.lower()

            if key in self.price_history and len(self.price_history[key]) > 3:
                trend = self.get_price_trend(ingredient.name)
                if trend == "rising":
                    tips.append(f"Price of {ingredient.name} is rising - consider buying now")

            # Look for substitutes
            subs = self._find_cheaper_alternatives(ingredient.name)
            if subs:
                tips.append(f"Consider using {subs[0]} instead of {ingredient.name}")

        return tips

    def _find_cheaper_alternatives(self, ingredient: str) -> list[str]:
        """Find cheaper alternative ingredients."""
        alternatives = {
            "chicken breast": ["chicken thighs"],
            "fresh vegetables": ["frozen vegetables"],
            "beef": ["ground beef"],
            "fresh herbs": ["dried herbs"],
        }
        return alternatives.get(ingredient.lower(), [])

    def calculate_seasonal_adjustment(
        self,
        ingredient_name: str,
        is_in_season: bool,
    ) -> Decimal:
        """Calculate seasonal price adjustment factor.

        Args:
            ingredient_name: Ingredient name.
            is_in_season: True if ingredient is in season.

        Returns:
            Decimal: Price adjustment multiplier (0.7-1.3).
        """
        # In-season items typically cost 20-30% less
        if is_in_season:
            return Decimal("0.7")
        else:
            return Decimal("1.3")

    def optimize_budget_recipe_selection(
        self,
        recipes: list[Recipe],
        budget: Decimal,
    ) -> list[Recipe]:
        """Select recipes that fit within budget, prioritizing value.

        Args:
            recipes: Available recipes.
            budget: Budget per meal.

        Returns:
            List[Recipe]: Selected recipes within budget.
        """
        costed_recipes = []

        for recipe in recipes:
            cost = self.calculate_recipe_cost(recipe)
            if cost and cost.cost_per_serving <= budget:
                costed_recipes.append(recipe)

        # Sort by cost per serving
        costed_recipes.sort(
            key=lambda r: (
                self.calculate_recipe_cost(r).cost_per_serving if self.calculate_recipe_cost(r) else Decimal("999")
            )
        )

        return costed_recipes
