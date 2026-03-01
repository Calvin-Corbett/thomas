"""Precipitation analysis and modeling for hydroclimatic studies.

This module provides precipitation analysis including IDF curves, return period
estimation, drought indices, precipitation classification, evapotranspiration
calculation, and water balance modeling.
"""

import math

from thomas.climate._exceptions import ClimateDataError, InvalidParameterError


def intensity_duration_frequency_curve(rainfall_events: list[tuple[float, int]], durations_minutes: list[int]) -> dict:
    """Calculate Intensity-Duration-Frequency (IDF) curves from rainfall data.

    IDF curves relate rainfall intensity to duration and return period.

    Args:
        rainfall_events: List of (rainfall_mm, duration_minutes) tuples.
        durations_minutes: Durations to calculate for in minutes.

    Returns:
        Dictionary of {duration: max_intensity_mm_hr} for different return periods.

    Raises:
        ClimateDataError: If insufficient data.
    """
    if not rainfall_events or len(rainfall_events) < 5:
        raise ClimateDataError("Need at least 5 rainfall events", rainfall_events)

    idf_curves = {}

    for duration in durations_minutes:
        # Filter events for this duration
        relevant_events = [r for r, d in rainfall_events if d == duration]

        if relevant_events:
            # Intensity in mm/hr
            intensities = [r / (duration / 60.0) for r in relevant_events]
            intensities.sort(reverse=True)

            # Simple Gumbel distribution fit
            if len(intensities) >= 2:
                mean_intensity = sum(intensities) / len(intensities)
                variance = sum((x - mean_intensity) ** 2 for x in intensities) / len(intensities)
                std_intensity = math.sqrt(variance)

                idf_curves[duration] = {
                    "mean": mean_intensity,
                    "max": intensities[0],
                    "2_year": mean_intensity + 0.3665 * std_intensity,
                    "10_year": mean_intensity + 1.3046 * std_intensity,
                    "100_year": mean_intensity + 2.2504 * std_intensity,
                }

    return idf_curves


def gumbel_return_period(extreme_values: list[float], return_period_years: int = 100) -> float:
    """Estimate extreme value at given return period using Gumbel distribution.

    Args:
        extreme_values: List of annual maximum or minimum values.
        return_period_years: Return period in years.

    Returns:
        Extreme value at specified return period.

    Raises:
        ClimateDataError: If insufficient data.
    """
    if not extreme_values or len(extreme_values) < 10:
        raise ClimateDataError("Need at least 10 extreme values", extreme_values)

    mean_val = sum(extreme_values) / len(extreme_values)
    variance = sum((x - mean_val) ** 2 for x in extreme_values) / len(extreme_values)
    std_val = math.sqrt(variance)

    # Gumbel parameters
    sqrt_6_pi = math.sqrt(6) / math.pi
    scale = sqrt_6_pi * std_val
    location = mean_val - 0.5772 * scale

    # Return value for given return period
    reduced_variate = -math.log(-math.log(1 - 1 / return_period_years))
    return_value = location + scale * reduced_variate

    return return_value


def standardized_precipitation_index(
    monthly_precipitation: list[float], time_scale_months: int = 12, calibration_period_years: int = 30
) -> list[float]:
    """Calculate Standardized Precipitation Index (SPI) for drought assessment.

    SPI measures precipitation anomalies normalized by fitting gamma distribution.

    Args:
        monthly_precipitation: List of monthly precipitation values in mm.
        time_scale_months: Aggregation period (3, 6, 12, 24 months).
        calibration_period_years: Years for calibration.

    Returns:
        List of SPI values (negative = drought, positive = wet).

    Raises:
        ClimateDataError: If insufficient data.
    """
    if not monthly_precipitation or len(monthly_precipitation) < 12:
        raise ClimateDataError("Need at least 12 months of data", monthly_precipitation)

    min_data_points = calibration_period_years * 12
    if len(monthly_precipitation) < min_data_points:
        raise ClimateDataError(f"Need at least {min_data_points} data points", monthly_precipitation)

    # Rolling aggregation
    aggregated = []
    for i in range(len(monthly_precipitation) - time_scale_months + 1):
        agg_value = sum(monthly_precipitation[i : i + time_scale_months])
        aggregated.append(agg_value)

    # Fit gamma distribution to calibration period
    calib_data = aggregated[: calibration_period_years * 12]
    mean_precip = sum(calib_data) / len(calib_data)
    variance = sum((x - mean_precip) ** 2 for x in calib_data) / len(calib_data)

    # Gamma distribution parameters
    alpha = (mean_precip**2) / variance
    beta = variance / mean_precip

    # Calculate probabilities and convert to standard normal (SPI)
    spi_values = []
    from scipy.stats import norm

    for value in aggregated:
        if value > 0:
            # Cumulative probability using incomplete gamma
            prob = sum(
                math.exp(-value / beta) * ((value / beta) ** k) / math.factorial(k) for k in range(int(alpha) + 1)
            )
            # Clamp probability to valid range
            prob = max(0.0001, min(0.9999, prob))
            spi = norm.ppf(prob)
        else:
            spi = -3.0  # Extreme drought

        spi_values.append(spi)

    return spi_values


def koppen_precipitation_classification(
    annual_precip_mm: float, winter_precip_mm: float, summer_precip_mm: float
) -> str:
    """Classify climate based on precipitation using Koppen classification.

    Args:
        annual_precip_mm: Annual precipitation in mm.
        winter_precip_mm: Winter season precipitation in mm.
        summer_precip_mm: Summer season precipitation in mm.

    Returns:
        Koppen precipitation class (B-E classification group).
    """
    if annual_precip_mm < 250:
        return "B_hyperarid"
    elif annual_precip_mm < 500:
        return "B_arid"
    elif annual_precip_mm < 1000:
        return "B_semiarid"
    elif annual_precip_mm < 2000:
        return "C_temperate"
    elif annual_precip_mm < 3000:
        return "D_continental"
    else:
        return "E_polar"


def snow_water_equivalent(snow_depth_cm: float, snow_density_kg_m3: float | None = None) -> float:
    """Calculate snow water equivalent (SWE) from depth and density.

    Args:
        snow_depth_cm: Snow depth in centimeters.
        snow_density_kg_m3: Snow density in kg/m³ (default 300 for fresh snow).

    Returns:
        Water equivalent in millimeters.

    Raises:
        InvalidParameterError: If parameters are invalid.
    """
    if snow_depth_cm < 0:
        raise InvalidParameterError("Snow depth cannot be negative", "snow_depth_cm", snow_depth_cm)

    if snow_density_kg_m3 is None:
        snow_density_kg_m3 = 300.0  # Fresh snow typical density

    if snow_density_kg_m3 <= 0:
        raise InvalidParameterError("Snow density must be positive", "snow_density_kg_m3", snow_density_kg_m3)

    # SWE = depth (cm) × density (kg/m³) / 10
    swe_mm = (snow_depth_cm * snow_density_kg_m3) / 10.0

    return swe_mm


def penman_monteith_evapotranspiration(
    net_radiation_mj_m2: float,
    temperature_c: float,
    wind_speed_m_s: float,
    relative_humidity: float,
    atmospheric_pressure_hpa: float = 101.3,
    crop_height_m: float = 0.12,
) -> float:
    """Calculate reference evapotranspiration using Penman-Monteith equation.

    Simplified version for reference grass evapotranspiration (ET0).

    Args:
        net_radiation_mj_m2: Net radiation in MJ/m²/day.
        temperature_c: Mean temperature in Celsius.
        wind_speed_m_s: Wind speed at 2m in m/s.
        relative_humidity: Relative humidity as percentage (0-100).
        atmospheric_pressure_hpa: Atmospheric pressure in hPa.
        crop_height_m: Crop height in meters.

    Returns:
        Reference evapotranspiration in mm/day.

    Raises:
        InvalidParameterError: If parameters are invalid.
    """
    if temperature_c < -50 or temperature_c > 60:
        raise InvalidParameterError("Invalid temperature range", "temperature_c", temperature_c)

    if relative_humidity < 0 or relative_humidity > 100:
        raise InvalidParameterError("Humidity must be 0-100%", "relative_humidity", relative_humidity)

    # Psychrometric constant
    gamma = 0.665e-3 * atmospheric_pressure_hpa

    # Saturation vapor pressure
    e_s = 0.6108 * math.exp((17.27 * temperature_c) / (temperature_c + 237.3))

    # Actual vapor pressure
    e_a = (relative_humidity / 100.0) * e_s

    # Vapor pressure deficit
    vpd = e_s - e_a

    # Slope of saturation vapor pressure curve
    delta = (4098 * e_s) / ((temperature_c + 237.3) ** 2)

    # Aerodynamic resistance
    z_u = 2.0  # Measurement height (2m)
    u_2 = wind_speed_m_s
    ra = 208.0 / u_2 if u_2 > 0.1 else 208.0

    # Surface resistance
    r_s = 70.0 if crop_height_m > 0.1 else 100.0

    # Reference crop coefficient approximation
    cn = 900.0

    # Penman-Monteith equation (simplified)
    numerator = 0.408 * delta * net_radiation_mj_m2 + gamma * (cn / (temperature_c + 273.0)) * u_2 * vpd
    denominator = delta + gamma * (1 + (r_s / ra))

    et0 = numerator / denominator

    return max(0.0, et0)


def water_balance(
    precipitation_mm: float, evapotranspiration_mm: float, runoff_mm: float, soil_moisture_change_mm: float
) -> float:
    """Calculate water balance residual (infiltration/percolation).

    Water balance equation:
    Precipitation = Evapotranspiration + Runoff + Change in Storage + Percolation

    Args:
        precipitation_mm: Total precipitation in mm.
        evapotranspiration_mm: Actual ET in mm.
        runoff_mm: Surface runoff in mm.
        soil_moisture_change_mm: Change in soil moisture in mm.

    Returns:
        Percolation/infiltration in mm.
    """
    percolation = precipitation_mm - evapotranspiration_mm - runoff_mm - soil_moisture_change_mm

    return max(0.0, percolation)


def drought_duration_frequency(spi_values: list[float], threshold: float = -1.0) -> tuple[int, float, float]:
    """Calculate drought duration and frequency from SPI series.

    Args:
        spi_values: List of SPI values.
        threshold: SPI threshold for drought (typically -1.0 or below).

    Returns:
        Tuple of (drought_months, drought_frequency_percent, mean_intensity).

    Raises:
        ClimateDataError: If insufficient data.
    """
    if not spi_values:
        raise ClimateDataError("SPI values list is empty", spi_values)

    drought_count = sum(1 for spi in spi_values if spi <= threshold)
    frequency = (drought_count / len(spi_values)) * 100

    # Mean intensity during droughts
    drought_values = [spi for spi in spi_values if spi <= threshold]
    mean_intensity = sum(drought_values) / len(drought_values) if drought_values else 0.0

    return drought_count, frequency, mean_intensity


def precipitation_concentration(monthly_values: list[float]) -> float:
    """Calculate precipitation concentration index (Gini coefficient-based).

    High values indicate concentration in few months; low values indicate
    even distribution.

    Args:
        monthly_values: List of 12 monthly precipitation values.

    Returns:
        Concentration index (0-1, where 1 is maximum concentration).

    Raises:
        ClimateDataError: If wrong number of months.
    """
    if len(monthly_values) != 12:
        raise ClimateDataError("Require exactly 12 monthly values", monthly_values)

    total = sum(monthly_values)
    if total == 0:
        return 0.0

    sorted_values = sorted(monthly_values)
    cumsum = sum((i + 1) * v for i, v in enumerate(sorted_values))

    concentration = (2 * cumsum) / (total * len(monthly_values)) - ((len(monthly_values) + 1) / len(monthly_values))

    return max(0.0, min(1.0, concentration))
