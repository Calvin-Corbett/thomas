"""Tests for climate control."""

import pytest

from thomas.marketplace.smart_home._exceptions import ClimateError
from thomas.marketplace.smart_home.climate import ThermostatScheduler


class TestThermostatScheduler:
    """Test ThermostatScheduler functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.scheduler = ThermostatScheduler()

    def test_create_zone(self):
        """Test creating a climate zone."""
        zone = self.scheduler.create_zone("living_room", ["thermostat1", "sensor1"])

        assert zone.zone_id == "living_room"
        assert zone.current_temp == 20.0
        assert zone.target_temp == 21.0

    def test_get_zone(self):
        """Test retrieving a zone."""
        self.scheduler.create_zone("zone1", [])

        zone = self.scheduler.get_zone("zone1")

        assert zone.zone_id == "zone1"

    def test_get_nonexistent_zone(self):
        """Test getting non-existent zone raises error."""
        with pytest.raises(ClimateError):
            self.scheduler.get_zone("nonexistent")

    def test_set_target_temperature(self):
        """Test setting target temperature."""
        self.scheduler.create_zone("zone1", [])

        self.scheduler.set_target_temperature("zone1", 22.0)

        zone = self.scheduler.get_zone("zone1")
        assert zone.target_temp == 22.0

    def test_set_target_temperature_clamping(self):
        """Test temperature clamping to valid range."""
        self.scheduler.create_zone("zone1", [])

        # Too high
        self.scheduler.set_target_temperature("zone1", 50.0)
        zone = self.scheduler.get_zone("zone1")
        assert zone.target_temp <= 30.0

        # Too low
        self.scheduler.set_target_temperature("zone1", 5.0)
        zone = self.scheduler.get_zone("zone1")
        assert zone.target_temp >= 15.0

    def test_set_current_temperature(self):
        """Test updating current temperature."""
        self.scheduler.create_zone("zone1", [])

        self.scheduler.set_current_temperature("zone1", 18.5)

        zone = self.scheduler.get_zone("zone1")
        assert zone.current_temp == 18.5

    def test_set_target_humidity(self):
        """Test setting target humidity."""
        self.scheduler.create_zone("zone1", [])

        self.scheduler.set_target_humidity("zone1", 55.0)

        zone = self.scheduler.get_zone("zone1")
        assert zone.target_humidity == 55.0

    def test_set_current_humidity(self):
        """Test updating current humidity."""
        self.scheduler.create_zone("zone1", [])

        self.scheduler.set_current_humidity("zone1", 45.0)

        zone = self.scheduler.get_zone("zone1")
        assert zone.humidity == 45.0

    def test_optimize_multi_zone_heating(self):
        """Test multi-zone heating optimization."""
        self.scheduler.create_zone("zone1", [])
        self.scheduler.create_zone("zone2", [])

        # Set up zones needing heat
        self.scheduler.set_current_temperature("zone1", 19.0)
        self.scheduler.set_target_temperature("zone1", 22.0)

        self.scheduler.set_current_temperature("zone2", 18.0)
        self.scheduler.set_target_temperature("zone2", 22.0)

        results = self.scheduler.optimize_multi_zone()

        assert results["zone1"]["heating"] is True
        assert results["zone2"]["heating"] is True

    def test_optimize_multi_zone_cooling(self):
        """Test multi-zone cooling optimization."""
        self.scheduler.create_zone("zone1", [])

        self.scheduler.set_current_temperature("zone1", 25.0)
        self.scheduler.set_target_temperature("zone1", 21.0)

        results = self.scheduler.optimize_multi_zone()

        assert results["zone1"]["cooling"] is True
        assert results["zone1"]["heating"] is False

    def test_predict_temperature(self):
        """Test temperature prediction."""
        self.scheduler.create_zone("zone1", [])

        self.scheduler.set_current_temperature("zone1", 20.0)
        self.scheduler.set_target_temperature("zone1", 22.0)

        # Predict 30 minutes ahead
        predicted = self.scheduler.predict_temperature("zone1", 30)

        # Should be closer to target but not fully reached
        assert 20.0 < predicted < 22.0

    def test_estimate_time_to_target(self):
        """Test time to target estimation."""
        self.scheduler.create_zone("zone1", [])

        self.scheduler.set_current_temperature("zone1", 20.0)
        self.scheduler.set_target_temperature("zone1", 25.0)

        time_to_target = self.scheduler.estimate_time_to_target("zone1")

        assert time_to_target > 0
        assert isinstance(time_to_target, float)

    def test_comfort_mode(self):
        """Test comfort mode."""
        self.scheduler.create_zone("zone1", [])

        self.scheduler.set_comfort_mode("zone1")

        zone = self.scheduler.get_zone("zone1")
        assert zone.target_temp == 21.0  # Comfort temp

    def test_economy_mode(self):
        """Test economy mode."""
        self.scheduler.create_zone("zone1", [])

        self.scheduler.set_economy_mode("zone1")

        zone = self.scheduler.get_zone("zone1")
        assert zone.target_temp == 18.0  # Economy temp

    def test_set_ventilation(self):
        """Test ventilation control."""
        self.scheduler.create_zone("zone1", [])

        self.scheduler.set_ventilation("zone1", 75)

        zone = self.scheduler.get_zone("zone1")
        assert zone.ventilation_level == 75

    def test_humidity_control_humidify(self):
        """Test humidity control - humidifying."""
        self.scheduler.create_zone("zone1", [])

        self.scheduler.set_current_humidity("zone1", 30.0)

        action = self.scheduler.control_humidity("zone1", 50.0)

        assert action["humidify"] is True
        assert action["dehumidify"] is False

    def test_humidity_control_dehumidify(self):
        """Test humidity control - dehumidifying."""
        self.scheduler.create_zone("zone1", [])

        self.scheduler.set_current_humidity("zone1", 70.0)

        action = self.scheduler.control_humidity("zone1", 50.0)

        assert action["humidify"] is False
        assert action["dehumidify"] is True

    def test_pre_heat_cool(self):
        """Test pre-heating."""
        from datetime import time

        self.scheduler.create_zone("zone1", [])

        self.scheduler.set_current_temperature("zone1", 18.0)
        self.scheduler.set_target_temperature("zone1", 21.0)

        target_time = time(8, 0)
        self.scheduler.pre_heat_cool("zone1", target_time)

        zone = self.scheduler.get_zone("zone1")
        # Target should be adjusted for pre-heating
        assert zone.target_temp != 21.0

    def test_weather_adjusted_schedule(self):
        """Test weather-adjusted schedule."""
        self.scheduler.create_zone("zone1", [])

        # Hot weather
        self.scheduler.update_weather(outdoor_temp=30.0)

        schedule = self.scheduler.weather_adjusted_schedule("zone1")

        assert schedule["adjusted_temp"] < schedule["base_temp"]

    def test_get_system_status(self):
        """Test system status reporting."""
        self.scheduler.create_zone("zone1", [])
        self.scheduler.create_zone("zone2", [])

        self.scheduler.set_current_temperature("zone1", 20.0)
        self.scheduler.set_target_temperature("zone1", 22.0)

        status = self.scheduler.get_system_status()

        assert "zones" in status
        assert "zone1" in status["zones"]
        assert status["zones"]["zone1"]["current"] == 20.0
        assert status["zones"]["zone1"]["target"] == 22.0

    def test_energy_efficiency_score(self):
        """Test efficiency score calculation."""
        self.scheduler.create_zone("zone1", [])

        self.scheduler.set_current_temperature("zone1", 21.0)
        self.scheduler.set_target_temperature("zone1", 21.0)

        score = self.scheduler.get_energy_efficiency_score("zone1")

        assert 0 <= score <= 100
        assert score > 50  # Efficient state

    def test_thermal_model_solar_gain(self):
        """Test thermal model with solar gain."""
        self.scheduler.create_zone("zone1", [])

        self.scheduler.set_current_temperature("zone1", 20.0)
        self.scheduler.set_target_temperature("zone1", 21.0)

        # High solar irradiance
        self.scheduler.update_weather(outdoor_temp=15.0, solar_irradiance=800)

        predicted = self.scheduler.predict_temperature("zone1", 30)

        # Solar gain should help reach target faster
        model = self.scheduler._thermal_models["zone1"]
        assert model.solar_gain > 0

    def test_multiple_zones_independence(self):
        """Test that zones are independent."""
        self.scheduler.create_zone("zone1", [])
        self.scheduler.create_zone("zone2", [])

        self.scheduler.set_current_temperature("zone1", 20.0)
        self.scheduler.set_target_temperature("zone1", 25.0)

        self.scheduler.set_current_temperature("zone2", 20.0)
        self.scheduler.set_target_temperature("zone2", 18.0)

        zone1 = self.scheduler.get_zone("zone1")
        zone2 = self.scheduler.get_zone("zone2")

        assert zone1.target_temp == 25.0
        assert zone2.target_temp == 18.0
