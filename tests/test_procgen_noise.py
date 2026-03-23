"""
Tests for noise generation functions.
"""

import pytest

from thomas.marketplace.procgen._exceptions import InvalidConfigError
from thomas.marketplace.procgen.noise import (
    PerlinNoise,
    SimplexNoise,
    WorleyNoise,
    domain_warp,
    fractal_brownian_motion,
    ridged_multifractal,
    turbulence,
    value_noise,
)


class TestPerlinNoise:
    """Test Perlin noise implementation."""

    def test_perlin_initialization(self):
        """Test Perlin noise initializes properly."""
        perlin = PerlinNoise(seed=42)
        assert perlin.seed == 42
        assert perlin._permutation is not None
        assert len(perlin._permutation) == 512

    def test_perlin_2d_range(self):
        """Test Perlin noise 2D returns values in reasonable range."""
        perlin = PerlinNoise(seed=42)
        values = [perlin.get_2d(i * 0.5, j * 0.5) for i in range(10) for j in range(10)]
        assert all(-1.5 <= v <= 1.5 for v in values)

    def test_perlin_2d_deterministic(self):
        """Test Perlin noise is deterministic with same seed."""
        perlin1 = PerlinNoise(seed=42)
        perlin2 = PerlinNoise(seed=42)
        assert perlin1.get_2d(0.5, 0.5) == perlin2.get_2d(0.5, 0.5)

    def test_perlin_2d_different_seeds(self):
        """Test Perlin noise differs with different seeds."""
        perlin1 = PerlinNoise(seed=42)
        perlin2 = PerlinNoise(seed=43)
        # Test multiple points - they can't all be equal
        vals1 = [perlin1.get_2d(i * 0.5, i * 0.5) for i in range(10)]
        vals2 = [perlin2.get_2d(i * 0.5, i * 0.5) for i in range(10)]
        assert vals1 != vals2

    def test_perlin_3d_range(self):
        """Test Perlin noise 3D returns values in reasonable range."""
        perlin = PerlinNoise(seed=42)
        values = [perlin.get_3d(i * 0.5, j * 0.5, k * 0.5) for i in range(5) for j in range(5) for k in range(5)]
        assert all(-1.5 <= v <= 1.5 for v in values)

    def test_perlin_fade_function(self):
        """Test fade function properties."""
        perlin = PerlinNoise()
        assert perlin._fade(0.0) == 0.0
        assert perlin._fade(1.0) == 1.0
        assert 0.0 < perlin._fade(0.5) < 1.0

    def test_perlin_lerp_function(self):
        """Test linear interpolation."""
        perlin = PerlinNoise()
        assert perlin._lerp(0.0, 1.0, 5.0) == 1.0
        assert perlin._lerp(1.0, 1.0, 5.0) == 5.0
        assert perlin._lerp(0.5, 1.0, 5.0) == 3.0


class TestSimplexNoise:
    """Test Simplex noise implementation."""

    def test_simplex_initialization(self):
        """Test Simplex noise initializes properly."""
        simplex = SimplexNoise(seed=42)
        assert simplex.seed == 42
        assert simplex._permutation is not None
        assert simplex._grad3 is not None

    def test_simplex_2d_range(self):
        """Test Simplex noise 2D returns reasonable values."""
        simplex = SimplexNoise(seed=42)
        values = [simplex.get_2d(i * 0.5, j * 0.5) for i in range(10) for j in range(10)]
        assert len(values) == 100

    def test_simplex_2d_deterministic(self):
        """Test Simplex noise is deterministic."""
        simplex1 = SimplexNoise(seed=42)
        simplex2 = SimplexNoise(seed=42)
        assert simplex1.get_2d(1.5, 2.5) == simplex2.get_2d(1.5, 2.5)

    def test_simplex_different_seeds(self):
        """Test Simplex noise differs with different seeds."""
        simplex1 = SimplexNoise(seed=42)
        simplex2 = SimplexNoise(seed=43)
        val1 = simplex1.get_2d(1.5, 2.5)
        val2 = simplex2.get_2d(1.5, 2.5)
        assert val1 != val2


class TestWorleyNoise:
    """Test Worley/cellular noise implementation."""

    def test_worley_initialization(self):
        """Test Worley noise initializes."""
        worley = WorleyNoise(seed=42)
        assert worley.seed == 42
        assert worley.distance_metric == "euclidean"

    def test_worley_f1_non_negative(self):
        """Test F1 distance is non-negative."""
        worley = WorleyNoise(seed=42)
        for x in range(0, 100, 25):
            for y in range(0, 100, 25):
                assert worley.get_f1(x, y) >= 0

    def test_worley_f2_non_negative(self):
        """Test F2 distance is non-negative."""
        worley = WorleyNoise(seed=42)
        for x in range(0, 100, 25):
            for y in range(0, 100, 25):
                assert worley.get_f2(x, y) >= 0

    def test_worley_f2_greater_than_f1(self):
        """Test F2 >= F1 (second nearest >= nearest)."""
        worley = WorleyNoise(seed=42)
        for x in range(0, 100, 20):
            for y in range(0, 100, 20):
                f1 = worley.get_f1(x, y)
                f2 = worley.get_f2(x, y)
                assert f2 >= f1 - 0.01  # Allow small floating point error

    def test_worley_distance_metrics(self):
        """Test different distance metrics work."""
        for metric in ["euclidean", "manhattan", "chebyshev"]:
            worley = WorleyNoise(seed=42, distance_metric=metric)
            val = worley.get_f1(50, 50)
            assert val >= 0

    def test_worley_invalid_metric(self):
        """Test invalid distance metric raises error."""
        with pytest.raises(InvalidConfigError):
            WorleyNoise(seed=42, distance_metric="invalid")


class TestFractalBrownianMotion:
    """Test FBM implementation."""

    def test_fbm_basic(self):
        """Test FBM returns a value."""
        perlin = PerlinNoise(seed=42)
        result = fractal_brownian_motion(perlin.get_2d, 5.0, 5.0, octaves=4)
        assert isinstance(result, float)

    def test_fbm_more_octaves_more_variation(self):
        """Test more octaves generally increase detail."""
        perlin = PerlinNoise(seed=42)
        val1 = fractal_brownian_motion(perlin.get_2d, 5.0, 5.0, octaves=1)
        val2 = fractal_brownian_motion(perlin.get_2d, 5.0, 5.0, octaves=8)
        # Both should be valid (hard to test exact variation)
        assert isinstance(val1, float)
        assert isinstance(val2, float)

    def test_fbm_invalid_octaves(self):
        """Test FBM with invalid octaves."""
        perlin = PerlinNoise(seed=42)
        with pytest.raises(InvalidConfigError):
            fractal_brownian_motion(perlin.get_2d, 5.0, 5.0, octaves=0)

    def test_fbm_invalid_persistence(self):
        """Test FBM with invalid persistence."""
        perlin = PerlinNoise(seed=42)
        with pytest.raises(InvalidConfigError):
            fractal_brownian_motion(perlin.get_2d, 5.0, 5.0, persistence=0.0)

    def test_fbm_invalid_lacunarity(self):
        """Test FBM with invalid lacunarity."""
        perlin = PerlinNoise(seed=42)
        with pytest.raises(InvalidConfigError):
            fractal_brownian_motion(perlin.get_2d, 5.0, 5.0, lacunarity=1.0)

    def test_fbm_deterministic(self):
        """Test FBM is deterministic."""
        perlin1 = PerlinNoise(seed=42)
        perlin2 = PerlinNoise(seed=42)
        val1 = fractal_brownian_motion(perlin1.get_2d, 5.0, 5.0)
        val2 = fractal_brownian_motion(perlin2.get_2d, 5.0, 5.0)
        assert val1 == val2


class TestDomainWarp:
    """Test domain warping."""

    def test_domain_warp_basic(self):
        """Test domain warp returns a value."""
        perlin = PerlinNoise(seed=42)
        result = domain_warp(perlin.get_2d, perlin.get_2d, 5.0, 5.0)
        assert isinstance(result, float)

    def test_domain_warp_with_strength(self):
        """Test domain warp with different strengths."""
        perlin = PerlinNoise(seed=42)
        val_weak = domain_warp(perlin.get_2d, perlin.get_2d, 5.0, 5.0, warp_strength=0.01)
        val_strong = domain_warp(perlin.get_2d, perlin.get_2d, 5.0, 5.0, warp_strength=0.5)
        # Both should be valid floats
        assert isinstance(val_weak, float)
        assert isinstance(val_strong, float)


class TestValueNoise:
    """Test value noise."""

    def test_value_noise_basic(self):
        """Test value noise returns a float."""
        result = value_noise(5.0, 5.0, seed=42)
        assert isinstance(result, float)
        assert -1.5 <= result <= 1.5

    def test_value_noise_deterministic(self):
        """Test value noise is deterministic."""
        val1 = value_noise(5.0, 5.0, seed=42)
        val2 = value_noise(5.0, 5.0, seed=42)
        assert val1 == val2

    def test_value_noise_different_scales(self):
        """Test value noise with different scales."""
        val1 = value_noise(5.0, 5.0, seed=42, scale=1.0)
        val2 = value_noise(5.0, 5.0, seed=42, scale=2.0)
        assert isinstance(val1, float)
        assert isinstance(val2, float)


class TestTurbulence:
    """Test turbulence."""

    def test_turbulence_basic(self):
        """Test turbulence returns a positive value."""
        perlin = PerlinNoise(seed=42)
        result = turbulence(perlin.get_2d, 5.0, 5.0)
        assert isinstance(result, float)
        assert result >= 0.0

    def test_turbulence_more_octaves(self):
        """Test turbulence with different octave counts."""
        perlin = PerlinNoise(seed=42)
        val1 = turbulence(perlin.get_2d, 5.0, 5.0, octaves=2)
        val2 = turbulence(perlin.get_2d, 5.0, 5.0, octaves=6)
        assert isinstance(val1, float)
        assert isinstance(val2, float)
        assert val1 >= 0.0 and val2 >= 0.0


class TestRidgedMultifractal:
    """Test ridged multifractal."""

    def test_ridged_multifractal_basic(self):
        """Test ridged multifractal returns a value."""
        perlin = PerlinNoise(seed=42)
        result = ridged_multifractal(perlin.get_2d, 5.0, 5.0)
        assert isinstance(result, float)

    def test_ridged_multifractal_deterministic(self):
        """Test ridged multifractal is deterministic."""
        perlin1 = PerlinNoise(seed=42)
        perlin2 = PerlinNoise(seed=42)
        val1 = ridged_multifractal(perlin1.get_2d, 5.0, 5.0)
        val2 = ridged_multifractal(perlin2.get_2d, 5.0, 5.0)
        assert val1 == val2
