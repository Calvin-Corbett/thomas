"""
Tests for solar energy module.
"""

import math
from datetime import datetime, timedelta

from thomas.energy._types import EnergySource, WeatherCondition
from thomas.energy.solar import (
    SolarPlant,
    apply_temperature_derating,
    calculate_air_mass,
    calculate_annual_yield,
    calculate_clearsky_irradiance,
    calculate_diffuse_irradiance,
    calculate_incident_angle,
    calculate_irradiance,
    calculate_poa_irradiance,
    calculate_solar_position,
    estimate_shading_loss,
    mppt_simulation,
    optimize_panel_angle,
)


class TestSolarPosition:
    """Test solar position calculations."""

    def test_solar_position_noon(self):
        """Test solar position at solar noon."""
        timestamp = datetime(2023, 3, 21, 12, 0, 0)  # Vernal equinox noon
        latitude = 40.0
        longitude = -105.0

        altitude, azimuth = calculate_solar_position(timestamp, latitude, longitude)

        # At equinox, solar altitude should be ~90 - latitude at solar noon
        assert altitude > 40
        assert 170 < azimuth < 190  # Roughly south

    def test_solar_position_night(self):
        """Test solar position at night."""
        timestamp = datetime(2023, 1, 1, 0, 0, 0)  # Midnight
        latitude = 40.0
        longitude = -105.0

        altitude, azimuth = calculate_solar_position(timestamp, latitude, longitude)

        # Sun below horizon
        assert altitude < 0


class TestAirMass:
    """Test air mass calculations."""

    def test_air_mass_zenith(self):
        """Test air mass at zenith."""
        am = calculate_air_mass(90.0)
        assert abs(am - 1.0) < 0.01

    def test_air_mass_horizon(self):
        """Test air mass at horizon."""
        am = calculate_air_mass(0.0)
        assert am > 35.0  # Very large air mass

    def test_air_mass_45_degrees(self):
        """Test air mass at 45 degrees."""
        am = calculate_air_mass(45.0)
        assert 1.4 < am < 1.5


class TestClearSkyIrradiance:
    """Test clear-sky irradiance calculations."""

    def test_clearsky_at_zenith(self):
        """Test clear-sky irradiance at solar zenith."""
        air_mass = 1.0
        solar_alt = 90.0

        dni = calculate_clearsky_irradiance(air_mass, solar_alt)

        # Should be near 950 W/m^2 (extraterrestrial)
        assert 900 < dni < 1000

    def test_clearsky_at_horizon(self):
        """Test clear-sky irradiance at horizon."""
        solar_alt = 0.0
        dni = calculate_clearsky_irradiance(100.0, solar_alt)

        assert dni == 0.0

    def test_clearsky_night(self):
        """Test clear-sky irradiance at night."""
        air_mass = 1.0
        solar_alt = -10.0

        dni = calculate_clearsky_irradiance(air_mass, solar_alt)

        assert dni == 0.0


class TestDiffuseIrradiance:
    """Test diffuse irradiance calculations."""

    def test_diffuse_clear_sky(self):
        """Test diffuse with clear sky."""
        dni = 800.0
        solar_alt = 60.0
        clearness = 0.9

        dhi = calculate_diffuse_irradiance(dni, solar_alt, clearness)

        assert dhi > 0
        assert dhi < 100  # Should be small for clear sky

    def test_diffuse_cloudy(self):
        """Test diffuse with cloudy conditions."""
        dni = 200.0  # Reduced by clouds
        solar_alt = 45.0
        clearness = 0.3

        dhi = calculate_diffuse_irradiance(dni, solar_alt, clearness)

        assert dhi > 0

    def test_diffuse_night(self):
        """Test diffuse at night."""
        solar_alt = -10.0
        dhi = calculate_diffuse_irradiance(0.0, solar_alt, 0.5)

        assert dhi == 0.0


class TestIncidentAngle:
    """Test incident angle calculations."""

    def test_incident_angle_perpendicular(self):
        """Test incident angle when sun perpendicular to surface."""
        solar_alt = 30.0
        solar_az = 180.0  # South
        surface_tilt = 30.0
        surface_az = 180.0  # South-facing

        incident = calculate_incident_angle(solar_alt, solar_az, surface_tilt, surface_az)

        # Should be approximately zero
        assert incident < 5.0

    def test_incident_angle_parallel(self):
        """Test incident angle when sun parallel to surface."""
        solar_alt = 0.0  # Horizon
        solar_az = 180.0
        surface_tilt = 90.0  # Vertical
        surface_az = 0.0  # North-facing

        incident = calculate_incident_angle(solar_alt, solar_az, surface_tilt, surface_az)

        # Should be approximately 90 degrees
        assert incident > 80.0


class TestPOAIrradiance:
    """Test plane-of-array irradiance calculations."""

    def test_poa_direct_component(self):
        """Test POA with direct component."""
        ghi = 800.0
        dni = 750.0
        dhi = 100.0
        incident = 20.0  # 20 degrees
        tilt = 30.0

        poa = calculate_poa_irradiance(ghi, dni, dhi, incident, tilt)

        assert poa > 0
        assert poa > dhi  # POA should exceed DHI with direct component

    def test_poa_grazing_angle(self):
        """Test POA at high incident angle."""
        ghi = 800.0
        dni = 750.0
        dhi = 100.0
        incident = 85.0  # Nearly parallel
        tilt = 30.0

        poa = calculate_poa_irradiance(ghi, dni, dhi, incident, tilt)

        # Should approach DHI component only
        assert poa < 200.0


class TestTemperatureDerating:
    """Test temperature derating."""

    def test_temp_derating_25c(self):
        """Test derating at reference temperature."""
        poa = 800.0
        cell_temp = 25.0

        factor = apply_temperature_derating(poa, cell_temp)

        # Should be near 1.0
        assert abs(factor - 1.0) < 0.05

    def test_temp_derating_cold(self):
        """Test derating at cold temperature."""
        poa = 800.0
        cell_temp = 0.0
        coeff = -0.004

        factor = apply_temperature_derating(poa, cell_temp, coeff)

        # Cold temps improve efficiency
        assert factor > 1.0

    def test_temp_derating_hot(self):
        """Test derating at hot temperature."""
        poa = 800.0
        cell_temp = 60.0
        coeff = -0.004

        factor = apply_temperature_derating(poa, cell_temp, coeff)

        # Hot temps reduce efficiency
        assert factor < 1.0


class TestFullIrradianceCalculation:
    """Test complete irradiance calculation."""

    def test_irradiance_calculation_day(self):
        """Test irradiance calculation during daytime."""
        timestamp = datetime(2023, 6, 21, 12, 0, 0)  # Summer solstice noon
        latitude = 40.0
        longitude = -105.0

        weather = WeatherCondition(
            timestamp=timestamp,
            temperature=25.0,
            wind_speed=3.0,
            wind_direction=180.0,
            solar_irradiance=800.0,
            cloud_cover=0.2,
            humidity=0.5,
            precipitation=0.0,
        )

        ghi, dni, dhi, poa = calculate_irradiance(timestamp, latitude, longitude, weather)

        # Should have significant irradiance
        assert ghi > 500
        assert dni > 500
        assert dhi > 0
        assert poa > 500

    def test_irradiance_calculation_night(self):
        """Test irradiance calculation at night."""
        timestamp = datetime(2023, 1, 1, 0, 0, 0)
        latitude = 40.0
        longitude = -105.0

        weather = WeatherCondition(
            timestamp=timestamp,
            temperature=0.0,
            wind_speed=5.0,
            wind_direction=0.0,
            solar_irradiance=0.0,
            cloud_cover=0.5,
            humidity=0.7,
            precipitation=0.0,
        )

        ghi, dni, dhi, poa = calculate_irradiance(timestamp, latitude, longitude, weather)

        assert ghi == 0.0
        assert dni == 0.0
        assert dhi == 0.0
        assert poa == 0.0


class TestPanelOptimization:
    """Test panel angle optimization."""

    def test_optimize_tilt_angle(self):
        """Test tilt angle optimization."""
        latitude = 40.0
        annual_data = {
            (10.0, 180.0): 1200,
            (30.0, 180.0): 1500,  # Optimal
            (50.0, 180.0): 1300,
            (70.0, 180.0): 1000,
        }

        tilt, azimuth = optimize_panel_angle(latitude, annual_data)

        assert tilt == 30.0
        assert azimuth == 180.0


class TestMPPT:
    """Test MPPT simulation."""

    def test_mppt_high_irradiance(self):
        """Test MPPT at high irradiance."""
        poa = 1000.0
        cell_temp = 45.0
        panel_efficiency = 0.20

        power_w, voltage, current = mppt_simulation(poa, cell_temp, panel_efficiency)

        assert power_w > 150  # At least 150W for 1m^2
        assert voltage > 30
        assert current > 0

    def test_mppt_low_irradiance(self):
        """Test MPPT at low irradiance."""
        poa = 100.0
        cell_temp = 25.0
        panel_efficiency = 0.20

        power_w, voltage, current = mppt_simulation(poa, cell_temp, panel_efficiency)

        assert power_w < 25  # Much lower power
        assert power_w > 0


class TestAnnualYield:
    """Test annual yield calculation."""

    def test_annual_yield_calculation(self):
        """Test annual yield calculation with synthetic data."""
        plant = SolarPlant(
            plant_id="solar_1",
            fuel_type=EnergySource.SOLAR,
            capacity_mw=1.0,
            latitude=40.0,
            longitude=-105.0,
            panel_count=500,
            panel_efficiency=0.20,
        )

        # Create synthetic hourly weather data
        weather_data = []
        for day in range(365):
            for hour in range(24):
                timestamp = datetime(2023, 1, 1) + timedelta(days=day, hours=hour)
                # Simple model: irradiance follows sinusoidal pattern
                hour_of_day = (hour - 6) / 12.0
                if 0 < hour_of_day < 2:
                    irradiance = 800 * math.sin(hour_of_day * math.pi / 2)
                else:
                    irradiance = 0.0

                weather = WeatherCondition(
                    timestamp=timestamp,
                    temperature=15.0 + 15 * math.sin(2 * math.pi * day / 365),
                    wind_speed=5.0,
                    wind_direction=180.0,
                    solar_irradiance=irradiance,
                    cloud_cover=0.2,
                    humidity=0.5,
                    precipitation=0.0,
                )
                weather_data.append(weather)

        annual_yield = calculate_annual_yield(plant, weather_data)

        # Should be reasonable for a 1MW solar plant
        assert annual_yield > 1000  # MWh
        assert annual_yield < 3000  # MWh


class TestShadingLoss:
    """Test shading loss estimation."""

    def test_no_obstacles(self):
        """Test with no obstacles."""
        obstacles = []
        solar_alt = 45.0
        solar_az = 180.0

        loss = estimate_shading_loss(obstacles, solar_alt, solar_az)

        assert loss == 0.0

    def test_shading_with_obstacle(self):
        """Test shading from obstacle."""
        obstacles = [(45.0, 180.0)]  # Obstacle at same position
        solar_alt = 45.0
        solar_az = 180.0

        loss = estimate_shading_loss(obstacles, solar_alt, solar_az)

        assert loss > 0.0
        assert loss < 1.0


class TestSolarPlant:
    """Test SolarPlant class."""

    def test_solar_plant_creation(self):
        """Test solar plant instantiation."""
        plant = SolarPlant(
            plant_id="solar_1",
            fuel_type=EnergySource.SOLAR,
            capacity_mw=10.0,
            latitude=40.0,
            longitude=-105.0,
            panel_count=5000,
            panel_efficiency=0.20,
        )

        assert plant.plant_id == "solar_1"
        assert plant.fuel_type == EnergySource.SOLAR
        assert plant.capacity_mw == 10.0

    def test_solar_plant_fuel_type_override(self):
        """Test that fuel type is set to SOLAR."""
        plant = SolarPlant(
            plant_id="solar_1",
            fuel_type=EnergySource.COAL,  # This should be overridden
            capacity_mw=10.0,
            latitude=40.0,
            longitude=-105.0,
        )

        assert plant.fuel_type == EnergySource.SOLAR
