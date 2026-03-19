"""
Nutrition analysis module for food technology platform.

Handles macronutrient and micronutrient calculations, BMR/TDEE estimation,
daily value percentages, and macro ratio analysis.
"""

from decimal import Decimal
from enum import Enum

from thomas.food_tech._types import Ingredient, Nutrient, NutritionFacts, Recipe


class ActivityLevel(Enum):
    """Physical activity levels for TDEE calculation."""

    SEDENTARY = Decimal("1.2")
    LIGHTLY_ACTIVE = Decimal("1.375")
    MODERATELY_ACTIVE = Decimal("1.55")
    VERY_ACTIVE = Decimal("1.725")
    EXTREMELY_ACTIVE = Decimal("1.9")


class MacroProfile(Enum):
    """Macronutrient distribution profiles."""

    BALANCED = {"protein": Decimal("30"), "fat": Decimal("30"), "carbs": Decimal("40")}
    KETO = {"protein": Decimal("25"), "fat": Decimal("70"), "carbs": Decimal("5")}
    HIGH_PROTEIN = {"protein": Decimal("40"), "fat": Decimal("25"), "carbs": Decimal("35")}
    LOW_CARB = {"protein": Decimal("35"), "fat": Decimal("40"), "carbs": Decimal("25")}


class NutritionAnalyzer:
    """Analyzes nutrition content of recipes and food items."""

    # Daily value references (FDA standards)
    DAILY_VALUES = {
        "vitamin_a_mcg": Decimal("900"),
        "vitamin_c_mg": Decimal("90"),
        "vitamin_d_mcg": Decimal("20"),
        "vitamin_e_mg": Decimal("15"),
        "vitamin_k_mcg": Decimal("120"),
        "iron_mg": Decimal("18"),
        "calcium_mg": Decimal("1300"),
        "potassium_mg": Decimal("3500"),
        "sodium_mg": Decimal("2300"),
    }

    def __init__(self) -> None:
        """Initialize nutrition analyzer with USDA-style nutrient database."""
        self.ingredient_database: dict[str, NutritionFacts] = {}
        self._load_sample_database()

    def _load_sample_database(self) -> None:
        """Load sample nutrition database (per 100g)."""
        self.ingredient_database = {
            "chicken_breast": NutritionFacts(
                calories=Decimal("165"),
                protein=Decimal("31"),
                fat=Decimal("3.6"),
                carbohydrates=Decimal("0"),
                fiber=Decimal("0"),
                sugar=Decimal("0"),
                sodium=Decimal("74"),
                micronutrients={
                    "vitamin_b12_mcg": Nutrient("B12", Decimal("0.3"), "mcg", Decimal("12")),
                    "iron_mg": Nutrient("Iron", Decimal("0.8"), "mg", Decimal("4")),
                },
            ),
            "brown_rice": NutritionFacts(
                calories=Decimal("111"),
                protein=Decimal("2.6"),
                fat=Decimal("0.9"),
                carbohydrates=Decimal("23"),
                fiber=Decimal("1.8"),
                sugar=Decimal("0.2"),
                sodium=Decimal("7"),
                micronutrients={
                    "manganese_mg": Nutrient("Manganese", Decimal("1.3"), "mg", Decimal("65")),
                    "magnesium_mg": Nutrient("Magnesium", Decimal("84"), "mg", Decimal("20")),
                },
            ),
            "broccoli": NutritionFacts(
                calories=Decimal("34"),
                protein=Decimal("2.8"),
                fat=Decimal("0.4"),
                carbohydrates=Decimal("7"),
                fiber=Decimal("2.4"),
                sugar=Decimal("1.4"),
                sodium=Decimal("64"),
                micronutrients={
                    "vitamin_c_mg": Nutrient("Vitamin C", Decimal("89"), "mg", Decimal("99")),
                    "vitamin_k_mcg": Nutrient("Vitamin K", Decimal("102"), "mcg", Decimal("85")),
                    "calcium_mg": Nutrient("Calcium", Decimal("47"), "mg", Decimal("4")),
                },
            ),
            "olive_oil": NutritionFacts(
                calories=Decimal("884"),
                protein=Decimal("0"),
                fat=Decimal("100"),
                carbohydrates=Decimal("0"),
                fiber=Decimal("0"),
                sugar=Decimal("0"),
                sodium=Decimal("2"),
            ),
            "salmon": NutritionFacts(
                calories=Decimal("208"),
                protein=Decimal("20"),
                fat=Decimal("13"),
                carbohydrates=Decimal("0"),
                fiber=Decimal("0"),
                sugar=Decimal("0"),
                sodium=Decimal("75"),
                micronutrients={
                    "vitamin_d_mcg": Nutrient("Vitamin D", Decimal("570"), "IU", Decimal("143")),
                    "omega_3_mg": Nutrient("Omega-3", Decimal("2260"), "mg"),
                },
            ),
        }

    def analyze_recipe(self, recipe: Recipe) -> NutritionFacts | None:
        """Calculate nutrition facts for a recipe per serving.

        Args:
            recipe: Recipe to analyze.

        Returns:
            Optional[NutritionFacts]: Nutrition facts per serving, or None if data incomplete.

        Raises:
            NutritionError: If analysis fails.
        """
        total_nutrition = NutritionFacts(
            calories=Decimal(0),
            protein=Decimal(0),
            fat=Decimal(0),
            carbohydrates=Decimal(0),
            fiber=Decimal(0),
            sugar=Decimal(0),
            sodium=Decimal(0),
        )

        for ingredient in recipe.ingredients:
            ing_nutrition = self.analyze_ingredient(ingredient)
            if ing_nutrition:
                total_nutrition.calories += ing_nutrition.calories
                total_nutrition.protein += ing_nutrition.protein
                total_nutrition.fat += ing_nutrition.fat
                total_nutrition.carbohydrates += ing_nutrition.carbohydrates
                total_nutrition.fiber += ing_nutrition.fiber
                total_nutrition.sugar += ing_nutrition.sugar
                total_nutrition.sodium += ing_nutrition.sodium

                for key, nutrient in ing_nutrition.micronutrients.items():
                    if key not in total_nutrition.micronutrients:
                        total_nutrition.micronutrients[key] = Nutrient(nutrient.name, Decimal(0), nutrient.unit)
                    total_nutrition.micronutrients[key].value += nutrient.value

        # Scale to per-serving
        per_serving = total_nutrition.scale(Decimal(1) / Decimal(recipe.servings))
        return per_serving

    def analyze_ingredient(self, ingredient: Ingredient) -> NutritionFacts | None:
        """Analyze nutrition content of an ingredient.

        Args:
            ingredient: Ingredient to analyze.

        Returns:
            Optional[NutritionFacts]: Scaled nutrition facts, or None if no data.
        """
        if ingredient.nutrition_per_100g:
            nutrition = ingredient.nutrition_per_100g
        else:
            db_key = ingredient.name.lower().replace(" ", "_")
            if db_key not in self.ingredient_database:
                return None
            nutrition = self.ingredient_database[db_key]

        # Approximate weight conversion for common units
        unit_weights = {
            "g": Decimal("1"),
            "oz": Decimal("28.35"),
            "cup": Decimal("240"),
            "tbsp": Decimal("15"),
            "tsp": Decimal("5"),
            "ml": Decimal("1"),
        }

        weight_g = ingredient.quantity * unit_weights.get(ingredient.unit, Decimal("1"))
        factor = weight_g / Decimal("100")

        return nutrition.scale(factor)

    def calculate_daily_values(self, nutrition: NutritionFacts) -> dict[str, Decimal]:
        """Calculate daily value percentages for nutrients.

        Args:
            nutrition: Nutrition facts.

        Returns:
            Dict[str, Decimal]: Nutrient name to daily value percentage.
        """
        daily_values = {}

        # Macronutrients
        if nutrition.sodium > 0:
            daily_values["sodium"] = (nutrition.sodium / self.DAILY_VALUES["sodium_mg"]) * 100

        # Micronutrients
        for key, nutrient in nutrition.micronutrients.items():
            if key in self.DAILY_VALUES:
                dv = (nutrient.value / self.DAILY_VALUES[key]) * 100
                daily_values[nutrient.name] = dv

        return daily_values

    def estimate_bmr(
        self,
        weight_kg: Decimal,
        height_cm: Decimal,
        age_years: int,
        is_male: bool,
    ) -> Decimal:
        """Calculate Basal Metabolic Rate using Mifflin-St Jeor equation.

        Args:
            weight_kg: Body weight in kilograms.
            height_cm: Height in centimeters.
            age_years: Age in years.
            is_male: True if male, False if female.

        Returns:
            Decimal: BMR in calories per day.
        """
        if is_male:
            bmr = Decimal("10") * weight_kg + Decimal("6.25") * height_cm - Decimal("5") * age_years + Decimal("5")
        else:
            bmr = Decimal("10") * weight_kg + Decimal("6.25") * height_cm - Decimal("5") * age_years - Decimal("161")

        return bmr.quantize(Decimal("0.01"))

    def estimate_tdee(
        self,
        bmr: Decimal,
        activity_level: ActivityLevel,
    ) -> Decimal:
        """Calculate Total Daily Energy Expenditure.

        Args:
            bmr: Basal Metabolic Rate.
            activity_level: ActivityLevel enum value.

        Returns:
            Decimal: TDEE in calories per day.
        """
        tdee = bmr * activity_level.value
        return tdee.quantize(Decimal("0.01"))

    def analyze_macro_ratios(self, nutrition: NutritionFacts) -> dict[str, Decimal]:
        """Analyze macronutrient ratios and compare to profiles.

        Args:
            nutrition: Nutrition facts.

        Returns:
            Dict[str, Decimal]: Macro percentages (protein, fat, carbs).
        """
        ratios = nutrition.macro_ratios()
        return ratios

    def match_macro_profile(self, ratios: dict[str, Decimal], tolerance: Decimal = Decimal("5")) -> str | None:
        """Match macro ratios to a macro profile.

        Args:
            ratios: Macronutrient ratios as percentages.
            tolerance: Tolerance in percentage points.

        Returns:
            Optional[str]: Matching profile name, or None.
        """
        for profile in MacroProfile:
            profile_ratios = profile.value
            if all(abs(ratios[key] - profile_ratios[key]) <= tolerance for key in ["protein", "fat", "carbs"]):
                return profile.name

        return None

    def calculate_calories_for_macros(
        self,
        protein_g: Decimal,
        fat_g: Decimal,
        carbs_g: Decimal,
    ) -> Decimal:
        """Calculate total calories from macronutrients.

        Args:
            protein_g: Protein in grams.
            fat_g: Fat in grams.
            carbs_g: Carbohydrates in grams.

        Returns:
            Decimal: Total calories.
        """
        calories = (protein_g * Decimal("4")) + (fat_g * Decimal("9")) + (carbs_g * Decimal("4"))
        return calories.quantize(Decimal("0.01"))

    def get_macro_targets(
        self,
        tdee: Decimal,
        profile: MacroProfile,
    ) -> dict[str, Decimal]:
        """Calculate daily macro targets in grams based on TDEE and profile.

        Args:
            tdee: Total Daily Energy Expenditure.
            profile: MacroProfile enum value.

        Returns:
            Dict[str, Decimal]: Daily targets in grams for protein, fat, carbs.
        """
        targets = {}
        profile_ratios = profile.value

        # Protein: 4 cal/g, Fat: 9 cal/g, Carbs: 4 cal/g
        targets["protein"] = ((tdee * profile_ratios["protein"] / 100) / Decimal("4")).quantize(Decimal("0.1"))
        targets["fat"] = ((tdee * profile_ratios["fat"] / 100) / Decimal("9")).quantize(Decimal("0.1"))
        targets["carbs"] = ((tdee * profile_ratios["carbs"] / 100) / Decimal("4")).quantize(Decimal("0.1"))

        return targets
