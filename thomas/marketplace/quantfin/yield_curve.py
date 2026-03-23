"""Fixed income analytics and yield curve modeling."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.interpolate import CubicSpline


@dataclass
class BondMetrics:
    """Bond pricing and risk metrics.

    Attributes:
        price: Bond price (percentage of par)
        yield_to_maturity: Yield to maturity
        duration: Modified duration
        convexity: Convexity
        dv01: Dollar value of 01 basis point move
        accrued_interest: Accrued interest
    """

    price: float
    yield_to_maturity: float
    duration: float
    convexity: float
    dv01: float
    accrued_interest: float


def bootstrap_spot_curve(
    par_rates: np.ndarray,
    maturities: np.ndarray,
    par_value: float = 100.0,
) -> np.ndarray:
    """Bootstrap spot curve from par rates.

    Iteratively solves for spot rates from par bond data.

    Args:
        par_rates: Par bond yields (annualized)
        maturities: Bond maturities in years
        par_value: Par value (default: 100)

    Returns:
        Spot rates for each maturity
    """
    if len(par_rates) != len(maturities):
        raise ValueError("Rates and maturities must be same length")

    spot_rates = np.zeros(len(par_rates))

    for i, (rate, maturity) in enumerate(zip(par_rates, maturities)):
        if i == 0:
            # First point: spot rate = par rate
            spot_rates[0] = rate
        else:
            # Solve for spot rate given previous spot rates
            coupon_payment = rate * par_value
            pv_coupons = 0.0

            # PV of intermediate coupons
            for j in range(i):
                time = maturities[j]
                pv_coupons += coupon_payment / (1 + spot_rates[j]) ** time

            # Solve: par_value = PV(coupons) + (par + coupon) / (1 + spot_rate)^maturity
            numerator = par_value - pv_coupons
            denominator = 1.0 + par_value / (1.0 + par_value)
            spot_rates[i] = (numerator / denominator) ** (1.0 / maturity) - 1.0

    return spot_rates


def spot_to_forward(
    spot_rates: np.ndarray,
    maturities: np.ndarray,
) -> np.ndarray:
    """Convert spot rates to forward rates.

    Forward rate from maturity t1 to t2:
    f(t1, t2) = [(1+s(t2))^t2 / (1+s(t1))^t1]^(1/(t2-t1)) - 1

    Args:
        spot_rates: Spot rates
        maturities: Maturities in years

    Returns:
        Forward rates for each maturity
    """
    forward_rates = np.zeros(len(spot_rates))
    forward_rates[0] = spot_rates[0]

    for i in range(1, len(spot_rates)):
        discount_factor_current = (1 + spot_rates[i]) ** maturities[i]
        discount_factor_prev = (1 + spot_rates[i - 1]) ** maturities[i - 1]

        forward_rate = (discount_factor_current / discount_factor_prev) ** (
            1.0 / (maturities[i] - maturities[i - 1])
        ) - 1.0
        forward_rates[i] = forward_rate

    return forward_rates


def bond_price(
    face_value: float,
    coupon_rate: float,
    yield_to_maturity: float,
    years_to_maturity: float,
    coupons_per_year: int = 2,
) -> float:
    """Calculate bond price from cash flows.

    Args:
        face_value: Bond face value
        coupon_rate: Annual coupon rate
        yield_to_maturity: Bond YTM (discount rate)
        years_to_maturity: Years to maturity
        coupons_per_year: Coupon frequency (default: 2 for semi-annual)

    Returns:
        Bond price (as percentage of par)
    """
    if yield_to_maturity < 0:
        raise ValueError("YTM must be non-negative")

    coupon_payment = face_value * coupon_rate / coupons_per_year
    num_periods = int(years_to_maturity * coupons_per_year)
    period_yield = yield_to_maturity / coupons_per_year

    # PV of coupons
    if period_yield == 0:
        pv_coupons = coupon_payment * num_periods
    else:
        pv_coupons = coupon_payment * (1 - (1 + period_yield) ** (-num_periods)) / period_yield

    # PV of face value
    pv_face = face_value / (1 + period_yield) ** num_periods

    return pv_coupons + pv_face


def bond_duration(
    face_value: float,
    coupon_rate: float,
    yield_to_maturity: float,
    years_to_maturity: float,
    coupons_per_year: int = 2,
) -> float:
    """Calculate Macaulay duration of bond.

    Duration = weighted average time to cash flow.

    Args:
        face_value: Bond face value
        coupon_rate: Annual coupon rate
        yield_to_maturity: Bond YTM
        years_to_maturity: Years to maturity
        coupons_per_year: Coupon frequency

    Returns:
        Duration in years
    """
    coupon_payment = face_value * coupon_rate / coupons_per_year
    num_periods = int(years_to_maturity * coupons_per_year)
    period_yield = yield_to_maturity / coupons_per_year

    bond_price_val = bond_price(face_value, coupon_rate, yield_to_maturity, years_to_maturity, coupons_per_year)

    # Calculate weighted cash flows
    weighted_cf = 0.0

    for period in range(1, num_periods + 1):
        time = period / coupons_per_year
        cf = coupon_payment
        pv_cf = cf / (1 + period_yield) ** period
        weighted_cf += time * pv_cf

    # Add face value
    time_face = years_to_maturity
    pv_face = face_value / (1 + period_yield) ** num_periods
    weighted_cf += time_face * pv_face

    duration = weighted_cf / bond_price_val
    return duration


def modified_duration(
    duration: float,
    yield_to_maturity: float,
    coupons_per_year: int = 2,
) -> float:
    """Calculate modified duration from Macaulay duration.

    Modified duration = Macaulay duration / (1 + y/m)

    Args:
        duration: Macaulay duration
        yield_to_maturity: Bond YTM
        coupons_per_year: Coupon frequency

    Returns:
        Modified duration
    """
    return duration / (1 + yield_to_maturity / coupons_per_year)


def bond_convexity(
    face_value: float,
    coupon_rate: float,
    yield_to_maturity: float,
    years_to_maturity: float,
    coupons_per_year: int = 2,
) -> float:
    """Calculate bond convexity.

    Convexity = sum(t * (t+1) * PV(CF)) / (Bond Price * (1+y)^2)

    Args:
        face_value: Bond face value
        coupon_rate: Annual coupon rate
        yield_to_maturity: Bond YTM
        years_to_maturity: Years to maturity
        coupons_per_year: Coupon frequency

    Returns:
        Convexity
    """
    coupon_payment = face_value * coupon_rate / coupons_per_year
    num_periods = int(years_to_maturity * coupons_per_year)
    period_yield = yield_to_maturity / coupons_per_year

    bond_price_val = bond_price(face_value, coupon_rate, yield_to_maturity, years_to_maturity, coupons_per_year)

    # Calculate weighted cash flows for convexity
    weighted_cf = 0.0

    for period in range(1, num_periods + 1):
        cf = coupon_payment
        pv_cf = cf / (1 + period_yield) ** period
        weighted_cf += period * (period + 1) * pv_cf

    # Add face value
    pv_face = face_value / (1 + period_yield) ** num_periods
    weighted_cf += num_periods * (num_periods + 1) * pv_face

    convexity = weighted_cf / (bond_price_val * (1 + period_yield) ** 2)
    return convexity


def dv01(
    face_value: float,
    coupon_rate: float,
    yield_to_maturity: float,
    years_to_maturity: float,
    coupons_per_year: int = 2,
    principal: float = 1000000.0,
) -> float:
    """Calculate dollar value of 1 basis point move (DV01).

    Args:
        face_value: Bond face value
        coupon_rate: Annual coupon rate
        yield_to_maturity: Bond YTM
        years_to_maturity: Years to maturity
        coupons_per_year: Coupon frequency
        principal: Principal amount (default: $1M)

    Returns:
        DV01 in dollars
    """
    duration = bond_duration(face_value, coupon_rate, yield_to_maturity, years_to_maturity, coupons_per_year)
    mod_duration = modified_duration(duration, yield_to_maturity, coupons_per_year)

    # DV01 = Principal * Modified Duration * 0.0001
    return (principal * mod_duration * 0.0001) / 100.0


def yield_curve_interpolation(
    maturities: np.ndarray,
    yields: np.ndarray,
    method: str = "linear",
) -> callable:
    """Create yield curve interpolation function.

    Args:
        maturities: Bond maturities
        yields: Bond yields
        method: Interpolation method ('linear', 'cubic', 'nelson_siegel')

    Returns:
        Function that takes maturity and returns interpolated yield
    """
    if method == "linear":
        return lambda t: float(np.interp(t, maturities, yields))
    elif method == "cubic":
        cs = CubicSpline(maturities, yields)
        return lambda t: float(cs(t))
    elif method == "nelson_siegel":
        # Fit Nelson-Siegel parameters
        params = nelson_siegel_fit(maturities, yields)
        return lambda t: nelson_siegel_yield(t, *params)
    else:
        raise ValueError(f"Unknown interpolation method: {method}")


def nelson_siegel_yield(
    maturity: float,
    beta0: float,
    beta1: float,
    beta2: float,
    lambda_param: float,
) -> float:
    """Nelson-Siegel yield curve model.

    y(t) = β0 + β1*exp(-λt) + β2*λt*exp(-λt)

    Args:
        maturity: Time to maturity
        beta0: Level component
        beta1: Slope component
        beta2: Curvature component
        lambda_param: Decay rate

    Returns:
        Yield at maturity
    """
    exp_term = np.exp(-lambda_param * maturity)
    return beta0 + beta1 * exp_term + beta2 * lambda_param * maturity * exp_term


def nelson_siegel_fit(
    maturities: np.ndarray,
    yields: np.ndarray,
    initial_lambda: float = 0.5,
) -> tuple[float, float, float, float]:
    """Fit Nelson-Siegel parameters to yield curve.

    Args:
        maturities: Bond maturities
        yields: Bond yields
        initial_lambda: Initial lambda guess

    Returns:
        Tuple of (beta0, beta1, beta2, lambda)
    """
    # Simple estimation (full MLE optimization omitted)
    beta0 = yields[-1]  # Long rate
    beta1 = yields[0] - beta0  # Short-long spread
    beta2 = 0.0  # Curvature (simplified)
    lambda_param = initial_lambda

    return beta0, beta1, beta2, lambda_param


def credit_spread(
    risk_free_yield: float,
    risky_yield: float,
) -> float:
    """Calculate credit spread.

    Args:
        risk_free_yield: Risk-free bond yield
        risky_yield: Risky bond yield

    Returns:
        Spread in basis points
    """
    return (risky_yield - risk_free_yield) * 10000.0


def oas_to_duration(
    duration: float,
    oas_change: float,
) -> float:
    """Calculate bond price change from OAS change.

    ΔPrice ≈ -Duration * ΔOAS

    Args:
        duration: Modified duration
        oas_change: OAS change in basis points

    Returns:
        Price change percentage
    """
    return -duration * (oas_change / 10000.0) * 100.0


def term_structure_slope(
    short_yield: float,
    long_yield: float,
) -> float:
    """Calculate yield curve slope.

    Args:
        short_yield: Short maturity yield
        long_yield: Long maturity yield

    Returns:
        Slope in basis points
    """
    return (long_yield - short_yield) * 10000.0


def spot_rate_to_discount_factor(
    spot_rate: float,
    maturity: float,
) -> float:
    """Convert spot rate to discount factor.

    Discount factor = 1 / (1 + spot_rate)^maturity

    Args:
        spot_rate: Spot interest rate
        maturity: Time to maturity in years

    Returns:
        Discount factor (0 to 1)
    """
    return 1.0 / (1.0 + spot_rate) ** maturity


def present_value_basis(
    futures_price: float,
    spot_price: float,
    repo_rate: float,
    days_to_delivery: int,
    basis_points: float = 0.0,
) -> float:
    """Calculate theoretical futures price using PV basis model.

    Args:
        spot_price: Current spot price
        futures_price: Quoted futures price
        repo_rate: Repo financing rate (annual)
        days_to_delivery: Days until futures delivery
        basis_points: Additional basis points

    Returns:
        Theoretical futures price
    """
    carry_cost = spot_price * (repo_rate / 365.0) * days_to_delivery
    cash_basis = futures_price - spot_price - carry_cost

    return futures_price - (cash_basis * (basis_points / 10000.0))
