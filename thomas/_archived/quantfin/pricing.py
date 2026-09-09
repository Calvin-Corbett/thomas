"""Option pricing models: Black-Scholes, binomial, Monte Carlo, and exotics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import newton
from scipy.stats import norm

from thomas.quantfin._exceptions import PricingError
from thomas.quantfin._types import Greeks, OptionType


@dataclass
class BlackScholesPrice:
    """Black-Scholes option price with Greeks."""

    call_price: float
    put_price: float
    call_greeks: Greeks
    put_greeks: Greeks


def black_scholes(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    q: float = 0.0,
) -> BlackScholesPrice:
    """Black-Scholes option pricing model.

    Calculates European option prices and Greeks (delta, gamma, theta, vega, rho)
    for both calls and puts with continuous dividend yield.

    Args:
        S: Current asset price
        K: Strike price
        T: Time to expiration (years)
        r: Risk-free rate
        sigma: Volatility (annualized)
        q: Dividend yield (default: 0.0)

    Returns:
        BlackScholesPrice with call/put prices and Greeks

    Raises:
        PricingError: If inputs are invalid
    """
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        raise PricingError("Invalid inputs: S, K, T, sigma must be positive")

    d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    # Call and put prices
    call_price = S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    put_price = K * np.exp(-r * T) * norm.cdf(-d2) - S * np.exp(-q * T) * norm.cdf(-d1)

    # Greeks for call
    call_delta = np.exp(-q * T) * norm.cdf(d1)
    call_gamma = np.exp(-q * T) * norm.pdf(d1) / (S * sigma * np.sqrt(T))
    call_vega = S * np.exp(-q * T) * norm.pdf(d1) * np.sqrt(T) / 100
    call_theta = (
        -S * np.exp(-q * T) * norm.pdf(d1) * sigma / (2 * np.sqrt(T))
        - r * K * np.exp(-r * T) * norm.cdf(d2)
        + q * S * np.exp(-q * T) * norm.cdf(d1)
    ) / 365
    call_rho = K * T * np.exp(-r * T) * norm.cdf(d2) / 100

    # Greeks for put
    put_delta = -np.exp(-q * T) * norm.cdf(-d1)
    put_gamma = call_gamma
    put_vega = call_vega
    put_theta = (
        -S * np.exp(-q * T) * norm.pdf(d1) * sigma / (2 * np.sqrt(T))
        + r * K * np.exp(-r * T) * norm.cdf(-d2)
        - q * S * np.exp(-q * T) * norm.cdf(-d1)
    ) / 365
    put_rho = -K * T * np.exp(-r * T) * norm.cdf(-d2) / 100

    call_greeks = Greeks(
        delta=call_delta,
        gamma=call_gamma,
        theta=call_theta,
        vega=call_vega,
        rho=call_rho,
    )
    put_greeks = Greeks(
        delta=put_delta,
        gamma=put_gamma,
        theta=put_theta,
        vega=put_vega,
        rho=put_rho,
    )

    return BlackScholesPrice(
        call_price=call_price,
        put_price=put_price,
        call_greeks=call_greeks,
        put_greeks=put_greeks,
    )


def implied_volatility(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: OptionType,
    q: float = 0.0,
    initial_guess: float = 0.25,
    tolerance: float = 1e-6,
) -> float:
    """Calculate implied volatility using Newton-Raphson method.

    Args:
        market_price: Observed market price of option
        S: Current asset price
        K: Strike price
        T: Time to expiration (years)
        r: Risk-free rate
        option_type: OptionType.CALL or OptionType.PUT
        q: Dividend yield (default: 0.0)
        initial_guess: Initial volatility guess (default: 0.25)
        tolerance: Convergence tolerance (default: 1e-6)

    Returns:
        Implied volatility

    Raises:
        PricingError: If IV calculation fails
    """

    def objective(sigma: float) -> float:
        """Objective function for Newton-Raphson."""
        if sigma <= 0:
            return float("inf")
        try:
            bs = black_scholes(S, K, T, r, sigma, q)
            if option_type == OptionType.CALL:
                return bs.call_price - market_price
            else:
                return bs.put_price - market_price
        except PricingError:
            return float("inf")

    def derivative(sigma: float) -> float:
        """Vega for derivative in Newton-Raphson."""
        if sigma <= 0:
            return 0.0
        try:
            bs = black_scholes(S, K, T, r, sigma, q)
            if option_type == OptionType.CALL:
                return bs.call_greeks.vega
            else:
                return bs.put_greeks.vega
        except PricingError:
            return 0.0

    try:
        iv = newton(objective, initial_guess, fprime=derivative, tol=tolerance, maxiter=100)
        if iv <= 0:
            raise PricingError("Implied volatility converged to non-positive value")
        return iv
    except (ValueError, RuntimeError) as e:
        raise PricingError(f"IV calculation failed: {e}")


def put_call_parity(
    call_price: float,
    put_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    q: float = 0.0,
) -> float:
    """Verify put-call parity.

    For European options: C - P = S*exp(-q*T) - K*exp(-r*T)

    Args:
        call_price: European call price
        put_price: European put price
        S: Current asset price
        K: Strike price
        T: Time to expiration (years)
        r: Risk-free rate
        q: Dividend yield

    Returns:
        Parity error (should be close to 0 for correctly priced options)
    """
    lhs = call_price - put_price
    rhs = S * np.exp(-q * T) - K * np.exp(-r * T)
    return abs(lhs - rhs)


def binomial_american_option(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: OptionType,
    steps: int = 100,
    q: float = 0.0,
) -> float:
    """Binomial model for American option pricing (CRR).

    Cox-Ross-Rubinstein binomial tree for American options that can be
    exercised early. Uses backward induction to determine optimal exercise.

    Args:
        S: Current asset price
        K: Strike price
        T: Time to expiration (years)
        r: Risk-free rate
        sigma: Volatility
        option_type: OptionType.CALL or OptionType.PUT
        steps: Number of time steps (default: 100)
        q: Dividend yield

    Returns:
        Option price

    Raises:
        PricingError: If inputs are invalid
    """
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0 or steps < 1:
        raise PricingError("Invalid inputs")

    dt = T / steps
    u = np.exp(sigma * np.sqrt(dt))
    d = 1.0 / u
    p = (np.exp((r - q) * dt) - d) / (u - d)

    if not (0 < p < 1):
        raise PricingError(f"Invalid probability p={p}")

    # Initialize asset prices at final nodes
    stock_prices = np.zeros(steps + 1)
    for j in range(steps + 1):
        stock_prices[j] = S * u**j * d ** (steps - j)

    # Initialize option values at final nodes
    option_values = np.zeros(steps + 1)
    for j in range(steps + 1):
        if option_type == OptionType.CALL:
            option_values[j] = max(stock_prices[j] - K, 0)
        else:
            option_values[j] = max(K - stock_prices[j], 0)

    # Backward induction through tree
    for i in range(steps - 1, -1, -1):
        for j in range(i + 1):
            stock_price = S * u**j * d ** (i - j)
            option_value = np.exp(-r * dt) * (p * option_values[j + 1] + (1 - p) * option_values[j])

            # American option: check for early exercise
            if option_type == OptionType.CALL:
                intrinsic = stock_price - K
            else:
                intrinsic = K - stock_price

            option_values[j] = max(option_value, intrinsic)

    return float(option_values[0])


def monte_carlo_option(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: OptionType,
    simulations: int = 10000,
    q: float = 0.0,
    use_antithetic: bool = True,
) -> float:
    """Monte Carlo option pricing with GBM paths.

    Uses geometric Brownian motion to simulate stock price paths.
    Supports antithetic variates for variance reduction.

    Args:
        S: Current asset price
        K: Strike price
        T: Time to expiration (years)
        r: Risk-free rate
        sigma: Volatility
        option_type: OptionType.CALL or OptionType.PUT
        simulations: Number of simulations (default: 10000)
        q: Dividend yield
        use_antithetic: Use antithetic variates (default: True)

    Returns:
        Option price

    Raises:
        PricingError: If inputs are invalid
    """
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0 or simulations < 1:
        raise PricingError("Invalid inputs")

    num_sims = simulations if not use_antithetic else simulations // 2

    # Generate random increments
    Z = np.random.standard_normal((num_sims, 1))

    # Standard paths
    ST = S * np.exp((r - q - 0.5 * sigma**2) * T + sigma * np.sqrt(T) * Z)

    if option_type == OptionType.CALL:
        payoffs = np.maximum(ST - K, 0)
    else:
        payoffs = np.maximum(K - ST, 0)

    # Antithetic variates
    if use_antithetic:
        ST_anti = S * np.exp((r - q - 0.5 * sigma**2) * T - sigma * np.sqrt(T) * Z)
        if option_type == OptionType.CALL:
            payoffs_anti = np.maximum(ST_anti - K, 0)
        else:
            payoffs_anti = np.maximum(K - ST_anti, 0)

        payoffs = np.concatenate([payoffs, payoffs_anti])

    option_price = np.mean(payoffs) * np.exp(-r * T)
    return float(option_price)


def barrier_option(
    S: float,
    K: float,
    B: float,
    T: float,
    r: float,
    sigma: float,
    option_type: OptionType,
    barrier_type: str = "knock_out_up",
    simulations: int = 10000,
    q: float = 0.0,
) -> float:
    """Exotic barrier option pricing via Monte Carlo.

    Simulates barrier option payoff. Barrier types: knock_out_up,
    knock_out_down, knock_in_up, knock_in_down.

    Args:
        S: Current asset price
        K: Strike price
        B: Barrier level
        T: Time to expiration (years)
        r: Risk-free rate
        sigma: Volatility
        option_type: OptionType.CALL or OptionType.PUT
        barrier_type: Type of barrier ('knock_out_up', 'knock_out_down', etc.)
        simulations: Number of simulations
        q: Dividend yield

    Returns:
        Barrier option price

    Raises:
        PricingError: If inputs are invalid
    """
    if S <= 0 or K <= 0 or B <= 0 or T <= 0 or sigma <= 0:
        raise PricingError("Invalid inputs")

    steps = 252  # Daily steps
    dt = T / steps
    payoffs = []

    for _ in range(simulations):
        S_current = S
        barrier_hit = False

        # Simulate path
        for _ in range(steps):
            Z = np.random.standard_normal()
            S_current = S_current * np.exp((r - q - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * Z)

            # Check barrier condition
            if barrier_type == "knock_out_up" and S_current >= B or barrier_type == "knock_out_down" and S_current <= B:
                barrier_hit = True
                break
            elif barrier_type == "knock_in_up" and S_current >= B or barrier_type == "knock_in_down" and S_current <= B:
                barrier_hit = True

        # Calculate payoff
        if barrier_type.startswith("knock_out"):
            if barrier_hit:
                payoff = 0.0
            else:
                if option_type == OptionType.CALL:
                    payoff = max(S_current - K, 0)
                else:
                    payoff = max(K - S_current, 0)
        else:  # knock_in
            if not barrier_hit:
                payoff = 0.0
            else:
                if option_type == OptionType.CALL:
                    payoff = max(S_current - K, 0)
                else:
                    payoff = max(K - S_current, 0)

        payoffs.append(payoff)

    option_price = np.mean(payoffs) * np.exp(-r * T)
    return float(option_price)


def asian_option(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: OptionType,
    simulations: int = 10000,
    q: float = 0.0,
    averaging: str = "arithmetic",
) -> float:
    """Asian average price option pricing.

    Option payoff based on average price over time. Supports arithmetic
    and geometric averaging.

    Args:
        S: Current asset price
        K: Strike price
        T: Time to expiration (years)
        r: Risk-free rate
        sigma: Volatility
        option_type: OptionType.CALL or OptionType.PUT
        simulations: Number of simulations
        q: Dividend yield
        averaging: 'arithmetic' or 'geometric'

    Returns:
        Asian option price

    Raises:
        PricingError: If inputs are invalid
    """
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        raise PricingError("Invalid inputs")

    steps = 252
    dt = T / steps
    payoffs = []

    for _ in range(simulations):
        prices = [S]
        S_current = S

        # Generate price path
        for _ in range(steps):
            Z = np.random.standard_normal()
            S_current = S_current * np.exp((r - q - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * Z)
            prices.append(S_current)

        # Calculate average
        if averaging == "arithmetic":
            avg_price = np.mean(prices)
        else:  # geometric
            avg_price = np.exp(np.mean(np.log(prices)))

        # Calculate payoff
        if option_type == OptionType.CALL:
            payoff = max(avg_price - K, 0)
        else:
            payoff = max(K - avg_price, 0)

        payoffs.append(payoff)

    option_price = np.mean(payoffs) * np.exp(-r * T)
    return float(option_price)
