"""Tests for descriptive statistics module."""

import pytest

from thomas.marketplace.stats import descriptive as desc
from thomas.marketplace.stats._exceptions import InsufficientDataError


class TestMean:
    def test_mean_simple(self):
        assert desc.mean([1, 2, 3]) == 2.0

    def test_mean_floats(self):
        assert abs(desc.mean([1.5, 2.5, 3.5]) - 2.5) < 1e-10

    def test_mean_negative(self):
        assert desc.mean([-1, 0, 1]) == 0.0

    def test_mean_empty(self):
        with pytest.raises(InsufficientDataError):
            desc.mean([])


class TestWeightedMean:
    def test_weighted_mean_equal_weights(self):
        result = desc.weighted_mean([1, 2, 3], [1, 1, 1])
        assert abs(result - 2.0) < 1e-10

    def test_weighted_mean_different_weights(self):
        result = desc.weighted_mean([1, 2, 3], [1, 2, 3])
        assert abs(result - 2.333333) < 1e-5

    def test_weighted_mean_empty(self):
        with pytest.raises(InsufficientDataError):
            desc.weighted_mean([], [])

    def test_weighted_mean_mismatch(self):
        with pytest.raises(ValueError):
            desc.weighted_mean([1, 2], [1, 2, 3])


class TestGeometricMean:
    def test_geometric_mean_simple(self):
        result = desc.geometric_mean([1, 2, 4])
        assert abs(result - 2.0) < 1e-10

    def test_geometric_mean_negative(self):
        with pytest.raises(ValueError):
            desc.geometric_mean([1, -2, 4])


class TestHarmonicMean:
    def test_harmonic_mean_simple(self):
        result = desc.harmonic_mean([1, 2, 4])
        assert abs(result - 1.714286) < 1e-5

    def test_harmonic_mean_zero(self):
        with pytest.raises(ValueError):
            desc.harmonic_mean([1, 0, 4])


class TestMedian:
    def test_median_odd(self):
        assert desc.median([1, 2, 3]) == 2

    def test_median_even(self):
        assert desc.median([1, 2, 3, 4]) == 2.5

    def test_median_single(self):
        assert desc.median([5]) == 5

    def test_median_empty(self):
        with pytest.raises(InsufficientDataError):
            desc.median([])


class TestMode:
    def test_mode_simple(self):
        result = desc.mode([1, 2, 2, 3])
        assert result == 2

    def test_mode_no_repeat(self):
        result = desc.mode([1, 2, 3])
        assert result is None

    def test_mode_empty(self):
        with pytest.raises(InsufficientDataError):
            desc.mode([])


class TestVariance:
    def test_variance_population(self):
        result = desc.variance([1, 2, 3], sample=False)
        assert abs(result - 0.666667) < 1e-5

    def test_variance_sample(self):
        result = desc.variance([1, 2, 3], sample=True)
        assert abs(result - 1.0) < 1e-10

    def test_variance_empty(self):
        with pytest.raises(InsufficientDataError):
            desc.variance([])

    def test_variance_sample_insufficient(self):
        with pytest.raises(InsufficientDataError):
            desc.variance([1], sample=True)


class TestStd:
    def test_std_population(self):
        result = desc.std([1, 2, 3], sample=False)
        assert abs(result - 0.816497) < 1e-5

    def test_std_sample(self):
        result = desc.std([1, 2, 3], sample=True)
        assert abs(result - 1.0) < 1e-10


class TestZScore:
    def test_z_score_simple(self):
        result = desc.z_score(2, [1, 2, 3])
        assert abs(result) < 0.01

    def test_z_score_negative(self):
        result = desc.z_score(1, [1, 2, 3])
        assert result < 0


class TestPercentile:
    def test_percentile_min(self):
        assert desc.percentile([1, 2, 3, 4, 5], 0) == 1

    def test_percentile_median(self):
        result = desc.percentile([1, 2, 3, 4, 5], 50)
        assert result == 3

    def test_percentile_max(self):
        assert desc.percentile([1, 2, 3, 4, 5], 100) == 5

    def test_percentile_invalid(self):
        with pytest.raises(ValueError):
            desc.percentile([1, 2, 3], 150)


class TestQuantile:
    def test_quantile_median(self):
        result = desc.quantile([1, 2, 3, 4, 5], 0.5)
        assert result == 3

    def test_quantile_quartile(self):
        result = desc.quantile([1, 2, 3, 4, 5], 0.25)
        assert 1 <= result <= 2

    def test_quantile_invalid(self):
        with pytest.raises(ValueError):
            desc.quantile([1, 2, 3], 1.5)


class TestIQR:
    def test_iqr_simple(self):
        result = desc.iqr([1, 2, 3, 4, 5])
        assert result == 2.0


class TestSkewness:
    def test_skewness_symmetric(self):
        result = desc.skewness([1, 2, 3, 4, 5])
        assert abs(result) < 0.1

    def test_skewness_insufficient(self):
        with pytest.raises(InsufficientDataError):
            desc.skewness([1, 2])

    def test_skewness_zero_std(self):
        result = desc.skewness([1, 1, 1, 1])
        assert result is None


class TestKurtosis:
    def test_kurtosis_insufficient(self):
        with pytest.raises(InsufficientDataError):
            desc.kurtosis([1, 2, 3])

    def test_kurtosis_normal(self):
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        result = desc.kurtosis(data)
        assert result is not None


class TestFiveNumberSummary:
    def test_five_number_summary(self):
        min_val, q1, med, q3, max_val = desc.five_number_summary([1, 2, 3, 4, 5])
        assert min_val == 1
        assert max_val == 5
        assert med == 3

    def test_five_number_empty(self):
        with pytest.raises(InsufficientDataError):
            desc.five_number_summary([])


class TestDescribe:
    def test_describe(self):
        data = [1, 2, 3, 4, 5]
        result = desc.describe(data)
        assert result.count == 5
        assert result.mean == 3.0
        assert result.median == 3
        assert result.min == 1
        assert result.max == 5

    def test_describe_empty(self):
        with pytest.raises(InsufficientDataError):
            desc.describe([])


class TestCoefficientOfVariation:
    def test_cv_simple(self):
        result = desc.coefficient_of_variation([1, 2, 3])
        assert result > 0

    def test_cv_zero_mean(self):
        with pytest.raises(ValueError):
            desc.coefficient_of_variation([-1, 0, 1])


class TestTrimmedMean:
    def test_trimmed_mean(self):
        result = desc.trimmed_mean([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], trim=0.1)
        assert 3 <= result <= 7

    def test_trimmed_mean_invalid(self):
        with pytest.raises(ValueError):
            desc.trimmed_mean([1, 2, 3], trim=0.6)


class TestWinsorizedMean:
    def test_winsorized_mean(self):
        result = desc.winsorized_mean([1, 2, 3, 4, 5, 100], limits=0.1)
        assert isinstance(result, float)

    def test_winsorized_mean_invalid(self):
        with pytest.raises(ValueError):
            desc.winsorized_mean([1, 2, 3], limits=0.6)


class TestRangeVal:
    def test_range_simple(self):
        assert desc.range_val([1, 5]) == 4

    def test_range_empty(self):
        with pytest.raises(InsufficientDataError):
            desc.range_val([])
