"""Livestock management module for animal production and herd tracking."""

from datetime import date, timedelta

from thomas.marketplace.agriculture._exceptions import LivestockError
from thomas.marketplace.agriculture._types import LivestockAnimal, LivestockType


class HerdTracking:
    """Tracks individual livestock animals and herd records."""

    def __init__(self) -> None:
        """Initialize herd tracking system."""
        self.animals: dict[str, LivestockAnimal] = {}

    def add_animal(self, animal: LivestockAnimal) -> None:
        """Add animal to herd.

        Args:
            animal: LivestockAnimal object
        """
        if animal.animal_id in self.animals:
            raise LivestockError(f"Animal ID already exists: {animal.animal_id}")
        self.animals[animal.animal_id] = animal

    def get_animal(self, animal_id: str) -> LivestockAnimal | None:
        """Get animal by ID.

        Args:
            animal_id: Animal identifier

        Returns:
            LivestockAnimal or None
        """
        return self.animals.get(animal_id)

    def get_herd(self, livestock_type: LivestockType) -> list[LivestockAnimal]:
        """Get all animals of a specific type.

        Args:
            livestock_type: LivestockType to filter

        Returns:
            List of animals
        """
        return [a for a in self.animals.values() if a.livestock_type == livestock_type]

    def calculate_herd_size(self, livestock_type: LivestockType | None = None) -> int:
        """Count animals in herd.

        Args:
            livestock_type: Filter by type, or None for total

        Returns:
            Number of animals
        """
        if livestock_type is None:
            return len(self.animals)
        return len(self.get_herd(livestock_type))

    def get_lineage(self, animal_id: str) -> dict[str, any]:
        """Get animal's lineage information.

        Args:
            animal_id: Animal to trace

        Returns:
            Dictionary with dam and sire information
        """
        animal = self.get_animal(animal_id)
        if not animal:
            raise LivestockError(f"Animal not found: {animal_id}")

        lineage = {
            "animal_id": animal_id,
            "dam": self.get_animal(animal.dam_id) if animal.dam_id else None,
            "sire": self.get_animal(animal.sire_id) if animal.sire_id else None,
        }
        return lineage


class FeedRationBalancer:
    """Balances least-cost feed rations meeting nutritional requirements."""

    def __init__(self) -> None:
        """Initialize feed ration calculator."""
        # Feed ingredient nutritional content
        self.feed_ingredients = {
            "corn": {
                "price_per_ton": 120,
                "dry_matter_pct": 88,
                "crude_protein_pct": 8.5,
                "tdn_pct": 88,
                "calcium_pct": 0.02,
                "phosphorus_pct": 0.28,
            },
            "soybean_meal": {
                "price_per_ton": 400,
                "dry_matter_pct": 89,
                "crude_protein_pct": 48,
                "tdn_pct": 80,
                "calcium_pct": 0.30,
                "phosphorus_pct": 0.65,
            },
            "alfalfa_hay": {
                "price_per_ton": 150,
                "dry_matter_pct": 88,
                "crude_protein_pct": 16,
                "tdn_pct": 58,
                "calcium_pct": 1.20,
                "phosphorus_pct": 0.20,
            },
            "grass_hay": {
                "price_per_ton": 100,
                "dry_matter_pct": 88,
                "crude_protein_pct": 8,
                "tdn_pct": 51,
                "calcium_pct": 0.40,
                "phosphorus_pct": 0.15,
            },
        }

        # Nutritional requirements for dairy cow
        self.nutrient_requirements = {
            "dry_matter_intake_lbs": 50,
            "crude_protein_pct": 12,
            "tdn_pct": 65,
            "calcium_pct": 0.60,
            "phosphorus_pct": 0.40,
        }

    def calculate_ration(
        self,
        ingredient_mix: dict[str, float],
    ) -> dict[str, float]:
        """Calculate nutritional content of ration.

        Args:
            ingredient_mix: Dictionary of ingredient: percent_of_total

        Returns:
            Dictionary with ration nutritional values
        """
        total_pct = sum(ingredient_mix.values())
        if total_pct == 0:
            raise LivestockError("No ingredients in ration")

        # Normalize percentages
        normalized_mix = {ing: pct / total_pct for ing, pct in ingredient_mix.items()}

        ration = {
            "crude_protein_pct": 0,
            "tdn_pct": 0,
            "calcium_pct": 0,
            "phosphorus_pct": 0,
            "cost_per_ton": 0,
        }

        for ingredient, fraction in normalized_mix.items():
            if ingredient not in self.feed_ingredients:
                raise LivestockError(f"Unknown ingredient: {ingredient}")

            feed = self.feed_ingredients[ingredient]
            ration["crude_protein_pct"] += feed["crude_protein_pct"] * fraction
            ration["tdn_pct"] += feed["tdn_pct"] * fraction
            ration["calcium_pct"] += feed["calcium_pct"] * fraction
            ration["phosphorus_pct"] += feed["phosphorus_pct"] * fraction
            ration["cost_per_ton"] += feed["price_per_ton"] * fraction

        return {k: round(v, 2) for k, v in ration.items()}

    def check_nutrient_adequacy(
        self,
        ration: dict[str, float],
    ) -> dict[str, bool]:
        """Check if ration meets requirements.

        Args:
            ration: Calculated ration nutritional values

        Returns:
            Dictionary of nutrient: meets_requirement
        """
        return {
            "crude_protein": ration["crude_protein_pct"] >= self.nutrient_requirements["crude_protein_pct"],
            "tdn": ration["tdn_pct"] >= self.nutrient_requirements["tdn_pct"],
            "calcium": ration["calcium_pct"] >= self.nutrient_requirements["calcium_pct"],
            "phosphorus": ration["phosphorus_pct"] >= self.nutrient_requirements["phosphorus_pct"],
        }


class BodyConditionScore:
    """Evaluates body condition of livestock."""

    @staticmethod
    def assess_condition(
        body_condition_score: float,
    ) -> str:
        """Assess body condition from BCS value.

        Uses 1-9 scale: 1=emaciated, 5=ideal, 9=obese

        Args:
            body_condition_score: BCS value (1-9)

        Returns:
            Condition assessment
        """
        if body_condition_score < 2:
            return "Emaciated - Immediate nutritional intervention needed"
        elif body_condition_score < 3.5:
            return "Thin - Increase nutrient intake"
        elif body_condition_score < 4.5:
            return "Below Average - Monitor and adjust feeding"
        elif body_condition_score < 5.5:
            return "Ideal - Optimal condition"
        elif body_condition_score < 7:
            return "Above Average - Monitor feed intake"
        elif body_condition_score < 8.5:
            return "Fat - Consider reducing feed"
        else:
            return "Obese - Reduce feed intake significantly"

    @staticmethod
    def recommend_adjustment(
        current_bcs: float,
        target_bcs: float = 5.0,
    ) -> str | None:
        """Recommend feeding adjustment.

        Args:
            current_bcs: Current body condition score
            target_bcs: Target body condition score

        Returns:
            Feeding recommendation or None
        """
        difference = target_bcs - current_bcs

        if abs(difference) < 0.3:
            return None  # At target
        elif difference > 1.0:
            return "Significantly increase feed quantity and quality"
        elif difference > 0.3:
            return "Moderately increase nutrient density"
        elif difference < -1.0:
            return "Significantly reduce feed quantity"
        else:
            return "Moderately reduce feed quantity"


class BreedingCalendar:
    """Manages animal breeding schedules and reproductive events."""

    def __init__(self) -> None:
        """Initialize breeding calendar."""
        # Gestation periods in days
        self.gestation_periods = {
            LivestockType.CATTLE: 283,
            LivestockType.SWINE: 114,
            LivestockType.SHEEP: 147,
            LivestockType.GOAT: 150,
            LivestockType.HORSE: 340,
        }

    def calculate_due_date(
        self,
        breeding_date: date,
        livestock_type: LivestockType,
    ) -> date:
        """Calculate expected birth date from breeding date.

        Args:
            breeding_date: Date of breeding
            livestock_type: Type of animal

        Returns:
            Expected birth date
        """
        if livestock_type not in self.gestation_periods:
            raise LivestockError(f"Unknown livestock type: {livestock_type}")

        gestation_days = self.gestation_periods[livestock_type]
        return breeding_date + timedelta(days=gestation_days)

    def calculate_breeding_date(
        self,
        target_birth_date: date,
        livestock_type: LivestockType,
    ) -> date:
        """Calculate when to breed for target birth date.

        Args:
            target_birth_date: Desired birth date
            livestock_type: Type of animal

        Returns:
            Breeding date needed
        """
        if livestock_type not in self.gestation_periods:
            raise LivestockError(f"Unknown livestock type: {livestock_type}")

        gestation_days = self.gestation_periods[livestock_type]
        return target_birth_date - timedelta(days=gestation_days)


class ProductionTracking:
    """Tracks milk and egg production per animal."""

    def __init__(self) -> None:
        """Initialize production tracking."""
        self.production_records: dict[str, list[float]] = {}

    def record_milk_production(
        self,
        animal_id: str,
        milk_lbs_per_day: float,
    ) -> None:
        """Record daily milk production.

        Args:
            animal_id: Animal identifier
            milk_lbs_per_day: Milk produced in pounds
        """
        if animal_id not in self.production_records:
            self.production_records[animal_id] = []
        self.production_records[animal_id].append(milk_lbs_per_day)

    def record_egg_production(
        self,
        animal_id: str,
        eggs_per_day: float,
    ) -> None:
        """Record daily egg production.

        Args:
            animal_id: Animal identifier
            eggs_per_day: Eggs produced per day
        """
        if animal_id not in self.production_records:
            self.production_records[animal_id] = []
        self.production_records[animal_id].append(eggs_per_day)

    def calculate_average_production(
        self,
        animal_id: str,
    ) -> float:
        """Calculate average production per day.

        Args:
            animal_id: Animal identifier

        Returns:
            Average daily production
        """
        records = self.production_records.get(animal_id, [])
        if not records:
            return 0.0
        return sum(records) / len(records)

    def calculate_lactation_total(
        self,
        animal_id: str,
        days_in_lactation: int = 305,
    ) -> float:
        """Project lactation production total.

        Dairy cattle: 305-day lactation cycle

        Args:
            animal_id: Animal identifier
            days_in_lactation: Lactation cycle length

        Returns:
            Projected total production
        """
        avg_daily = self.calculate_average_production(animal_id)
        return avg_daily * days_in_lactation


class StockingRate:
    """Calculates appropriate stocking rates for pasture."""

    @staticmethod
    def calculate_animal_units(
        number_of_animals: int,
        avg_weight_lbs: float,
    ) -> float:
        """Convert animals to Animal Units (AU).

        1 AU = 1,000 lbs of animal (typically 1 cow).

        Args:
            number_of_animals: Number of animals
            avg_weight_lbs: Average weight per animal

        Returns:
            Animal Units equivalent
        """
        total_weight = number_of_animals * avg_weight_lbs
        au = total_weight / 1000.0
        return au

    @staticmethod
    def calculate_max_stocking_rate(
        forage_production_tons_acre: float,
        forage_utilization_pct: float = 50.0,
        annual_forage_requirement_lbs_au: float = 6000.0,
    ) -> float:
        """Calculate maximum stocking rate based on forage.

        Args:
            forage_production_tons_acre: Annual forage production
            forage_utilization_pct: Percentage forage that can be grazed
            annual_forage_requirement_lbs_au: Forage needed per AU per year

        Returns:
            Maximum AU per acre
        """
        if annual_forage_requirement_lbs_au <= 0:
            raise LivestockError("Forage requirement must be positive")

        available_forage_lbs = forage_production_tons_acre * 2000 * (forage_utilization_pct / 100.0)

        max_au_per_acre = available_forage_lbs / annual_forage_requirement_lbs_au
        return round(max_au_per_acre, 2)


class AnimalHealthRecords:
    """Manages animal health and medical records."""

    def __init__(self) -> None:
        """Initialize health records system."""
        self.health_records: dict[str, list[dict[str, any]]] = {}

    def record_treatment(
        self,
        animal_id: str,
        treatment_date: date,
        treatment_type: str,
        medication: str,
        withdrawal_days: int = 0,
    ) -> None:
        """Record medical treatment.

        Args:
            animal_id: Animal identifier
            treatment_date: Date of treatment
            treatment_type: Type of treatment (vaccination, antibiotic, etc.)
            medication: Medication used
            withdrawal_days: Milk/meat withdrawal period
        """
        if animal_id not in self.health_records:
            self.health_records[animal_id] = []

        record = {
            "date": treatment_date,
            "type": treatment_type,
            "medication": medication,
            "withdrawal_days": withdrawal_days,
            "withdrawal_until": treatment_date + timedelta(days=withdrawal_days),
        }
        self.health_records[animal_id].append(record)

    def can_sell_product(
        self,
        animal_id: str,
        current_date: date,
    ) -> bool:
        """Check if animal can be sold for milk/meat production.

        Checks withdrawal periods from medications.

        Args:
            animal_id: Animal identifier
            current_date: Current date

        Returns:
            True if withdrawal period has expired
        """
        records = self.health_records.get(animal_id, [])
        if not records:
            return True

        for record in records:
            if record["withdrawal_until"] > current_date:
                return False

        return True


class WeightGainPrediction:
    """Predicts weight gain based on nutrition and genetics."""

    @staticmethod
    def predict_daily_gain(
        current_weight_lbs: float,
        target_weight_lbs: float,
        days_to_target: int,
        feed_conversion_ratio: float = 5.0,
    ) -> dict[str, float]:
        """Predict daily weight gain.

        Args:
            current_weight_lbs: Current animal weight
            target_weight_lbs: Target weight
            days_to_target: Days to reach target
            feed_conversion_ratio: Feed required per lb gain

        Returns:
            Dictionary with gain predictions
        """
        if days_to_target <= 0:
            raise LivestockError("Days to target must be positive")

        weight_gain_needed = target_weight_lbs - current_weight_lbs
        daily_gain = weight_gain_needed / days_to_target
        daily_feed_needed = daily_gain * feed_conversion_ratio

        return {
            "daily_gain_lbs": round(daily_gain, 2),
            "daily_feed_required_lbs": round(daily_feed_needed, 1),
            "total_feed_required_lbs": round(daily_feed_needed * days_to_target, 1),
        }
