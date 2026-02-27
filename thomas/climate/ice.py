"""Cryosphere (ice) analysis and modeling.

This module provides analysis of ice sheets, glaciers, sea ice, albedo
feedback, permafrost, snow cover, and paleoclimate ice core data.
"""

import math

from thomas.climate._exceptions import ClimateDataError, InvalidParameterError


def ice_sheet_mass_balance(accumulation_gt_year: float, ablation_gt_year: float) -> float:
    """Calculate ice sheet mass balance (accumulation - ablation).

    Positive values indicate net accumulation; negative indicate net loss.

    Args:
        accumulation_gt_year: Accumulation rate in Gt/year.
        ablation_gt_year: Ablation rate in Gt/year.

    Returns:
        Mass balance in Gt/year.
    """
    return accumulation_gt_year - ablation_gt_year


def ice_sheet_volume_to_sea_level(volume_km3: float, ice_type: str = "greenland") -> float:
    """Convert ice sheet volume to sea level rise equivalent.

    Args:
        volume_km3: Ice volume in km³.
        ice_type: "greenland" or "antarctica".

    Returns:
        Sea level rise equivalent in meters.

    Raises:
        InvalidParameterError: If ice type is invalid.
    """
    if ice_type not in ("greenland", "antarctica"):
        raise InvalidParameterError("ice_type must be 'greenland' or 'antarctica'", "ice_type", ice_type)

    # Sea level rise equivalents
    equivalents = {"greenland": 0.007, "antarctica": 0.026}  # m per km³

    return volume_km3 * equivalents[ice_type]


def glacier_flow_model_shallow_ice(
    ice_thickness_m: float, surface_slope_deg: float, temperature_c: float = -5.0
) -> float:
    """Model glacier flow velocity using shallow ice approximation.

    Velocity: u ≈ A × (ρg sin α)ⁿ × H^(n+1)
    where A is flow parameter, n=3 for Glen's flow law.

    Args:
        ice_thickness_m: Ice thickness in meters.
        surface_slope_deg: Surface slope in degrees.
        temperature_c: Ice temperature in Celsius.

    Returns:
        Mean flow velocity in m/year.

    Raises:
        InvalidParameterError: If parameters are invalid.
    """
    if ice_thickness_m <= 0:
        raise InvalidParameterError("Ice thickness must be positive", "ice_thickness_m", ice_thickness_m)

    if surface_slope_deg < 0 or surface_slope_deg > 90:
        raise InvalidParameterError("Slope must be 0-90 degrees", "surface_slope_deg", surface_slope_deg)

    # Flow rate parameter (temperature-dependent)
    a0 = 2.4e-24  # Pa^-3 s^-1 at -10°C
    a = a0 * math.exp(0.1 * temperature_c)  # Increases with temperature

    # Physical constants
    rho = 917.0  # kg/m³ ice density
    g = 9.81  # m/s²
    n = 3.0  # Glen's flow law exponent

    # Slope angle in radians
    alpha_rad = math.radians(surface_slope_deg)

    # Shear stress
    stress = rho * g * ice_thickness_m * math.sin(alpha_rad)

    # Velocity calculation (convert to m/year)
    velocity_m_s = a * (stress**n) * (ice_thickness_m ** (n + 1))
    velocity_m_year = velocity_m_s * 31536000.0  # Convert to m/year

    return velocity_m_year


def sea_ice_extent_classification(ice_area_km2: float, reference_climatology_km2: float) -> tuple[str, float]:
    """Classify sea ice extent relative to climatology.

    Args:
        ice_area_km2: Current sea ice extent in km².
        reference_climatology_km2: 30-year climatological normal in km².

    Returns:
        Tuple of (classification, anomaly_percent).
    """
    anomaly_percent = ((ice_area_km2 - reference_climatology_km2) / reference_climatology_km2) * 100

    if anomaly_percent < -30:
        classification = "extremely_low"
    elif anomaly_percent < -15:
        classification = "very_low"
    elif anomaly_percent < -5:
        classification = "below_normal"
    elif anomaly_percent < 5:
        classification = "normal"
    elif anomaly_percent < 15:
        classification = "above_normal"
    elif anomaly_percent < 30:
        classification = "very_high"
    else:
        classification = "extremely_high"

    return classification, anomaly_percent


def albedo_feedback_calculation(surface_type: str, temperature_change_k: float) -> float:
    """Calculate albedo feedback from surface change.

    Args:
        surface_type: "ice", "snow", or "water".
        temperature_change_k: Temperature change in Kelvin.

    Returns:
        Albedo feedback in W/m²/K.
    """
    # Albedos for different surfaces
    albedos = {
        "ice": {"baseline": 0.6, "sensitivity": 0.02},
        "snow": {"baseline": 0.8, "sensitivity": 0.025},
        "water": {"baseline": 0.06, "sensitivity": 0.001},
    }

    if surface_type not in albedos:
        surface_type = "ice"

    params = albedos[surface_type]

    # Albedo change with temperature
    albedo_change = params["sensitivity"] * temperature_change_k

    # Solar constant (average insolation)
    solar_constant = 340.0  # W/m²

    # Feedback: Change in reflected energy
    feedback = solar_constant * albedo_change

    return feedback


def permafrost_temperature_profile(
    surface_temperature_c: float,
    depth_m: list[float],
    thermal_conductivity_w_m_k: float = 1.5,
    thermal_diffusivity_m2_s: float = 5e-7,
) -> list[float]:
    """Calculate permafrost temperature profile using 1D heat diffusion.

    Args:
        surface_temperature_c: Surface temperature in Celsius.
        depth_m: List of depths in meters to calculate.
        thermal_conductivity_w_m_k: Thermal conductivity of soil.
        thermal_diffusivity_m2_s: Thermal diffusivity.

    Returns:
        List of temperatures in Celsius at specified depths.
    """
    temperatures = []

    # Characteristic depth scale (geothermal gradient effect)
    depth_scale = 50.0  # meters

    for z in depth_m:
        # Exponential decay of temperature anomaly with depth
        # Assumes steady-state geothermal gradient
        temp = surface_temperature_c * math.exp(-z / depth_scale)

        # Add geothermal gradient (approximately 0.025°C/m)
        temp += 0.025 * z

        temperatures.append(temp)

    return temperatures


def active_layer_thickness(thaw_degree_days: float, soil_type: str = "mineral") -> float:
    """Estimate active layer thickness from thaw degree days.

    Active layer is annual thawing layer above permafrost.

    Args:
        thaw_degree_days: Cumulative positive degree days (°C·days).
        soil_type: "organic", "mineral", or "bedrock".

    Returns:
        Active layer thickness in meters.
    """
    # Empirical relationships
    coefficients = {
        "organic": 0.008,  # m per degree day
        "mineral": 0.012,
        "bedrock": 0.005,
    }

    coeff = coefficients.get(soil_type, 0.012)
    thickness = coeff * thaw_degree_days

    return min(thickness, 5.0)  # Cap at 5 meters


def snow_cover_duration(daily_snow_depth_cm: list[float]) -> tuple[int, float]:
    """Calculate snow cover duration and mean depth during season.

    Args:
        daily_snow_depth_cm: List of daily snow depth in cm.

    Returns:
        Tuple of (duration_days, mean_depth_cm).

    Raises:
        ClimateDataError: If insufficient data.
    """
    if not daily_snow_depth_cm:
        raise ClimateDataError("Snow depth list is empty", daily_snow_depth_cm)

    # Count days with snow cover (>= 2 cm)
    snow_days = sum(1 for depth in daily_snow_depth_cm if depth >= 2.0)

    # Mean depth during snow-covered period
    snow_covered = [d for d in daily_snow_depth_cm if d >= 2.0]
    mean_depth = sum(snow_covered) / len(snow_covered) if snow_covered else 0.0

    return snow_days, mean_depth


def ice_core_temperature_reconstruction(
    delta_18o_values: list[float], depth_m: list[float], spatial_gradient_per_mil_per_km: float = 0.5
) -> list[float]:
    """Reconstruct past temperatures from ice core oxygen isotope ratios.

    Isotopic composition reflects temperature during snow deposition.

    Args:
        delta_18o_values: δ18O values in per mil (‰) relative to VSMOW.
        depth_m: Corresponding depths in meters.
        spatial_gradient_per_mil_per_km: Spatial gradient in ‰/km latitude.

    Returns:
        List of reconstructed temperatures in Celsius.

    Raises:
        ClimateDataError: If lengths don't match.
    """
    if len(delta_18o_values) != len(depth_m):
        raise ClimateDataError("δ18O and depth arrays must have same length", delta_18o_values)

    temperatures = []

    # Reference relationship (Dansgaard effect)
    # Temperature ≈ (δ18O - baseline) × slope
    baseline_delta_18o = -40.0  # ‰ at surface
    temp_slope = 0.67  # °C per ‰

    for delta_18o in delta_18o_values:
        # Calculate temperature anomaly
        anomaly = (delta_18o - baseline_delta_18o) * temp_slope

        # Reference temperature (Antarctica mean)
        reference_temp = -50.0  # °C

        # Reconstructed temperature
        temp = reference_temp + anomaly

        temperatures.append(temp)

    return temperatures


def glacier_extent_change(
    current_length_m: float, previous_length_m: float, years_elapsed: float
) -> tuple[float, float]:
    """Calculate glacier retreat rate from length change.

    Args:
        current_length_m: Current glacier length in meters.
        previous_length_m: Previous glacier length in meters.
        years_elapsed: Time between measurements in years.

    Returns:
        Tuple of (retreat_m, retreat_rate_m_year).
    """
    retreat_m = previous_length_m - current_length_m
    retreat_rate = retreat_m / years_elapsed if years_elapsed > 0 else 0

    return retreat_m, retreat_rate


def ice_albedo_feedback_index(
    ice_area_km2_current: float, ice_area_km2_baseline: float, albedo_ice: float = 0.6, albedo_water: float = 0.06
) -> float:
    """Calculate ice-albedo feedback strength.

    Args:
        ice_area_km2_current: Current ice coverage in km².
        ice_area_km2_baseline: Baseline ice coverage in km².
        albedo_ice: Albedo of ice surface.
        albedo_water: Albedo of underlying water.

    Returns:
        Feedback parameter (W/m²/K) - typically -0.15 to -0.25.
    """
    # Change in ice area
    area_change = ice_area_km2_current - ice_area_km2_baseline

    # Albedo change due to area loss
    albedo_change = (albedo_ice - albedo_water) * (area_change / max(ice_area_km2_baseline, 1.0))

    # Solar input (average insolation)
    solar = 340.0  # W/m²

    # Feedback parameter
    feedback = solar * albedo_change / 273.15  # Normalized per Kelvin

    return feedback


def melt_rate_degree_day_model(
    temperature_c: float, degree_day_factor_mm_c_day: float = 5.0, base_temperature_c: float = 0.0
) -> float:
    """Calculate ice/snow melt using degree-day model.

    Args:
        temperature_c: Air temperature in Celsius.
        degree_day_factor_mm_c_day: Melt per degree-day above base.
        base_temperature_c: Base temperature threshold.

    Returns:
        Daily melt in mm water equivalent.
    """
    if temperature_c > base_temperature_c:
        melt = (temperature_c - base_temperature_c) * degree_day_factor_mm_c_day
    else:
        melt = 0.0

    return melt
