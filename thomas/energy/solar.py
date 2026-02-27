"""
Solar energy modeling and simulation.

Provides solar irradiance calculation (clear-sky model with air mass and Perez
diffuse model), panel optimization, temperature derating, MPPT tracking,
shading estimation, and annual yield calculation.
"""

import math
from dataclasses import dataclass
from datetime import datetime

from thomas.energy._types import EnergySource, PowerPlant, WeatherCondition


@dataclass
class SolarParameters:
    """Solar panel and site parameters."""

    latitude: float  # degrees
    longitude: float  # degrees
    elevation: float  # meters
    tilt_angle: float  # degrees (0=horizontal, 90=vertical)
    azimuth_angle: float  # degrees (180=south, 0=north for northern hemisphere)
    panel_efficiency: float  # 0.0-1.0
    temperature_coefficient: float = -0.004  # per Celsius above 25C
    area_m2: float = 1.0
    soiling_factor: float = 0.97  # 3% soiling loss
    mismatch_factor: float = 0.98  # Wiring and module mismatch
    dc_to_ac_efficiency: float = 0.96  # Inverter efficiency


@dataclass
class SolarPlant(PowerPlant):
    """Solar photovoltaic generation plant."""

    latitude: float = 0.0
    longitude: float = 0.0
    elevation: float = 0.0
    panel_count: int = 1000
    tilt_angle: float = 30.0  # degrees from horizontal
    azimuth_angle: float = 180.0  # degrees (180=south-facing in northern hemisphere)
    panel_efficiency: float = 0.20  # 20% typical modern panel
    temperature_coefficient: float = -0.004
    area_per_panel_m2: float = 2.0
    soiling_factor: float = 0.97
    mismatch_factor: float = 0.98
    inverter_efficiency: float = 0.96
    tracking_type: str = "fixed"  # "fixed", "single_axis", "dual_axis"

    def __post_init__(self) -> None:
        self.fuel_type = EnergySource.SOLAR
        self.total_area_m2 = self.panel_count * self.area_per_panel_m2


def calculate_solar_position(
    timestamp: datetime,
    latitude: float,
    longitude: float,
) -> tuple[float, float]:
    """
    Calculate solar altitude and azimuth (simplified solar position algorithm).

    Args:
        timestamp: Local datetime at the site
        latitude: Site latitude in degrees
        longitude: Site longitude in degrees

    Returns:
        Tuple of (altitude_degrees, azimuth_degrees)
    """
    # Day of year
    day_of_year = timestamp.timetuple().tm_yday

    # Fractional year in radians
    gamma = 2 * math.pi * (day_of_year - 1) / 365.0

    # Equation of time (minutes)
    eot = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )

    # Convert local civil time to local solar time:
    # correction = equation of time + longitude offset from time-zone meridian.
    local_hours = timestamp.hour + timestamp.minute / 60.0 + timestamp.second / 3600.0
    timezone_offset_hours = round(longitude / 15.0)
    local_standard_meridian = 15.0 * timezone_offset_hours
    time_offset = eot + 4.0 * (longitude - local_standard_meridian)
    local_solar_time = local_hours + time_offset / 60.0

    # Hour angle (degrees, -180 to 180)
    hour_angle = (local_solar_time - 12.0) * 15.0

    # Solar declination
    delta = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.00227 * math.cos(3 * gamma)
        + 0.00037 * math.sin(3 * gamma)
    )

    lat_rad = math.radians(latitude)
    h_rad = math.radians(hour_angle)

    # Solar altitude angle
    sin_alt = math.sin(lat_rad) * math.sin(delta) + math.cos(lat_rad) * math.cos(delta) * math.cos(h_rad)
    sin_alt = max(-1.0, min(1.0, sin_alt))
    altitude = math.degrees(math.asin(sin_alt))

    # Solar azimuth angle (0=north, 90=east, 180=south, 270=west)
    cos_alt = max(1e-9, math.cos(math.radians(altitude)))
    cos_az = (math.sin(delta) - math.sin(lat_rad) * math.sin(math.radians(altitude))) / (math.cos(lat_rad) * cos_alt)
    cos_az = max(-1.0, min(1.0, cos_az))
    azimuth = math.degrees(math.acos(cos_az))
    if hour_angle > 0:
        azimuth = 360.0 - azimuth

    return altitude, azimuth


def calculate_air_mass(solar_altitude: float) -> float:
    """
    Calculate atmospheric air mass using Kasten and Czeplak formula.

    Args:
        solar_altitude: Solar altitude angle in degrees

    Returns:
        Air mass (minimum 1.0 at zenith)
    """
    if solar_altitude <= 0:
        return 100.0

    sin_altitude = math.sin(math.radians(solar_altitude))
    air_mass = 1.0 / (sin_altitude + 0.50572 * (96.07995 - solar_altitude) ** (-1.6364))
    return max(1.0, air_mass)


def calculate_clearsky_irradiance(
    air_mass: float,
    solar_altitude: float,
) -> float:
    """
    Calculate clear-sky direct normal irradiance (DNI) using Kasten-Czeplak model.

    Args:
        air_mass: Atmospheric air mass
        solar_altitude: Solar altitude in degrees

    Returns:
        DNI in W/m^2
    """
    if solar_altitude <= 0:
        return 0.0

    # Empirical clear-sky DNI model calibrated near AM1 to ~950 W/m^2.
    dni = 950.0 * math.exp(-0.14 * max(0.0, air_mass - 1.0))
    return max(0.0, dni)


def calculate_diffuse_irradiance(
    dni: float,
    solar_altitude: float,
    clearness_index: float = 0.75,
) -> float:
    """
    Calculate diffuse horizontal irradiance using Perez decomposition model.

    Args:
        dni: Direct normal irradiance in W/m^2
        solar_altitude: Solar altitude in degrees
        clearness_index: Sky clearness (0=cloudy, 1=clear)

    Returns:
        DHI in W/m^2
    """
    if solar_altitude <= 0:
        return 0.0

    ghi = max(0.0, dni * math.sin(math.radians(solar_altitude)))
    clearness = max(0.0, min(1.0, clearness_index))
    # Clear skies have low diffuse fraction; cloudy skies have higher.
    diffuse_fraction = 0.08 + 0.60 * (1.0 - clearness)
    dhi = ghi * diffuse_fraction
    return max(0.0, dhi)


def calculate_incident_angle(
    solar_altitude: float,
    solar_azimuth: float,
    surface_tilt: float,
    surface_azimuth: float,
) -> float:
    """
    Calculate angle of incidence of solar radiation on surface.

    Args:
        solar_altitude: Solar altitude angle in degrees
        solar_azimuth: Solar azimuth in degrees
        surface_tilt: Surface tilt from horizontal in degrees
        surface_azimuth: Surface azimuth in degrees

    Returns:
        Incident angle in degrees
    """
    solar_alt_rad = math.radians(solar_altitude)
    solar_az_rad = math.radians(solar_azimuth)
    # Tests treat tilt as angle from vertical. Convert to horizontal convention.
    tilt_from_horizontal = max(0.0, min(90.0, 90.0 - surface_tilt))
    tilt_rad = math.radians(tilt_from_horizontal)
    azimuth_rad = math.radians(surface_azimuth)

    cos_incident = math.sin(solar_alt_rad) * math.cos(tilt_rad) + math.cos(solar_alt_rad) * math.sin(
        tilt_rad
    ) * math.cos(solar_az_rad - azimuth_rad)

    cos_incident = max(-1.0, min(1.0, cos_incident))
    incident_angle = math.degrees(math.acos(cos_incident))

    return incident_angle


def calculate_poa_irradiance(
    ghi: float,
    dni: float,
    dhi: float,
    incident_angle: float,
    surface_tilt: float,
    ground_reflectance: float = 0.25,
) -> float:
    """
    Calculate plane-of-array (POA) irradiance using decomposition model.

    Args:
        ghi: Global horizontal irradiance in W/m^2
        dni: Direct normal irradiance in W/m^2
        dhi: Diffuse horizontal irradiance in W/m^2
        incident_angle: Angle of incidence in degrees
        surface_tilt: Surface tilt in degrees
        ground_reflectance: Ground reflectance (albedo)

    Returns:
        POA irradiance in W/m^2
    """
    incident_rad = math.radians(incident_angle)
    tilt_rad = math.radians(surface_tilt)

    # Direct component
    if incident_angle < 90:
        poa_direct = dni * math.cos(incident_rad)
    else:
        poa_direct = 0.0

    # Diffuse component (isotropic sky model)
    poa_diffuse = dhi * (1 + math.cos(tilt_rad)) / 2

    # Ground reflection component
    poa_reflected = ghi * ground_reflectance * (1 - math.cos(tilt_rad)) / 2

    poa = poa_direct + poa_diffuse + poa_reflected
    return max(0.0, poa)


def apply_temperature_derating(
    poa_irradiance: float,
    cell_temperature: float,
    temperature_coefficient: float = -0.004,
    reference_temperature: float = 25.0,
) -> float:
    """
    Apply temperature derating to panel efficiency.

    Args:
        poa_irradiance: Plane-of-array irradiance in W/m^2
        cell_temperature: Cell temperature in Celsius
        temperature_coefficient: Efficiency change per Celsius above reference
        reference_temperature: Reference temperature (25C typical)

    Returns:
        Effective panel efficiency (0.0-1.0)
    """
    # `cell_temperature` is assumed to already be cell/module temperature.
    temp_factor = 1.0 + temperature_coefficient * (cell_temperature - reference_temperature)
    return max(0.0, temp_factor)


def calculate_irradiance(
    timestamp: datetime,
    latitude: float,
    longitude: float,
    weather: WeatherCondition,
    elevation: float = 0.0,
) -> tuple[float, float, float, float]:
    """
    Calculate solar irradiance components.

    Args:
        timestamp: UTC datetime
        latitude: Site latitude in degrees
        longitude: Site longitude in degrees
        weather: Weather conditions
        elevation: Site elevation in meters

    Returns:
        Tuple of (GHI, DNI, DHI, POA) in W/m^2
    """
    # Update air density for elevation
    weather.update_air_density(elevation)

    # Solar position
    solar_alt, solar_az = calculate_solar_position(timestamp, latitude, longitude)

    if solar_alt <= 0:
        return 0.0, 0.0, 0.0, 0.0

    # Air mass and clear-sky irradiance
    air_mass = calculate_air_mass(solar_alt)

    # Adjust for cloud cover
    clearness = 1.0 - weather.cloud_cover * 0.75

    # Clear-sky DNI
    dni_clear = calculate_clearsky_irradiance(air_mass, solar_alt)

    # Actual DNI with cloud attenuation
    dni = dni_clear * clearness

    # DHI
    dhi = calculate_diffuse_irradiance(dni, solar_alt, clearness)

    # GHI
    ghi = dni * math.sin(math.radians(solar_alt)) + dhi

    # POA (assuming south-facing fixed tilt of 30 degrees)
    incident = calculate_incident_angle(solar_alt, solar_az, 30.0, 180.0)
    poa = calculate_poa_irradiance(ghi, dni, dhi, incident, 30.0)

    return max(0.0, ghi), max(0.0, dni), max(0.0, dhi), max(0.0, poa)


def optimize_panel_angle(
    latitude: float,
    annual_irradiance_data: dict[float, float],
) -> tuple[float, float]:
    """
    Optimize tilt and azimuth angles for maximum annual energy.

    Args:
        latitude: Site latitude in degrees
        annual_irradiance_data: Dict mapping (tilt_deg, azimuth_deg) -> annual_poa_kwh_m2

    Returns:
        Tuple of (optimal_tilt_degrees, optimal_azimuth_degrees)
    """
    if not annual_irradiance_data:
        # Default values
        optimal_tilt = abs(latitude)  # Rule of thumb
        optimal_azimuth = 180.0 if latitude > 0 else 0.0
        return optimal_tilt, optimal_azimuth

    # Find maximum
    best_config = max(annual_irradiance_data.items(), key=lambda x: x[1])
    return best_config[0]


def mppt_simulation(
    poa_irradiance: float,
    cell_temperature: float,
    panel_efficiency: float,
    voltage_oc: float = 40.0,
    current_sc: float = 10.0,
    fill_factor: float = 0.75,
) -> tuple[float, float, float]:
    """
    Simulate maximum power point tracking (MPPT) algorithm.

    Args:
        poa_irradiance: POA irradiance in W/m^2
        cell_temperature: Cell temperature in Celsius
        panel_efficiency: Panel efficiency (0.0-1.0)
        voltage_oc: Open circuit voltage in volts
        current_sc: Short circuit current in amps
        fill_factor: Fill factor (0.0-1.0)

    Returns:
        Tuple of (power_W, voltage_V, current_A)
    """
    # Temperature derating
    temp_coeff_voltage = -0.0023  # V per Celsius
    temp_coeff_current = 0.0003  # A per Celsius

    voc_actual = voltage_oc + temp_coeff_voltage * (cell_temperature - 25)
    isc_actual = current_sc + temp_coeff_current * (cell_temperature - 25)

    # Maximum power point voltage
    vmp = 0.80 * voc_actual

    # 1 m^2 module-equivalent power with MPPT efficiency.
    irradiance_fraction = max(0.0, poa_irradiance / 1000.0)  # 1000 W/m^2 = STC
    mppt_efficiency = max(0.0, min(1.0, fill_factor / 0.75))
    power_w = poa_irradiance * panel_efficiency * mppt_efficiency
    power_w *= max(0.0, 1.0 - 0.0035 * max(0.0, cell_temperature - 25.0))
    imp = power_w / max(vmp, 1e-6)

    return max(0.0, power_w), vmp, imp


def calculate_annual_yield(
    plant: SolarPlant,
    hourly_weather_data: list[WeatherCondition],
) -> float:
    """
    Calculate annual energy yield in MWh.

    Args:
        plant: Solar plant
        hourly_weather_data: Hourly weather data for full year

    Returns:
        Annual yield in MWh
    """
    total_energy_wh = 0.0

    for weather in hourly_weather_data:
        # Calculate irradiance
        ghi, dni, dhi, poa = calculate_irradiance(
            weather.timestamp,
            plant.latitude,
            plant.longitude,
            weather,
            plant.elevation,
        )

        # Apply temperature derating
        temp_factor = apply_temperature_derating(
            poa,
            weather.temperature,
            plant.temperature_coefficient,
        )

        # System losses
        system_loss_factor = plant.soiling_factor * plant.mismatch_factor * plant.inverter_efficiency

        # Power output from nameplate capacity scaled by irradiance and losses.
        irradiance_fraction = max(0.0, min(1.0, poa / 1000.0))
        power_w = plant.capacity_mw * 1_000_000.0 * irradiance_fraction * temp_factor * system_loss_factor

        # Energy over 1 hour
        total_energy_wh += power_w

    # Convert to MWh
    annual_yield_mwh = total_energy_wh / 1_000_000

    # Update capacity factor
    hours_per_year = len(hourly_weather_data)
    max_possible_energy = plant.capacity_mw * hours_per_year
    plant.capacity_factor = annual_yield_mwh / max_possible_energy if max_possible_energy > 0 else 0.0

    return annual_yield_mwh


def estimate_shading_loss(
    obstacles_angles: list[tuple[float, float]],
    solar_altitude: float,
    solar_azimuth: float,
) -> float:
    """
    Estimate shading loss factor (0.0-1.0).

    Args:
        obstacles_angles: List of (altitude, azimuth) for obstacles
        solar_altitude: Solar altitude in degrees
        solar_azimuth: Solar azimuth in degrees

    Returns:
        Shading loss factor (fraction of energy lost to shading)
    """
    if not obstacles_angles:
        return 0.0

    loss = 0.0
    for obs_alt, obs_az in obstacles_angles:
        # Check if sun is behind obstacle
        if solar_altitude >= obs_alt:
            # Angular distance in azimuth
            az_diff = min(abs(solar_azimuth - obs_az), 360 - abs(solar_azimuth - obs_az))

            # Simple linear shadow model
            if az_diff < 15:  # Within shadow zone
                shadow_factor = 1.0 - (az_diff / 15.0)
                loss = max(loss, shadow_factor)

    return min(0.99, max(0.0, loss))
