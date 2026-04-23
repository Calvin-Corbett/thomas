"""Tests for lighting control."""

import pytest

from thomas.marketplace.smart_home._exceptions import LightingError
from thomas.marketplace.smart_home.lighting import HSLColor, LightingController, RGBColor


class TestLightingController:
    """Test LightingController functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.controller = LightingController()

    def test_register_light(self):
        """Test light registration."""
        light = self.controller.register_light("light1")

        assert light.light_id == "light1"
        assert light.on is False

    def test_turn_on_light(self):
        """Test turning on a light."""
        self.controller.register_light("light1")

        self.controller.turn_on("light1")

        light = self.controller.get_light("light1")
        assert light.on is True
        assert light.brightness == 255

    def test_turn_on_with_brightness(self):
        """Test turning on with specific brightness."""
        self.controller.register_light("light1")

        self.controller.turn_on("light1", brightness=150)

        light = self.controller.get_light("light1")
        assert light.brightness == 150

    def test_turn_off_light(self):
        """Test turning off a light."""
        self.controller.register_light("light1")

        self.controller.turn_on("light1")
        self.controller.turn_off("light1")

        light = self.controller.get_light("light1")
        assert light.on is False
        assert light.brightness == 0

    def test_set_brightness(self):
        """Test setting brightness."""
        self.controller.register_light("light1")

        self.controller.set_brightness("light1", 100)

        light = self.controller.get_light("light1")
        assert light.brightness == 100
        assert light.on is True

    def test_brightness_clamping(self):
        """Test brightness clamping to valid range."""
        self.controller.register_light("light1")

        # Too high
        self.controller.set_brightness("light1", 300)
        light = self.controller.get_light("light1")
        assert light.brightness <= 255

        # Too low
        self.controller.set_brightness("light1", -10)
        light = self.controller.get_light("light1")
        assert light.brightness >= 0

    def test_set_color_temperature(self):
        """Test setting color temperature."""
        self.controller.register_light("light1")

        self.controller.set_color_temperature("light1", 3000)

        light = self.controller.get_light("light1")
        assert light.color_temp_kelvin == 3000

    def test_set_rgb_color(self):
        """Test setting RGB color."""
        self.controller.register_light("light1")

        self.controller.set_rgb_color("light1", 255, 128, 0)

        light = self.controller.get_light("light1")
        assert light.rgb.red == 255
        assert light.rgb.green == 128
        assert light.rgb.blue == 0

    def test_set_xy_color(self):
        """Test setting CIE xy color."""
        self.controller.register_light("light1")

        self.controller.set_xy_color("light1", 0.5, 0.4)

        light = self.controller.get_light("light1")
        assert light.xy == (0.5, 0.4)

    def test_rgb_to_hsl_conversion(self):
        """Test RGB to HSL conversion."""
        # Red
        rgb = RGBColor(red=255, green=0, blue=0)
        hsl = self.controller.rgb_to_hsl(rgb)

        assert 0 <= hsl.hue <= 360
        assert 0 <= hsl.saturation <= 100
        assert 0 <= hsl.lightness <= 100

    def test_hsl_to_rgb_conversion(self):
        """Test HSL to RGB conversion."""
        hsl = HSLColor(hue=0, saturation=100, lightness=50)
        rgb = self.controller.hsl_to_rgb(hsl)

        assert 0 <= rgb.red <= 255
        assert 0 <= rgb.green <= 255
        assert 0 <= rgb.blue <= 255

    def test_color_conversion_roundtrip(self):
        """Test RGB -> HSL -> RGB roundtrip."""
        original = RGBColor(red=100, green=150, blue=200)

        hsl = self.controller.rgb_to_hsl(original)
        converted = self.controller.hsl_to_rgb(hsl)

        # Should be close (allowing for rounding)
        assert abs(converted.red - original.red) <= 1
        assert abs(converted.green - original.green) <= 1
        assert abs(converted.blue - original.blue) <= 1

    def test_kelvin_to_rgb_conversion(self):
        """Test color temperature to RGB conversion."""
        # Warm light
        warm = self.controller.kelvin_to_rgb(3000)
        assert warm.red > warm.blue

        # Cool light
        cool = self.controller.kelvin_to_rgb(6000)
        assert cool.red <= cool.blue or cool.red == cool.green

    def test_enable_circadian_rhythm(self):
        """Test enabling circadian rhythm."""
        self.controller.register_light("light1")

        self.controller.enable_circadian_rhythm("light1")

        assert self.controller._circadian_enabled.get("light1") is True

    def test_circadian_temperature_schedule(self):
        """Test circadian temperature variations."""
        morning_temp = self.controller.get_circadian_temperature(hour=7)
        day_temp = self.controller.get_circadian_temperature(hour=12)
        evening_temp = self.controller.get_circadian_temperature(hour=20)
        night_temp = self.controller.get_circadian_temperature(hour=2)

        # Morning should be warmer than night
        assert morning_temp > night_temp
        # Day should be cooler than evening
        assert day_temp > evening_temp

    def test_light_group_creation(self):
        """Test creating light groups."""
        self.controller.register_light("light1")
        self.controller.register_light("light2")
        self.controller.register_light("light3")

        self.controller.create_group("living_room", ["light1", "light2", "light3"])

        lights = self.controller.get_lights_in_group("living_room")
        assert len(lights) == 3

    def test_group_brightness_control(self):
        """Test controlling brightness for group."""
        self.controller.register_light("light1")
        self.controller.register_light("light2")

        self.controller.create_group("group1", ["light1", "light2"])

        self.controller.set_group_brightness("group1", 100)

        light1 = self.controller.get_light("light1")
        light2 = self.controller.get_light("light2")

        assert light1.brightness == 100
        assert light2.brightness == 100

    def test_motion_activate_light(self):
        """Test motion-activated lighting."""
        self.controller.register_light("light1")

        self.controller.motion_activate_light("light1", brightness=180)

        light = self.controller.get_light("light1")
        assert light.on is True
        assert light.brightness == 180

    def test_daylight_harvesting(self):
        """Test daylight harvesting."""
        self.controller.register_light("light1")

        # Bright daylight
        self.controller.daylight_harvest("light1", ambient_lux=500)

        light = self.controller.get_light("light1")
        # Brightness should be reduced
        assert light.brightness < 255

    def test_transition_light(self):
        """Test light transition."""
        self.controller.register_light("light1")

        self.controller.transition_light("light1", target_brightness=50, target_temp=3000, duration_ms=1000)

        light = self.controller.get_light("light1")
        assert light.brightness == 50
        assert light.color_temp_kelvin == 3000

    def test_color_interpolation(self):
        """Test color interpolation."""
        rgb1 = RGBColor(red=0, green=0, blue=0)
        rgb2 = RGBColor(red=255, green=255, blue=255)

        # Midpoint
        mid = self.controller.interpolate_color(rgb1, rgb2, 0.5)

        assert 100 < mid.red < 150
        assert 100 < mid.green < 150
        assert 100 < mid.blue < 150

    def test_get_all_lights(self):
        """Test getting all lights."""
        for i in range(5):
            self.controller.register_light(f"light{i}")

        all_lights = self.controller.get_all_lights()

        assert len(all_lights) == 5

    def test_invalid_light_access(self):
        """Test accessing invalid light."""
        with pytest.raises(LightingError):
            self.controller.get_light("nonexistent")

    def test_invalid_group_access(self):
        """Test accessing invalid group."""
        with pytest.raises(LightingError):
            self.controller.get_lights_in_group("nonexistent")

    def test_set_circadian_temperature(self):
        """Test setting circadian temperature."""
        self.controller.register_light("light1")

        self.controller.set_circadian_temperature("light1", hour=6)

        light = self.controller.get_light("light1")
        assert light.color_temp_kelvin > 0

    def test_xy_to_rgb_conversion(self):
        """Test CIE xy to RGB conversion."""
        rgb = self.controller.xy_to_rgb(0.5, 0.4, brightness=200)

        assert 0 <= rgb.red <= 255
        assert 0 <= rgb.green <= 255
        assert 0 <= rgb.blue <= 255
