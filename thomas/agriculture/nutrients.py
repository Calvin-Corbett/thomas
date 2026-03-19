"""Nutrient management module for fertilizer recommendations and balance."""

from thomas.agriculture._exceptions import NutrientError


class SoilTestInterpretation:
    """Interprets soil test results and determines nutrient sufficiency."""

    # Sufficiency ranges for crops (lbs/acre)
    SUFFICIENCY_RANGES = {
        "nitrogen": {
            "corn": (10, 25, 50),  # (low, medium, high)
            "soybean": (5, 10, 20),
            "wheat": (10, 20, 40),
        },
        "phosphorus": {
            "corn": (15, 25, 50),
            "soybean": (10, 20, 40),
            "wheat": (10, 15, 30),
        },
        "potassium": {
            "corn": (100, 150, 250),
            "soybean": (80, 120, 200),
            "wheat": (75, 100, 150),
        },
    }

    @staticmethod
    def interpret_nutrient_level(
        nutrient: str,
        crop: str,
        test_value: float,
    ) -> str:
        """Interpret nutrient sufficiency level.

        Args:
            nutrient: Nutrient name ("nitrogen", "phosphorus", "potassium")
            crop: Crop type ("corn", "soybean", "wheat")
            test_value: Test result value (lbs/acre)

        Returns:
            Sufficiency level ("Low", "Medium", "High")

        Raises:
            NutrientError: If nutrient or crop not recognized
        """
        if nutrient not in SoilTestInterpretation.SUFFICIENCY_RANGES:
            raise NutrientError(f"Unknown nutrient: {nutrient}")

        if crop not in SoilTestInterpretation.SUFFICIENCY_RANGES[nutrient]:
            raise NutrientError(f"Unknown crop: {crop}")

        low, medium, high = SoilTestInterpretation.SUFFICIENCY_RANGES[nutrient][crop]

        if test_value < low:
            return "Low"
        elif test_value < medium:
            return "Low-Medium"
        elif test_value < high:
            return "Medium-High"
        else:
            return "High"


class FertilizerRecommendation:
    """Generates fertilizer recommendations based on yield goals."""

    @staticmethod
    def recommend_nitrogen(
        yield_goal_bu_acre: float,
        soil_nitrate_n_ppm: float,
        previous_crop_n_credit_lbs: float = 0.0,
        organic_matter_pct: float = 2.5,
    ) -> float:
        """Recommend nitrogen application rate.

        Uses yield goal approach: Total N needed - soil supply - credits

        Args:
            yield_goal_bu_acre: Target crop yield
            soil_nitrate_n_ppm: Soil test nitrate-N
            previous_crop_n_credit_lbs: N credit from previous crop (e.g., legumes)
            organic_matter_pct: Soil organic matter percentage

        Returns:
            Recommended N application in lbs/acre
        """
        # Corn N requirement ~1 lb/bu
        crop_n_requirement = yield_goal_bu_acre * 1.0

        # Convert soil nitrate to lbs/acre (top 6 inches)
        # ~4 lbs/acre per ppm for surface 6 inches
        soil_n_supply = soil_nitrate_n_ppm * 4.0

        # Organic matter mineralization ~20 lbs N/acre per 1% OM
        om_n_mineralization = organic_matter_pct * 20.0

        # Total available N
        total_available = soil_n_supply + om_n_mineralization + previous_crop_n_credit_lbs

        # Recommendation with safety factor
        recommended_n = max(0.0, crop_n_requirement - total_available)
        return round(recommended_n, 0)

    @staticmethod
    def recommend_phosphorus(
        yield_goal_bu_acre: float,
        soil_phosphorus_lbs: float,
    ) -> float:
        """Recommend phosphorus application rate.

        Args:
            yield_goal_bu_acre: Target crop yield
            soil_phosphorus_lbs: Soil test phosphorus in lbs/acre

        Returns:
            Recommended P2O5 application in lbs/acre
        """
        # P requirement for corn ~0.4 lb P2O5/bu
        crop_p_requirement = yield_goal_bu_acre * 0.4

        # Sufficiency level for corn ~25 lbs/acre
        if soil_phosphorus_lbs >= 30:
            soil_contribution = crop_p_requirement * 0.5
        elif soil_phosphorus_lbs >= 20:
            soil_contribution = crop_p_requirement * 0.3
        else:
            soil_contribution = crop_p_requirement * 0.1

        recommended_p = max(0.0, crop_p_requirement - soil_contribution)
        return round(recommended_p, 0)

    @staticmethod
    def recommend_potassium(
        yield_goal_bu_acre: float,
        soil_potassium_lbs: float,
    ) -> float:
        """Recommend potassium application rate.

        Args:
            yield_goal_bu_acre: Target crop yield
            soil_potassium_lbs: Soil test potassium in lbs/acre

        Returns:
            Recommended K2O application in lbs/acre
        """
        # K requirement for corn ~0.35 lb K2O/bu
        crop_k_requirement = yield_goal_bu_acre * 0.35

        # Sufficiency level for corn ~150 lbs/acre
        if soil_potassium_lbs >= 200:
            soil_contribution = crop_k_requirement * 0.6
        elif soil_potassium_lbs >= 120:
            soil_contribution = crop_k_requirement * 0.4
        else:
            soil_contribution = crop_k_requirement * 0.2

        recommended_k = max(0.0, crop_k_requirement - soil_contribution)
        return round(recommended_k, 0)


class FertilizerBlendCalculator:
    """Calculates fertilizer blend to achieve target nutrient ratios."""

    @staticmethod
    def calculate_blend(
        target_n_lbs: float,
        target_p_lbs: float,
        target_k_lbs: float,
    ) -> dict[str, float]:
        """Calculate fertilizer blend to meet targets.

        Uses common fertilizer products: 46-0-0 (urea), 0-46-0 (TSP), 0-0-60 (MOP).

        Args:
            target_n_lbs: Target nitrogen (lbs/acre)
            target_p_lbs: Target phosphorus P2O5 (lbs/acre)
            target_k_lbs: Target potassium K2O (lbs/acre)

        Returns:
            Dictionary of product names and application rates
        """
        blend = {}

        # Use urea (46-0-0) for nitrogen
        urea_rate = 0.0
        if target_n_lbs > 0:
            urea_rate = target_n_lbs / 0.46
            blend["Urea (46-0-0)"] = round(urea_rate, 1)

        # Use Triple Super Phosphate (0-46-0) for phosphorus
        tsp_rate = 0.0
        if target_p_lbs > 0:
            tsp_rate = target_p_lbs / 0.46
            blend["TSP (0-46-0)"] = round(tsp_rate, 1)

        # Use Muriate of Potash (0-0-60) for potassium
        mop_rate = 0.0
        if target_k_lbs > 0:
            mop_rate = target_k_lbs / 0.60
            blend["MOP (0-0-60)"] = round(mop_rate, 1)

        # Total application rate
        total_rate = urea_rate + tsp_rate + mop_rate
        blend["Total Application Rate (lbs/acre)"] = round(total_rate, 1)

        return blend


class VariableRatePrescription:
    """Generates variable rate application maps based on field variability."""

    @staticmethod
    def create_zones(
        yield_history: list[float],
        soil_test_values: list[float],
        num_zones: int = 3,
    ) -> list[tuple[str, float, float]]:
        """Create management zones based on yield and soil variability.

        Simple approach: divide field into high/medium/low productivity zones.

        Args:
            yield_history: Historical yield values by location
            soil_test_values: Soil test values by location
            num_zones: Number of zones to create

        Returns:
            List of (zone_name, lower_bound, upper_bound) tuples
        """
        if not yield_history or not soil_test_values:
            return [("Uniform", 0.0, 1.0)]

        # Weighted average of normalized yield and soil
        combined = [
            0.6 * (y / max(yield_history)) + 0.4 * (s / max(soil_test_values))
            for y, s in zip(yield_history, soil_test_values)
        ]

        combined_sorted = sorted(combined)
        zone_size = len(combined_sorted) // num_zones

        zones = []
        for i in range(num_zones):
            start_idx = i * zone_size
            end_idx = start_idx + zone_size if i < num_zones - 1 else len(combined_sorted)

            if start_idx < len(combined_sorted):
                lower = combined_sorted[start_idx]
                upper = combined_sorted[end_idx - 1] if end_idx <= len(combined_sorted) else 1.0
                zone_name = ["Low", "Medium", "High"][i] if num_zones == 3 else f"Zone {i+1}"
                zones.append((zone_name, lower, upper))

        return zones

    @staticmethod
    def generate_vr_map(
        zones: list[tuple[str, float, float]],
        base_nitrogen_lbs: float,
    ) -> dict[str, float]:
        """Generate variable rate N application by zone.

        Args:
            zones: List of (zone_name, lower_bound, upper_bound) tuples
            base_nitrogen_lbs: Base N rate for medium zone

        Returns:
            Dictionary of zone names to N application rates
        """
        vr_map = {}

        for zone_name, _, _ in zones:
            if zone_name == "Low":
                # Reduce N application in low productivity areas
                vr_map[zone_name] = round(base_nitrogen_lbs * 0.7, 0)
            elif zone_name == "Medium":
                vr_map[zone_name] = round(base_nitrogen_lbs, 0)
            elif zone_name == "High":
                # Increase N in high productivity areas
                vr_map[zone_name] = round(base_nitrogen_lbs * 1.3, 0)
            else:
                vr_map[zone_name] = round(base_nitrogen_lbs, 0)

        return vr_map


class NutrientBudget:
    """Tracks nutrient inputs, outputs, and balance."""

    @staticmethod
    def calculate_annual_budget(
        nitrogen_applied_lbs: float,
        nitrogen_harvested_lbs: float,
        nitrogen_leached_lbs: float = 0.0,
        nitrogen_gaseous_loss_lbs: float = 0.0,
    ) -> float:
        """Calculate annual nitrogen budget.

        Budget = Inputs - Outputs

        Args:
            nitrogen_applied_lbs: N applied via fertilizer
            nitrogen_harvested_lbs: N removed in harvested crop
            nitrogen_leached_lbs: N lost to leaching
            nitrogen_gaseous_loss_lbs: N lost via volatilization, denitrification

        Returns:
            Net nitrogen balance (lbs/acre)
        """
        total_input = nitrogen_applied_lbs
        total_output = nitrogen_harvested_lbs + nitrogen_leached_lbs + nitrogen_gaseous_loss_lbs
        return total_input - total_output


class ManureCrediting:
    """Calculates nutrient credits from manure applications."""

    # Nutrient content by animal type (lbs/ton of fresh manure)
    MANURE_COMPOSITION = {
        "cattle": {"nitrogen": 10, "phosphorus": 2, "potassium": 8},
        "swine": {"nitrogen": 12, "phosphorus": 3, "potassium": 6},
        "poultry": {"nitrogen": 18, "phosphorus": 5, "potassium": 8},
        "horse": {"nitrogen": 12, "phosphorus": 2, "potassium": 10},
    }

    @staticmethod
    def get_nutrient_content(
        animal_type: str,
        manure_tons_acre: float,
    ) -> dict[str, float]:
        """Get nutrient content of applied manure.

        Args:
            animal_type: Type of animal (cattle, swine, poultry, horse)
            manure_tons_acre: Amount of manure applied

        Returns:
            Dictionary of nutrient: lbs/acre
        """
        if animal_type not in ManureCrediting.MANURE_COMPOSITION:
            raise NutrientError(f"Unknown animal type: {animal_type}")

        composition = ManureCrediting.MANURE_COMPOSITION[animal_type]
        return {nutrient: amount * manure_tons_acre for nutrient, amount in composition.items()}

    @staticmethod
    def calculate_available_nitrogen(
        manure_nitrogen_total_lbs: float,
        first_year_availability: float = 0.3,
    ) -> float:
        """Calculate plant-available nitrogen from manure.

        Only fraction of manure N is available first year; rest mineralizes over time.

        Args:
            manure_nitrogen_total_lbs: Total N in applied manure
            first_year_availability: Fraction available first year (typically 0.2-0.4)

        Returns:
            Available nitrogen in lbs/acre for current year
        """
        return manure_nitrogen_total_lbs * first_year_availability
