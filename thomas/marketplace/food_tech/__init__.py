"""
Food Technology Module - Recipe Management, Nutrition Analysis, and Meal Planning.

A comprehensive platform for managing recipes, tracking nutrition, planning meals,
managing dietary restrictions, and analyzing food-related data.
"""

from thomas.marketplace.food_tech._exceptions import (
    CostError,
    DietaryError,
    FoodTechError,
    InventoryError,
    MealPlanError,
    NutritionError,
    RecipeError,
)
from thomas.marketplace.food_tech._types import (
    Allergen,
    CookingMethod,
    CookingStep,
    CostBreakdown,
    DietaryRestriction,
    FoodCategory,
    FoodItem,
    GroceryList,
    Ingredient,
    KitchenEquipment,
    MealPlan,
    Nutrient,
    NutritionFacts,
    Recipe,
    ServingSize,
    Substitution,
)

__version__ = "1.0.0"
__all__ = [
    "Recipe",
    "Ingredient",
    "Nutrient",
    "MealPlan",
    "DietaryRestriction",
    "Allergen",
    "FoodItem",
    "ServingSize",
    "NutritionFacts",
    "CookingMethod",
    "CookingStep",
    "KitchenEquipment",
    "GroceryList",
    "FoodCategory",
    "Substitution",
    "CostBreakdown",
    "FoodTechError",
    "RecipeError",
    "NutritionError",
    "MealPlanError",
    "DietaryError",
    "InventoryError",
    "CostError",
]
