"""Crop management module for planting, growth tracking, and rotation."""

from datetime import date, timedelta

from thomas.marketplace.agriculture._exceptions import CropError
from thomas.marketplace.agriculture._types import (
    Crop,
    CropFamily,
    CropVariety,
    GrowthStage,
    Weather,
)


class CropDatabase:
    """Database of common crop varieties with growing requirements."""

    def __init__(self) -> None:
        """Initialize crop database with common varieties."""
        self._varieties: dict[str, CropVariety] = self._load_varieties()

    def _load_varieties(self) -> dict[str, CropVariety]:
        """Load standard crop varieties.

        Returns:
            Dictionary mapping variety_id to CropVariety
        """
        varieties = {
            "corn_p1197am": CropVariety(
                variety_id="corn_p1197am",
                name="Pioneer P1197AM",
                crop_type="Corn",
                family=CropFamily.POACEAE,
                days_to_maturity=113,
                gdd_required=2700,
                temp_min=50.0,
                temp_opt=75.0,
                temp_max=95.0,
                water_requirement_in=20.0,
                nitrogen_lbs_per_acre=150,
                phosphorus_lbs_per_acre=45,
                potassium_lbs_per_acre=40,
            ),
            "soybean_ag4632": CropVariety(
                variety_id="soybean_ag4632",
                name="Asgrow AG4632",
                crop_type="Soybean",
                family=CropFamily.FABACEAE,
                days_to_maturity=119,
                gdd_required=2600,
                temp_min=50.0,
                temp_opt=70.0,
                temp_max=90.0,
                water_requirement_in=18.0,
                nitrogen_lbs_per_acre=0,  # Nitrogen-fixing
                phosphorus_lbs_per_acre=30,
                potassium_lbs_per_acre=35,
            ),
            "wheat_delivery": CropVariety(
                variety_id="wheat_delivery",
                name="Delivery Wheat",
                crop_type="Wheat",
                family=CropFamily.POACEAE,
                days_to_maturity=160,
                gdd_required=2100,
                temp_min=40.0,
                temp_opt=65.0,
                temp_max=85.0,
                water_requirement_in=15.0,
                nitrogen_lbs_per_acre=100,
                phosphorus_lbs_per_acre=35,
                potassium_lbs_per_acre=30,
            ),
        }
        return varieties

    def get_variety(self, variety_id: str) -> CropVariety:
        """Get a crop variety by ID.

        Args:
            variety_id: Unique variety identifier

        Returns:
            CropVariety object

        Raises:
            CropError: If variety not found
        """
        if variety_id not in self._varieties:
            raise CropError(f"Crop variety not found: {variety_id}")
        return self._varieties[variety_id]

    def list_varieties(self) -> list[CropVariety]:
        """List all available varieties.

        Returns:
            List of CropVariety objects
        """
        return list(self._varieties.values())


class PlantingCalendar:
    """Manages planting dates based on frost data."""

    def __init__(
        self,
        avg_last_frost_date: date,
        avg_first_frost_date: date,
    ) -> None:
        """Initialize planting calendar.

        Args:
            avg_last_frost_date: Average last spring frost date
            avg_first_frost_date: Average first fall frost date
        """
        self.avg_last_frost_date = avg_last_frost_date
        self.avg_first_frost_date = avg_first_frost_date

    def recommend_planting_date(
        self,
        variety: CropVariety,
        year: int,
    ) -> date:
        """Recommend planting date for a crop variety.

        For warm-season crops, recommends planting 1-2 weeks after last frost.
        For cool-season crops, adjusts based on growing season requirements.

        Args:
            variety: CropVariety object
            year: Calendar year for planting

        Returns:
            Recommended planting date
        """
        # Adjust last frost date to the requested year
        last_frost = self.avg_last_frost_date.replace(year=year)

        # For warm-season crops (corn, soybeans)
        if variety.crop_type in ["Corn", "Soybean"]:
            return last_frost + timedelta(days=7)

        # For cool-season crops (wheat)
        if variety.crop_type == "Wheat":
            # Fall planting before first frost
            first_frost = self.avg_first_frost_date.replace(year=year)
            days_needed = variety.days_to_maturity
            return first_frost - timedelta(days=days_needed)

        return last_frost + timedelta(days=7)

    def estimate_harvest_date(
        self,
        planting_date: date,
        variety: CropVariety,
    ) -> date:
        """Estimate harvest date from planting date.

        Args:
            planting_date: Date crop was planted
            variety: CropVariety object

        Returns:
            Estimated harvest date
        """
        return planting_date + timedelta(days=variety.days_to_maturity)


class GrowthTracker:
    """Tracks crop growth using Growing Degree Days (GDD)."""

    def __init__(self, base_temp_f: float = 50.0) -> None:
        """Initialize growth tracker.

        Args:
            base_temp_f: Base temperature for GDD calculation (default 50°F for corn)
        """
        self.base_temp_f = base_temp_f

    def calculate_gdd(
        self,
        temp_max_f: float,
        temp_min_f: float,
    ) -> float:
        """Calculate Growing Degree Days for one day.

        Standard method: GDD = ((Tmax + Tmin) / 2) - Tbase
        Never negative, capped at max temperature.

        Args:
            temp_max_f: Daily maximum temperature (°F)
            temp_min_f: Daily minimum temperature (°F)

        Returns:
            GDD accumulation for the day
        """
        avg_temp = (temp_max_f + temp_min_f) / 2.0
        gdd = max(0, avg_temp - self.base_temp_f)
        return gdd

    def update_crop_growth(
        self,
        crop: Crop,
        weather_readings: list[Weather],
    ) -> Crop:
        """Update crop GDD and growth stage from weather data.

        Args:
            crop: Crop to update
            weather_readings: List of Weather objects in chronological order

        Returns:
            Updated Crop object
        """
        for weather in weather_readings:
            if weather.date > date.today():
                continue
            gdd = self.calculate_gdd(weather.temp_max_f, weather.temp_min_f)
            crop.gdd_accumulated += gdd

        # Determine growth stage based on GDD
        crop.growth_stage = self._determine_growth_stage(
            crop.gdd_accumulated,
            crop.variety.gdd_required,
        )
        return crop

    def _determine_growth_stage(
        self,
        gdd_accumulated: float,
        gdd_required: float,
    ) -> GrowthStage:
        """Determine growth stage from GDD accumulation.

        Args:
            gdd_accumulated: Total GDD accumulated
            gdd_required: Total GDD required for maturity

        Returns:
            Current GrowthStage
        """
        percent_mature = gdd_accumulated / gdd_required if gdd_required > 0 else 0

        if percent_mature < 0.05:
            return GrowthStage.GERMINATION
        elif percent_mature < 0.60:
            return GrowthStage.VEGETATIVE
        elif percent_mature < 0.80:
            return GrowthStage.FLOWERING
        elif percent_mature < 0.95:
            return GrowthStage.GRAIN_FILL
        else:
            return GrowthStage.MATURITY


class CropRotationPlanner:
    """Plans crop rotations to avoid disease and optimize fertility."""

    def __init__(self) -> None:
        """Initialize crop rotation planner."""
        pass

    def can_plant(
        self,
        desired_crop_family: CropFamily,
        previous_crops: list[tuple[CropFamily, int]],
        years_since_family: int = 2,
    ) -> bool:
        """Check if crop can be planted based on rotation rules.

        Standard rule: Same family not planted in consecutive years, ideally
        3+ years between plantings to break pest/disease cycles.

        Args:
            desired_crop_family: Family of crop to plant
            previous_crops: List of (CropFamily, years_ago) tuples
            years_since_family: Minimum years required between same family

        Returns:
            True if crop can be planted
        """
        for family, years_ago in previous_crops:
            if family == desired_crop_family and years_ago < years_since_family:
                return False
        return True

    def get_nitrogen_benefit(
        self,
        previous_crop_family: CropFamily,
    ) -> float:
        """Get nitrogen credit from previous crop.

        Legumes (Fabaceae) fix atmospheric nitrogen and provide credits
        to following crops.

        Args:
            previous_crop_family: Family of previous crop

        Returns:
            Pounds of nitrogen credit per acre
        """
        if previous_crop_family == CropFamily.FABACEAE:
            return 50.0  # Legumes provide ~50 lbs N/acre credit
        return 0.0

    def recommend_rotation_sequence(
        self,
        years: int = 4,
    ) -> list[str]:
        """Recommend a multi-year rotation sequence.

        Args:
            years: Number of years to plan

        Returns:
            List of recommended crops
        """
        sequence = ["Corn", "Soybean", "Corn", "Wheat"]
        return sequence[:years]


class CompanionPlanting:
    """Database of crop companion planting relationships."""

    def __init__(self) -> None:
        """Initialize companion planting matrix."""
        self._beneficial: dict[str, list[str]] = {
            "Corn": ["Beans", "Peas", "Squash"],
            "Beans": ["Corn", "Squash", "Cucumber"],
            "Squash": ["Corn", "Beans", "Melon"],
        }
        self._harmful: dict[str, list[str]] = {
            "Corn": ["Brassicas"],
            "Beans": ["Onions", "Garlic"],
            "Cucumber": ["Aromatic herbs"],
        }

    def get_beneficial(self, crop: str) -> list[str]:
        """Get beneficial companion crops.

        Args:
            crop: Crop name

        Returns:
            List of beneficial companion crops
        """
        return self._beneficial.get(crop, [])

    def get_harmful(self, crop: str) -> list[str]:
        """Get harmful companion crops to avoid.

        Args:
            crop: Crop name

        Returns:
            List of crops to avoid planting nearby
        """
        return self._harmful.get(crop, [])

    def are_compatible(self, crop1: str, crop2: str) -> bool:
        """Check if two crops can be planted together.

        Args:
            crop1: First crop
            crop2: Second crop

        Returns:
            True if compatible
        """
        harmful1 = self.get_harmful(crop1)
        harmful2 = self.get_harmful(crop2)

        return crop2 not in harmful1 and crop1 not in harmful2


class YieldEstimator:
    """Estimates crop yield from multiple factors."""

    def estimate_yield(
        self,
        gdd_accumulated: float,
        gdd_required: float,
        water_availability_in: float,
        water_requirement_in: float,
        nitrogen_available_lbs: float,
        nitrogen_requirement_lbs: float,
        baseline_yield_bu_acre: float = 150.0,
    ) -> float:
        """Estimate yield from GDD, water, and nitrogen factors.

        Uses multiplicative model: Yield = Baseline × GDD_factor × Water_factor × N_factor

        Args:
            gdd_accumulated: Total GDD accumulated
            gdd_required: Total GDD required for maturity
            water_availability_in: Water received (rain + irrigation)
            water_requirement_in: Water requirement for season
            nitrogen_available_lbs: Nitrogen available in soil
            nitrogen_requirement_lbs: Nitrogen needed
            baseline_yield_bu_acre: Baseline yield potential

        Returns:
            Estimated yield in bu/acre
        """
        # GDD factor: incomplete season = reduced yield
        gdd_factor = min(gdd_accumulated / gdd_required, 1.0)

        # Water factor: water balance affects yield
        water_factor = min(water_availability_in / water_requirement_in, 1.0)
        water_factor = max(water_factor, 0.5)  # Never drop below 50%

        # Nitrogen factor: deficiency reduces yield quadratically
        n_factor = min(nitrogen_available_lbs / nitrogen_requirement_lbs, 1.0)
        n_factor = max(n_factor, 0.4)  # Never drop below 40%

        estimated_yield = baseline_yield_bu_acre * gdd_factor * water_factor * n_factor
        return round(estimated_yield, 1)
