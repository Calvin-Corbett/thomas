"""
Recipe management module for food technology platform.

Handles recipe CRUD operations, versioning, ingredient parsing, scaling,
categorization, search, and similarity analysis.
"""

import re
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from thomas.food_tech._exceptions import (
    InvalidRecipeError,
    RecipeNotFoundError,
    RecipeParsingError,
)
from thomas.food_tech._types import (
    CookingStep,
    DietaryRestriction,
    Ingredient,
    KitchenEquipment,
    Recipe,
)


class RecipeManager:
    """Manages recipe CRUD operations with versioning and search."""

    def __init__(self) -> None:
        """Initialize recipe manager."""
        self.recipes: dict[str, list[Recipe]] = {}  # id -> versions
        self.search_index: dict[str, set[str]] = {}  # word -> recipe_ids

    def create_recipe(
        self,
        name: str,
        description: str,
        ingredients: list[Ingredient],
        steps: list[CookingStep],
        servings: int,
        prep_time_minutes: int,
        cook_time_minutes: int,
        cuisine: str,
        meal_type: str,
        difficulty: str,
        tags: set[str] | None = None,
        equipment: list[KitchenEquipment] | None = None,
        dietary_restrictions: set[DietaryRestriction] | None = None,
    ) -> Recipe:
        """Create a new recipe.

        Args:
            name: Recipe name.
            description: Recipe description.
            ingredients: List of ingredients.
            steps: Cooking steps.
            servings: Number of servings.
            prep_time_minutes: Preparation time in minutes.
            cook_time_minutes: Cooking time in minutes.
            cuisine: Cuisine type.
            meal_type: Meal type (breakfast, lunch, etc.).
            difficulty: Difficulty level (easy, medium, hard).
            tags: Optional tags.
            equipment: Optional kitchen equipment list.
            dietary_restrictions: Optional dietary restrictions.

        Returns:
            Recipe: Created recipe.

        Raises:
            InvalidRecipeError: If recipe data is invalid.
        """
        if not name or not ingredients or not steps:
            raise InvalidRecipeError("Recipe must have name, ingredients, and steps")

        recipe = Recipe(
            id=str(uuid4()),
            name=name,
            description=description,
            ingredients=ingredients,
            steps=steps,
            servings=servings,
            prep_time_minutes=prep_time_minutes,
            cook_time_minutes=cook_time_minutes,
            total_time_minutes=prep_time_minutes + cook_time_minutes,
            cuisine=cuisine,
            meal_type=meal_type,
            difficulty=difficulty,
            tags=tags or set(),
            equipment=equipment or [],
            dietary_restrictions=dietary_restrictions or set(),
        )

        self.recipes[recipe.id] = [recipe]
        self._update_search_index(recipe)
        return recipe

    def get_recipe(self, recipe_id: str, version: int | None = None) -> Recipe:
        """Get a recipe by ID, optionally at a specific version.

        Args:
            recipe_id: Recipe ID.
            version: Optional version number (defaults to latest).

        Returns:
            Recipe: The requested recipe.

        Raises:
            RecipeNotFoundError: If recipe or version not found.
        """
        if recipe_id not in self.recipes:
            raise RecipeNotFoundError(f"Recipe {recipe_id} not found")

        versions = self.recipes[recipe_id]
        if version is None:
            return versions[-1]

        for v in versions:
            if v.version == version:
                return v

        raise RecipeNotFoundError(f"Recipe {recipe_id} version {version} not found")

    def update_recipe(
        self,
        recipe_id: str,
        **kwargs,
    ) -> Recipe:
        """Update a recipe, creating a new version.

        Args:
            recipe_id: Recipe ID.
            **kwargs: Fields to update (name, description, ingredients, etc.).

        Returns:
            Recipe: Updated recipe.

        Raises:
            RecipeNotFoundError: If recipe not found.
        """
        current = self.get_recipe(recipe_id)
        new_recipe = Recipe(
            id=current.id,
            name=kwargs.get("name", current.name),
            description=kwargs.get("description", current.description),
            ingredients=kwargs.get("ingredients", current.ingredients),
            steps=kwargs.get("steps", current.steps),
            servings=kwargs.get("servings", current.servings),
            prep_time_minutes=kwargs.get("prep_time_minutes", current.prep_time_minutes),
            cook_time_minutes=kwargs.get("cook_time_minutes", current.cook_time_minutes),
            total_time_minutes=kwargs.get("total_time_minutes", current.total_time_minutes),
            cuisine=kwargs.get("cuisine", current.cuisine),
            meal_type=kwargs.get("meal_type", current.meal_type),
            difficulty=kwargs.get("difficulty", current.difficulty),
            tags=kwargs.get("tags", current.tags),
            equipment=kwargs.get("equipment", current.equipment),
            nutrition_per_serving=kwargs.get("nutrition_per_serving", current.nutrition_per_serving),
            dietary_restrictions=kwargs.get("dietary_restrictions", current.dietary_restrictions),
            version=current.version + 1,
            created_at=current.created_at,
            updated_at=datetime.now(),
            rating=current.rating,
            review_count=current.review_count,
            cost_per_serving=kwargs.get("cost_per_serving", current.cost_per_serving),
        )

        self.recipes[recipe_id].append(new_recipe)
        self._update_search_index(new_recipe)
        return new_recipe

    def delete_recipe(self, recipe_id: str) -> None:
        """Delete a recipe.

        Args:
            recipe_id: Recipe ID.

        Raises:
            RecipeNotFoundError: If recipe not found.
        """
        if recipe_id not in self.recipes:
            raise RecipeNotFoundError(f"Recipe {recipe_id} not found")

        del self.recipes[recipe_id]
        self._clean_search_index(recipe_id)

    def _update_search_index(self, recipe: Recipe) -> None:
        """Update search index for a recipe."""
        words = set()
        words.update(recipe.name.lower().split())
        words.update(recipe.cuisine.lower().split())
        words.update(recipe.meal_type.lower().split())
        words.update(recipe.tags)
        for ing in recipe.ingredients:
            words.update(ing.name.lower().split())

        for word in words:
            if word not in self.search_index:
                self.search_index[word] = set()
            self.search_index[word].add(recipe.id)

    def _clean_search_index(self, recipe_id: str) -> None:
        """Remove recipe from search index."""
        for word in list(self.search_index.keys()):
            self.search_index[word].discard(recipe_id)
            if not self.search_index[word]:
                del self.search_index[word]

    def search_recipes(
        self,
        keywords: list[str] | None = None,
        tags: set[str] | None = None,
        ingredients: list[str] | None = None,
        cuisine: str | None = None,
        meal_type: str | None = None,
        max_prep_time: int | None = None,
    ) -> list[Recipe]:
        """Search recipes by multiple criteria.

        Args:
            keywords: Keywords to search in name, description, ingredients.
            tags: Tags to filter by.
            ingredients: Required ingredients.
            cuisine: Cuisine type filter.
            meal_type: Meal type filter.
            max_prep_time: Maximum preparation time in minutes.

        Returns:
            List[Recipe]: Matching recipes.
        """
        results: set[str] = None

        if keywords:
            for keyword in keywords:
                keyword_lower = keyword.lower()
                if keyword_lower in self.search_index:
                    ids = self.search_index[keyword_lower]
                    if results is None:
                        results = ids.copy()
                    else:
                        results &= ids

        if results is None:
            results = set(self.recipes.keys())

        filtered_recipes = []
        for recipe_id in results:
            recipe = self.get_recipe(recipe_id)

            if tags and not tags.issubset(recipe.tags):
                continue

            if ingredients:
                recipe_ingredients = {ing.name.lower() for ing in recipe.ingredients}
                if not all(ing.lower() in recipe_ingredients for ing in ingredients):
                    continue

            if cuisine and recipe.cuisine.lower() != cuisine.lower():
                continue

            if meal_type and recipe.meal_type.lower() != meal_type.lower():
                continue

            if max_prep_time and recipe.prep_time_minutes > max_prep_time:
                continue

            filtered_recipes.append(recipe)

        return filtered_recipes

    def calculate_recipe_similarity(self, recipe_id1: str, recipe_id_2: str) -> Decimal:
        """Calculate Jaccard similarity between two recipes based on ingredients.

        Args:
            recipe_id1: First recipe ID.
            recipe_id_2: Second recipe ID.

        Returns:
            Decimal: Similarity score between 0 and 1.

        Raises:
            RecipeNotFoundError: If recipes not found.
        """
        recipe1 = self.get_recipe(recipe_id1)
        recipe2 = self.get_recipe(recipe_id_2)

        ingredients1 = {ing.name.lower() for ing in recipe1.ingredients}
        ingredients2 = {ing.name.lower() for ing in recipe2.ingredients}

        if not ingredients1 and not ingredients2:
            return Decimal(1)

        intersection = len(ingredients1 & ingredients2)
        union = len(ingredients1 | ingredients2)

        if union == 0:
            return Decimal(0)

        return Decimal(intersection) / Decimal(union)

    def find_similar_recipes(
        self, recipe_id: str, min_similarity: Decimal = Decimal("0.3")
    ) -> list[tuple[str, Decimal]]:
        """Find similar recipes based on ingredient overlap.

        Args:
            recipe_id: Recipe ID.
            min_similarity: Minimum similarity threshold.

        Returns:
            List[Tuple[str, Decimal]]: List of (recipe_id, similarity) tuples.
        """
        similar = []
        for other_id in self.recipes.keys():
            if other_id == recipe_id:
                continue
            similarity = self.calculate_recipe_similarity(recipe_id, other_id)
            if similarity >= min_similarity:
                similar.append((other_id, similarity))

        return sorted(similar, key=lambda x: x[1], reverse=True)

    def rate_recipe(self, recipe_id: str, rating: Decimal) -> Recipe:
        """Rate a recipe and update rating average.

        Args:
            recipe_id: Recipe ID.
            rating: Rating value (0-5).

        Returns:
            Recipe: Updated recipe.

        Raises:
            RecipeNotFoundError: If recipe not found.
            ValueError: If rating is out of range.
        """
        if not (Decimal(0) <= rating <= Decimal(5)):
            raise ValueError("Rating must be between 0 and 5")

        recipe = self.get_recipe(recipe_id)
        current_total = recipe.rating * Decimal(recipe.review_count) if recipe.rating else Decimal(0)
        new_total = current_total + rating
        new_count = recipe.review_count + 1
        new_rating = (new_total / Decimal(new_count)).quantize(Decimal("0.01"))

        # Create new version with updated rating
        new_recipe = Recipe(
            id=recipe.id,
            name=recipe.name,
            description=recipe.description,
            ingredients=recipe.ingredients,
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
            version=recipe.version + 1,
            created_at=recipe.created_at,
            updated_at=datetime.now(),
            rating=new_rating,
            review_count=new_count,
            cost_per_serving=recipe.cost_per_serving,
        )

        self.recipes[recipe_id].append(new_recipe)
        return new_recipe


class IngredientParser:
    """Parses ingredient strings into structured ingredient objects."""

    UNIT_PATTERNS = {
        "cup": ["cup", "cups", "c"],
        "tablespoon": ["tbsp", "tbsps", "tablespoon", "tablespoons"],
        "teaspoon": ["tsp", "tsps", "teaspoon", "teaspoons"],
        "gram": ["g", "gram", "grams"],
        "ml": ["ml", "mls"],
        "oz": ["oz", "ounce", "ounces"],
        "lb": ["lb", "lbs", "pound", "pounds"],
    }

    @staticmethod
    def parse_ingredient(ingredient_str: str) -> tuple[Decimal, str, str]:
        """Parse ingredient string into quantity, unit, and name.

        Args:
            ingredient_str: Ingredient string (e.g., "2 cups flour").

        Returns:
            Tuple[Decimal, str, str]: (quantity, unit, ingredient_name).

        Raises:
            RecipeParsingError: If parsing fails.
        """
        ingredient_str = ingredient_str.strip()
        pattern = r"^(\d+(?:\.\d+)?)\s*(\w+)?\s+(.+)$"
        match = re.match(pattern, ingredient_str)

        if not match:
            raise RecipeParsingError(f"Cannot parse ingredient: {ingredient_str}")

        quantity_str, unit, name = match.groups()
        quantity = Decimal(quantity_str)
        unit = unit or "unit"
        name = name.strip()

        return quantity, unit, name

    @staticmethod
    def normalize_unit(unit: str) -> str:
        """Normalize unit to standard form.

        Args:
            unit: Unit string.

        Returns:
            str: Normalized unit.
        """
        unit_lower = unit.lower()
        for standard, variants in IngredientParser.UNIT_PATTERNS.items():
            if unit_lower in variants:
                return standard
        return unit

    @staticmethod
    def parse_multiple_ingredients(
        ingredients_text: str,
    ) -> list[tuple[Decimal, str, str]]:
        """Parse multiple ingredient lines.

        Args:
            ingredients_text: Multi-line ingredient text.

        Returns:
            List[Tuple[Decimal, str, str]]: List of (quantity, unit, name).
        """
        ingredients = []
        for line in ingredients_text.split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                try:
                    parsed = IngredientParser.parse_ingredient(line)
                    ingredients.append(parsed)
                except RecipeParsingError:
                    continue

        return ingredients
