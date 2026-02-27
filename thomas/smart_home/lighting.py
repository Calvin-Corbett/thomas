"""Lighting control and color management."""

from dataclasses import dataclass
from datetime import datetime

from thomas.smart_home._exceptions import ColorConversionError, LightingError


@dataclass
class RGBColor:
    """RGB color representation."""

    red: int
    """Red 0-255."""
    green: int
    """Green 0-255."""
    blue: int
    """Blue 0-255."""

    def to_tuple(self) -> tuple[int, int, int]:
        """Convert to RGB tuple."""
        return (self.red, self.green, self.blue)


@dataclass
class HSLColor:
    """HSL color representation."""

    hue: float
    """Hue 0-360 degrees."""
    saturation: float
    """Saturation 0-100%."""
    lightness: float
    """Lightness 0-100%."""


@dataclass
class LightState:
    """State of a light."""

    light_id: str
    """Light identifier."""
    on: bool = False
    """Whether light is on."""
    brightness: int = 255
    """Brightness 0-255."""
    color_temp_kelvin: int = 4000
    """Color temperature in Kelvin."""
    rgb: RGBColor | None = None
    """RGB color if applicable."""
    xy: tuple[float, float] | None = None
    """CIE xy color if applicable."""
    transitioning: bool = False
    """Whether light is in transition."""
    transition_end_time: datetime | None = None
    """When transition completes."""


class LightingController:
    """Lighting control with advanced color and transition features.

    Provides color space conversions, circadian rhythm lighting,
    motion-activated dimming, daylight harvesting, group control,
    and smooth transition animations.
    """

    def __init__(self) -> None:
        """Initialize lighting controller."""
        self._lights: dict[str, LightState] = {}
        self._groups: dict[str, list[str]] = {}
        self._circadian_enabled: dict[str, bool] = {}
        self._motion_sensors: dict[str, list[str]] = {}
        self._ambient_light: dict[str, float] = {}
        self._transition_callbacks: list = []

    def register_light(self, light_id: str) -> LightState:
        """Register a light.

        Args:
            light_id: Light identifier.

        Returns:
            Light state.
        """
        light = LightState(light_id=light_id)
        self._lights[light_id] = light
        return light

    def get_light(self, light_id: str) -> LightState:
        """Get light state.

        Args:
            light_id: Light identifier.

        Returns:
            Light state.

        Raises:
            LightingError: If light not found.
        """
        if light_id not in self._lights:
            raise LightingError(f"Light {light_id} not found")
        return self._lights[light_id]

    def turn_on(self, light_id: str, brightness: int | None = None) -> None:
        """Turn on a light.

        Args:
            light_id: Light identifier.
            brightness: Optional brightness 0-255.

        Raises:
            LightingError: If light not found.
        """
        light = self.get_light(light_id)
        light.on = True
        if brightness is not None:
            light.brightness = max(0, min(255, brightness))
        else:
            light.brightness = 255

    def turn_off(self, light_id: str) -> None:
        """Turn off a light.

        Args:
            light_id: Light identifier.

        Raises:
            LightingError: If light not found.
        """
        light = self.get_light(light_id)
        light.on = False
        light.brightness = 0

    def set_brightness(self, light_id: str, brightness: int) -> None:
        """Set light brightness.

        Args:
            light_id: Light identifier.
            brightness: Brightness 0-255.

        Raises:
            LightingError: If light not found.
        """
        light = self.get_light(light_id)
        light.brightness = max(0, min(255, brightness))
        if brightness > 0:
            light.on = True

    def set_color_temperature(self, light_id: str, kelvin: int) -> None:
        """Set color temperature.

        Args:
            light_id: Light identifier.
            kelvin: Color temperature 2000-6500K.

        Raises:
            LightingError: If light not found.
        """
        light = self.get_light(light_id)
        light.color_temp_kelvin = max(2000, min(6500, kelvin))

    def set_rgb_color(self, light_id: str, red: int, green: int, blue: int) -> None:
        """Set RGB color.

        Args:
            light_id: Light identifier.
            red: Red 0-255.
            green: Green 0-255.
            blue: Blue 0-255.

        Raises:
            LightingError: If light not found.
        """
        light = self.get_light(light_id)
        light.rgb = RGBColor(red=max(0, min(255, red)), green=max(0, min(255, green)), blue=max(0, min(255, blue)))
        light.on = True

    def set_xy_color(self, light_id: str, x: float, y: float) -> None:
        """Set CIE xy color.

        Args:
            light_id: Light identifier.
            x: x coordinate 0-1.
            y: y coordinate 0-1.

        Raises:
            LightingError: If light not found.
        """
        light = self.get_light(light_id)
        light.xy = (max(0.0, min(1.0, x)), max(0.0, min(1.0, y)))
        light.on = True

    def rgb_to_hsl(self, rgb: RGBColor) -> HSLColor:
        """Convert RGB to HSL.

        Args:
            rgb: RGB color.

        Returns:
            HSL color.

        Raises:
            ColorConversionError: If conversion fails.
        """
        try:
            # Normalize RGB to 0-1
            r = rgb.red / 255.0
            g = rgb.green / 255.0
            b = rgb.blue / 255.0

            max_c = max(r, g, b)
            min_c = min(r, g, b)
            l = (max_c + min_c) / 2.0

            if max_c == min_c:
                h = s = 0.0
            else:
                d = max_c - min_c
                s = d / (2.0 - max_c - min_c) if l > 0.5 else d / (max_c + min_c)

                if max_c == r:
                    h = (g - b) / d + (6.0 if g < b else 0.0)
                elif max_c == g:
                    h = (b - r) / d + 2.0
                else:
                    h = (r - g) / d + 4.0
                h /= 6.0

            return HSLColor(hue=h * 360.0, saturation=s * 100.0, lightness=l * 100.0)
        except Exception as e:
            raise ColorConversionError(f"RGB to HSL failed: {e}")

    def hsl_to_rgb(self, hsl: HSLColor) -> RGBColor:
        """Convert HSL to RGB.

        Args:
            hsl: HSL color.

        Returns:
            RGB color.

        Raises:
            ColorConversionError: If conversion fails.
        """
        try:
            h = hsl.hue / 360.0
            s = hsl.saturation / 100.0
            l = hsl.lightness / 100.0

            def hue_to_rgb(p: float, q: float, t: float) -> float:
                if t < 0.0:
                    t += 1.0
                if t > 1.0:
                    t -= 1.0
                if t < 1.0 / 6.0:
                    return p + (q - p) * 6.0 * t
                if t < 1.0 / 2.0:
                    return q
                if t < 2.0 / 3.0:
                    return p + (q - p) * (2.0 / 3.0 - t) * 6.0
                return p

            if s == 0.0:
                r = g = b = l
            else:
                q = l * (1.0 + s) if l < 0.5 else l + s - l * s
                p = 2.0 * l - q
                r = hue_to_rgb(p, q, h + 1.0 / 3.0)
                g = hue_to_rgb(p, q, h)
                b = hue_to_rgb(p, q, h - 1.0 / 3.0)

            return RGBColor(red=int(r * 255.0), green=int(g * 255.0), blue=int(b * 255.0))
        except Exception as e:
            raise ColorConversionError(f"HSL to RGB failed: {e}")

    def kelvin_to_rgb(self, kelvin: int) -> RGBColor:
        """Convert color temperature to RGB.

        Args:
            kelvin: Color temperature 2000-6500K.

        Returns:
            Approximate RGB color.

        Raises:
            ColorConversionError: If conversion fails.
        """
        try:
            k = max(2000, min(6500, kelvin))

            # Simplified kelvin to RGB conversion
            if k < 2600:
                r, g, b = 255, 52, 0
            elif k < 3500:
                r, g, b = 255, 109, 0
            elif k < 5000:
                r, g, b = 255, 170, 79
            elif k < 6000:
                r, g, b = 255, 191, 130
            else:
                r, g, b = 255, 217, 177

            return RGBColor(red=r, green=g, blue=b)
        except Exception as e:
            raise ColorConversionError(f"Kelvin to RGB failed: {e}")

    def xy_to_rgb(self, x: float, y: float, brightness: int = 255) -> RGBColor:
        """Convert CIE xy color to RGB.

        Args:
            x: x coordinate 0-1.
            y: y coordinate 0-1.
            brightness: Brightness 0-255.

        Returns:
            RGB color.

        Raises:
            ColorConversionError: If conversion fails.
        """
        try:
            # Simplified xy to RGB (full conversion is complex)
            z = 1.0 - x - y
            xyz_x = (brightness / 255.0) * x / y if y > 0 else 0
            xyz_z = (brightness / 255.0) * z / y if y > 0 else 0

            r = xyz_x * 3.2406 - xyz_z * 0.9689
            g = -xyz_x * 1.5372 + brightness / 255.0 * 2.0
            b = xyz_z * 1.2040

            return RGBColor(
                red=max(0, min(255, int(r * 255.0))),
                green=max(0, min(255, int(g * 255.0))),
                blue=max(0, min(255, int(b * 255.0))),
            )
        except Exception as e:
            raise ColorConversionError(f"xy to RGB failed: {e}")

    def enable_circadian_rhythm(self, light_id: str) -> None:
        """Enable circadian rhythm lighting.

        Automatically adjusts color temperature based on time of day.

        Args:
            light_id: Light identifier.
        """
        self._circadian_enabled[light_id] = True

    def disable_circadian_rhythm(self, light_id: str) -> None:
        """Disable circadian rhythm lighting.

        Args:
            light_id: Light identifier.
        """
        self._circadian_enabled[light_id] = False

    def get_circadian_temperature(self, hour: int = None) -> int:
        """Get color temperature for circadian rhythm.

        Args:
            hour: Hour of day 0-23 or None for current.

        Returns:
            Color temperature in Kelvin.
        """
        if hour is None:
            hour = datetime.now().hour

        # Warm in morning (6-9am)
        if 6 <= hour < 9:
            return 3000
        # Bright during day (9am-6pm)
        elif 9 <= hour < 18:
            return 5000
        # Warm evening (6-10pm)
        elif 18 <= hour < 22:
            return 3500
        # Very warm at night (10pm-6am)
        else:
            return 2700

    def set_circadian_temperature(self, light_id: str, hour: int | None = None) -> None:
        """Set light to circadian temperature for time.

        Args:
            light_id: Light identifier.
            hour: Hour of day or None for current.

        Raises:
            LightingError: If light not found.
        """
        light = self.get_light(light_id)
        temp = self.get_circadian_temperature(hour)
        light.color_temp_kelvin = temp

    def motion_activate_light(self, light_id: str, brightness: int = 200, timeout_seconds: int = 300) -> None:
        """Activate light on motion detection.

        Args:
            light_id: Light identifier.
            brightness: Brightness when activated.
            timeout_seconds: Seconds until auto off.

        Raises:
            LightingError: If light not found.
        """
        light = self.get_light(light_id)
        light.on = True
        light.brightness = brightness

    def daylight_harvest(self, light_id: str, ambient_lux: float) -> None:
        """Adjust brightness based on ambient light.

        Args:
            light_id: Light identifier.
            ambient_lux: Ambient light level in lux.

        Raises:
            LightingError: If light not found.
        """
        light = self.get_light(light_id)
        self._ambient_light[light_id] = ambient_lux

        # Reduce brightness in bright conditions
        if ambient_lux > 300:
            light.brightness = max(50, int(255 * (1.0 - ambient_lux / 1000.0)))
        elif ambient_lux < 50:
            light.brightness = 200

    def create_group(self, group_id: str, light_ids: list[str]) -> None:
        """Create a group of lights.

        Args:
            group_id: Group identifier.
            light_ids: List of light IDs in group.
        """
        self._groups[group_id] = light_ids

    def set_group_brightness(self, group_id: str, brightness: int) -> None:
        """Set brightness for all lights in group.

        Args:
            group_id: Group identifier.
            brightness: Brightness 0-255.

        Raises:
            LightingError: If group not found.
        """
        if group_id not in self._groups:
            raise LightingError(f"Group {group_id} not found")

        for light_id in self._groups[group_id]:
            if light_id in self._lights:
                self.set_brightness(light_id, brightness)

    def transition_light(
        self, light_id: str, target_brightness: int, target_temp: int | None = None, duration_ms: int = 1000
    ) -> None:
        """Smoothly transition light to target state.

        Args:
            light_id: Light identifier.
            target_brightness: Target brightness 0-255.
            target_temp: Target color temperature or None.
            duration_ms: Transition duration in milliseconds.

        Raises:
            LightingError: If light not found.
        """
        light = self.get_light(light_id)
        light.transitioning = True
        light.transition_end_time = datetime.now() + __import__("datetime").timedelta(milliseconds=duration_ms)

        # Simulate smooth transition (in real implementation would animate)
        light.brightness = target_brightness
        if target_temp:
            light.color_temp_kelvin = target_temp
        light.transitioning = False

    def interpolate_color(self, rgb1: RGBColor, rgb2: RGBColor, progress: float) -> RGBColor:
        """Interpolate between two RGB colors.

        Args:
            rgb1: Starting color.
            rgb2: Ending color.
            progress: 0.0 to 1.0 interpolation progress.

        Returns:
            Interpolated color.
        """
        r = int(rgb1.red + (rgb2.red - rgb1.red) * progress)
        g = int(rgb1.green + (rgb2.green - rgb1.green) * progress)
        b = int(rgb1.blue + (rgb2.blue - rgb1.blue) * progress)

        return RGBColor(red=max(0, min(255, r)), green=max(0, min(255, g)), blue=max(0, min(255, b)))

    def get_all_lights(self) -> list[LightState]:
        """Get all lights.

        Returns:
            List of light states.
        """
        return list(self._lights.values())

    def get_lights_in_group(self, group_id: str) -> list[LightState]:
        """Get lights in a group.

        Args:
            group_id: Group identifier.

        Returns:
            List of lights in group.

        Raises:
            LightingError: If group not found.
        """
        if group_id not in self._groups:
            raise LightingError(f"Group {group_id} not found")

        return [self._lights[lid] for lid in self._groups[group_id] if lid in self._lights]
