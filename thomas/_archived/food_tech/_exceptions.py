"""
Exception classes for the food technology platform.

Defines custom exceptions for different modules and error scenarios.
"""


class FoodTechError(Exception):
    """Base exception for all food tech errors."""

    pass


class RecipeError(FoodTechError):
    """Raised when recipe operations fail."""

    pass


class RecipeNotFoundError(RecipeError):
    """Raised when a recipe cannot be found."""

    pass


class InvalidRecipeError(RecipeError):
    """Raised when recipe data is invalid."""

    pass


class RecipeParsingError(RecipeError):
    """Raised when parsing recipe text fails."""

    pass


class NutritionError(FoodTechError):
    """Raised when nutrition analysis fails."""

    pass


class NutrientNotFoundError(NutritionError):
    """Raised when nutrient data is unavailable."""

    pass


class MacroCalculationError(NutritionError):
    """Raised when macronutrient calculation fails."""

    pass


class MealPlanError(FoodTechError):
    """Raised when meal planning fails."""

    pass


class PlanGenerationError(MealPlanError):
    """Raised when meal plan generation fails."""

    pass


class ConstraintViolationError(MealPlanError):
    """Raised when meal plan constraints cannot be satisfied."""

    pass


class DietaryError(FoodTechError):
    """Raised when dietary restriction operations fail."""

    pass


class AllergenError(DietaryError):
    """Raised when allergen checks fail."""

    pass


class InventoryError(FoodTechError):
    """Raised when inventory operations fail."""

    pass


class LowStockError(InventoryError):
    """Raised when items are low in stock."""

    pass


class ExpiredItemError(InventoryError):
    """Raised when expired items are detected."""

    pass


class CostError(FoodTechError):
    """Raised when cost analysis fails."""

    pass


class PriceDataError(CostError):
    """Raised when price data is unavailable."""

    pass
