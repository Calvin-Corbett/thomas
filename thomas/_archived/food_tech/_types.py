"""
Core type definitions for the food technology platform.

Defines all primary data structures for recipes, nutrition, meal planning,
dietary management, and food inventory.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum


class FoodCategory(Enum):
    """Categories for food items."""

    VEGETABLES = "vegetables"
    FRUITS = "fruits"
    GRAINS = "grains"
    PROTEINS = "proteins"
    DAIRY = "dairy"
    FATS = "fats"
    CONDIMENTS = "condiments"
    BEVERAGES = "beverages"
    SPICES = "spices"
    NUTS_SEEDS = "nuts_seeds"
    LEGUMES = "legumes"
    PREPARED = "prepared"


class CookingMethod(Enum):
    """Methods for cooking food."""

    BAKING = "baking"
    ROASTING = "roasting"
    GRILLING = "grilling"
    BOILING = "boiling"
    STEAMING = "steaming"
    FRYING = "frying"
    SAUTEING = "sauteing"
    BRAISING = "braising"
    POACHING = "poaching"
    MICROWAVING = "microwaving"
    RAW = "raw"
    BLENDING = "blending"


class DietaryRestriction(Enum):
    """Dietary restriction types."""

    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    GLUTEN_FREE = "gluten_free"
    DAIRY_FREE = "dairy_free"
    NUT_FREE = "nut_free"
    KOSHER = "kosher"
    HALAL = "halal"
    KETO = "keto"
    PALEO = "paleo"
    LOW_SODIUM = "low_sodium"
    LOW_FODMAP = "low_fodmap"
    PESCATARIAN = "pescatarian"


class Allergen(Enum):
    """Common allergens."""

    PEANUTS = "peanuts"
    TREE_NUTS = "tree_nuts"
    MILK = "milk"
    EGGS = "eggs"
    FISH = "fish"
    SHELLFISH = "shellfish"
    SOY = "soy"
    WHEAT = "wheat"
    SESAME = "sesame"


@dataclass
class ServingSize:
    """Represents a serving size unit and quantity."""

    quantity: Decimal
    unit: str  # e.g., 'cup', 'g', 'oz', 'tbsp', 'tsp', 'ml'
    gram_equivalent: Decimal | None = None

    def to_grams(self) -> Decimal:
        """Convert serving size to grams.

        Returns:
            Decimal: Weight in grams.

        Raises:
            ValueError: If conversion is not possible.
        """
        if self.gram_equivalent is not None:
            return self.quantity * self.gram_equivalent
        raise ValueError(f"Cannot convert {self.unit} to grams")


@dataclass
class Nutrient:
    """Represents a single nutrient value."""

    name: str
    value: Decimal
    unit: str
    daily_value_percent: Decimal | None = None

    def scale(self, factor: Decimal) -> "Nutrient":
        """Scale nutrient by a factor.

        Args:
            factor: Multiplication factor.

        Returns:
            Nutrient: Scaled nutrient.
        """
        dv = self.daily_value_percent * factor if self.daily_value_percent else None
        return Nutrient(
            name=self.name,
            value=self.value * factor,
            unit=self.unit,
            daily_value_percent=dv,
        )


@dataclass
class NutritionFacts:
    """Complete nutrition information for a food item."""

    calories: Decimal
    protein: Decimal  # grams
    fat: Decimal  # grams
    carbohydrates: Decimal  # grams
    fiber: Decimal  # grams
    sugar: Decimal  # grams
    sodium: Decimal  # mg
    micronutrients: dict[str, Nutrient] = field(default_factory=dict)

    def scale(self, factor: Decimal) -> "NutritionFacts":
        """Scale nutrition facts by a factor.

        Args:
            factor: Multiplication factor.

        Returns:
            NutritionFacts: Scaled nutrition facts.
        """
        return NutritionFacts(
            calories=self.calories * factor,
            protein=self.protein * factor,
            fat=self.fat * factor,
            carbohydrates=self.carbohydrates * factor,
            fiber=self.fiber * factor,
            sugar=self.sugar * factor,
            sodium=self.sodium * factor,
            micronutrients={k: v.scale(factor) for k, v in self.micronutrients.items()},
        )

    def macro_ratios(self) -> dict[str, Decimal]:
        """Calculate macronutrient ratios as percentages.

        Returns:
            Dict[str, Decimal]: Percentages for protein, fat, carbs.
        """
        total_cals = (self.protein * 4) + (self.fat * 9) + (self.carbohydrates * 4)
        if total_cals == 0:
            return {"protein": Decimal(0), "fat": Decimal(0), "carbs": Decimal(0)}
        return {
            "protein": (self.protein * 4) / total_cals * 100,
            "fat": (self.fat * 9) / total_cals * 100,
            "carbs": (self.carbohydrates * 4) / total_cals * 100,
        }


@dataclass
class Ingredient:
    """Represents an ingredient in a recipe."""

    name: str
    quantity: Decimal
    unit: str
    category: FoodCategory
    nutrition_per_100g: NutritionFacts | None = None
    allergens: set[Allergen] = field(default_factory=set)
    notes: str = ""

    def scale(self, factor: Decimal) -> "Ingredient":
        """Scale ingredient quantity by a factor.

        Args:
            factor: Multiplication factor.

        Returns:
            Ingredient: Scaled ingredient.
        """
        return Ingredient(
            name=self.name,
            quantity=self.quantity * factor,
            unit=self.unit,
            category=self.category,
            nutrition_per_100g=self.nutrition_per_100g,
            allergens=self.allergens.copy(),
            notes=self.notes,
        )


@dataclass
class CookingStep:
    """Represents a single step in recipe preparation."""

    step_number: int
    description: str
    duration_minutes: int | None = None
    temperature_celsius: int | None = None
    notes: str = ""


@dataclass
class KitchenEquipment:
    """Kitchen equipment needed for a recipe."""

    name: str
    quantity: int = 1
    optional: bool = False


@dataclass
class Recipe:
    """Complete recipe with ingredients, instructions, and metadata."""

    id: str
    name: str
    description: str
    ingredients: list[Ingredient]
    steps: list[CookingStep]
    servings: int
    prep_time_minutes: int
    cook_time_minutes: int
    total_time_minutes: int
    cuisine: str
    meal_type: str  # breakfast, lunch, dinner, snack, dessert
    difficulty: str  # easy, medium, hard
    tags: set[str] = field(default_factory=set)
    equipment: list[KitchenEquipment] = field(default_factory=list)
    nutrition_per_serving: NutritionFacts | None = None
    dietary_restrictions: set[DietaryRestriction] = field(default_factory=set)
    version: int = 1
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    rating: Decimal | None = None
    review_count: int = 0
    cost_per_serving: Decimal | None = None

    def scale_servings(self, new_servings: int) -> "Recipe":
        """Create a scaled version of the recipe for different servings.

        Args:
            new_servings: Desired number of servings.

        Returns:
            Recipe: Scaled recipe.
        """
        factor = Decimal(new_servings) / Decimal(self.servings)
        return Recipe(
            id=self.id,
            name=self.name,
            description=self.description,
            ingredients=[ing.scale(factor) for ing in self.ingredients],
            steps=self.steps.copy(),
            servings=new_servings,
            prep_time_minutes=self.prep_time_minutes,
            cook_time_minutes=self.cook_time_minutes,
            total_time_minutes=self.total_time_minutes,
            cuisine=self.cuisine,
            meal_type=self.meal_type,
            difficulty=self.difficulty,
            tags=self.tags.copy(),
            equipment=self.equipment.copy(),
            nutrition_per_serving=(self.nutrition_per_serving.scale(factor) if self.nutrition_per_serving else None),
            dietary_restrictions=self.dietary_restrictions.copy(),
            version=self.version,
            created_at=self.created_at,
            updated_at=self.updated_at,
            rating=self.rating,
            review_count=self.review_count,
            cost_per_serving=self.cost_per_serving,
        )


@dataclass
class FoodItem:
    """Item in kitchen inventory."""

    name: str
    category: FoodCategory
    quantity: Decimal
    unit: str
    expiry_date: datetime | None = None
    storage_location: str = "pantry"  # pantry, fridge, freezer
    purchase_date: datetime = field(default_factory=datetime.now)
    cost: Decimal | None = None
    supplier: str = ""


@dataclass
class Substitution:
    """Ingredient substitution mapping."""

    original: str
    replacement: str
    ratio: Decimal = Decimal(1)  # multiplier for quantity
    notes: str = ""


@dataclass
class GroceryList:
    """Shopping list aggregating ingredients from recipes."""

    items: dict[str, tuple[Decimal, str]]  # name -> (quantity, unit)
    estimated_cost: Decimal | None = None
    dietary_notes: str = ""
    organized_by_category: dict[FoodCategory, list[str]] = field(default_factory=dict)


@dataclass
class CostBreakdown:
    """Cost analysis for a recipe."""

    recipe_id: str
    total_cost: Decimal
    cost_per_serving: Decimal
    ingredient_costs: dict[str, Decimal]  # name -> cost
    price_per_unit: dict[str, Decimal]  # normalized unit prices


@dataclass
class MealPlan:
    """Weekly meal plan with optimization."""

    start_date: datetime
    meals: dict[str, list[Recipe]]  # day -> [breakfast, lunch, dinner]
    total_calories: Decimal
    average_macros: dict[str, Decimal]  # protein, fat, carbs percentages
    grocery_list: GroceryList
    total_cost: Decimal
    estimated_prep_time_hours: Decimal
    constraints_met: dict[str, bool] = field(default_factory=dict)
