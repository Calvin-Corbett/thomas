"""Regression analysis methods."""

import math

from . import descriptive as desc
from . import distributions as dist
from ._exceptions import InsufficientDataError
from ._types import RegressionResult


def _gaussian_elimination(A: list[list[float]], b: list[float]) -> list[float]:
    """Solve Ax = b using Gaussian elimination with partial pivoting."""
    n = len(A)
    aug = [row[:] + [b[i]] for i, row in enumerate(A)]

    for col in range(n):
        max_row = col
        for row in range(col + 1, n):
            if abs(aug[row][col]) > abs(aug[max_row][col]):
                max_row = row
        aug[col], aug[max_row] = aug[max_row], aug[col]

        if abs(aug[col][col]) < 1e-10:
            continue

        for row in range(col + 1, n):
            factor = aug[row][col] / aug[col][col]
            for j in range(col, n + 1):
                aug[row][j] -= factor * aug[col][j]

    x = [0] * n
    for i in range(n - 1, -1, -1):
        x[i] = aug[i][n]
        for j in range(i + 1, n):
            x[i] -= aug[i][j] * x[j]
        if abs(aug[i][i]) > 1e-10:
            x[i] /= aug[i][i]

    return x


def simple_linear_regression(x: list[float], y: list[float]) -> RegressionResult:
    """
    Simple linear regression (y = a + b*x) using OLS.

    Args:
        x: Independent variable.
        y: Dependent variable (must have same length as x).

    Returns:
        RegressionResult with coefficients, R², and statistics.

    Raises:
        ValueError: If x and y have different lengths.
        InsufficientDataError: If data is too small.
    """
    if len(x) != len(y):
        raise ValueError("x and y must have the same length")

    if len(x) < 3:
        raise InsufficientDataError("Need at least 3 observations for regression")

    n = len(x)
    mean_x = desc.mean(x)
    mean_y = desc.mean(y)

    sxx = sum((xi - mean_x) ** 2 for xi in x)
    sxy = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))

    if sxx == 0:
        raise ValueError("No variation in x")

    b = sxy / sxx
    a = mean_y - b * mean_x

    fitted = [a + b * xi for xi in x]
    residuals = [yi - fi for yi, fi in zip(y, fitted)]

    ss_res = sum(r**2 for r in residuals)
    ss_tot = sum((yi - mean_y) ** 2 for yi in y)

    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    adj_r_squared = 1 - (1 - r_squared) * (n - 1) / (n - 2) if n > 2 else 0

    mse = ss_res / (n - 2) if n > 2 else 0
    se_b = math.sqrt(mse / sxx) if sxx > 0 else 0
    se_a = math.sqrt(mse * (1 / n + mean_x**2 / sxx)) if mse > 0 else 0

    t_b = b / se_b if se_b > 0 else 0
    t_a = a / se_a if se_a > 0 else 0

    df = n - 2
    p_b = 2 * (1 - dist.t_cdf(abs(t_b), df)) if df > 0 else 1
    p_a = 2 * (1 - dist.t_cdf(abs(t_a), df)) if df > 0 else 1

    f_stat = (ss_tot - ss_res) / (ss_res / (n - 2)) if ss_res > 0 and n > 2 else 0
    f_p_value = 1 - dist.f_cdf(f_stat, 1, n - 2) if f_stat > 0 else 1

    aic = n * math.log(ss_res / n) + 4 if ss_res > 0 else float("inf")
    bic = n * math.log(ss_res / n) + 2 * math.log(n) if ss_res > 0 else float("inf")

    return RegressionResult(
        coefficients=[b],
        intercept=a,
        r_squared=r_squared,
        adj_r_squared=adj_r_squared,
        residuals=residuals,
        fitted_values=fitted,
        std_errors=[se_a, se_b],
        t_stats=[t_a, t_b],
        p_values=[p_a, p_b],
        f_statistic=f_stat,
        f_p_value=f_p_value,
        aic=aic,
        bic=bic,
        observations=n,
    )


def multiple_linear_regression(X: list[list[float]], y: list[float]) -> RegressionResult:
    """
    Multiple linear regression using Gaussian elimination.

    Args:
        X: Design matrix (each row is observations, each column is a variable).
        y: Dependent variable.

    Returns:
        RegressionResult with coefficients, R², and statistics.

    Raises:
        ValueError: If X and y have incompatible dimensions.
        InsufficientDataError: If data is too small.
    """
    if not X or not X[0]:
        raise ValueError("X cannot be empty")

    n = len(X)
    p = len(X[0])

    if len(y) != n:
        raise ValueError("X and y must have same number of observations")

    if n < p + 1:
        raise InsufficientDataError("Need more observations than variables")

    X_with_const = [[1.0] + row for row in X]

    XtX = [[0.0] * (p + 1) for _ in range(p + 1)]
    Xty = [0.0] * (p + 1)

    for i in range(p + 1):
        for j in range(p + 1):
            for k in range(n):
                XtX[i][j] += X_with_const[k][i] * X_with_const[k][j]
        for k in range(n):
            Xty[i] += X_with_const[k][i] * y[k]

    beta = _gaussian_elimination(XtX, Xty)

    intercept = beta[0]
    coefficients = beta[1:]

    fitted = [sum(X_with_const[i][j] * beta[j] for j in range(p + 1)) for i in range(n)]
    residuals = [y[i] - fitted[i] for i in range(n)]

    mean_y = desc.mean(y)
    ss_res = sum(r**2 for r in residuals)
    ss_tot = sum((yi - mean_y) ** 2 for yi in y)

    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    adj_r_squared = 1 - (1 - r_squared) * (n - 1) / (n - p - 1) if n > p + 1 else 0

    mse = ss_res / (n - p - 1) if n > p + 1 else 0

    std_errors = []
    t_stats = []
    p_values = []

    for i in range(p + 1):
        if mse > 0 and i < len(XtX):
            try:
                se = math.sqrt(mse * XtX[i][i]) if XtX[i][i] > 0 else 0
            except (ValueError, ArithmeticError):
                se = 0
        else:
            se = 0

        std_errors.append(se)
        t_stat = beta[i] / se if se > 0 else 0
        t_stats.append(t_stat)

        df = n - p - 1
        p_value = 2 * (1 - dist.t_cdf(abs(t_stat), df)) if df > 0 else 1
        p_values.append(p_value)

    f_stat = (ss_tot - ss_res) / p / (ss_res / (n - p - 1)) if ss_res > 0 and n > p + 1 else 0
    f_p_value = 1 - dist.f_cdf(f_stat, p, n - p - 1) if f_stat > 0 else 1

    aic = n * math.log(ss_res / n) + 2 * (p + 1) if ss_res > 0 else float("inf")
    bic = n * math.log(ss_res / n) + (p + 1) * math.log(n) if ss_res > 0 else float("inf")

    return RegressionResult(
        coefficients=coefficients,
        intercept=intercept,
        r_squared=r_squared,
        adj_r_squared=adj_r_squared,
        residuals=residuals,
        fitted_values=fitted,
        std_errors=std_errors,
        t_stats=t_stats,
        p_values=p_values,
        f_statistic=f_stat,
        f_p_value=f_p_value,
        aic=aic,
        bic=bic,
        observations=n,
    )


def polynomial_regression(x: list[float], y: list[float], degree: int = 2) -> RegressionResult:
    """
    Polynomial regression of specified degree.

    Args:
        x: Independent variable.
        y: Dependent variable.
        degree: Polynomial degree (default 2).

    Returns:
        RegressionResult with polynomial coefficients and statistics.

    Raises:
        InsufficientDataError: If data is too small.
        ValueError: If degree is invalid.
    """
    if degree < 1:
        raise ValueError("Degree must be at least 1")

    if len(x) < degree + 2:
        raise InsufficientDataError("Need more observations than polynomial degree")

    X = [[xi ** (degree - j) for j in range(degree + 1)] for xi in x]

    return multiple_linear_regression(X, y)


def ridge_regression(X: list[list[float]], y: list[float], lambda_param: float = 1.0) -> RegressionResult:
    """
    Ridge regression (L2 penalty) using matrix solution.

    Args:
        X: Design matrix.
        y: Dependent variable.
        lambda_param: Regularization parameter (default 1.0).

    Returns:
        RegressionResult with regularized coefficients.

    Raises:
        ValueError: If X and y have incompatible dimensions.
        InsufficientDataError: If data is too small.
    """
    if not X or not X[0]:
        raise ValueError("X cannot be empty")

    n = len(X)
    p = len(X[0])

    if len(y) != n:
        raise ValueError("X and y must have same number of observations")

    if n < p + 1:
        raise InsufficientDataError("Need more observations than variables")

    X_with_const = [[1.0] + row for row in X]

    XtX = [[0.0] * (p + 1) for _ in range(p + 1)]
    Xty = [0.0] * (p + 1)

    for i in range(p + 1):
        for j in range(p + 1):
            for k in range(n):
                XtX[i][j] += X_with_const[k][i] * X_with_const[k][j]
            if i == j and i > 0:
                XtX[i][j] += lambda_param
        for k in range(n):
            Xty[i] += X_with_const[k][i] * y[k]

    beta = _gaussian_elimination(XtX, Xty)

    intercept = beta[0]
    coefficients = beta[1:]

    fitted = [sum(X_with_const[i][j] * beta[j] for j in range(p + 1)) for i in range(n)]
    residuals = [y[i] - fitted[i] for i in range(n)]

    mean_y = desc.mean(y)
    ss_res = sum(r**2 for r in residuals)
    ss_tot = sum((yi - mean_y) ** 2 for yi in y)

    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    adj_r_squared = 1 - (1 - r_squared) * (n - 1) / (n - p - 1) if n > p + 1 else 0

    mse = ss_res / (n - p - 1) if n > p + 1 else 0
    std_errors = [math.sqrt(mse) if mse > 0 else 0] * (p + 1)
    t_stats = [beta[i] / std_errors[i] if std_errors[i] > 0 else 0 for i in range(p + 1)]
    p_values = [1.0] * (p + 1)

    f_stat = 0
    f_p_value = 1

    aic = n * math.log(ss_res / n) + 2 * (p + 1) if ss_res > 0 else float("inf")
    bic = n * math.log(ss_res / n) + (p + 1) * math.log(n) if ss_res > 0 else float("inf")

    return RegressionResult(
        coefficients=coefficients,
        intercept=intercept,
        r_squared=r_squared,
        adj_r_squared=adj_r_squared,
        residuals=residuals,
        fitted_values=fitted,
        std_errors=std_errors,
        t_stats=t_stats,
        p_values=p_values,
        f_statistic=f_stat,
        f_p_value=f_p_value,
        aic=aic,
        bic=bic,
        observations=n,
    )


def logistic_regression(
    X: list[list[float]], y: list[int], max_iter: int = 100, learning_rate: float = 0.01
) -> RegressionResult:
    """
    Logistic regression using gradient descent.

    Args:
        X: Design matrix.
        y: Binary target (0 or 1).
        max_iter: Maximum iterations for gradient descent.
        learning_rate: Learning rate for gradient descent.

    Returns:
        RegressionResult with logistic coefficients.

    Raises:
        ValueError: If X and y have incompatible dimensions or y is not binary.
        InsufficientDataError: If data is too small.
    """
    if not X or not X[0]:
        raise ValueError("X cannot be empty")

    if not all(yi in (0, 1) for yi in y):
        raise ValueError("y must contain only 0 and 1 values")

    n = len(X)
    p = len(X[0])

    if len(y) != n:
        raise ValueError("X and y must have same number of observations")

    if n < 2:
        raise InsufficientDataError("Need at least 2 observations")

    X_with_const = [[1.0] + row for row in X]

    beta = [0.0] * (p + 1)

    for iteration in range(max_iter):
        predictions = []
        for i in range(n):
            z = sum(X_with_const[i][j] * beta[j] for j in range(p + 1))
            prob = 1.0 / (1.0 + math.exp(-z))
            predictions.append(prob)

        gradient = [0.0] * (p + 1)
        for i in range(n):
            error = predictions[i] - y[i]
            for j in range(p + 1):
                gradient[j] += error * X_with_const[i][j]

        for j in range(p + 1):
            gradient[j] /= n
            beta[j] -= learning_rate * gradient[j]

    fitted = []
    for i in range(n):
        z = sum(X_with_const[i][j] * beta[j] for j in range(p + 1))
        prob = 1.0 / (1.0 + math.exp(-z))
        fitted.append(prob)

    residuals = [y[i] - fitted[i] for i in range(n)]

    std_errors = [0.0] * (p + 1)
    t_stats = [0.0] * (p + 1)
    p_values = [1.0] * (p + 1)

    return RegressionResult(
        coefficients=beta[1:],
        intercept=beta[0],
        r_squared=0,
        adj_r_squared=0,
        residuals=residuals,
        fitted_values=fitted,
        std_errors=std_errors,
        t_stats=t_stats,
        p_values=p_values,
        f_statistic=0,
        f_p_value=1,
        aic=float("inf"),
        bic=float("inf"),
        observations=n,
    )


def standardized_residuals(residuals: list[float], fitted: list[float]) -> list[float]:
    """
    Calculate standardized residuals.

    Args:
        residuals: Model residuals.
        fitted: Fitted values.

    Returns:
        List of standardized residuals.
    """
    if not residuals:
        return []

    residual_std = desc.std(residuals, sample=True)

    if residual_std == 0:
        return [0] * len(residuals)

    return [r / residual_std for r in residuals]


def prediction_interval(x: float, result: RegressionResult, confidence: float = 0.95) -> tuple[float, float]:
    """
    Calculate prediction interval for a new observation (simple linear regression).

    Args:
        x: New x value.
        result: RegressionResult from simple_linear_regression.
        confidence: Confidence level (default 0.95).

    Returns:
        Tuple of (lower, upper) bounds.

    Raises:
        ValueError: If result doesn't have proper structure.
    """
    if not result.coefficients or len(result.coefficients) != 1:
        raise ValueError("This function is for simple linear regression")

    b = result.coefficients[0]
    a = result.intercept

    prediction = a + b * x

    residual_std = desc.std(result.residuals, sample=True)
    alpha = 1 - confidence
    result.observations - 2

    t_crit = dist.normal_icdf(1 - alpha / 2)

    margin = t_crit * residual_std * math.sqrt(1 + 1 / result.observations)

    return (prediction - margin, prediction + margin)
