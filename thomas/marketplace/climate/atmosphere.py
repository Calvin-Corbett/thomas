"""Atmospheric physics calculations for climate science.

This module provides fundamental atmospheric physics calculations including
ideal gas law, pressure-altitude relationships, humidity calculations,
stability classification, and various atmospheric parameters.
"""

import math

from thomas.marketplace.climate._exceptions import InvalidParameterError

# Physical constants
UNIVERSAL_GAS_CONSTANT: float = 287.0  # J/(kg·K) for dry air
STANDARD_PRESSURE: float = 101325.0  # Pa
STANDARD_TEMPERATURE: float = 288.15  # K (15°C)
GRAVITY: float = 9.80665  # m/s²
LAPSE_RATE_DRY: float = 0.0065  # K/m dry adiabatic
LAPSE_RATE_MOIST: float = 0.006  # K/m moist adiabatic (approximate)
CELSIUS_TO_KELVIN: float = 273.15


def ideal_gas_law(pressure_pa: float, density_kg_m3: float, temperature_k: float) -> float:
    """Calculate air density using ideal gas law.

    The ideal gas law: P = ρ × R × T
    where P is pressure, ρ is density, R is specific gas constant, T is temperature.

    Args:
        pressure_pa: Pressure in Pascals.
        density_kg_m3: Air density in kg/m³.
        temperature_k: Temperature in Kelvin.

    Returns:
        Gas constant R in J/(kg·K).

    Raises:
        InvalidParameterError: If any parameter is invalid.
    """
    if temperature_k <= 0:
        raise InvalidParameterError("Temperature must be positive", "temperature_k", temperature_k)
    if density_kg_m3 <= 0:
        raise InvalidParameterError("Density must be positive", "density_kg_m3", density_kg_m3)

    return pressure_pa / (density_kg_m3 * temperature_k)


def air_density(pressure_pa: float, temperature_c: float, relative_humidity: float = 0.0) -> float:
    """Calculate air density from pressure and temperature.

    Uses ideal gas law with humidity correction via virtual temperature.

    Args:
        pressure_pa: Pressure in Pascals.
        temperature_c: Temperature in Celsius.
        relative_humidity: Relative humidity as percentage (0-100).

    Returns:
        Air density in kg/m³.

    Raises:
        InvalidParameterError: If parameters are invalid.
    """
    if pressure_pa <= 0:
        raise InvalidParameterError("Pressure must be positive", "pressure_pa", pressure_pa)
    if relative_humidity < 0 or relative_humidity > 100:
        raise InvalidParameterError("Humidity must be 0-100%", "relative_humidity", relative_humidity)

    temperature_k = temperature_c + CELSIUS_TO_KELVIN

    # Saturation vapor pressure (Tetens formula)
    e_s = 6.112 * math.exp((17.67 * temperature_c) / (temperature_c + 243.5))
    e = (relative_humidity / 100.0) * e_s

    # Virtual temperature correction
    mixing_ratio = 0.622 * e / (pressure_pa / 100 - e)
    virtual_temp_k = temperature_k * (1 + mixing_ratio / 0.622) / (1 + mixing_ratio)

    # Ideal gas law with dry air gas constant
    return pressure_pa / (UNIVERSAL_GAS_CONSTANT * virtual_temp_k)


def pressure_from_altitude(
    altitude_m: float, sea_level_pressure_pa: float = STANDARD_PRESSURE, temperature_c: float = 15.0
) -> float:
    """Convert altitude to pressure using barometric formula.

    Uses the International Barometric Formula (simplified).

    Args:
        altitude_m: Altitude in meters.
        sea_level_pressure_pa: Sea level pressure in Pa.
        temperature_c: Mean temperature in Celsius.

    Returns:
        Pressure in Pascals.

    Raises:
        InvalidParameterError: If parameters are invalid.
    """
    if altitude_m < 0:
        raise InvalidParameterError("Altitude cannot be negative", "altitude_m", altitude_m)
    if sea_level_pressure_pa <= 0:
        raise InvalidParameterError(
            "Sea level pressure must be positive", "sea_level_pressure_pa", sea_level_pressure_pa
        )

    temperature_k = temperature_c + CELSIUS_TO_KELVIN
    exponent = -(GRAVITY * altitude_m) / (UNIVERSAL_GAS_CONSTANT * temperature_k)
    return sea_level_pressure_pa * math.exp(exponent)


def altitude_from_pressure(
    pressure_pa: float, sea_level_pressure_pa: float = STANDARD_PRESSURE, temperature_c: float = 15.0
) -> float:
    """Convert pressure to altitude using barometric formula (inverted).

    Args:
        pressure_pa: Pressure in Pascals.
        sea_level_pressure_pa: Sea level pressure in Pa.
        temperature_c: Mean temperature in Celsius.

    Returns:
        Altitude in meters.

    Raises:
        InvalidParameterError: If parameters are invalid.
    """
    if pressure_pa <= 0:
        raise InvalidParameterError("Pressure must be positive", "pressure_pa", pressure_pa)
    if sea_level_pressure_pa <= 0:
        raise InvalidParameterError(
            "Sea level pressure must be positive", "sea_level_pressure_pa", sea_level_pressure_pa
        )

    temperature_k = temperature_c + CELSIUS_TO_KELVIN
    ratio = pressure_pa / sea_level_pressure_pa
    if ratio <= 0:
        raise InvalidParameterError("Invalid pressure ratio", "ratio", ratio)

    return -(UNIVERSAL_GAS_CONSTANT * temperature_k / GRAVITY) * math.log(ratio)


def dew_point_magnus(temperature_c: float, relative_humidity: float) -> float:
    """Calculate dew point using Magnus formula.

    The Magnus formula is accurate to ±0.35°C over -40 to 50°C.

    Args:
        temperature_c: Temperature in Celsius.
        relative_humidity: Relative humidity as percentage (0-100).

    Returns:
        Dew point temperature in Celsius.

    Raises:
        InvalidParameterError: If parameters are invalid.
    """
    if relative_humidity < 0 or relative_humidity > 100:
        raise InvalidParameterError("Humidity must be 0-100%", "relative_humidity", relative_humidity)

    a, b, _c = 17.27, 237.7, 110.6

    alpha = ((a * temperature_c) / (b + temperature_c)) + math.log(relative_humidity / 100.0)
    dew_point = (b * alpha) / (a - alpha)

    return dew_point


def saturation_vapor_pressure_clausius_clapeyron(temperature_c: float) -> float:
    """Calculate saturation vapor pressure using Clausius-Clapeyron equation.

    Args:
        temperature_c: Temperature in Celsius.

    Returns:
        Saturation vapor pressure in hPa.
    """
    temperature_k = temperature_c + CELSIUS_TO_KELVIN

    # Reference values
    t0 = 273.15  # K
    p0 = 6.112  # hPa at 0°C
    L = 2.5e6  # J/kg latent heat of vaporization
    Rv = 461.5  # J/(kg·K) gas constant for water vapor

    exponent = (L / Rv) * (1 / t0 - 1 / temperature_k)
    return p0 * math.exp(exponent)


def heat_index_rothfusz(temperature_c: float, relative_humidity: float) -> float:
    """Calculate heat index using Rothfusz regression.

    Heat index represents apparent temperature experienced due to
    combined effects of heat and humidity.

    Args:
        temperature_c: Temperature in Celsius.
        relative_humidity: Relative humidity as percentage (0-100).

    Returns:
        Heat index in Celsius.

    Raises:
        InvalidParameterError: If parameters are invalid.
    """
    if relative_humidity < 0 or relative_humidity > 100:
        raise InvalidParameterError("Humidity must be 0-100%", "relative_humidity", relative_humidity)

    # Convert to Fahrenheit for formula
    t_f = (temperature_c * 9 / 5) + 32
    rh = relative_humidity

    # Rothfusz regression coefficients
    c1 = -42.379
    c2 = 2.04901523
    c3 = 10.14333127
    c4 = -0.22475541
    c5 = -0.00683783
    c6 = -0.05481717
    c7 = 0.00122874
    c8 = 0.00085282
    c9 = -0.00000199

    hi_f = (
        c1
        + c2 * t_f
        + c3 * rh
        + c4 * t_f * rh
        + c5 * t_f**2
        + c6 * rh**2
        + c7 * t_f**2 * rh
        + c8 * t_f * rh**2
        + c9 * t_f**2 * rh**2
    )

    # Convert back to Celsius
    return (hi_f - 32) * 5 / 9


def wind_chill_nws(temperature_c: float, wind_speed_ms: float) -> float:
    """Calculate wind chill index using NWS formula.

    Only valid for temperatures ≤ 10°C and wind speed ≥ 4.8 m/s.

    Args:
        temperature_c: Temperature in Celsius.
        wind_speed_ms: Wind speed in meters per second.

    Returns:
        Wind chill temperature in Celsius.

    Raises:
        InvalidParameterError: If parameters are invalid.
    """
    if wind_speed_ms < 0:
        raise InvalidParameterError("Wind speed cannot be negative", "wind_speed_ms", wind_speed_ms)

    # Convert to mph for formula
    t_f = (temperature_c * 9 / 5) + 32
    v_mph = wind_speed_ms * 2.23694

    if wind_speed_ms < 4.8 or temperature_c > 10:
        return temperature_c

    # NWS wind chill formula
    wc_f = 35.74 + 0.6215 * t_f - 35.75 * (v_mph**0.16) + 0.4275 * t_f * (v_mph**0.16)

    return (wc_f - 32) * 5 / 9


def atmospheric_lapse_rate(altitude_m: float, temperature_sea_level_c: float, is_moist: bool = False) -> float:
    """Calculate temperature at altitude using lapse rate.

    Args:
        altitude_m: Altitude in meters.
        temperature_sea_level_c: Sea level temperature in Celsius.
        is_moist: Use moist adiabatic rate (True) or dry (False).

    Returns:
        Temperature at altitude in Celsius.

    Raises:
        InvalidParameterError: If parameters are invalid.
    """
    if altitude_m < 0:
        raise InvalidParameterError("Altitude cannot be negative", "altitude_m", altitude_m)

    lapse_rate = LAPSE_RATE_MOIST if is_moist else LAPSE_RATE_DRY
    temperature_change = -lapse_rate * altitude_m

    return temperature_sea_level_c + temperature_change


def pasquill_gifford_stability(
    temperature_c: float, wind_speed_ms: float, solar_radiation_wm2: float | None = None, hour_utc: int = 12
) -> str:
    """Classify atmospheric stability using Pasquill-Gifford categories.

    Categories: A (very unstable) to F (stable)

    Args:
        temperature_c: Temperature in Celsius.
        wind_speed_ms: Wind speed in meters per second.
        solar_radiation_wm2: Solar radiation in W/m² (optional).
        hour_utc: Hour in UTC (0-23) for nighttime detection.

    Returns:
        Stability class letter (A-F).

    Raises:
        InvalidParameterError: If parameters are invalid.
    """
    if wind_speed_ms < 0:
        raise InvalidParameterError("Wind speed cannot be negative", "wind_speed_ms", wind_speed_ms)

    is_night = hour_utc < 6 or hour_utc > 18
    is_cloudy = solar_radiation_wm2 is not None and solar_radiation_wm2 < 50

    # Daytime classification
    if not is_night:
        if solar_radiation_wm2 is None or solar_radiation_wm2 < 150:
            rad_level = "weak"
        elif solar_radiation_wm2 < 400:
            rad_level = "moderate"
        else:
            rad_level = "strong"

        if wind_speed_ms < 2:
            if rad_level == "strong":
                return "A"
            elif rad_level == "moderate":
                return "B"
            else:
                return "C"
        elif wind_speed_ms < 3:
            if rad_level == "strong" or rad_level == "moderate":
                return "B"
            else:
                return "C"
        elif wind_speed_ms < 5:
            if rad_level == "strong" or rad_level == "moderate":
                return "C"
            else:
                return "D"
        elif wind_speed_ms < 6:
            return "D"
        else:
            return "D"

    # Nighttime classification
    else:
        if is_cloudy:
            if wind_speed_ms < 3:
                return "E"
            else:
                return "D"
        else:
            if wind_speed_ms < 3:
                return "F"
            elif wind_speed_ms < 4.5:
                return "E"
            else:
                return "D"


def relative_humidity_from_dewpoint(temperature_c: float, dew_point_c: float) -> float:
    """Calculate relative humidity from temperature and dew point.

    Args:
        temperature_c: Temperature in Celsius.
        dew_point_c: Dew point in Celsius.

    Returns:
        Relative humidity as percentage (0-100).
    """
    a, b = 17.27, 237.7

    numerator = math.exp((a * dew_point_c) / (b + dew_point_c))
    denominator = math.exp((a * temperature_c) / (b + temperature_c))

    rh = 100.0 * (numerator / denominator)
    return min(100.0, max(0.0, rh))


def mixing_ratio(vapor_pressure_hpa: float, dry_pressure_hpa: float) -> float:
    """Calculate mixing ratio of water vapor in air.

    Mixing ratio is mass of water vapor per mass of dry air.

    Args:
        vapor_pressure_hpa: Partial pressure of water vapor in hPa.
        dry_pressure_hpa: Partial pressure of dry air in hPa.

    Returns:
        Mixing ratio in g/kg.

    Raises:
        InvalidParameterError: If parameters are invalid.
    """
    if dry_pressure_hpa <= 0:
        raise InvalidParameterError("Dry pressure must be positive", "dry_pressure_hpa", dry_pressure_hpa)

    # Mixing ratio in g/kg
    return 621.97 * (vapor_pressure_hpa / dry_pressure_hpa)


def equivalent_potential_temperature(temperature_c: float, mixing_ratio_g_kg: float, pressure_hpa: float) -> float:
    """Calculate equivalent potential temperature (theta-e).

    Theta-e is conservative property during moist adiabatic processes.

    Args:
        temperature_c: Temperature in Celsius.
        mixing_ratio_g_kg: Mixing ratio in g/kg.
        pressure_hpa: Pressure in hPa.

    Returns:
        Equivalent potential temperature in Kelvin.
    """
    t_k = temperature_c + CELSIUS_TO_KELVIN

    # Dry potential temperature
    theta = t_k * (1000 / pressure_hpa) ** 0.286

    # Latent heat contribution (simplified)
    lh = 2.5e6  # J/kg
    cp = 1005  # J/(kg·K)
    theta_e = theta * math.exp((lh * mixing_ratio_g_kg / 1000) / (cp * t_k))

    return theta_e
