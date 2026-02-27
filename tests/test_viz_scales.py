"""Tests for visualization scales."""

from datetime import datetime

import pytest

from thomas.visualization._exceptions import InvalidScaleError
from thomas.visualization.scales import (
    CategoricalScale,
    LinearScale,
    LogarithmicScale,
    PowerScale,
    QuantizeScale,
    TimeScale,
)


class TestLinearScale:
    """Tests for linear scale."""

    def test_linear_scale_basic_mapping(self) -> None:
        """Test basic linear mapping."""
        scale = LinearScale((0.0, 100.0), (0.0, 1000.0))

        assert scale.map_value(0.0) == 0.0
        assert scale.map_value(50.0) == 500.0
        assert scale.map_value(100.0) == 1000.0

    def test_linear_scale_invert(self) -> None:
        """Test inverse mapping."""
        scale = LinearScale((0.0, 100.0), (0.0, 1000.0))

        assert scale.invert(0.0) == 0.0
        assert scale.invert(500.0) == 50.0
        assert scale.invert(1000.0) == 100.0

    def test_linear_scale_negative_domain(self) -> None:
        """Test with negative domain."""
        scale = LinearScale((-100.0, 100.0), (0.0, 1000.0))

        assert scale.map_value(-100.0) == 0.0
        assert scale.map_value(0.0) == 500.0
        assert scale.map_value(100.0) == 1000.0

    def test_linear_scale_tick_generation(self) -> None:
        """Test tick generation."""
        scale = LinearScale((0.0, 100.0), (0.0, 1000.0))
        ticks = scale.generate_ticks(10)

        assert len(ticks) > 0
        assert all(0.0 <= t.value <= 100.0 for t in ticks)
        assert all(0.0 <= t.position <= 1.0 for t in ticks)

    def test_linear_scale_equal_domain(self) -> None:
        """Test with equal min/max domain."""
        scale = LinearScale((50.0, 50.0), (0.0, 1000.0))

        assert scale.map_value(50.0) == 500.0

    def test_linear_scale_zero_range(self) -> None:
        """Test with zero range."""
        scale = LinearScale((0.0, 100.0), (500.0, 500.0))

        result = scale.map_value(50.0)
        assert result == 500.0


class TestLogarithmicScale:
    """Tests for logarithmic scale."""

    def test_logarithmic_scale_basic(self) -> None:
        """Test basic logarithmic mapping."""
        scale = LogarithmicScale((1.0, 100.0), (0.0, 1000.0), base=10.0)

        assert scale.map_value(1.0) == 0.0
        assert scale.map_value(100.0) == 1000.0

    def test_logarithmic_scale_middle_value(self) -> None:
        """Test middle value mapping."""
        scale = LogarithmicScale((1.0, 100.0), (0.0, 1000.0), base=10.0)

        result = scale.map_value(10.0)
        assert 490.0 < result < 510.0

    def test_logarithmic_scale_negative_domain_raises(self) -> None:
        """Test that negative domain raises error."""
        with pytest.raises(InvalidScaleError):
            LogarithmicScale((-1.0, 100.0), (0.0, 1000.0))

    def test_logarithmic_scale_invert(self) -> None:
        """Test inverse mapping."""
        scale = LogarithmicScale((1.0, 100.0), (0.0, 1000.0), base=10.0)

        assert scale.invert(0.0) == 1.0
        assert scale.invert(1000.0) == 100.0

    def test_logarithmic_scale_different_bases(self) -> None:
        """Test different logarithm bases."""
        scale_10 = LogarithmicScale((1.0, 100.0), (0.0, 1000.0), base=10.0)
        scale_2 = LogarithmicScale((1.0, 100.0), (0.0, 1000.0), base=2.0)

        result_10 = scale_10.map_value(10.0)
        result_2 = scale_2.map_value(10.0)

        assert result_10 == pytest.approx(result_2)


class TestCategoricalScale:
    """Tests for categorical scale."""

    def test_categorical_scale_basic(self) -> None:
        """Test basic categorical mapping."""
        categories = ("A", "B", "C")
        scale = CategoricalScale(categories, (0.0, 300.0))

        pos_a = scale.map_value("A")
        pos_b = scale.map_value("B")
        pos_c = scale.map_value("C")

        assert pos_a < pos_b < pos_c

    def test_categorical_scale_unknown_category(self) -> None:
        """Test mapping unknown category raises error."""
        scale = CategoricalScale(("A", "B", "C"), (0.0, 300.0))

        with pytest.raises(InvalidScaleError):
            scale.map_value("D")

    def test_categorical_scale_invert(self) -> None:
        """Test inverse mapping to categories."""
        categories = ("A", "B", "C")
        scale = CategoricalScale(categories, (0.0, 300.0))

        assert scale.invert(50.0) == "A"
        assert scale.invert(150.0) == "B"
        assert scale.invert(250.0) == "C"

    def test_categorical_scale_padding(self) -> None:
        """Test padding between categories."""
        categories = ("A", "B", "C")
        scale = CategoricalScale(categories, (0.0, 300.0), padding=0.2)

        pos_a = scale.map_value("A")
        assert pos_a > 0

    def test_categorical_scale_tick_generation(self) -> None:
        """Test tick generation for categories."""
        categories = ("A", "B", "C")
        scale = CategoricalScale(categories, (0.0, 300.0))
        ticks = scale.generate_ticks()

        assert len(ticks) == 3
        assert all(t.label in categories for t in ticks)


class TestTimeScale:
    """Tests for time scale."""

    def test_time_scale_basic(self) -> None:
        """Test basic time mapping."""
        start = datetime(2024, 1, 1)
        end = datetime(2024, 1, 31)
        scale = TimeScale((start, end), (0.0, 1000.0))

        assert scale.map_value(start) == 0.0
        assert scale.map_value(end) == 1000.0

    def test_time_scale_middle_date(self) -> None:
        """Test middle date mapping."""
        start = datetime(2024, 1, 1)
        end = datetime(2024, 1, 31)
        middle = datetime(2024, 1, 16)

        scale = TimeScale((start, end), (0.0, 1000.0))
        result = scale.map_value(middle)

        assert 480.0 < result < 520.0

    def test_time_scale_invert(self) -> None:
        """Test inverse time mapping."""
        start = datetime(2024, 1, 1)
        end = datetime(2024, 1, 31)
        scale = TimeScale((start, end), (0.0, 1000.0))

        result = scale.invert(500.0)
        assert isinstance(result, datetime)

    def test_time_scale_invalid_domain(self) -> None:
        """Test invalid domain raises error."""
        start = datetime(2024, 1, 1)

        with pytest.raises(InvalidScaleError):
            TimeScale((start, start), (0.0, 1000.0))

    def test_time_scale_tick_generation(self) -> None:
        """Test tick generation for time scale."""
        start = datetime(2024, 1, 1)
        end = datetime(2024, 12, 31)
        scale = TimeScale((start, end), (0.0, 1000.0))

        ticks = scale.generate_ticks(12)
        assert len(ticks) > 0
        assert all(isinstance(t.value, datetime) for t in ticks)


class TestPowerScale:
    """Tests for power scale."""

    def test_power_scale_quadratic(self) -> None:
        """Test quadratic (power=2) scale."""
        scale = PowerScale((0.0, 100.0), (0.0, 1000.0), exponent=2.0)

        assert scale.map_value(0.0) == 0.0
        assert scale.map_value(100.0) == 1000.0

    def test_power_scale_sqrt(self) -> None:
        """Test square root (power=0.5) scale."""
        scale = PowerScale((0.0, 100.0), (0.0, 1000.0), exponent=0.5)

        assert scale.map_value(0.0) == 0.0
        assert scale.map_value(100.0) == 1000.0

    def test_power_scale_zero_exponent_raises(self) -> None:
        """Test that zero exponent raises error."""
        with pytest.raises(InvalidScaleError):
            PowerScale((0.0, 100.0), (0.0, 1000.0), exponent=0.0)

    def test_power_scale_negative_domain(self) -> None:
        """Test power scale with negative domain falls back to linear."""
        scale = PowerScale((-100.0, 100.0), (0.0, 1000.0), exponent=2.0)

        result = scale.map_value(0.0)
        assert result == 500.0


class TestQuantizeScale:
    """Tests for quantize scale."""

    def test_quantize_scale_basic(self) -> None:
        """Test basic quantization."""
        thresholds = [33.33, 66.67]
        scale = QuantizeScale((0.0, 100.0), (0.0, 300.0), thresholds=thresholds)

        assert scale.map_value(10.0) == 0.0
        assert scale.map_value(50.0) == 100.0
        assert scale.map_value(90.0) == 200.0

    def test_quantize_scale_no_thresholds(self) -> None:
        """Test quantization without thresholds."""
        scale = QuantizeScale((0.0, 100.0), (0.0, 100.0))

        result = scale.map_value(50.0)
        assert isinstance(result, float)

    def test_quantize_scale_invert(self) -> None:
        """Test inverse quantization."""
        thresholds = [33.33, 66.67]
        scale = QuantizeScale((0.0, 100.0), (0.0, 300.0), thresholds=thresholds)

        assert scale.invert(0.0) == 0
        assert scale.invert(100.0) == 1
        assert scale.invert(200.0) == 2


class TestScaleIntegration:
    """Integration tests for scales."""

    def test_scale_consistency(self) -> None:
        """Test that forward and inverse mappings are consistent."""
        scale = LinearScale((0.0, 100.0), (0.0, 1000.0))

        for value in [0.0, 25.0, 50.0, 75.0, 100.0]:
            pixel = scale.map_value(value)
            back = scale.invert(pixel)
            assert abs(back - value) < 0.01

    def test_scale_domain_range_preservation(self) -> None:
        """Test that domain endpoints map to range endpoints."""
        d_min, d_max = 10.0, 90.0
        r_min, r_max = 100.0, 500.0
        scale = LinearScale((d_min, d_max), (r_min, r_max))

        assert scale.map_value(d_min) == r_min
        assert scale.map_value(d_max) == r_max
