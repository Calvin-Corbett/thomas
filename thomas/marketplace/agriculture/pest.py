"""Pest management module for integrated pest management (IPM) and control."""

from thomas.marketplace.agriculture._exceptions import PestError
from thomas.marketplace.agriculture._types import PestType


class IPMDecisionFramework:
    """Integrated Pest Management decision support system."""

    def __init__(self) -> None:
        """Initialize IPM framework."""
        self.steps = [
            "Scout",
            "Identify",
            "Count",
            "Threshold",
            "Action",
        ]

    def scout_field(
        self,
        field_id: str,
        sample_size_plants: int,
        pest_count: int,
    ) -> dict[str, int]:
        """Record field scouting data.

        Args:
            field_id: Field being scouted
            sample_size_plants: Number of plants sampled
            pest_count: Number of pests found

        Returns:
            Dictionary with scouting results
        """
        if sample_size_plants <= 0:
            raise PestError("Sample size must be positive")

        pest_per_plant = pest_count / sample_size_plants
        return {
            "field_id": field_id,
            "sample_size": sample_size_plants,
            "pest_count": pest_count,
            "pest_per_plant": round(pest_per_plant, 2),
        }

    def identify_pest(
        self,
        pest_name: str,
        symptoms: list[str],
    ) -> dict[str, any]:
        """Identify pest from symptoms.

        Args:
            pest_name: Name of suspected pest
            symptoms: List of observed symptoms

        Returns:
            Dictionary with identification results
        """
        return {
            "pest_name": pest_name,
            "symptoms": symptoms,
            "confidence": 0.85,  # Simplified confidence score
        }

    def evaluate_threshold(
        self,
        pest_per_plant: float,
        economic_threshold_per_plant: float,
    ) -> bool:
        """Check if pest population exceeds economic threshold.

        Args:
            pest_per_plant: Current pest population per plant
            economic_threshold_per_plant: Treatment threshold

        Returns:
            True if treatment recommended
        """
        return pest_per_plant >= economic_threshold_per_plant

    def recommend_action(
        self,
        pest_type: PestType,
        pest_population: float,
        threshold: float,
    ) -> str | None:
        """Recommend IPM action based on pest level.

        Args:
            pest_type: Type of pest
            pest_population: Current population level
            threshold: Economic threshold

        Returns:
            Recommended action or None
        """
        if pest_population < threshold:
            return "Monitor"
        elif pest_population < threshold * 1.5:
            return "Prepare equipment, scout more frequently"
        else:
            return "Treat immediately"


class EconomicThresholdCalculator:
    """Calculates economic thresholds for pest treatment decisions."""

    @staticmethod
    def calculate_threshold(
        treatment_cost_per_acre: float,
        yield_goal_bu_acre: float,
        grain_price_per_bu: float,
        damage_pct_per_pest_unit: float,
    ) -> float:
        """Calculate economic threshold for treatment.

        Treatment is justified when: Pest damage cost > Treatment cost

        Args:
            treatment_cost_per_acre: Cost to spray ($/acre)
            yield_goal_bu_acre: Expected yield
            grain_price_per_bu: Market price per bushel
            damage_pct_per_pest_unit: Yield loss per pest unit (0-1)

        Returns:
            Economic threshold (pests per plant)
        """
        if grain_price_per_bu <= 0:
            raise PestError("Grain price must be positive")

        # Total yield value at risk
        yield_value = yield_goal_bu_acre * grain_price_per_bu

        # Pests needed to cause damage worth treating
        # Assumes plant spacing: typical corn ~32,000 plants/acre
        plants_per_acre = 32000

        threshold = (treatment_cost_per_acre / yield_value) / damage_pct_per_pest_unit / plants_per_acre
        return max(0.01, threshold)


class PestPredictionModel:
    """Predicts pest emergence and development using temperature models."""

    def __init__(self, base_temperature_f: float = 50.0) -> None:
        """Initialize pest prediction model.

        Args:
            base_temperature_f: Base temperature for degree-day accumulation
        """
        self.base_temp = base_temperature_f
        # Example: corn borer ~600 degree-days for first generation
        self.gdd_for_emergence = {
            "corn_borer": 600,
            "armyworm": 400,
            "cutworm": 300,
            "japanese_beetle": 700,
        }

    def calculate_pest_gdd(
        self,
        temp_max_f: float,
        temp_min_f: float,
    ) -> float:
        """Calculate growing degree days for pest development.

        Args:
            temp_max_f: Daily maximum temperature
            temp_min_f: Daily minimum temperature

        Returns:
            Pest GDD accumulation
        """
        avg_temp = (temp_max_f + temp_min_f) / 2.0
        gdd = max(0, avg_temp - self.base_temp)
        return gdd

    def predict_emergence(
        self,
        pest_type: str,
        gdd_accumulated: float,
    ) -> dict[str, any]:
        """Predict pest emergence timing.

        Args:
            pest_type: Type of pest
            gdd_accumulated: Accumulated degree days

        Returns:
            Dictionary with emergence prediction
        """
        if pest_type not in self.gdd_for_emergence:
            raise PestError(f"Unknown pest type: {pest_type}")

        gdd_needed = self.gdd_for_emergence[pest_type]
        percent_development = (gdd_accumulated / gdd_needed) * 100

        if percent_development >= 100:
            status = "Peak emergence expected"
        elif percent_development >= 75:
            status = "Emergence imminent (1-2 weeks)"
        elif percent_development >= 50:
            status = "Emerging (2-4 weeks)"
        else:
            status = f"{100 - percent_development:.0f}% away from emergence"

        return {
            "pest_type": pest_type,
            "gdd_accumulated": round(gdd_accumulated, 1),
            "gdd_needed": gdd_needed,
            "percent_development": round(percent_development, 1),
            "status": status,
        }


class SprayTimingOptimization:
    """Optimizes spray timing for maximum pesticide efficacy."""

    @staticmethod
    def recommend_spray_time(
        pest_stage: str,
        weather_conditions: dict[str, float],
    ) -> dict[str, str]:
        """Recommend spray timing based on pest stage and weather.

        Args:
            pest_stage: Life stage of pest (egg, nymph, adult)
            weather_conditions: Dictionary with wind_mph, rain_expected, temp_f

        Returns:
            Dictionary with spray recommendations
        """
        recommendations = {}

        # Optimal conditions: low wind, no rain, moderate temps
        if weather_conditions.get("wind_mph", 0) > 15:
            recommendations["wind"] = "Too windy (>15 mph), wait"
        else:
            recommendations["wind"] = "Wind acceptable"

        if weather_conditions.get("rain_expected", False):
            recommendations["rain"] = "Rain expected, wait"
        else:
            recommendations["rain"] = "No rain expected, good"

        temp = weather_conditions.get("temp_f", 70)
        if 50 <= temp <= 85:
            recommendations["temperature"] = "Optimal temperature"
        elif temp < 50:
            recommendations["temperature"] = "Too cold, wait"
        else:
            recommendations["temperature"] = "Too hot, wait"

        # Pest stage recommendations
        if pest_stage == "nymph":
            recommendations["stage"] = "Best stage to spray"
        elif pest_stage == "adult":
            recommendations["stage"] = "Spray effective but more resistant"
        else:
            recommendations["stage"] = f"Spray for {pest_stage} timing"

        return recommendations


class ResistanceManagement:
    """Manages pesticide resistance through rotation strategies."""

    # Mode of action groups for rotation
    MODE_OF_ACTION = {
        "pyrethroids": ["permethrin", "cypermethrin", "lambda-cyhalothrin"],
        "neonicotinoids": ["imidacloprid", "clothianidin", "thiamethoxam"],
        "organophosphates": ["malathion", "parathion"],
        "carbamates": ["carbaryl"],
        "biological": ["bt"],
    }

    @staticmethod
    def get_mode_of_action(product_name: str) -> str | None:
        """Get mode of action for a pesticide product.

        Args:
            product_name: Pesticide product name

        Returns:
            Mode of action group or None
        """
        product_lower = product_name.lower()
        for moa, products in ResistanceManagement.MODE_OF_ACTION.items():
            if any(p in product_lower for p in products):
                return moa
        return None

    @staticmethod
    def check_rotation(
        previous_applications: list[str],
        current_product: str,
        years_back: int = 2,
    ) -> bool:
        """Check if current product represents good mode of action rotation.

        Args:
            previous_applications: List of previously used product names
            current_product: Product to apply now
            years_back: Years to check for rotation

        Returns:
            True if good rotation, False if same MOA used recently
        """
        current_moa = ResistanceManagement.get_mode_of_action(current_product)
        if not current_moa:
            return True  # Unknown product, assume OK

        # Check last applications
        for prev_product in previous_applications[:years_back]:
            prev_moa = ResistanceManagement.get_mode_of_action(prev_product)
            if prev_moa == current_moa:
                return False  # Same MOA recently used

        return True


class PestIdentification:
    """Database for pest identification from symptoms."""

    def __init__(self) -> None:
        """Initialize pest identification database."""
        self.pest_database = {
            "european_corn_borer": {
                "symptoms": ["holes_in_stalks", "sawdust_frass", "wilting"],
                "damage_type": "stem_borer",
                "threshold": 0.5,  # per plant
            },
            "corn_rootworm": {
                "symptoms": ["lodging", "stunting", "root_damage"],
                "damage_type": "root_feeder",
                "threshold": 0.8,
            },
            "fall_armyworm": {
                "symptoms": ["ragged_leaves", "dark_droppings", "stripped_plants"],
                "damage_type": "leaf_feeder",
                "threshold": 0.3,
            },
        }

    def identify_by_symptoms(
        self,
        symptoms: list[str],
    ) -> list[tuple[str, float]]:
        """Identify pest from observed symptoms.

        Args:
            symptoms: List of observed symptoms

        Returns:
            List of (pest_name, confidence_score) tuples
        """
        results = []

        for pest_name, info in self.pest_database.items():
            pest_symptoms = info["symptoms"]
            matches = sum(1 for s in symptoms if s in pest_symptoms)
            confidence = matches / len(pest_symptoms) if pest_symptoms else 0.0

            if confidence > 0:
                results.append((pest_name, confidence))

        # Sort by confidence
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def get_pest_info(self, pest_name: str) -> dict[str, any] | None:
        """Get pest information from database.

        Args:
            pest_name: Pest name

        Returns:
            Dictionary with pest info or None
        """
        return self.pest_database.get(pest_name.lower().replace(" ", "_"))
