"""Weather analysis and near-term forecasting tools.

This module provides synoptic analysis, wind scale classification, precipitation
type determination, visibility estimation, air quality assessment, UV index
calculation, and forecast verification metrics.
"""

import math

from thomas.marketplace.climate._exceptions import ClimateDataError, InvalidParameterError


def beaufort_wind_scale_description(beaufort_number: int) -> str:
    """Get Beaufort scale description for wind speed.

    Args:
        beaufort_number: Beaufort scale number (0-12).

    Returns:
        Description of wind conditions.

    Raises:
        InvalidParameterError: If number out of range.
    """
    descriptions = {
        0: "Calm",
        1: "Light Air",
        2: "Light Breeze",
        3: "Gentle Breeze",
        4: "Moderate Breeze",
        5: "Fresh Breeze",
        6: "Strong Breeze",
        7: "Near Gale",
        8: "Gale",
        9: "Severe Gale",
        10: "Storm",
        11: "Violent Storm",
        12: "Hurricane",
    }

    if beaufort_number < 0 or beaufort_number > 12:
        raise InvalidParameterError("Beaufort number must be 0-12", "beaufort_number", beaufort_number)

    return descriptions[beaufort_number]


def precipitation_type_determination(
    temperature_c: float, wet_bulb_temperature_c: float, surface_temperature_c: float
) -> str:
    """Determine precipitation type based on temperature profile.

    Args:
        temperature_c: Air temperature in Celsius.
        wet_bulb_temperature_c: Wet bulb temperature in Celsius.
        surface_temperature_c: Surface temperature in Celsius.

    Returns:
        Precipitation type: "rain", "freezing_rain", "snow", "sleet", or "mixed".
    """
    # Simple decision tree for precipitation type
    if surface_temperature_c > 2.0:
        if temperature_c > 5.0 or temperature_c > 2.0:
            return "rain"
        else:
            if wet_bulb_temperature_c > 0:
                return "freezing_rain"
            else:
                return "snow"
    else:
        if temperature_c > 0:
            return "freezing_rain"
        else:
            if wet_bulb_temperature_c > -2:
                return "sleet"
            else:
                return "snow"


def visibility_estimation(
    liquid_water_content_g_m3: float, particle_size_microns: float = 10.0, wavelength_um: float = 0.55
) -> float:
    """Estimate visibility from atmospheric particles using optical theory.

    Uses Mie scattering for particle size on order of visible wavelength.

    Args:
        liquid_water_content_g_m3: Liquid water content in g/m³.
        particle_size_microns: Characteristic particle diameter in microns.
        wavelength_um: Wavelength of light in micrometers.

    Returns:
        Visibility range in meters.

    Raises:
        InvalidParameterError: If parameters are invalid.
    """
    if liquid_water_content_g_m3 < 0:
        raise InvalidParameterError(
            "Liquid water content cannot be negative", "liquid_water_content_g_m3", liquid_water_content_g_m3
        )

    if liquid_water_content_g_m3 == 0:
        return float("inf")

    # Extinction coefficient (simplified Mie scattering)
    # Q_ext ≈ 2 for particles ~10 μm
    q_ext = 2.0

    # Particle number concentration from liquid water content
    # lwc = (4/3) × π × r³ × ρ_water × n
    radius_m = particle_size_microns * 1e-6 / 2.0
    lwc_kg_m3 = liquid_water_content_g_m3 / 1e6
    rho_water = 1000.0  # kg/m³

    particle_count = lwc_kg_m3 / ((4 / 3) * math.pi * radius_m**3 * rho_water)

    # Extinction coefficient
    cross_section = q_ext * math.pi * radius_m**2
    extinction = cross_section * particle_count

    # Visibility (contrast reduction to 5% threshold)
    visibility = 3.0 / extinction if extinction > 0 else float("inf")

    return min(visibility, 50000.0)  # Cap at 50 km


def air_quality_index_from_pollutants(
    pm25_ug_m3: float, pm10_ug_m3: float, o3_ppb: float, no2_ppb: float, so2_ppb: float, co_ppm: float
) -> tuple[int, str]:
    """Calculate Air Quality Index (AQI) from multiple pollutants.

    AQI scale: 0-50 (Good), 51-100 (Moderate), 101-150 (Unhealthy for sensitive),
    151-200 (Unhealthy), 201-300 (Very unhealthy), 301+ (Hazardous)

    Args:
        pm25_ug_m3: PM2.5 in μg/m³.
        pm10_ug_m3: PM10 in μg/m³.
        o3_ppb: Ozone in ppb.
        no2_ppb: Nitrogen dioxide in ppb.
        so2_ppb: Sulfur dioxide in ppb.
        co_ppm: Carbon monoxide in ppm.

    Returns:
        Tuple of (AQI value, category string).
    """

    # AQI breakpoints for each pollutant
    def sub_index(conc: float, breakpoints: list[tuple[float, float, float, float]]) -> float:
        """Calculate sub-index for a pollutant."""
        for lo_c, hi_c, lo_i, hi_i in breakpoints:
            if lo_c <= conc <= hi_c:
                return lo_i + ((conc - lo_c) / (hi_c - lo_c)) * (hi_i - lo_i)
        return 0.0

    # PM2.5 breakpoints (24-hour)
    pm25_breaks = [
        (0, 12, 0, 50),
        (12.1, 35.4, 51, 100),
        (35.5, 55.4, 101, 150),
        (55.5, 150.4, 151, 200),
        (150.5, 250.4, 201, 300),
        (250.5, 500, 301, 500),
    ]

    # O3 breakpoints (8-hour)
    o3_breaks = [
        (0, 55, 0, 50),
        (56, 70, 51, 100),
        (71, 85, 101, 150),
        (86, 105, 151, 200),
        (106, 200, 201, 300),
        (201, 600, 301, 500),
    ]

    # Calculate sub-indices
    aqi_pm25 = sub_index(pm25_ug_m3, pm25_breaks)
    aqi_o3 = sub_index(o3_ppb, o3_breaks)

    # Take maximum
    aqi = int(max(aqi_pm25, aqi_o3))

    # Categorize
    if aqi <= 50:
        category = "Good"
    elif aqi <= 100:
        category = "Moderate"
    elif aqi <= 150:
        category = "Unhealthy for Sensitive Groups"
    elif aqi <= 200:
        category = "Unhealthy"
    elif aqi <= 300:
        category = "Very Unhealthy"
    else:
        category = "Hazardous"

    return aqi, category


def uv_index_calculation(
    solar_zenith_angle_deg: float,
    total_ozone_dobson_units: float = 300.0,
    surface_albedo: float = 0.1,
    cloud_optical_depth: float = 0.0,
) -> tuple[float, str]:
    """Calculate UV Index from solar geometry and ozone.

    UV Index scale: 0-2 (Low), 3-5 (Moderate), 6-7 (High),
    8-10 (Very High), 11+ (Extreme)

    Args:
        solar_zenith_angle_deg: Solar zenith angle in degrees (90 = horizon).
        total_ozone_dobson_units: Total column ozone in Dobson units.
        surface_albedo: Surface reflectivity (0-1).
        cloud_optical_depth: Cloud optical depth.

    Returns:
        Tuple of (UV Index value, intensity category).

    Raises:
        InvalidParameterError: If parameters are invalid.
    """
    if solar_zenith_angle_deg < 0 or solar_zenith_angle_deg > 180:
        raise InvalidParameterError(
            "Solar zenith angle must be 0-180°", "solar_zenith_angle_deg", solar_zenith_angle_deg
        )

    if total_ozone_dobson_units <= 0:
        raise InvalidParameterError("Ozone must be positive", "total_ozone_dobson_units", total_ozone_dobson_units)

    # Clear sky UV Index at sea level
    # Reference: ~12 at solar noon with 300 DU ozone
    reference_uvi = 12.0
    reference_ozone = 300.0
    reference_zenith = 0.0

    # Adjust for solar zenith angle (air mass)
    zenith_rad = math.radians(solar_zenith_angle_deg)
    if zenith_rad < math.pi / 2:
        air_mass = 1.0 / math.cos(zenith_rad)
    else:
        return 0.0, "Night"

    # Adjust for ozone (Beer-Lambert law)
    ozone_factor = (reference_ozone / total_ozone_dobson_units) ** 1.0

    # Cloud attenuation (e^(-optical_depth))
    cloud_factor = math.exp(-cloud_optical_depth)

    # Surface albedo enhancement
    albedo_factor = 1.0 + 0.15 * surface_albedo

    # Calculate UV Index
    uvi = reference_uvi * (1.0 / air_mass) * ozone_factor * cloud_factor * albedo_factor

    uvi = max(0, uvi)

    # Categorize
    if uvi < 3:
        category = "Low"
    elif uvi < 6:
        category = "Moderate"
    elif uvi < 8:
        category = "High"
    elif uvi < 11:
        category = "Very High"
    else:
        category = "Extreme"

    return uvi, category


def forecast_brier_score(forecast_probabilities: list[float], observations: list[int]) -> float:
    """Calculate Brier Score for probabilistic forecast verification.

    Brier Score = mean((forecast - observation)²)
    Range: 0 (perfect) to 1 (worst).

    Args:
        forecast_probabilities: List of forecast probabilities (0-1).
        observations: List of observations (0 or 1).

    Returns:
        Brier Score value.

    Raises:
        ClimateDataError: If lengths don't match.
    """
    if len(forecast_probabilities) != len(observations):
        raise ClimateDataError("Forecast and observation arrays must match length")

    if not forecast_probabilities:
        return 0.0

    brier_score = sum((f - o) ** 2 for f, o in zip(forecast_probabilities, observations))
    brier_score /= len(forecast_probabilities)

    return brier_score


def forecast_hit_rate_and_false_alarm_rate(
    forecast_events: list[int], observed_events: list[int]
) -> tuple[float, float]:
    """Calculate hit rate and false alarm rate for deterministic forecasts.

    Args:
        forecast_events: List of forecasted events (0 or 1).
        observed_events: List of observed events (0 or 1).

    Returns:
        Tuple of (hit_rate, false_alarm_rate).

    Raises:
        ClimateDataError: If lengths don't match.
    """
    if len(forecast_events) != len(observed_events):
        raise ClimateDataError("Forecast and observation arrays must match length")

    if not forecast_events:
        return 0.0, 0.0

    # Contingency table
    hits = sum(1 for f, o in zip(forecast_events, observed_events) if f == 1 and o == 1)
    misses = sum(1 for f, o in zip(forecast_events, observed_events) if f == 0 and o == 1)
    false_alarms = sum(1 for f, o in zip(forecast_events, observed_events) if f == 1 and o == 0)
    correct_negatives = sum(1 for f, o in zip(forecast_events, observed_events) if f == 0 and o == 0)

    # Rates
    hit_rate = hits / (hits + misses) if (hits + misses) > 0 else 0.0
    false_alarm_rate = (
        false_alarms / (false_alarms + correct_negatives) if (false_alarms + correct_negatives) > 0 else 0.0
    )

    return hit_rate, false_alarm_rate


def pressure_tendency_forecast(pressure_hpa: list[float], hours: list[float]) -> float:
    """Calculate pressure tendency for short-term weather forecasting.

    Pressure tendency = dp/dt in hPa/hour

    Args:
        pressure_hpa: List of pressure observations in hPa.
        hours: List of times in hours.

    Returns:
        Pressure tendency in hPa/hour.

    Raises:
        ClimateDataError: If insufficient data.
    """
    if len(pressure_hpa) < 2 or len(hours) < 2:
        raise ClimateDataError("Need at least 2 observations", pressure_hpa)

    if len(pressure_hpa) != len(hours):
        raise ClimateDataError("Pressure and time arrays must match length")

    # Simple linear regression for trend
    from scipy import stats

    slope, _, _, _, _ = stats.linregress(hours, pressure_hpa)

    return slope


def lifted_index_stability(
    surface_temperature_c: float,
    surface_pressure_hpa: float,
    environmental_temperature_500mb_c: float,
    environmental_pressure_500mb_hpa: float = 500.0,
) -> float:
    """Calculate Lifted Index for atmospheric stability assessment.

    LI < -4: Severe thunderstorm potential
    LI -4 to 0: Moderate instability
    LI 0 to 4: Weakly unstable
    LI > 4: Stable

    Args:
        surface_temperature_c: Surface air temperature in Celsius.
        surface_pressure_hpa: Surface pressure in hPa.
        environmental_temperature_500mb_c: Environmental temp at 500 mb in Celsius.
        environmental_pressure_500mb_hpa: Pressure at upper level (typically 500).

    Returns:
        Lifted Index in Celsius (negative = unstable).
    """
    # Simplified lifted index calculation
    # Temperature change from lifting: dry adiabatic until saturation,
    # then moist adiabatic

    # Dry adiabatic lapse rate
    dry_lapse = 0.0098  # K/m

    # Pressure ratio
    pressure_ratio = surface_pressure_hpa / environmental_pressure_500mb_hpa

    # Temperature change (simplified)
    temp_change = -dry_lapse * (environmental_pressure_500mb_hpa - surface_pressure_hpa) / 10

    # Parcel temperature at 500 mb
    parcel_temp_500 = surface_temperature_c + temp_change

    # Lifted Index
    li = environmental_temperature_500mb_c - parcel_temp_500

    return li
