"""Tests for regression module."""

import pytest

from thomas.stats import regression as reg
from thomas.stats._exceptions import InsufficientDataError


class TestSimpleLinearRegression:
    def test_simple_linear_regression(self):
        x = [1, 2, 3, 4, 5]
        y = [2, 4, 6, 8, 10]
        result = reg.simple_linear_regression(x, y)
        assert abs(result.intercept) < 1e-10
        assert abs(result.coefficients[0] - 2.0) < 1e-10
        assert result.r_squared > 0.99

    def test_simple_linear_regression_with_noise(self):
        x = [1, 2, 3, 4, 5]
        y = [2.1, 3.9, 6.2, 7.8, 10.1]
        result = reg.simple_linear_regression(x, y)
        assert 1.8 < result.coefficients[0] < 2.2
        assert result.r_squared > 0.95

    def test_simple_linear_insufficient(self):
        with pytest.raises(InsufficientDataError):
            reg.simple_linear_regression([1, 2], [1, 2])

    def test_simple_linear_length_mismatch(self):
        with pytest.raises(ValueError):
            reg.simple_linear_regression([1, 2, 3], [1, 2])

    def test_simple_linear_no_variation(self):
        with pytest.raises(ValueError):
            reg.simple_linear_regression([1, 1, 1], [1, 2, 3])


class TestMultipleLinearRegression:
    def test_multiple_linear_regression(self):
        X = [[1, 0], [1, 1], [2, 0], [2, 1], [3, 0], [3, 1]]
        y = [1, 2, 2, 3, 3, 4]
        result = reg.multiple_linear_regression(X, y)
        assert len(result.coefficients) == 2
        assert result.r_squared > 0

    def test_multiple_linear_insufficient(self):
        with pytest.raises(InsufficientDataError):
            reg.multiple_linear_regression([[1, 2]], [1])

    def test_multiple_linear_length_mismatch(self):
        with pytest.raises(ValueError):
            reg.multiple_linear_regression([[1, 2], [3, 4]], [1, 2, 3])


class TestPolynomialRegression:
    def test_polynomial_regression_degree2(self):
        x = [1, 2, 3, 4, 5]
        y = [1, 4, 9, 16, 25]
        result = reg.polynomial_regression(x, y, degree=2)
        assert result.r_squared > 0.99

    def test_polynomial_regression_invalid_degree(self):
        with pytest.raises(ValueError):
            reg.polynomial_regression([1, 2, 3], [1, 2, 3], degree=0)

    def test_polynomial_regression_insufficient(self):
        with pytest.raises(InsufficientDataError):
            reg.polynomial_regression([1, 2], [1, 2], degree=2)


class TestRidgeRegression:
    def test_ridge_regression(self):
        X = [[1, 0], [1, 1], [2, 0], [2, 1], [3, 0], [3, 1]]
        y = [1, 2, 2, 3, 3, 4]
        result = reg.ridge_regression(X, y, lambda_param=0.1)
        assert len(result.coefficients) == 2
        assert result.r_squared > 0

    def test_ridge_regression_zero_lambda(self):
        X = [[1, 0], [1, 1], [2, 0], [2, 1]]
        y = [1, 2, 2, 3]
        result = reg.ridge_regression(X, y, lambda_param=0)
        assert result.intercept is not None


class TestLogisticRegression:
    def test_logistic_regression(self):
        X = [[1], [2], [3], [4], [5]]
        y = [0, 0, 0, 1, 1]
        result = reg.logistic_regression(X, y, max_iter=100)
        assert len(result.coefficients) == 1
        assert len(result.fitted_values) == 5

    def test_logistic_regression_invalid_y(self):
        with pytest.raises(ValueError):
            reg.logistic_regression([[1], [2]], [0, 2])

    def test_logistic_regression_insufficient(self):
        with pytest.raises(InsufficientDataError):
            reg.logistic_regression([[1]], [1])


class TestStandardizedResiduals:
    def test_standardized_residuals(self):
        residuals = [1, 2, 3, -1, -2, -3]
        fitted = [1, 2, 3, 4, 5, 6]
        result = reg.standardized_residuals(residuals, fitted)
        assert len(result) == 6

    def test_standardized_residuals_empty(self):
        result = reg.standardized_residuals([], [])
        assert result == []


class TestPredictionInterval:
    def test_prediction_interval(self):
        x = [1, 2, 3, 4, 5]
        y = [2.1, 3.9, 6.2, 7.8, 10.1]
        result = reg.simple_linear_regression(x, y)
        lower, upper = reg.prediction_interval(3, result)
        assert lower <= upper
        assert lower < 6.2 or upper > 6.2

    def test_prediction_interval_invalid(self):
        from thomas.stats._exceptions import InsufficientDataError

        x = [[1, 2], [3, 4]]
        y = [1, 2]
        with pytest.raises(InsufficientDataError):
            result = reg.multiple_linear_regression(x, y)
