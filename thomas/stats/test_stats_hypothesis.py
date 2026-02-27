"""Tests for hypothesis testing module."""

import pytest

from thomas.stats import hypothesis as hyp
from thomas.stats._exceptions import InsufficientDataError


class TestOneSampleTTest:
    def test_one_sample_t_test_simple(self):
        data = [98, 99, 100, 101, 102]
        result = hyp.one_sample_t_test(data, mu=100)
        assert result.df == 4
        assert result.p_value > 0

    def test_one_sample_t_test_reject(self):
        data = [1, 2, 3, 4, 5]
        result = hyp.one_sample_t_test(data, mu=100)
        assert result.p_value < 0.05

    def test_one_sample_t_test_insufficient(self):
        with pytest.raises(InsufficientDataError):
            hyp.one_sample_t_test([1])

    def test_one_sample_t_test_alternatives(self):
        data = [98, 99, 100, 101, 102]
        result_greater = hyp.one_sample_t_test(data, mu=100, alternative="greater")
        result_less = hyp.one_sample_t_test(data, mu=100, alternative="less")
        assert result_greater.p_value > 0
        assert result_less.p_value > 0


class TestTwoSampleTTest:
    def test_two_sample_t_test_equal_var(self):
        data1 = [1, 2, 3, 4, 5]
        data2 = [1, 2, 3, 4, 5]
        result = hyp.two_sample_t_test(data1, data2, equal_var=True)
        assert result.p_value > 0.05

    def test_two_sample_t_test_unequal_var(self):
        data1 = [1, 2, 3, 4, 5]
        data2 = [1, 2, 3, 4, 5]
        result = hyp.two_sample_t_test(data1, data2, equal_var=False)
        assert result.p_value > 0.05

    def test_two_sample_t_test_different(self):
        data1 = [1, 2, 3, 4, 5]
        data2 = [10, 11, 12, 13, 14]
        result = hyp.two_sample_t_test(data1, data2)
        assert result.statistic != 0

    def test_two_sample_t_test_insufficient(self):
        with pytest.raises(InsufficientDataError):
            hyp.two_sample_t_test([1], [1, 2])


class TestPairedTTest:
    def test_paired_t_test_same(self):
        data1 = [1, 2, 3, 4, 5]
        data2 = [1, 2, 3, 4, 5]
        result = hyp.paired_t_test(data1, data2)
        assert result.p_value > 0.05

    def test_paired_t_test_different(self):
        data1 = [1, 2, 3, 4, 5]
        data2 = [10, 11, 12, 13, 14]
        result = hyp.paired_t_test(data1, data2)
        assert result.statistic != 0

    def test_paired_t_test_length_mismatch(self):
        with pytest.raises(ValueError):
            hyp.paired_t_test([1, 2, 3], [1, 2])


class TestChi2GoodnessOfFit:
    def test_chi2_goodness_of_fit(self):
        observed = [25, 25, 25, 25]
        expected = [25, 25, 25, 25]
        result = hyp.chi2_goodness_of_fit(observed, expected)
        assert result.statistic == 0
        assert result.p_value >= 0.95

    def test_chi2_goodness_of_fit_different(self):
        observed = [10, 20, 30, 40]
        expected = [25, 25, 25, 25]
        result = hyp.chi2_goodness_of_fit(observed, expected)
        assert result.statistic > 0


class TestChi2Contingency:
    def test_chi2_contingency_independent(self):
        table = [[25, 25], [25, 25]]
        result = hyp.chi2_contingency(table)
        assert result.statistic == 0

    def test_chi2_contingency_dependent(self):
        table = [[40, 10], [10, 40]]
        result = hyp.chi2_contingency(table)
        assert result.statistic > 0

    def test_chi2_contingency_invalid(self):
        with pytest.raises(ValueError):
            hyp.chi2_contingency([[]])


class TestMannWhitneyU:
    def test_mann_whitney_u_same(self):
        data1 = [1, 2, 3, 4, 5]
        data2 = [1, 2, 3, 4, 5]
        result = hyp.mann_whitney_u(data1, data2)
        assert result.p_value > 0.05

    def test_mann_whitney_u_different(self):
        data1 = [1, 2, 3]
        data2 = [10, 11, 12]
        result = hyp.mann_whitney_u(data1, data2)
        assert result.p_value < 0.05


class TestWilcoxonSignedRank:
    def test_wilcoxon_signed_rank_same(self):
        data1 = [1, 2, 3, 4, 5]
        data2 = [1, 2, 3, 4, 5]
        result = hyp.wilcoxon_signed_rank(data1, data2)
        assert result.p_value > 0.05

    def test_wilcoxon_signed_rank_different(self):
        data1 = [1, 2, 3, 4, 5]
        data2 = [10, 11, 12, 13, 14]
        result = hyp.wilcoxon_signed_rank(data1, data2)
        assert result.statistic >= 0


class TestFTestEqualVariance:
    def test_f_test_equal_variance(self):
        data1 = [1, 2, 3, 4, 5]
        data2 = [1, 2, 3, 4, 5]
        result = hyp.f_test_equal_variance(data1, data2)
        assert result.statistic >= 0

    def test_f_test_unequal_variance(self):
        data1 = [1, 2, 3]
        data2 = [1, 100, 200]
        result = hyp.f_test_equal_variance(data1, data2)
        assert result.statistic > 1


class TestKolmogorovSmirnov:
    def test_ks_test_same(self):
        from thomas.stats import distributions as dist

        data = [1, 2, 3, 4, 5]
        result = hyp.kolmogorov_smirnov(data, lambda x: dist.normal_cdf(x, mu=3, sigma=1))
        assert result.statistic >= 0


class TestOneWayAnova:
    def test_anova_same_groups(self):
        groups = [[1, 2, 3], [1, 2, 3], [1, 2, 3]]
        result = hyp.one_way_anova(groups)
        assert result.p_value > 0.05

    def test_anova_different_groups(self):
        groups = [[1, 2, 3], [5, 6, 7], [10, 11, 12]]
        result = hyp.one_way_anova(groups)
        assert result.statistic > 0

    def test_anova_insufficient_groups(self):
        with pytest.raises(ValueError):
            hyp.one_way_anova([[1, 2, 3]])

    def test_anova_empty_group(self):
        with pytest.raises(InsufficientDataError):
            hyp.one_way_anova([[1, 2, 3], []])
