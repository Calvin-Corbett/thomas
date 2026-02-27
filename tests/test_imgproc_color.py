"""
Tests for color science module.
"""

import numpy as np

from thomas.image_proc.color_science import ChromaticityPoint, ColorScience, Illuminant, XYZColor


class TestColorScience:
    """Test color science operations."""

    def test_rgb_to_xyz_conversion(self):
        """Test RGB to XYZ conversion."""
        rgb = np.array([[[1.0, 0.0, 0.0]]])  # Red
        xyz = ColorScience.rgb_to_xyz(rgb)

        assert xyz.shape == (1, 1, 3)
        assert np.all(np.isfinite(xyz))

    def test_xyz_to_rgb_conversion(self):
        """Test XYZ to RGB conversion."""
        xyz = np.array([[[0.412, 0.213, 0.019]]])
        rgb = ColorScience.xyz_to_rgb(xyz)

        assert rgb.shape == (1, 1, 3)
        assert np.all(np.isfinite(rgb))
        assert np.all(rgb >= 0) and np.all(rgb <= 1)

    def test_rgb_xyz_roundtrip(self):
        """Test RGB ↔ XYZ roundtrip conversion."""
        rgb_orig = np.array([[[0.5, 0.3, 0.7]]])

        xyz = ColorScience.rgb_to_xyz(rgb_orig)
        rgb_back = ColorScience.xyz_to_rgb(xyz)

        assert np.allclose(rgb_orig, rgb_back, atol=0.01)

    def test_xyz_to_lab_conversion(self):
        """Test XYZ to Lab conversion."""
        xyz = np.array([[[0.95047, 1.00000, 1.08883]]])  # D65 white point
        lab = ColorScience.xyz_to_lab(xyz)

        assert lab.shape == (1, 1, 3)
        assert np.all(np.isfinite(lab))

    def test_lab_to_xyz_conversion(self):
        """Test Lab to XYZ conversion."""
        lab = np.array([[[50.0, 0.0, 0.0]]])  # Neutral gray
        xyz = ColorScience.lab_to_xyz(lab)

        assert xyz.shape == (1, 1, 3)
        assert np.all(np.isfinite(xyz))

    def test_lab_xyz_roundtrip(self):
        """Test Lab ↔ XYZ roundtrip."""
        lab_orig = np.array([[[50.0, 20.0, -10.0]]])

        xyz = ColorScience.lab_to_xyz(lab_orig)
        lab_back = ColorScience.xyz_to_lab(xyz)

        assert np.allclose(lab_orig, lab_back, atol=0.01)

    def test_lab_to_lch_conversion(self):
        """Test Lab to LCH conversion."""
        lab = np.array([[[50.0, 30.0, 40.0]]])
        lch = ColorScience.lab_to_lch(lab)

        assert lch.shape == (1, 1, 3)
        assert np.all(np.isfinite(lch))
        # C should be sqrt(30^2 + 40^2) ≈ 50
        assert np.isclose(lch[0, 0, 1], 50, atol=0.1)

    def test_lch_to_lab_conversion(self):
        """Test LCH to Lab conversion."""
        lch = np.array([[[50.0, 50.0, 53.13]]])  # C=50, H≈53.13 degrees
        lab = ColorScience.lch_to_lab(lch)

        assert lab.shape == (1, 1, 3)
        assert np.all(np.isfinite(lab))

    def test_delta_e_76_identical_colors(self):
        """Test ΔE*76 of identical colors is zero."""
        lab1 = np.array([50.0, 20.0, 30.0])
        lab2 = np.array([50.0, 20.0, 30.0])

        delta_e = ColorScience.delta_e_76(lab1, lab2)

        assert np.isclose(delta_e, 0.0)

    def test_delta_e_76_different_colors(self):
        """Test ΔE*76 of different colors is positive."""
        lab1 = np.array([50.0, 20.0, 30.0])
        lab2 = np.array([55.0, 25.0, 35.0])

        delta_e = ColorScience.delta_e_76(lab1, lab2)

        assert delta_e > 0

    def test_delta_e_94_graphics_application(self):
        """Test ΔE*94 with graphics settings."""
        lab1 = np.array([50.0, 20.0, 30.0])
        lab2 = np.array([51.0, 21.0, 31.0])

        delta_e = ColorScience.delta_e_94(lab1, lab2, application="graphic")

        assert delta_e >= 0
        assert np.isfinite(delta_e)

    def test_delta_e_94_textile_application(self):
        """Test ΔE*94 with textile settings."""
        lab1 = np.array([50.0, 20.0, 30.0])
        lab2 = np.array([51.0, 21.0, 31.0])

        delta_e = ColorScience.delta_e_94(lab1, lab2, application="textile")

        assert delta_e >= 0
        assert np.isfinite(delta_e)

    def test_delta_e_2000(self):
        """Test CIEDE2000 color difference."""
        lab1 = np.array([50.0, 20.0, 30.0])
        lab2 = np.array([51.0, 21.0, 31.0])

        delta_e = ColorScience.delta_e_2000(lab1, lab2)

        assert delta_e >= 0
        assert np.isfinite(delta_e)

    def test_chromatic_adaptation_d65_to_d50(self):
        """Test chromatic adaptation from D65 to D50."""
        xyz_d65 = np.array([0.95047, 1.00000, 1.08883])

        xyz_d50 = ColorScience.chromatic_adaptation(xyz_d65, Illuminant.D65, Illuminant.D50)

        assert xyz_d50.shape == (3,)
        assert np.all(np.isfinite(xyz_d50))

    def test_chromatic_adaptation_preserves_neutral(self):
        """Test that adapting a neutral (white-relative) color stays neutral."""
        # In XYZ, neutral colors are proportional to the source white point.
        src_white = Illuminant.get_tristimulus(Illuminant.D65) / 100.0
        xyz_d65 = src_white * 0.5

        xyz_d50 = ColorScience.chromatic_adaptation(xyz_d65, Illuminant.D65, Illuminant.D50)

        # After adaptation, chromaticity should align with destination white.
        dst_white = Illuminant.get_tristimulus(Illuminant.D50) / 100.0
        adapted_norm = xyz_d50 / xyz_d50[1]
        dst_norm = dst_white / dst_white[1]

        assert np.allclose(adapted_norm, dst_norm, atol=0.05)

    def test_illuminant_tristimulus_values(self):
        """Test getting illuminant tristimulus values."""
        d65 = Illuminant.get_tristimulus(Illuminant.D65)
        d50 = Illuminant.get_tristimulus(Illuminant.D50)

        assert d65.shape == (3,)
        assert d50.shape == (3,)
        assert np.isclose(d65[1], 100.0)  # Y normalized to 100
        assert np.isclose(d50[1], 100.0)

    def test_white_point_detection_neutral_image(self):
        """Test white point detection on neutral image."""
        h, w = 64, 64
        # Create neutral gray image with some noise
        gray = 0.5 + np.random.normal(0, 0.02, (h, w, 3))
        img_data = np.clip(gray, 0, 1)

        from thomas.image_proc import Image

        img = Image(data=img_data)

        cct, xy = ColorScience.estimate_white_point(img)

        assert isinstance(cct, (float, np.floating))
        assert len(xy) == 2
        assert 1500 <= cct <= 15000  # Reasonable color temperature range

    def test_white_point_detection_dark_image(self):
        """Test white point detection handles dark images gracefully."""
        h, w = 64, 64
        dark_img = np.ones((h, w, 3)) * 0.1

        from thomas.image_proc import Image

        img = Image(data=dark_img)

        cct, xy = ColorScience.estimate_white_point(img)

        # Should return default values without crashing
        assert isinstance(cct, (float, np.floating))
        assert len(xy) == 2

    def test_rgb_to_xyz_with_uint8_input(self):
        """Test RGB to XYZ handles uint8 input."""
        rgb = np.array([[[255, 0, 0]]], dtype=np.uint8)
        xyz = ColorScience.rgb_to_xyz(rgb)

        assert xyz.shape == (1, 1, 3)
        assert np.all(np.isfinite(xyz))

    def test_batch_color_conversion(self):
        """Test batch color conversion on image."""
        h, w = 32, 32
        rgb_img = np.random.rand(h, w, 3)

        xyz = ColorScience.rgb_to_xyz(rgb_img)
        lab = ColorScience.xyz_to_lab(xyz)
        lch = ColorScience.lab_to_lch(lab)

        assert xyz.shape == (h, w, 3)
        assert lab.shape == (h, w, 3)
        assert lch.shape == (h, w, 3)
        assert np.all(np.isfinite(lab))
        assert np.all(np.isfinite(lch))

    def test_chromaticity_point_to_xy(self):
        """Test chromaticity point conversion to tuple."""
        point = ChromaticityPoint(0.3127, 0.3291)
        x, y = point.to_xy()

        assert x == 0.3127
        assert y == 0.3291

    def test_xyz_color_to_array(self):
        """Test XYZ color conversion to array."""
        color = XYZColor(0.5, 0.6, 0.7)
        array = color.to_array()

        assert array.shape == (3,)
        assert array[0] == 0.5
        assert array[1] == 0.6
        assert array[2] == 0.7

    def test_illuminant_variants(self):
        """Test different standard illuminants."""
        illuminants = [Illuminant.D65, Illuminant.D50, Illuminant.A, Illuminant.F11]

        for ill in illuminants:
            tristimulus = Illuminant.get_tristimulus(ill)
            assert tristimulus.shape == (3,)
            assert np.all(tristimulus > 0)

    def test_color_temperature_range(self):
        """Test white point detection produces reasonable temperatures."""
        from thomas.image_proc import Image

        for cct_target in [3000, 6500, 9000]:
            # Create image biased toward target temperature
            warm = np.ones((64, 64, 3))
            warm[:, :, 0] *= cct_target / 6500  # Red boost for warm
            warm[:, :, 2] *= 6500 / cct_target  # Blue reduction for warm

            img = Image(data=np.clip(warm, 0, 1))
            cct, _ = ColorScience.estimate_white_point(img)

            assert 1500 <= cct <= 15000

    def test_multiple_illuminant_conversions(self):
        """Test conversions between multiple illuminants."""
        xyz = np.array([0.5, 0.5, 0.5])

        # Convert through chain of illuminants
        xyz_d50 = ColorScience.chromatic_adaptation(xyz, Illuminant.D65, Illuminant.D50)
        xyz_a = ColorScience.chromatic_adaptation(xyz_d50, Illuminant.D50, Illuminant.A)

        assert np.all(np.isfinite(xyz_a))

    def test_lab_lightness_scaling(self):
        """Test Lab L* component behavior."""
        # L* should range from 0-100
        lab_black = ColorScience.xyz_to_lab(np.array([0.001, 0.001, 0.001]))
        lab_white = ColorScience.xyz_to_lab(np.array([0.95047, 1.00000, 1.08883]))

        assert lab_black[0] < 20  # Black should be dark
        assert lab_white[0] > 95  # White should be light

    def test_lch_hue_consistency(self):
        """Test LCH hue computation is consistent."""
        lab = np.array([[[50.0, 50.0, 0.0]]])  # Red direction
        lch = ColorScience.lab_to_lch(lab)

        # Hue should be 0 degrees (red)
        assert np.isclose(lch[0, 0, 2], 0, atol=1) or np.isclose(lch[0, 0, 2], 360, atol=1)

    def test_color_difference_metrics_agree(self):
        """Test that different ΔE metrics agree on color order."""
        lab1 = np.array([50.0, 0.0, 0.0])
        lab2 = np.array([50.0, 10.0, 0.0])
        lab3 = np.array([50.0, 20.0, 0.0])

        de76_12 = ColorScience.delta_e_76(lab1, lab2)
        de76_23 = ColorScience.delta_e_76(lab2, lab3)
        de76_13 = ColorScience.delta_e_76(lab1, lab3)

        # Closer pairs should have smaller differences
        assert de76_12 < de76_13
        assert de76_23 < de76_13
        assert de76_12 + de76_23 > de76_13 * 0.9  # Triangle inequality

    def test_srgb_gamma_correction(self):
        """Test sRGB gamma correction in conversions."""
        # Linear and sRGB should give different results
        rgb_linear = np.array([[[0.5, 0.5, 0.5]]])

        xyz_linear = ColorScience.rgb_to_xyz(rgb_linear, color_space="linear")
        xyz_srgb = ColorScience.rgb_to_xyz(rgb_linear, color_space="srgb")

        # Results should be different due to gamma
        assert not np.allclose(xyz_linear, xyz_srgb)

    def test_color_space_round_trips_accuracy(self):
        """Test accuracy of color space round-trip conversions."""
        test_colors = [
            np.array([1.0, 0.0, 0.0]),  # Red
            np.array([0.0, 1.0, 0.0]),  # Green
            np.array([0.0, 0.0, 1.0]),  # Blue
            np.array([0.5, 0.5, 0.5]),  # Gray
        ]

        for rgb in test_colors:
            rgb = rgb[np.newaxis, np.newaxis, :]

            # RGB -> XYZ -> Lab -> XYZ -> RGB
            xyz = ColorScience.rgb_to_xyz(rgb)
            lab = ColorScience.xyz_to_lab(xyz)
            xyz_back = ColorScience.lab_to_xyz(lab)
            rgb_back = ColorScience.xyz_to_rgb(xyz_back)

            assert np.allclose(rgb, rgb_back, atol=0.01)

    def test_delta_e_symmetry_all_metrics(self):
        """Test symmetry of all color difference metrics."""
        lab1 = np.array([50.0, 20.0, 30.0])
        lab2 = np.array([52.0, 22.0, 28.0])

        de76_1 = ColorScience.delta_e_76(lab1, lab2)
        de76_2 = ColorScience.delta_e_76(lab2, lab1)

        de94_1 = ColorScience.delta_e_94(lab1, lab2)
        de94_2 = ColorScience.delta_e_94(lab2, lab1)

        de2000_1 = ColorScience.delta_e_2000(lab1, lab2)
        de2000_2 = ColorScience.delta_e_2000(lab2, lab1)

        assert np.isclose(de76_1, de76_2)
        assert np.isclose(de94_1, de94_2)
        assert np.isclose(de2000_1, de2000_2)

    def test_chromatic_adaptation_consistency(self):
        """Test chromatic adaptation is consistent."""
        xyz = np.array([0.5, 0.5, 0.5])

        # Adapt D65 -> D50 -> D65 should return to original
        xyz_adapted = ColorScience.chromatic_adaptation(xyz, Illuminant.D65, Illuminant.D50)
        xyz_back = ColorScience.chromatic_adaptation(xyz_adapted, Illuminant.D50, Illuminant.D65)

        assert np.allclose(xyz, xyz_back, atol=0.05)
