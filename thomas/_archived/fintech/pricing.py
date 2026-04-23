"""
Financial instrument pricing and valuation.

Implements pricing models for bonds and options, Greeks calculation,
and implied volatility estimation. Includes Black-Scholes option pricing,
bond present value calculations, and binomial tree models.
"""

from __future__ import annotations

import math
from decimal import Decimal
from enum import Enum

from scipy import stats


class OptionType(str, Enum):
    """Option type: CALL or PUT."""

    CALL = "CALL"
    PUT = "PUT"


class Greeks:
    """Option Greeks for risk management."""

    def __init__(
        self,
        delta: Decimal,
        gamma: Decimal,
        theta: Decimal,
        vega: Decimal,
        rho: Decimal,
    ) -> None:
        """
        Initialize Greeks.

        Args:
            delta: Sensitivity to price change
            gamma: Sensitivity of delta to price change
            theta: Time decay
            vega: Sensitivity to volatility
            rho: Sensitivity to interest rate
        """
        self.delta = delta
        self.gamma = gamma
        self.theta = theta
        self.vega = vega
        self.rho = rho

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"Greeks(delta={self.delta:.4f}, gamma={self.gamma:.4f}, "
            f"theta={self.theta:.4f}, vega={self.vega:.4f}, rho={self.rho:.4f})"
        )


class BlackScholesCalculator:
    """
    Black-Scholes option pricing model.

    Calculates theoretical option prices and Greeks for European options.
    """

    @staticmethod
    def calculate_option_price(
        spot_price: Decimal,
        strike_price: Decimal,
        time_to_expiry: Decimal,
        volatility: Decimal,
        risk_free_rate: Decimal,
        option_type: OptionType = OptionType.CALL,
    ) -> Decimal:
        """
        Calculate option price using Black-Scholes formula.

        Args:
            spot_price: Current price of underlying
            strike_price: Strike price
            time_to_expiry: Time to expiry in years
            volatility: Volatility (annualized)
            risk_free_rate: Risk-free rate
            option_type: CALL or PUT

        Returns:
            Option price
        """
        S = float(spot_price)
        K = float(strike_price)
        T = float(time_to_expiry)
        sigma = float(volatility)
        r = float(risk_free_rate)

        if T <= 0 or sigma <= 0:
            if option_type == OptionType.CALL:
                return max(Decimal(str(S - K)), Decimal("0"))
            else:
                return max(Decimal(str(K - S)), Decimal("0"))

        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        if option_type == OptionType.CALL:
            price = S * stats.norm.cdf(d1) - K * math.exp(-r * T) * stats.norm.cdf(d2)
        else:
            price = K * math.exp(-r * T) * stats.norm.cdf(-d2) - S * stats.norm.cdf(-d1)

        return Decimal(str(max(price, 0)))

    @staticmethod
    def calculate_greeks(
        spot_price: Decimal,
        strike_price: Decimal,
        time_to_expiry: Decimal,
        volatility: Decimal,
        risk_free_rate: Decimal,
        option_type: OptionType = OptionType.CALL,
    ) -> Greeks:
        """
        Calculate option Greeks.

        Args:
            spot_price: Current price of underlying
            strike_price: Strike price
            time_to_expiry: Time to expiry in years
            volatility: Volatility
            risk_free_rate: Risk-free rate
            option_type: CALL or PUT

        Returns:
            Greeks object
        """
        S = float(spot_price)
        K = float(strike_price)
        T = float(time_to_expiry)
        sigma = float(volatility)
        r = float(risk_free_rate)

        if T <= 0 or sigma <= 0:
            return Greeks(
                delta=Decimal("0"),
                gamma=Decimal("0"),
                theta=Decimal("0"),
                vega=Decimal("0"),
                rho=Decimal("0"),
            )

        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        # Delta
        if option_type == OptionType.CALL:
            delta = stats.norm.cdf(d1)
        else:
            delta = stats.norm.cdf(d1) - 1

        # Gamma
        pdf_d1 = stats.norm.pdf(d1)
        gamma = pdf_d1 / (S * sigma * math.sqrt(T))

        # Vega
        vega = S * pdf_d1 * math.sqrt(T)

        # Theta
        call_theta = -S * pdf_d1 * sigma / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * stats.norm.cdf(d2)

        if option_type == OptionType.CALL:
            theta = call_theta / 365  # Per day
        else:
            put_theta = -S * pdf_d1 * sigma / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * stats.norm.cdf(-d2)
            theta = put_theta / 365

        # Rho
        if option_type == OptionType.CALL:
            rho = K * T * math.exp(-r * T) * stats.norm.cdf(d2)
        else:
            rho = -K * T * math.exp(-r * T) * stats.norm.cdf(-d2)

        return Greeks(
            delta=Decimal(str(delta)),
            gamma=Decimal(str(gamma)),
            theta=Decimal(str(theta)),
            vega=Decimal(str(vega)),
            rho=Decimal(str(rho)),
        )


class ImpliedVolatilityCalculator:
    """
    Calculate implied volatility from option prices.

    Uses bisection method to find volatility that produces target price.
    """

    @staticmethod
    def calculate_implied_volatility(
        option_price: Decimal,
        spot_price: Decimal,
        strike_price: Decimal,
        time_to_expiry: Decimal,
        risk_free_rate: Decimal,
        option_type: OptionType = OptionType.CALL,
        tolerance: Decimal = Decimal("0.0001"),
        max_iterations: int = 100,
    ) -> Decimal | None:
        """
        Calculate implied volatility using bisection method.

        Args:
            option_price: Market price of option
            spot_price: Current price of underlying
            strike_price: Strike price
            time_to_expiry: Time to expiry in years
            risk_free_rate: Risk-free rate
            option_type: CALL or PUT
            tolerance: Convergence tolerance
            max_iterations: Maximum iterations

        Returns:
            Implied volatility or None if not found
        """
        low_vol = Decimal("0.0001")
        high_vol = Decimal("5.0")

        for _ in range(max_iterations):
            mid_vol = (low_vol + high_vol) / 2

            calculated_price = BlackScholesCalculator.calculate_option_price(
                spot_price,
                strike_price,
                time_to_expiry,
                mid_vol,
                risk_free_rate,
                option_type,
            )

            diff = calculated_price - option_price

            if abs(diff) < tolerance:
                return mid_vol

            if diff < 0:
                low_vol = mid_vol
            else:
                high_vol = mid_vol

        return None


class BondCalculator:
    """
    Bond pricing and yield calculations.

    Calculates present value, yield to maturity, and duration.
    """

    @staticmethod
    def calculate_present_value(
        face_value: Decimal,
        coupon_rate: Decimal,
        yield_to_maturity: Decimal,
        years_to_maturity: Decimal,
        payments_per_year: int = 2,
    ) -> Decimal:
        """
        Calculate bond present value (price).

        Args:
            face_value: Bond face value
            coupon_rate: Annual coupon rate
            yield_to_maturity: Yield to maturity
            years_to_maturity: Years to maturity
            payments_per_year: Coupon payment frequency

        Returns:
            Bond price
        """
        fv = float(face_value)
        c = float(coupon_rate) / payments_per_year
        y = float(yield_to_maturity) / payments_per_year
        n = int(float(years_to_maturity) * payments_per_year)
        coupon_payment = fv * float(coupon_rate) / payments_per_year

        if y == 0:
            price = fv + coupon_payment * n
        else:
            pv_coupons = coupon_payment * (1 - (1 + y) ** -n) / y
            pv_face = fv / (1 + y) ** n
            price = pv_coupons + pv_face

        return Decimal(str(max(price, 0)))

    @staticmethod
    def calculate_yield_to_maturity(
        bond_price: Decimal,
        face_value: Decimal,
        coupon_rate: Decimal,
        years_to_maturity: Decimal,
        payments_per_year: int = 2,
        tolerance: Decimal = Decimal("0.0001"),
        max_iterations: int = 100,
    ) -> Decimal | None:
        """
        Calculate yield to maturity using Newton-Raphson method.

        Args:
            bond_price: Current bond price
            face_value: Face value
            coupon_rate: Coupon rate
            years_to_maturity: Years to maturity
            payments_per_year: Payment frequency
            tolerance: Convergence tolerance
            max_iterations: Maximum iterations

        Returns:
            Yield to maturity or None if not converged
        """
        ytm = coupon_rate  # Initial guess

        for _ in range(max_iterations):
            pv = BondCalculator.calculate_present_value(
                face_value,
                coupon_rate,
                ytm,
                years_to_maturity,
                payments_per_year,
            )

            if abs(pv - bond_price) < tolerance:
                return ytm

            # Newton-Raphson adjustment
            duration = BondCalculator.calculate_duration(
                face_value,
                coupon_rate,
                ytm,
                years_to_maturity,
                payments_per_year,
            )

            if duration == 0:
                break

            ytm += (bond_price - pv) / (pv * float(duration))

        return None

    @staticmethod
    def calculate_duration(
        face_value: Decimal,
        coupon_rate: Decimal,
        yield_to_maturity: Decimal,
        years_to_maturity: Decimal,
        payments_per_year: int = 2,
    ) -> Decimal:
        """
        Calculate modified duration.

        Args:
            face_value: Face value
            coupon_rate: Coupon rate
            yield_to_maturity: YTM
            years_to_maturity: Years to maturity
            payments_per_year: Payment frequency

        Returns:
            Modified duration in years
        """
        fv = float(face_value)
        c = float(coupon_rate) / payments_per_year
        y = float(yield_to_maturity) / payments_per_year
        n = int(float(years_to_maturity) * payments_per_year)
        coupon_payment = fv * float(coupon_rate) / payments_per_year

        if y == 0 or n == 0:
            return Decimal("0")

        # Macaulay duration numerator
        duration_sum = Decimal("0")
        for t in range(1, n + 1):
            duration_sum += (
                Decimal(str(t / payments_per_year)) * Decimal(str(coupon_payment)) / Decimal(str((1 + y) ** t))
            )

        duration_sum += Decimal(str(n / payments_per_year)) * Decimal(str(fv)) / Decimal(str((1 + y) ** n))

        bond_price = BondCalculator.calculate_present_value(
            face_value,
            coupon_rate,
            yield_to_maturity,
            years_to_maturity,
            payments_per_year,
        )

        macaulay_duration = duration_sum / bond_price
        modified_duration = macaulay_duration / (1 + y)

        return modified_duration

    @staticmethod
    def calculate_convexity(
        face_value: Decimal,
        coupon_rate: Decimal,
        yield_to_maturity: Decimal,
        years_to_maturity: Decimal,
        payments_per_year: int = 2,
    ) -> Decimal:
        """
        Calculate bond convexity.

        Args:
            face_value: Face value
            coupon_rate: Coupon rate
            yield_to_maturity: YTM
            years_to_maturity: Years to maturity
            payments_per_year: Payment frequency

        Returns:
            Convexity
        """
        fv = float(face_value)
        c = float(coupon_rate) / payments_per_year
        y = float(yield_to_maturity) / payments_per_year
        n = int(float(years_to_maturity) * payments_per_year)
        coupon_payment = fv * float(coupon_rate) / payments_per_year

        if y == 0 or n == 0:
            return Decimal("0")

        convexity_sum = Decimal("0")
        for t in range(1, n + 1):
            t_years = t / payments_per_year
            convexity_sum += (
                Decimal(str(t_years * (t_years + 1 / payments_per_year)))
                * Decimal(str(coupon_payment))
                / Decimal(str((1 + y) ** t))
            )

        convexity_sum += (
            Decimal(str(n / payments_per_year * (n + 1) / payments_per_year))
            * Decimal(str(fv))
            / Decimal(str((1 + y) ** n))
        )

        bond_price = BondCalculator.calculate_present_value(
            face_value,
            coupon_rate,
            yield_to_maturity,
            years_to_maturity,
            payments_per_year,
        )

        return convexity_sum / (bond_price * (1 + y) ** 2)


class TimeValueCalculator:
    """Calculate present and future value of money."""

    @staticmethod
    def calculate_present_value(
        future_value: Decimal,
        discount_rate: Decimal,
        periods: Decimal,
    ) -> Decimal:
        """
        Calculate present value.

        Args:
            future_value: Future value
            discount_rate: Discount rate per period
            periods: Number of periods

        Returns:
            Present value
        """
        if discount_rate == 0:
            return future_value

        return future_value / ((1 + discount_rate) ** periods)

    @staticmethod
    def calculate_future_value(
        present_value: Decimal,
        rate: Decimal,
        periods: Decimal,
    ) -> Decimal:
        """
        Calculate future value.

        Args:
            present_value: Present value
            rate: Rate per period
            periods: Number of periods

        Returns:
            Future value
        """
        return present_value * ((1 + rate) ** periods)

    @staticmethod
    def calculate_amortization_schedule(
        principal: Decimal,
        annual_rate: Decimal,
        years: Decimal,
        payments_per_year: int = 12,
    ) -> list[dict[str, Decimal]]:
        """
        Generate amortization schedule.

        Args:
            principal: Loan principal
            annual_rate: Annual interest rate
            years: Loan term in years
            payments_per_year: Payment frequency

        Returns:
            List of payment schedules with principal and interest
        """
        rate_per_period = annual_rate / payments_per_year
        num_periods = int(float(years) * payments_per_year)

        if rate_per_period == 0:
            payment = principal / num_periods
        else:
            payment = principal * rate_per_period / (1 - (1 + rate_per_period) ** -num_periods)

        schedule = []
        balance = principal

        for period in range(1, num_periods + 1):
            interest = balance * rate_per_period
            principal_payment = payment - interest
            balance -= principal_payment

            schedule.append(
                {
                    "period": Decimal(str(period)),
                    "payment": payment,
                    "principal": principal_payment,
                    "interest": interest,
                    "balance": max(Decimal("0"), balance),
                }
            )

        return schedule
