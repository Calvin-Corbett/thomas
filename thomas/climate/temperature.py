"""Temperature analysis and trend calculation for climate science.

This module provides temperature analysis tools including anomaly calculation,
urban heat island estimation, trend analysis, seasonal decomposition, extreme
event detection, and degree day calculations.
"""

import math

from scipy import stats

from thomas.climate._exceptions import ClimateDataError, InvalidParameterError


def temperature_anomaly(temperature_c: float, baseline_mean_c: float) -> float:
    """Calculate temperature anomaly relative to baseline period.

    Anomaly represents deviation from long-term mean (typically 30-year baseline).

    Args:
        temperature_c: Current temperature in Celsius.
        baseline_mean_c: Baseline period mean temperature in Celsius.

    Returns:
        Temperature anomaly in Celsius.
    """
    return temperature_c - baseline_mean_c


def global_temperature_anomaly(
    temperatures_c: list[float], baseline_period_mean_c: float | None = None
) -> tuple[list[float], float]:
    """Calculate global temperature anomalies for a series of measurements.

    Args:
        temperatures_c: List of temperature measurements in Celsius.
        baseline_period_mean_c: Mean of baseline period. If None, uses first 10 years.

    Returns:
        Tuple of (anomalies list, baseline mean) in Celsius.

    Raises:
        ClimateDataError: If insufficient data.
    """
    if not temperatures_c or len(temperatures_c) < 10:
        raise ClimateDataError("Need at least 10 temperature observations", temperatures_c)

    if baseline_period_mean_c is None:
        baseline_period_mean_c = sum(temperatures_c[:10]) / 10

    anomalies = [temperature_anomaly(t, baseline_period_mean_c) for t in temperatures_c]
    return anomalies, baseline_period_mean_c


def urban_heat_island_estimation(
    urban_temperature_c: float, rural_temperature_c: float, urban_area_km2: float
) -> float:
    """Estimate urban heat island effect intensity.

    Urban heat island effect is the difference between urban and rural temperatures.

    Args:
        urban_temperature_c: Temperature in urban area in Celsius.
        rural_temperature_c: Temperature in surrounding rural area in Celsius.
        urban_area_km2: Urban area size in km².

    Returns:
        Urban heat island intensity in Celsius.
    """
    uhi_intensity = urban_temperature_c - rural_temperature_c
    return uhi_intensity


def linear_temperature_trend(
    temperatures_c: list[float], years: list[float] | None = None
) -> tuple[float, float, float]:
    """Calculate linear temperature trend using linear regression.

    Args:
        temperatures_c: List of annual mean temperatures in Celsius.
        years: List of years (defaults to 0, 1, 2, ...).

    Returns:
        Tuple of (slope °C/year, intercept °C, r_squared).

    Raises:
        ClimateDataError: If insufficient data.
    """
    if not temperatures_c or len(temperatures_c) < 2:
        raise ClimateDataError("Need at least 2 data points", temperatures_c)

    if years is None:
        years = list(range(len(temperatures_c)))

    if len(years) != len(temperatures_c):
        raise ClimateDataError("Years and temperatures must have same length")

    # Linear regression
    slope, intercept, r_value, _, _ = stats.linregress(years, temperatures_c)
    r_squared = r_value**2

    return slope, intercept, r_squared


def seasonal_decomposition_climatological(
    temperatures_c: list[float], months: list[int], window_years: int = 30
) -> tuple[list[float], list[float]]:
    """Decompose temperature into climatological normals and anomalies.

    Args:
        temperatures_c: List of monthly temperatures in Celsius.
        months: List of month numbers (1-12) corresponding to temperatures.
        window_years: Years for climatological normal computation.

    Returns:
        Tuple of (climatological_normals, anomalies) for each month.

    Raises:
        ClimateDataError: If insufficient data.
    """
    if not temperatures_c or len(temperatures_c) < 12:
        raise ClimateDataError("Need at least 12 months of data", temperatures_c)

    # Group by month
    monthly_data: dict = {m: [] for m in range(1, 13)}
    for temp, month in zip(temperatures_c, months):
        monthly_data[month].append(temp)

    # Calculate climatological normals for each month
    normals = {}
    for month in range(1, 13):
        if monthly_data[month]:
            normals[month] = sum(monthly_data[month]) / len(monthly_data[month])
        else:
            normals[month] = 0.0

    # Calculate anomalies
    climatological_normals = [normals[m] for m in months]
    anomalies = [t - n for t, n in zip(temperatures_c, climatological_normals)]

    return climatological_normals, anomalies


def return_period_gev(temperature_extremes_c: list[float], return_year: int = 100) -> float:
    """Calculate extreme temperature value for return period using GEV distribution.

    Args:
        temperature_extremes_c: List of annual temperature extremes (maxima or minima).
        return_year: Return period in years (default 100-year event).

    Returns:
        Temperature at specified return period in Celsius.

    Raises:
        ClimateDataError: If insufficient data.
    """
    if not temperature_extremes_c or len(temperature_extremes_c) < 10:
        raise ClimateDataError("Need at least 10 years of extremes", temperature_extremes_c)

    # Simple GEV fit using Gumbel (Type I) approximation
    # Location and scale parameters
    mean_temp = sum(temperature_extremes_c) / len(temperature_extremes_c)
    std_temp = math.sqrt(sum((t - mean_temp) ** 2 for t in temperature_extremes_c) / len(temperature_extremes_c))

    # Gumbel distribution parameters
    sqrt_6_pi = math.sqrt(6) / math.pi
    location = mean_temp - sqrt_6_pi * std_temp * 0.5772
    scale = sqrt_6_pi * std_temp

    # Return value calculation
    reduced_variate = -math.log(-math.log(1 - 1 / return_year))
    return_value = location + scale * reduced_variate

    return return_value


def extreme_event_frequency(
    temperatures_c: list[float], threshold_c: float, event_type: str = "hot"
) -> tuple[int, float]:
    """Detect extreme temperature events and calculate frequency.

    Args:
        temperatures_c: List of temperature observations in Celsius.
        threshold_c: Temperature threshold for extreme event.
        event_type: "hot" for events >= threshold, "cold" for events <= threshold.

    Returns:
        Tuple of (event_count, frequency_percent).

    Raises:
        InvalidParameterError: If event_type is invalid.
    """
    if event_type not in ("hot", "cold"):
        raise InvalidParameterError("event_type must be 'hot' or 'cold'", "event_type", event_type)

    if not temperatures_c:
        return 0, 0.0

    if event_type == "hot":
        extreme_count = sum(1 for t in temperatures_c if t >= threshold_c)
    else:
        extreme_count = sum(1 for t in temperatures_c if t <= threshold_c)

    frequency = (extreme_count / len(temperatures_c)) * 100
    return extreme_count, frequency


def growing_degree_days(
    temperatures_c: list[float], base_temperature_c: float = 10.0, max_threshold_c: float | None = None
) -> float:
    """Calculate accumulated growing degree days (GDD).

    GDD measures heat accumulation relevant to plant growth.

    Args:
        temperatures_c: List of daily mean temperatures in Celsius.
        base_temperature_c: Base temperature (typically 10°C for crops).
        max_threshold_c: Maximum threshold (optional cap on temperature).

    Returns:
        Accumulated growing degree days.

    Raises:
        InvalidParameterError: If parameters are invalid.
    """
    if not temperatures_c:
        return 0.0

    gdd = 0.0
    for temp in temperatures_c:
        # Temperature must exceed base
        if temp > base_temperature_c:
            contrib = temp - base_temperature_c

            # Cap at maximum if specified
            if max_threshold_c is not None:
                contrib = min(contrib, max_threshold_c - base_temperature_c)

            gdd += contrib

    return gdd


def heating_degree_days(temperatures_c: list[float], base_temperature_c: float = 18.3) -> float:
    """Calculate heating degree days (HDD).

    HDD measures energy requirement for heating buildings.

    Args:
        temperatures_c: List of daily mean temperatures in Celsius.
        base_temperature_c: Base temperature (typically 18.3°C or 65°F).

    Returns:
        Accumulated heating degree days.
    """
    if not temperatures_c:
        return 0.0

    hdd = 0.0
    for temp in temperatures_c:
        if temp < base_temperature_c:
            hdd += base_temperature_c - temp

    return hdd


def cooling_degree_days(temperatures_c: list[float], base_temperature_c: float = 18.3) -> float:
    """Calculate cooling degree days (CDD).

    CDD measures energy requirement for cooling buildings.

    Args:
        temperatures_c: List of daily mean temperatures in Celsius.
        base_temperature_c: Base temperature (typically 18.3°C or 65°F).

    Returns:
        Accumulated cooling degree days.
    """
    if not temperatures_c:
        return 0.0

    cdd = 0.0
    for temp in temperatures_c:
        if temp > base_temperature_c:
            cdd += temp - base_temperature_c

    return cdd


def temperature_percentile(temperatures_c: list[float], percentile: float) -> float:
    """Calculate temperature percentile value.

    Args:
        temperatures_c: List of temperatures in Celsius.
        percentile: Percentile (0-100).

    Returns:
        Temperature at specified percentile in Celsius.

    Raises:
        InvalidParameterError: If percentile is invalid.
    """
    if not temperatures_c:
        raise ClimateDataError("Temperature list is empty", temperatures_c)

    if percentile < 0 or percentile > 100:
        raise InvalidParameterError("Percentile must be 0-100", "percentile", percentile)

    sorted_temps = sorted(temperatures_c)
    index = int((percentile / 100.0) * len(sorted_temps))
    index = min(index, len(sorted_temps) - 1)

    return sorted_temps[index]


def diurnal_temperature_range(daily_highs_c: list[float], daily_lows_c: list[float]) -> float:
    """Calculate mean diurnal (daily) temperature range.

    Args:
        daily_highs_c: List of daily maximum temperatures in Celsius.
        daily_lows_c: List of daily minimum temperatures in Celsius.

    Returns:
        Mean diurnal temperature range in Celsius.

    Raises:
        ClimateDataError: If lists have different lengths.
    """
    if len(daily_highs_c) != len(daily_lows_c):
        raise ClimateDataError("High and low temperatures must have same length")

    if not daily_highs_c:
        return 0.0

    dtr = sum((h - l) for h, l in zip(daily_highs_c, daily_lows_c)) / len(daily_highs_c)
    return dtr


def mann_kendall_trend_test(data: list[float]) -> tuple[float, float]:
    """Perform Mann-Kendall trend test for monotonic trends.

    Returns Z-statistic and p-value.
    Positive Z indicates increasing trend, negative indicates decreasing.

    Args:
        data: List of values to test for trend.

    Returns:
        Tuple of (z_statistic, p_value).

    Raises:
        ClimateDataError: If insufficient data.
    """
    if not data or len(data) < 3:
        raise ClimateDataError("Need at least 3 data points", data)

    n = len(data)
    s = 0

    # Calculate Mann-Kendall S statistic
    for i in range(n - 1):
        for j in range(i + 1, n):
            if data[j] > data[i]:
                s += 1
            elif data[j] < data[i]:
                s -= 1

    # Variance calculation
    var_s = n * (n - 1) * (2 * n + 5) / 18

    # Z-score calculation
    if s > 0:
        z = (s - 1) / math.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / math.sqrt(var_s)
    else:
        z = 0.0

    # Two-tailed p-value using normal distribution
    from scipy.stats import norm

    p_value = 2 * (1 - norm.cdf(abs(z)))

    return z, p_value
