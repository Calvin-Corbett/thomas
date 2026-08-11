"""
Photo effects and filtering module.

Implements vignette, tilt-shift, lens flare, film grain, color grading,
miniature effect, and cross-processing.
"""

from __future__ import annotations

import numpy as np

from ._types import Image


class EffectsProcessor:
    """
    Photo effects and artistic filters.

    Implements:
    - Vignette (radial darkening)
    - Tilt-shift (DOF with gradient mask)
    - Lens flare (hexagonal bokeh, ghosts)
    - Film grain
    - Color grading (3D LUT, split toning)
    - Miniature effect
    - Cross-processing
    """

    def vignette(
        self,
        image: Image,
        strength: float = 0.5,
        radius: float = 1.0,
    ) -> Image:
        """
        Apply vignette effect (darkens edges).

        Args:
            image: Input image.
            strength: Vignette strength (0.0-1.0).
            radius: Vignette radius relative to image diagonal.

        Returns:
            Image with vignette applied.
        """
        img_float = image.to_float32()
        h, w = img_float.height, img_float.width

        # Create radial gradient mask
        y_center, x_center = h / 2, w / 2
        diagonal = np.sqrt(h**2 + w**2)

        y_grid, x_grid = np.ogrid[:h, :w]
        dist = np.sqrt((y_grid - y_center) ** 2 + (x_grid - x_center) ** 2)

        # Vignette mask: 1 at center, 0 at edges
        vignette_mask = 1.0 - (dist / (diagonal * radius)) ** 2
        vignette_mask = np.clip(vignette_mask, 0, 1)

        # Blend
        vignette_mask = 1.0 - strength * (1.0 - vignette_mask)

        result = img_float.data * vignette_mask[:, :, np.newaxis]

        return Image(
            data=np.clip(result, 0, 1).astype(np.float32),
            color_space=image.color_space,
            bit_depth=32,
        )

    def tilt_shift(
        self,
        image: Image,
        focus_y: float | None = None,
        focus_height: float = 0.2,
        blur_amount: float = 10.0,
    ) -> Image:
        """
        Apply tilt-shift effect (miniature-like DOF).

        Applies strong blur to top and bottom while keeping center sharp.

        Args:
            image: Input image.
            focus_y: Y position of focus band (0-1), default to center.
            focus_height: Height of sharp band (0-1).
            blur_amount: Sigma for Gaussian blur.

        Returns:
            Image with tilt-shift applied.
        """
        from scipy.ndimage import gaussian_filter

        img_float = image.to_float32()
        h = img_float.height

        if focus_y is None:
            focus_y = 0.5

        focus_center = int(focus_y * h)
        focus_half_height = int(focus_height * h / 2)

        # Create focus mask (sharp in center, blurred elsewhere)
        mask = np.ones(h)

        for y in range(h):
            dist_from_focus = abs(y - focus_center)

            if dist_from_focus > focus_half_height:
                # Blur more the farther from focus
                mask[y] = np.exp(-0.5 * ((dist_from_focus - focus_half_height) / (h * 0.2)) ** 2)
            else:
                mask[y] = 1.0

        # Apply blur
        result = img_float.data.copy()

        for c in range(img_float.channels):
            blurred = gaussian_filter(img_float.data[:, :, c], sigma=blur_amount)
            result[:, :, c] = img_float.data[:, :, c] * mask[:, np.newaxis] + blurred * (1 - mask[:, np.newaxis])

        return Image(
            data=np.clip(result, 0, 1).astype(np.float32),
            color_space=image.color_space,
            bit_depth=32,
        )

    def lens_flare(
        self,
        image: Image,
        center: tuple[float, float] | None = None,
        intensity: float = 0.8,
    ) -> Image:
        """
        Add lens flare effect.

        Creates hexagonal bokeh and ghost artifacts.

        Args:
            image: Input image.
            center: (y, x) as fraction of image (default to random bright area).
            intensity: Flare intensity (0.0-1.0).

        Returns:
            Image with lens flare.
        """
        img_float = image.to_float32()
        h, w = img_float.height, img_float.width

        # Find bright area if center not specified
        if center is None:
            gray = np.mean(img_float.data, axis=2)
            y_bright, x_bright = np.unravel_index(np.argmax(gray), gray.shape)
            center = (y_bright / h, x_bright / w)

        cy, cx = int(center[0] * h), int(center[1] * w)

        result = img_float.data.copy()

        # Main hexagonal bokeh
        for dy in range(-30, 31):
            for dx in range(-30, 31):
                py, px = cy + dy, cx + dx

                if 0 <= py < h and 0 <= px < w:
                    # Hexagonal shape
                    angle = np.arctan2(dy, dx)
                    dist_from_center = np.sqrt(dx**2 + dy**2)

                    # Hexagon: 6 sides
                    hex_factor = np.cos(3 * angle)

                    if dist_from_center < 30 and hex_factor > 0.5:
                        # Blend white flare
                        blend = intensity * (1 - dist_from_center / 30) * (hex_factor - 0.5)
                        result[py, px] = result[py, px] * (1 - blend) + blend

        # Ghost images
        for ghost_dist in [50, 100, 150]:
            ghost_x = cx + ghost_dist
            ghost_y = cy

            if 0 <= ghost_y < h and 0 <= ghost_x < w:
                ghost_size = 20
                for dy in range(-ghost_size, ghost_size + 1):
                    for dx in range(-ghost_size, ghost_size + 1):
                        py, px = ghost_y + dy, ghost_x + dx

                        if 0 <= py < h and 0 <= px < w:
                            dist = np.sqrt(dx**2 + dy**2)

                            if dist < ghost_size:
                                blend = intensity * 0.3 * (1 - dist / ghost_size) ** 2
                                result[py, px] = result[py, px] * (1 - blend) + blend

        return Image(
            data=np.clip(result, 0, 1).astype(np.float32),
            color_space=image.color_space,
            bit_depth=32,
        )

    def film_grain(
        self,
        image: Image,
        amount: float = 0.05,
        size: float = 1.5,
    ) -> Image:
        """
        Add film grain noise.

        Luminance-dependent grain for natural look.

        Args:
            image: Input image.
            amount: Grain strength (0.0-0.2).
            size: Grain size (1.0-3.0).

        Returns:
            Image with film grain.
        """
        from scipy.ndimage import gaussian_filter

        img_float = image.to_float32()

        # Generate grain at different scales
        grain = np.zeros_like(img_float.data)

        for c in range(img_float.channels):
            # Perlin-like noise (simplified using Gaussian pyramid)
            noise = np.random.normal(0, amount, img_float.data.shape[:2])
            noise = gaussian_filter(noise, sigma=size)

            # Make grain luminance-dependent
            luminance = np.mean(img_float.data, axis=2)

            # Stronger grain in shadows and midtones
            grain_strength = np.sin(luminance * np.pi) * 0.5 + 0.5
            grain[:, :, c] = noise * grain_strength

        result = img_float.data + grain

        return Image(
            data=np.clip(result, 0, 1).astype(np.float32),
            color_space=image.color_space,
            bit_depth=32,
        )

    def color_grading(
        self,
        image: Image,
        shadows_tint: tuple[float, float, float] | None = None,
        highlights_tint: tuple[float, float, float] | None = None,
        saturation: float = 1.0,
        temperature: float = 0.0,
    ) -> Image:
        """
        Apply color grading with split toning.

        Args:
            image: Input image.
            shadows_tint: RGB tint for shadows.
            highlights_tint: RGB tint for highlights.
            saturation: Saturation multiplier.
            temperature: Color temperature shift (-1.0 to 1.0).

        Returns:
            Graded image.
        """
        img_float = image.to_float32()

        if img_float.channels < 3:
            # Convert grayscale to RGB
            img_float.data = np.dstack([img_float.data] * 3)

        result = img_float.data.copy()

        # Luminance mask
        luminance = np.mean(result, axis=2, keepdims=True)

        # Apply shadow tint
        if shadows_tint is not None:
            shadow_mask = 1.0 - np.clip(luminance * 2, 0, 1)
            for c in range(3):
                result[:, :, c] = result[:, :, c] * (1 - shadow_mask[:, :, 0] * 0.3) + (
                    shadows_tint[c] * shadow_mask[:, :, 0] * 0.3
                )

        # Apply highlight tint
        if highlights_tint is not None:
            highlight_mask = np.clip((luminance - 0.5) * 2, 0, 1)
            for c in range(3):
                result[:, :, c] = result[:, :, c] * (1 - highlight_mask[:, :, 0] * 0.3) + (
                    highlights_tint[c] * highlight_mask[:, :, 0] * 0.3
                )

        # Adjust saturation
        if saturation != 1.0:
            hsv = self._rgb_to_hsv(result)
            hsv[:, :, 1] = np.clip(hsv[:, :, 1] * saturation, 0, 1)
            result = self._hsv_to_rgb(hsv)

        # Temperature shift (warm/cool)
        if temperature != 0.0:
            if temperature > 0:  # Warmer (add red, reduce blue)
                result[:, :, 0] = np.clip(result[:, :, 0] * (1 + temperature * 0.2), 0, 1)
                result[:, :, 2] = np.clip(result[:, :, 2] * (1 - temperature * 0.1), 0, 1)
            else:  # Cooler (add blue, reduce red)
                result[:, :, 0] = np.clip(result[:, :, 0] * (1 + temperature * 0.1), 0, 1)
                result[:, :, 2] = np.clip(result[:, :, 2] * (1 - temperature * 0.2), 0, 1)

        return Image(
            data=np.clip(result, 0, 1).astype(np.float32),
            color_space=image.color_space,
            bit_depth=32,
        )

    def miniature_effect(
        self,
        image: Image,
        focus_y: float | None = None,
        saturation_boost: float = 1.5,
    ) -> Image:
        """
        Create miniature/toy model effect.

        Combines tilt-shift with saturated colors.

        Args:
            image: Input image.
            focus_y: Vertical focus position (0-1).
            saturation_boost: Saturation increase.

        Returns:
            Miniaturized image.
        """
        # First apply tilt-shift
        result = self.tilt_shift(image, focus_y=focus_y, blur_amount=8.0)

        # Then boost color
        result = self.color_grading(result, saturation=saturation_boost)

        return result

    def cross_process(self, image: Image) -> Image:
        """
        Simulate cross-processed film effect.

        Creates characteristic color casts of cross-processing.

        Args:
            image: Input image.

        Returns:
            Cross-processed image.
        """
        img_float = image.to_float32()

        if img_float.channels < 3:
            img_float.data = np.dstack([img_float.data] * 3)

        result = img_float.data.copy()

        # Luminance-based color mapping
        luminance = np.mean(result, axis=2, keepdims=True)

        # Shadow: cyan-green cast
        shadows = np.zeros_like(result)
        shadows[:, :, 0] = 0.3  # Reduce red
        shadows[:, :, 1] = 0.6  # Increase green
        shadows[:, :, 2] = 0.8  # Increase blue

        # Highlight: warm yellow-red cast
        highlights = np.ones_like(result)
        highlights[:, :, 0] = 1.0  # Keep/boost red
        highlights[:, :, 1] = 0.8  # Reduce green
        highlights[:, :, 2] = 0.4  # Reduce blue

        # Blend based on luminance
        for c in range(3):
            shadow_mask = 1.0 - np.clip(luminance[:, :, 0] * 2, 0, 1)
            highlight_mask = np.clip((luminance[:, :, 0] - 0.5) * 2, 0, 1)
            midtone_mask = 1.0 - shadow_mask - highlight_mask

            result[:, :, c] = (
                result[:, :, c] * 0.7 * midtone_mask
                + shadows[:, :, c] * shadow_mask * 0.5
                + highlights[:, :, c] * highlight_mask * 0.3
            ) + result[:, :, c] * 0.3

        return Image(
            data=np.clip(result, 0, 1).astype(np.float32),
            color_space=image.color_space,
            bit_depth=32,
        )

    @staticmethod
    def _rgb_to_hsv(rgb: np.ndarray) -> np.ndarray:
        """Convert RGB to HSV."""
        r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]

        max_val = np.maximum(np.maximum(r, g), b)
        min_val = np.minimum(np.minimum(r, g), b)
        delta = max_val - min_val

        hsv = np.zeros_like(rgb)

        # Value
        hsv[:, :, 2] = max_val

        # Saturation
        hsv[:, :, 1] = np.where(max_val > 0, delta / max_val, 0)

        # Hue
        hue = np.zeros_like(r)
        mask_r = max_val == r
        mask_g = max_val == g
        mask_b = max_val == b

        hue[mask_r] = ((g[mask_r] - b[mask_r]) / (delta[mask_r] + 1e-10)) % 6
        hue[mask_g] = ((b[mask_g] - r[mask_g]) / (delta[mask_g] + 1e-10)) + 2
        hue[mask_b] = ((r[mask_b] - g[mask_b]) / (delta[mask_b] + 1e-10)) + 4

        hsv[:, :, 0] = (hue / 6) % 1.0

        return hsv

    @staticmethod
    def _hsv_to_rgb(hsv: np.ndarray) -> np.ndarray:
        """Convert HSV to RGB."""
        h, s, v = hsv[:, :, 0] * 6, hsv[:, :, 1], hsv[:, :, 2]

        c = v * s
        x = c * (1 - np.abs((h % 2) - 1))
        m = v - c

        rgb = np.zeros_like(hsv)

        mask0 = h < 1
        mask1 = h < 2
        mask2 = h < 3
        mask3 = h < 4
        mask4 = h < 5

        rgb[mask0, 0] = c[mask0]
        rgb[mask0, 1] = x[mask0]
        rgb[mask1 & ~mask0, 0] = x[mask1 & ~mask0]
        rgb[mask1 & ~mask0, 1] = c[mask1 & ~mask0]
        rgb[mask2 & ~mask1, 1] = c[mask2 & ~mask1]
        rgb[mask2 & ~mask1, 2] = x[mask2 & ~mask1]
        rgb[mask3 & ~mask2, 1] = x[mask3 & ~mask2]
        rgb[mask3 & ~mask2, 2] = c[mask3 & ~mask2]
        rgb[mask4 & ~mask3, 0] = x[mask4 & ~mask3]
        rgb[mask4 & ~mask3, 2] = c[mask4 & ~mask3]
        rgb[~mask4, 0] = c[~mask4]
        rgb[~mask4, 2] = x[~mask4]

        rgb += m[:, :, np.newaxis]

        return rgb
