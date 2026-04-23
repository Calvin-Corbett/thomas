"""
Dietary management module for food technology platform.

Handles dietary restrictions, allergen detection, ingredient substitutions,
and diet compliance scoring.
"""

from decimal import Decimal

from thomas.food_tech._types import (
    Allergen,
    DietaryRestriction,
    Ingredient,
    Recipe,
    Substitution,
)


class DietaryManager:
    """Manages dietary restrictions, allergens, and substitutions."""

    # Mapping of dietary restrictions to restricted ingredients
    RESTRICTION_INGREDIENTS = {
        DietaryRestriction.VEGETARIAN: {"meat", "poultry", "fish", "shellfish"},
        DietaryRestriction.VEGAN: {"meat", "poultry", "fish", "shellfish", "milk", "egg", "honey"},
        DietaryRestriction.GLUTEN_FREE: {"wheat", "barley", "rye", "oats"},
        DietaryRestriction.DAIRY_FREE: {"milk", "cheese", "butter", "yogurt", "cream"},
        DietaryRestriction.NUT_FREE: {"peanuts", "tree nuts", "almond", "walnut", "cashew"},
        DietaryRestriction.KOSHER: {"pork", "shellfish", "mixing meat and dairy"},
        DietaryRestriction.HALAL: {"pork", "alcohol", "non-halal meat"},
        DietaryRestriction.KETO: {"grains", "sugar", "starch"},
        DietaryRestriction.PALEO: {"grains", "legumes", "dairy", "processed foods"},
        DietaryRestriction.LOW_SODIUM: {"salt", "cured meats", "processed foods"},
        DietaryRestriction.LOW_FODMAP: {"onions", "garlic", "wheat", "honey"},
        DietaryRestriction.PESCATARIAN: {"meat", "poultry"},
    }

    # Allergen to common food sources mapping
    ALLERGEN_SOURCES = {
        Allergen.PEANUTS: {"peanut", "peanut oil", "peanut butter"},
        Allergen.TREE_NUTS: {
            "almond",
            "walnut",
            "cashew",
            "pecan",
            "macadamia",
            "pistachio",
        },
        Allergen.MILK: {"milk", "cheese", "butter", "yogurt", "cream", "whey"},
        Allergen.EGGS: {"egg", "mayonnaise"},
        Allergen.FISH: {"fish", "salmon", "tuna", "cod", "anchovy"},
        Allergen.SHELLFISH: {"shrimp", "crab", "lobster", "clam", "oyster"},
        Allergen.SOY: {"soy", "soybean", "tofu", "tempeh", "soy sauce"},
        Allergen.WHEAT: {"wheat", "flour", "bread", "pasta", "cereal"},
        Allergen.SESAME: {"sesame", "tahini", "sesame oil"},
    }

    def __init__(self) -> None:
        """Initialize dietary manager."""
        self.user_restrictions: set[DietaryRestriction] = set()
        self.user_allergens: set[Allergen] = set()
        self.substitutions: dict[str, list[Substitution]] = {}

    def set_restrictions(self, restrictions: set[DietaryRestriction]) -> None:
        """Set user dietary restrictions.

        Args:
            restrictions: Set of dietary restrictions.
        """
        self.user_restrictions = restrictions

    def set_allergens(self, allergens: set[Allergen]) -> None:
        """Set user allergens.

        Args:
            allergens: Set of allergens to avoid.
        """
        self.user_allergens = allergens

    def add_substitution(self, substitution: Substitution) -> None:
        """Add an ingredient substitution.

        Args:
            substitution: Substitution mapping.
        """
        original = substitution.original.lower()
        if original not in self.substitutions:
            self.substitutions[original] = []
        self.substitutions[original].append(substitution)

    def check_recipe_compliance(self, recipe: Recipe) -> dict[str, bool]:
        """Check if a recipe complies with user dietary restrictions.

        Args:
            recipe: Recipe to check.

        Returns:
            Dict[str, bool]: Compliance status for each restriction.
        """
        compliance = {}

        for restriction in self.user_restrictions:
            if restriction in self.RESTRICTION_INGREDIENTS:
                restricted = self.RESTRICTION_INGREDIENTS[restriction]
                recipe_ingredients_lower = {ing.name.lower() for ing in recipe.ingredients}

                # Check if any restricted ingredient is in recipe
                violates = False
                for restricted_item in restricted:
                    if any(restricted_item.lower() in ing_name for ing_name in recipe_ingredients_lower):
                        violates = True
                        break

                compliance[restriction.value] = not violates

        return compliance

    def is_recipe_safe(self, recipe: Recipe) -> bool:
        """Check if recipe is safe based on allergens.

        Args:
            recipe: Recipe to check.

        Returns:
            bool: True if recipe contains no user allergens.
        """
        recipe_allergens = set()

        for ingredient in recipe.ingredients:
            recipe_allergens.update(ingredient.allergens)

        return recipe_allergens.isdisjoint(self.user_allergens)

    def detect_allergens_in_ingredient(self, ingredient: str) -> set[Allergen]:
        """Detect potential allergens in an ingredient string.

        Args:
            ingredient: Ingredient name or description.

        Returns:
            Set[Allergen]: Detected allergens.
        """
        detected = set()
        ingredient_lower = ingredient.lower()

        for allergen, sources in self.ALLERGEN_SOURCES.items():
            if any(source in ingredient_lower for source in sources):
                detected.add(allergen)

        return detected

    def find_substitutions(
        self,
        ingredient: str,
        substitution_count: int = 3,
    ) -> list[Substitution]:
        """Find substitutions for an ingredient.

        Args:
            ingredient: Ingredient to substitute.
            substitution_count: Number of substitutions to return.

        Returns:
            List[Substitution]: Available substitutions.
        """
        ingredient_lower = ingredient.lower()
        if ingredient_lower in self.substitutions:
            return self.substitutions[ingredient_lower][:substitution_count]

        # Return common substitutions based on ingredient type
        common_subs = self._get_common_substitutions(ingredient_lower)
        return common_subs[:substitution_count]

    def _get_common_substitutions(self, ingredient: str) -> list[Substitution]:
        """Get common substitutions for an ingredient."""
        # Basic substitution library
        substitution_map = {
            "butter": [
                Substitution("butter", "olive oil", Decimal("0.75")),
                Substitution("butter", "applesauce", Decimal("1")),
                Substitution("butter", "coconut oil", Decimal("1")),
            ],
            "milk": [
                Substitution("milk", "almond milk", Decimal("1")),
                Substitution("milk", "coconut milk", Decimal("1")),
                Substitution("milk", "oat milk", Decimal("1")),
            ],
            "egg": [
                Substitution("egg", "flax egg", Decimal("1")),
                Substitution("egg", "chia egg", Decimal("1")),
                Substitution("egg", "applesauce", Decimal("0.25")),
            ],
            "sugar": [
                Substitution("sugar", "honey", Decimal("0.75")),
                Substitution("sugar", "maple syrup", Decimal("0.75")),
                Substitution("sugar", "stevia", Decimal("0.5")),
            ],
            "flour": [
                Substitution("flour", "almond flour", Decimal("1.25")),
                Substitution("flour", "coconut flour", Decimal("0.25")),
                Substitution("flour", "oat flour", Decimal("1.3")),
            ],
        }

        return substitution_map.get(ingredient, [])

    def substitute_ingredient_in_recipe(
        self,
        recipe: Recipe,
        original_ingredient: str,
        substitution: Substitution,
    ) -> Recipe:
        """Create a recipe variant with substituted ingredient.

        Args:
            recipe: Original recipe.
            original_ingredient: Ingredient to replace.
            substitution: Substitution to apply.

        Returns:
            Recipe: Recipe with substituted ingredient.
        """
        new_ingredients = []

        for ingredient in recipe.ingredients:
            if ingredient.name.lower() == original_ingredient.lower():
                # Create substituted ingredient
                new_ing = Ingredient(
                    name=substitution.replacement,
                    quantity=ingredient.quantity * substitution.ratio,
                    unit=ingredient.unit,
                    category=ingredient.category,
                    nutrition_per_100g=ingredient.nutrition_per_100g,
                    allergens=ingredient.allergens.copy(),
                    notes=ingredient.notes + f" (substituted from {ingredient.name})",
                )
                new_ingredients.append(new_ing)
            else:
                new_ingredients.append(ingredient)

        return Recipe(
            id=recipe.id,
            name=f"{recipe.name} (with {substitution.replacement})",
            description=recipe.description,
            ingredients=new_ingredients,
            steps=recipe.steps,
            servings=recipe.servings,
            prep_time_minutes=recipe.prep_time_minutes,
            cook_time_minutes=recipe.cook_time_minutes,
            total_time_minutes=recipe.total_time_minutes,
            cuisine=recipe.cuisine,
            meal_type=recipe.meal_type,
            difficulty=recipe.difficulty,
            tags=recipe.tags,
            equipment=recipe.equipment,
            nutrition_per_serving=recipe.nutrition_per_serving,
            dietary_restrictions=recipe.dietary_restrictions,
            version=recipe.version,
            created_at=recipe.created_at,
            updated_at=recipe.updated_at,
            rating=recipe.rating,
            review_count=recipe.review_count,
            cost_per_serving=recipe.cost_per_serving,
        )

    def calculate_compliance_score(self, recipe: Recipe) -> Decimal:
        """Calculate a recipe's compliance with user dietary goals (0-100).

        Args:
            recipe: Recipe to evaluate.

        Returns:
            Decimal: Compliance score percentage.
        """
        score = Decimal(100)

        # Check dietary restrictions
        compliance = self.check_recipe_compliance(recipe)
        violations = sum(1 for v in compliance.values() if not v)
        if violations > 0:
            score -= Decimal(violations) * Decimal(25)

        # Check allergens
        if not self.is_recipe_safe(recipe):
            score -= Decimal(50)

        # Check dietary restriction alignment (bonus)
        recipe_restrictions = recipe.dietary_restrictions & self.user_restrictions
        if len(recipe_restrictions) > 0:
            score = min(Decimal(100), score + Decimal(10))

        return max(Decimal(0), min(Decimal(100), score))

    def count_macronutrients_for_diet(
        self,
        recipes: list[Recipe],
    ) -> dict[str, Decimal]:
        """Count macronutrients across recipes for diet analysis.

        Args:
            recipes: List of recipes.

        Returns:
            Dict[str, Decimal]: Totals for protein, fat, carbs, calories.
        """
        totals = {
            "protein": Decimal(0),
            "fat": Decimal(0),
            "carbs": Decimal(0),
            "calories": Decimal(0),
        }

        for recipe in recipes:
            if recipe.nutrition_per_serving:
                totals["protein"] += recipe.nutrition_per_serving.protein
                totals["fat"] += recipe.nutrition_per_serving.fat
                totals["carbs"] += recipe.nutrition_per_serving.carbohydrates
                totals["calories"] += recipe.nutrition_per_serving.calories

        return totals
