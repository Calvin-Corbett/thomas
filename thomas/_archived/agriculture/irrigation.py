"""Irrigation management module for water scheduling and efficiency."""

from thomas.agriculture._exceptions import IrrigationError
from thomas.agriculture._types import IrrigationType


class CropWaterRequirement:
    """Calculates crop water requirements using reference evapotranspiration."""

    def __init__(self) -> None:
        """Initialize crop water requirement calculator."""
        # Crop coefficient (Kc) by growth stage (normalized to 0-1 period)
        self.kc_stages = {
            "Initial": 0.3,  # 0-10% of season
            "Development": 0.6,  # 10-40% of season
            "Mid-Season": 0.95,  # 40-85% of season
            "Late-Season": 0.7,  # 85-100% of season
        }

    def get_crop_coefficient(
        self,
        gdd_accumulated: float,
        gdd_required: float,
    ) -> float:
        """Get crop coefficient (Kc) for current growth stage.

        Args:
            gdd_accumulated: Growing degree days accumulated
            gdd_required: Total GDD required for season

        Returns:
            Crop coefficient (Kc) value
        """
        if gdd_required <= 0:
            return 0.3

        season_progress = gdd_accumulated / gdd_required

        if season_progress < 0.1:
            return self.kc_stages["Initial"]
        elif season_progress < 0.4:
            # Interpolate between Initial and Development
            alpha = (season_progress - 0.1) / 0.3
            return self.kc_stages["Initial"] * (1 - alpha) + self.kc_stages["Development"] * alpha
        elif season_progress < 0.85:
            # Interpolate between Development and Mid-Season
            alpha = (season_progress - 0.4) / 0.45
            return self.kc_stages["Development"] * (1 - alpha) + self.kc_stages["Mid-Season"] * alpha
        else:
            # Interpolate between Mid-Season and Late-Season
            alpha = (season_progress - 0.85) / 0.15
            return self.kc_stages["Mid-Season"] * (1 - alpha) + self.kc_stages["Late-Season"] * alpha

    def calculate_daily_et(
        self,
        reference_et_in: float,
        gdd_accumulated: float,
        gdd_required: float,
    ) -> float:
        """Calculate actual evapotranspiration (ET).

        ET = ET0 × Kc (Allen et al., 1998 FAO-56)

        Args:
            reference_et_in: Reference evapotranspiration (ET0) in inches
            gdd_accumulated: Growing degree days accumulated
            gdd_required: Total GDD required for season

        Returns:
            Actual evapotranspiration in inches
        """
        kc = self.get_crop_coefficient(gdd_accumulated, gdd_required)
        return reference_et_in * kc


class SoilMoistureBalance:
    """Tracks soil moisture balance for irrigation scheduling."""

    def __init__(self) -> None:
        """Initialize soil moisture balance tracker."""
        pass

    def calculate_daily_balance(
        self,
        previous_moisture_in: float,
        precipitation_in: float,
        irrigation_in: float,
        et_in: float,
        percolation_in: float = 0.0,
    ) -> float:
        """Calculate daily soil moisture balance.

        Moisture = Previous + Precipitation + Irrigation - ET - Percolation

        Args:
            previous_moisture_in: Previous available moisture in inches
            precipitation_in: Daily rainfall in inches
            irrigation_in: Daily irrigation in inches
            et_in: Daily evapotranspiration in inches
            percolation_in: Deep percolation loss in inches

        Returns:
            Updated available moisture in inches
        """
        moisture = previous_moisture_in + precipitation_in + irrigation_in - et_in - percolation_in
        return max(0.0, moisture)


class IrrigationScheduler:
    """Schedules irrigation based on soil moisture and management thresholds."""

    def __init__(
        self,
        available_water_capacity_in: float,
        management_allowable_depletion: float = 0.5,
    ) -> None:
        """Initialize irrigation scheduler.

        Args:
            available_water_capacity_in: Total available water in root zone
            management_allowable_depletion: Fraction of AWC before irrigation (0-1)
        """
        self.awc = available_water_capacity_in
        self.mad = management_allowable_depletion

    def calculate_depletion_threshold(self) -> float:
        """Calculate soil moisture depletion trigger point.

        Returns:
            Soil moisture level (inches) at which irrigation should start
        """
        return self.awc * self.mad

    def is_irrigation_needed(
        self,
        current_moisture_in: float,
    ) -> bool:
        """Check if irrigation is needed.

        Args:
            current_moisture_in: Current available soil moisture in inches

        Returns:
            True if irrigation needed
        """
        threshold = self.calculate_depletion_threshold()
        return current_moisture_in <= threshold

    def calculate_irrigation_amount(
        self,
        current_moisture_in: float,
        target_moisture_in: float | None = None,
    ) -> float:
        """Calculate irrigation amount to refill soil profile.

        Args:
            current_moisture_in: Current available moisture in inches
            target_moisture_in: Target moisture level (default full capacity)

        Returns:
            Irrigation needed in inches
        """
        if target_moisture_in is None:
            target_moisture_in = self.awc

        return max(0.0, target_moisture_in - current_moisture_in)


class IrrigationEfficiency:
    """Calculates irrigation system efficiency and water use."""

    # Typical application efficiencies by system
    EFFICIENCY_RATES = {
        IrrigationType.FLOOD: 0.60,
        IrrigationType.FURROW: 0.65,
        IrrigationType.SPRINKLER: 0.75,
        IrrigationType.CENTER_PIVOT: 0.85,
        IrrigationType.DRIP: 0.95,
        IrrigationType.MICRO: 0.90,
    }

    @staticmethod
    def get_efficiency(irrigation_type: IrrigationType) -> float:
        """Get application efficiency for irrigation type.

        Args:
            irrigation_type: IrrigationType

        Returns:
            Application efficiency (0-1)
        """
        return IrrigationEfficiency.EFFICIENCY_RATES.get(
            irrigation_type,
            0.75,
        )

    @staticmethod
    def calculate_water_requirement(
        needed_depth_in: float,
        irrigation_type: IrrigationType,
    ) -> float:
        """Calculate total water to apply accounting for inefficiency.

        Args:
            needed_depth_in: Water needed by crop in inches
            irrigation_type: IrrigationType

        Returns:
            Water to apply at source in inches
        """
        efficiency = IrrigationEfficiency.get_efficiency(irrigation_type)
        if efficiency <= 0:
            raise IrrigationError("Efficiency must be positive")
        return needed_depth_in / efficiency


class FerrtigationCalculator:
    """Calculates fertilizer amounts for fertigation (fertilizer through irrigation)."""

    def calculate_nutrient_concentration(
        self,
        nutrient_amount_lbs_acre: float,
        irrigation_depth_in: float,
    ) -> float:
        """Calculate nutrient concentration in irrigation water.

        Args:
            nutrient_amount_lbs_acre: Nutrient to apply in lbs/acre
            irrigation_depth_in: Irrigation application in inches

        Returns:
            Concentration in ppm (mg/L)
        """
        # 1 inch water = 27,154 gallons/acre
        # 1 ppm = 2.7 lbs/acre for 1 inch irrigation
        gallons_acre = irrigation_depth_in * 27154
        if gallons_acre <= 0:
            return 0.0

        ppm = (nutrient_amount_lbs_acre / gallons_acre) * 1e6
        return ppm

    def calculate_application_rate(
        self,
        desired_ppm: float,
        irrigation_rate_gpm: float,
        duration_hours: float,
    ) -> float:
        """Calculate fertilizer injection rate for desired concentration.

        Args:
            desired_ppm: Target concentration in ppm
            irrigation_rate_gpm: Irrigation system flow rate
            duration_hours: Application duration

        Returns:
            Fertilizer injection rate in gph (gallons per hour)
        """
        total_gallons = irrigation_rate_gpm * duration_hours
        if total_gallons <= 0:
            return 0.0

        # ppm to lbs: ppm × gallons × 0.00001337
        total_lbs_needed = desired_ppm * total_gallons * 0.00001337

        # Assume fertilizer solution is specific gravity ~1.2, density ~10 lbs/gal
        injection_gph = total_lbs_needed / 10.0 / duration_hours
        return injection_gph


class PumpSizing:
    """Calculates pump requirements for irrigation systems."""

    @staticmethod
    def calculate_required_flow(
        total_area_acres: float,
        irrigation_depth_in: float,
        application_hours: float,
    ) -> float:
        """Calculate required pump flow rate.

        Args:
            total_area_acres: Area to irrigate in acres
            irrigation_depth_in: Application depth in inches
            application_hours: Hours available for application

        Returns:
            Required flow rate in GPM
        """
        if application_hours <= 0:
            raise IrrigationError("Application hours must be positive")

        # Gallons = acres × depth_in × 27,154 gal/acre/inch
        total_gallons = total_area_acres * irrigation_depth_in * 27154
        gpm = total_gallons / (application_hours * 60)
        return gpm

    @staticmethod
    def calculate_pressure_head_ft(
        elevation_change_ft: float,
        friction_loss_psi: float = 10.0,
        operating_pressure_psi: float = 50.0,
    ) -> float:
        """Calculate total dynamic head for pump sizing.

        Args:
            elevation_change_ft: Elevation difference from source to field
            friction_loss_psi: Pressure loss in pipes
            operating_pressure_psi: System operating pressure

        Returns:
            Total dynamic head in feet
        """
        # Convert psi to feet (1 psi = 2.31 ft)
        friction_ft = friction_loss_psi * 2.31
        pressure_ft = operating_pressure_psi * 2.31

        total_head = elevation_change_ft + friction_ft + pressure_ft
        return total_head


class DeficitIrrigationStrategy:
    """Manages deficit irrigation to maximize water use efficiency."""

    @staticmethod
    def calculate_deficit_strategy(
        full_requirement_in: float,
        available_water_in: float,
        yield_reduction_tolerance: float = 0.10,
    ) -> float:
        """Calculate deficit irrigation water allocation.

        Reduces water application to non-critical growth stages to save water
        while limiting yield loss to acceptable level.

        Args:
            full_requirement_in: Full irrigation requirement
            available_water_in: Available water for irrigation
            yield_reduction_tolerance: Acceptable yield loss (0-1)

        Returns:
            Recommended irrigation amount in inches
        """
        if available_water_in >= full_requirement_in:
            return full_requirement_in

        # Can achieve 90% yield with ~70% of water in mid-to-late season deficit
        deficit_factor = 0.7 + (0.3 * (1 - yield_reduction_tolerance))
        recommended_water = full_requirement_in * deficit_factor

        return min(available_water_in, recommended_water)
