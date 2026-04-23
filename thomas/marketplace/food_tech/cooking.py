"""
Cooking science module for food technology platform.

Handles cooking time estimation, temperature conversion, unit conversion,
cooking method optimization, food safety, and altitude adjustments.
"""

from decimal import Decimal
from enum import Enum

from thomas.marketplace.food_tech._types import CookingMethod


class FoodSafetyTemperature(Enum):
    """Safe internal temperatures for different protein types (Fahrenheit)."""

    POULTRY = Decimal("165")
    GROUND_MEAT = Decimal("160")
    BEEF_STEAK = Decimal("145")
    PORK = Decimal("145")
    FISH = Decimal("145")
    EGG_DISHES = Decimal("160")
    LEFTOVERS = Decimal("165")


class CookingScience:
    """Handles cooking calculations and transformations."""

    # Cooking time estimation formulas (minutes per 100g)
    COOKING_TIME_PER_100G = {
        CookingMethod.BAKING: Decimal("1.2"),
        CookingMethod.ROASTING: Decimal("0.8"),
        CookingMethod.GRILLING: Decimal("0.5"),
        CookingMethod.BOILING: Decimal("0.6"),
        CookingMethod.STEAMING: Decimal("0.7"),
        CookingMethod.FRYING: Decimal("0.4"),
        CookingMethod.SAUTEING: Decimal("0.3"),
        CookingMethod.BRAISING: Decimal("2.0"),
        CookingMethod.POACHING: Decimal("1.0"),
        CookingMethod.MICROWAVING: Decimal("0.2"),
    }

    # Energy efficiency ranking (lower is more efficient)
    ENERGY_EFFICIENCY = {
        CookingMethod.MICROWAVING: 1,
        CookingMethod.STEAMING: 2,
        CookingMethod.BOILING: 3,
        CookingMethod.POACHING: 4,
        CookingMethod.SAUTEING: 5,
        CookingMethod.FRYING: 6,
        CookingMethod.ROASTING: 7,
        CookingMethod.BAKING: 8,
        CookingMethod.BRAISING: 9,
        CookingMethod.GRILLING: 10,
    }

    @staticmethod
    def celsius_to_fahrenheit(celsius: Decimal) -> Decimal:
        """Convert temperature from Celsius to Fahrenheit.

        Args:
            celsius: Temperature in Celsius.

        Returns:
            Decimal: Temperature in Fahrenheit.
        """
        return ((celsius * Decimal("9")) / Decimal("5")) + Decimal("32")

    @staticmethod
    def fahrenheit_to_celsius(fahrenheit: Decimal) -> Decimal:
        """Convert temperature from Fahrenheit to Celsius.

        Args:
            fahrenheit: Temperature in Fahrenheit.

        Returns:
            Decimal: Temperature in Celsius.
        """
        return ((fahrenheit - Decimal("32")) * Decimal("5")) / Decimal("9")

    @staticmethod
    def convert_volume(value: Decimal, from_unit: str, to_unit: str) -> Decimal:
        """Convert between volume units.

        Args:
            value: Value to convert.
            from_unit: Source unit (cup, ml, tbsp, tsp).
            to_unit: Target unit.

        Returns:
            Decimal: Converted value.

        Raises:
            ValueError: If units invalid.
        """
        # Convert to milliliters first
        to_ml = {
            "ml": Decimal("1"),
            "cup": Decimal("236.588"),
            "tbsp": Decimal("14.787"),
            "tsp": Decimal("4.929"),
            "oz": Decimal("29.574"),
            "liter": Decimal("1000"),
        }

        if from_unit not in to_ml or to_unit not in to_ml:
            raise ValueError(f"Invalid unit: {from_unit} or {to_unit}")

        ml_value = value * to_ml[from_unit]
        return (ml_value / to_ml[to_unit]).quantize(Decimal("0.01"))

    @staticmethod
    def convert_weight(value: Decimal, from_unit: str, to_unit: str) -> Decimal:
        """Convert between weight units.

        Args:
            value: Value to convert.
            from_unit: Source unit (g, oz, lb, kg).
            to_unit: Target unit.

        Returns:
            Decimal: Converted value.

        Raises:
            ValueError: If units invalid.
        """
        # Convert to grams first
        to_g = {
            "g": Decimal("1"),
            "kg": Decimal("1000"),
            "oz": Decimal("28.35"),
            "lb": Decimal("453.592"),
            "mg": Decimal("0.001"),
        }

        if from_unit not in to_g or to_unit not in to_g:
            raise ValueError(f"Invalid unit: {from_unit} or {to_unit}")

        g_value = value * to_g[from_unit]
        return (g_value / to_g[to_unit]).quantize(Decimal("0.01"))

    @staticmethod
    def estimate_cooking_time(
        weight_g: Decimal,
        cooking_method: CookingMethod,
        thickness_cm: Decimal | None = None,
    ) -> int:
        """Estimate cooking time based on weight and method.

        Args:
            weight_g: Weight in grams.
            cooking_method: Cooking method.
            thickness_cm: Optional thickness for more accurate estimate.

        Returns:
            int: Estimated cooking time in minutes.
        """
        base_time = (weight_g / Decimal("100")) * CookingScience.COOKING_TIME_PER_100G[cooking_method]

        # Adjust for thickness
        if thickness_cm and thickness_cm > Decimal("2"):
            base_time *= thickness_cm / Decimal("2")

        return int(base_time.quantize(Decimal("1"), rounding="ROUND_UP"))

    @staticmethod
    def get_safe_internal_temperature(
        protein_type: str,
    ) -> tuple[Decimal, str]:
        """Get safe internal temperature for a protein.

        Args:
            protein_type: Type of protein (chicken, beef, fish, etc.).

        Returns:
            Tuple[Decimal, str]: (temperature_F, description).
        """
        protein_lower = protein_type.lower()

        if any(p in protein_lower for p in ["chicken", "poultry", "turkey"]):
            return FoodSafetyTemperature.POULTRY.value, "Poultry"
        elif any(p in protein_lower for p in ["ground", "minced"]):
            return FoodSafetyTemperature.GROUND_MEAT.value, "Ground meat"
        elif any(p in protein_lower for p in ["beef", "steak"]):
            return FoodSafetyTemperature.BEEF_STEAK.value, "Beef steak"
        elif any(p in protein_lower for p in ["pork", "ham"]):
            return FoodSafetyTemperature.PORK.value, "Pork"
        elif any(p in protein_lower for p in ["fish", "salmon", "cod"]):
            return FoodSafetyTemperature.FISH.value, "Fish"
        else:
            return FoodSafetyTemperature.BEEF_STEAK.value, "General"

    @staticmethod
    def get_energy_efficiency_ranking(cooking_method: CookingMethod) -> int:
        """Get energy efficiency ranking for a cooking method.

        Args:
            cooking_method: Cooking method.

        Returns:
            int: Efficiency rank (1 = most efficient).
        """
        return CookingScience.ENERGY_EFFICIENCY.get(cooking_method, 10)

    @staticmethod
    def adjust_for_altitude(
        base_temperature_f: Decimal,
        altitude_feet: Decimal,
        is_baking: bool = True,
    ) -> dict[str, Decimal]:
        """Adjust cooking parameters for altitude.

        Args:
            base_temperature_f: Base oven temperature in Fahrenheit.
            altitude_feet: Altitude in feet.
            is_baking: True if baking, False if boiling.

        Returns:
            Dict[str, Decimal]: Adjustments (temperature, time_increase_percent, liquid_increase_percent).
        """
        if is_baking:
            # Baking adjustments for altitude
            temp_increase = (altitude_feet / Decimal("1000")) * Decimal("25")
            time_increase = (altitude_feet / Decimal("1000")) * Decimal("10")
            liquid_increase = (altitude_feet / Decimal("1000")) * Decimal("2")

            return {
                "temperature_f": base_temperature_f + temp_increase,
                "time_increase_percent": time_increase,
                "liquid_increase_percent": liquid_increase,
            }
        else:
            # Boiling adjustments
            boiling_point_f = Decimal("212") - (altitude_feet / Decimal("500"))
            time_increase = (altitude_feet / Decimal("1000")) * Decimal("5")

            return {
                "boiling_point_f": boiling_point_f,
                "time_increase_percent": time_increase,
            }

    @staticmethod
    def calculate_yeast_rise_time(
        temperature_f: Decimal,
        base_minutes: int = 60,
    ) -> int:
        """Calculate yeast rise time based on temperature.

        Args:
            temperature_f: Ambient temperature in Fahrenheit.
            base_minutes: Base rise time at 70°F.

        Returns:
            int: Estimated rise time in minutes.
        """
        # Yeast rises roughly twice as fast for each 18°F increase
        deviation = temperature_f - Decimal("70")
        time_factor = Decimal("2") ** (deviation / Decimal("18"))
        adjusted_time = base_minutes / time_factor

        return int(adjusted_time.quantize(Decimal("1"), rounding="ROUND_UP"))

    @staticmethod
    def scale_baker_percentage(
        original_flour_g: Decimal,
        ingredient_percentage: Decimal,
    ) -> Decimal:
        """Calculate ingredient weight using baker's percentages.

        Args:
            original_flour_g: Weight of flour in grams.
            ingredient_percentage: Ingredient as percentage of flour.

        Returns:
            Decimal: Ingredient weight in grams.
        """
        return (original_flour_g * ingredient_percentage) / Decimal("100")

    @staticmethod
    def calculate_water_absorption(
        flour_g: Decimal,
        flour_type: str = "all_purpose",
    ) -> Decimal:
        """Calculate water absorption for dough based on flour type.

        Args:
            flour_g: Weight of flour in grams.
            flour_type: Type of flour (all_purpose, bread, whole_wheat, etc.).

        Returns:
            Decimal: Recommended water weight in grams.
        """
        # Standard hydration percentages by flour type
        hydration = {
            "all_purpose": Decimal("60"),
            "bread": Decimal("65"),
            "whole_wheat": Decimal("70"),
            "cake": Decimal("40"),
            "pastry": Decimal("55"),
        }

        pct = hydration.get(flour_type.lower(), Decimal("60"))
        return (flour_g * pct) / Decimal("100")

    @staticmethod
    def get_cooking_method_recommendations(
        protein_type: str,
        preferred_energy_efficiency: bool = False,
    ) -> list:
        """Get recommended cooking methods for a protein.

        Args:
            protein_type: Type of protein.
            preferred_energy_efficiency: If True, rank by efficiency.

        Returns:
            list: Recommended cooking methods.
        """
        recommendations = {
            "chicken": [
                CookingMethod.ROASTING,
                CookingMethod.GRILLING,
                CookingMethod.BAKING,
                CookingMethod.BOILING,
            ],
            "beef": [
                CookingMethod.GRILLING,
                CookingMethod.ROASTING,
                CookingMethod.BRAISING,
            ],
            "fish": [
                CookingMethod.BAKING,
                CookingMethod.GRILLING,
                CookingMethod.POACHING,
                CookingMethod.STEAMING,
            ],
            "pork": [
                CookingMethod.ROASTING,
                CookingMethod.GRILLING,
                CookingMethod.BRAISING,
            ],
            "vegetables": [
                CookingMethod.ROASTING,
                CookingMethod.STEAMING,
                CookingMethod.SAUTEING,
                CookingMethod.GRILLING,
            ],
        }

        methods = recommendations.get(protein_type.lower(), [CookingMethod.ROASTING])

        if preferred_energy_efficiency:
            methods.sort(key=lambda m: CookingScience.ENERGY_EFFICIENCY.get(m, 10))

        return methods
