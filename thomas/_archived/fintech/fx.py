"""
Foreign exchange operations and currency conversion.

Implements currency pair management, exchange rate handling, cross-rate
calculation via triangulation, FX conversion, and forward rate computation
using interest rate differentials.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from ._types import Currency, ExchangeRate


class CurrencyPair:
    """
    Represents a currency pair (e.g., EUR/USD).

    Handles currency pair operations and rate representation.
    """

    def __init__(self, base: Currency, quote: Currency) -> None:
        """
        Initialize currency pair.

        Args:
            base: Base currency
            quote: Quote currency
        """
        if base == quote:
            raise ValueError("Base and quote currencies must be different")

        self.base = base
        self.quote = quote

    def __str__(self) -> str:
        """String representation."""
        return f"{self.base.value}/{self.quote.value}"

    def __eq__(self, other: CurrencyPair) -> bool:
        """Check equality."""
        return self.base == other.base and self.quote == other.quote

    def __hash__(self) -> int:
        """Hash for use in dictionaries."""
        return hash((self.base, self.quote))

    def get_inverse(self) -> CurrencyPair:
        """Get inverse pair (swap base and quote)."""
        return CurrencyPair(self.quote, self.base)

    def get_rate_string(self, rate: Decimal) -> str:
        """Format rate for display."""
        return f"{self} = {rate:.6f}"


class FxRateManager:
    """
    Manage FX rates and rate history.

    Stores current and historical exchange rates with bid/ask spreads.
    """

    def __init__(self) -> None:
        """Initialize FX rate manager."""
        self.rates: dict[tuple[Currency, Currency], ExchangeRate] = {}
        self.rate_history: dict[tuple[Currency, Currency], list[ExchangeRate]] = {}

    def set_rate(
        self,
        base: Currency,
        quote: Currency,
        bid: Decimal,
        ask: Decimal,
    ) -> ExchangeRate:
        """
        Set or update exchange rate.

        Args:
            base: Base currency
            quote: Quote currency
            bid: Bid rate
            ask: Ask rate

        Returns:
            Exchange rate record
        """
        rate = ExchangeRate(
            base=base,
            quote=quote,
            bid=bid,
            ask=ask,
        )

        key = (base, quote)
        self.rates[key] = rate

        if key not in self.rate_history:
            self.rate_history[key] = []

        self.rate_history[key].append(rate)
        return rate

    def get_rate(self, base: Currency, quote: Currency) -> ExchangeRate | None:
        """
        Get current exchange rate.

        Args:
            base: Base currency
            quote: Quote currency

        Returns:
            Exchange rate or None if not found
        """
        key = (base, quote)
        return self.rates.get(key)

    def get_inverse_rate(
        self,
        base: Currency,
        quote: Currency,
    ) -> ExchangeRate | None:
        """
        Get inverse rate (quote/base) if direct rate not available.

        Args:
            base: Base currency
            quote: Quote currency

        Returns:
            Constructed inverse rate or None
        """
        direct_rate = self.get_rate(base, quote)
        if direct_rate:
            return direct_rate

        inverse_rate = self.get_rate(quote, base)
        if inverse_rate:
            # Invert bid/ask
            inverted = ExchangeRate(
                base=base,
                quote=quote,
                bid=Decimal("1") / inverse_rate.ask,
                ask=Decimal("1") / inverse_rate.bid,
            )
            return inverted

        return None

    def get_rate_history(
        self,
        base: Currency,
        quote: Currency,
        limit: int = 100,
    ) -> list[ExchangeRate]:
        """
        Get rate history for a pair.

        Args:
            base: Base currency
            quote: Quote currency
            limit: Maximum records to return

        Returns:
            List of historical rates
        """
        key = (base, quote)
        history = self.rate_history.get(key, [])
        return history[-limit:]

    def get_average_rate(
        self,
        base: Currency,
        quote: Currency,
        lookback_minutes: int = 60,
    ) -> Decimal | None:
        """
        Get average rate over period.

        Args:
            base: Base currency
            quote: Quote currency
            lookback_minutes: Look back period

        Returns:
            Average mid rate or None
        """
        cutoff = datetime.utcnow() - timedelta(minutes=lookback_minutes)
        key = (base, quote)

        rates = [r for r in self.rate_history.get(key, []) if r.timestamp >= cutoff]

        if not rates:
            return None

        avg_rate = sum(r.get_mid_rate() for r in rates) / len(rates)
        return avg_rate


class FxConverter:
    """
    Convert amounts between currencies.

    Uses rate manager to perform currency conversions.
    """

    def __init__(self, rate_manager: FxRateManager) -> None:
        """
        Initialize FX converter.

        Args:
            rate_manager: FX rate manager instance
        """
        self.rate_manager = rate_manager

    def convert(
        self,
        amount: Decimal,
        from_currency: Currency,
        to_currency: Currency,
        use_bid: bool = False,
    ) -> Decimal | None:
        """
        Convert amount between currencies.

        Args:
            amount: Amount to convert
            from_currency: Source currency
            to_currency: Target currency
            use_bid: Use bid rate (default ask)

        Returns:
            Converted amount or None if rate not available
        """
        if from_currency == to_currency:
            return amount

        rate = self.rate_manager.get_inverse_rate(from_currency, to_currency)
        if rate is None:
            return None

        conversion_rate = rate.bid if use_bid else rate.ask
        return amount * conversion_rate

    def convert_via_intermediate(
        self,
        amount: Decimal,
        from_currency: Currency,
        to_currency: Currency,
        intermediate: Currency,
    ) -> Decimal | None:
        """
        Convert via intermediate currency (triangulation).

        Args:
            amount: Amount to convert
            from_currency: Source currency
            to_currency: Target currency
            intermediate: Intermediate currency

        Returns:
            Converted amount or None if rates not available
        """
        # Convert to intermediate
        intermediate_amount = self.convert(
            amount,
            from_currency,
            intermediate,
        )
        if intermediate_amount is None:
            return None

        # Convert to target
        target_amount = self.convert(
            intermediate_amount,
            intermediate,
            to_currency,
        )

        return target_amount


class CrossRateCalculator:
    """
    Calculate cross rates via triangulation.

    Derives cross rates from known currency pairs.
    """

    def __init__(self, rate_manager: FxRateManager) -> None:
        """
        Initialize cross rate calculator.

        Args:
            rate_manager: FX rate manager instance
        """
        self.rate_manager = rate_manager

    def calculate_cross_rate(
        self,
        base: Currency,
        quote: Currency,
        via: Currency,
    ) -> ExchangeRate | None:
        """
        Calculate cross rate using triangulation.

        Example: EUR/JPY via USD
        EUR/JPY = (EUR/USD) * (USD/JPY)

        Args:
            base: Base currency
            quote: Quote currency
            via: Intermediate currency

        Returns:
            Calculated cross rate or None if rates unavailable
        """
        # Get rates
        base_via = self.rate_manager.get_inverse_rate(base, via)
        via_quote = self.rate_manager.get_inverse_rate(via, quote)

        if base_via is None or via_quote is None:
            return None

        # Calculate cross rates
        cross_bid = base_via.bid * via_quote.bid
        cross_ask = base_via.ask * via_quote.ask

        return ExchangeRate(
            base=base,
            quote=quote,
            bid=cross_bid,
            ask=cross_ask,
        )

    def find_best_cross_route(
        self,
        base: Currency,
        quote: Currency,
        available_pairs: list[tuple[Currency, Currency]],
    ) -> list[Currency] | None:
        """
        Find best path for cross rate calculation.

        Args:
            base: Base currency
            quote: Quote currency
            available_pairs: List of available currency pairs

        Returns:
            Path through currencies or None if no path found
        """
        # Simple BFS to find shortest path
        from collections import deque

        visited = {base}
        queue = deque([(base, [base])])

        while queue:
            current, path = queue.popleft()

            if current == quote:
                return path

            for curr_a, curr_b in available_pairs:
                if curr_a == current and curr_b not in visited:
                    visited.add(curr_b)
                    queue.append((curr_b, path + [curr_b]))
                elif curr_b == current and curr_a not in visited:
                    visited.add(curr_a)
                    queue.append((curr_a, path + [curr_a]))

        return None


class ForwardRateCalculator:
    """
    Calculate forward exchange rates.

    Uses interest rate parity to calculate forward rates from spot rates
    and interest rate differentials.
    """

    @staticmethod
    def calculate_forward_rate(
        spot_rate: Decimal,
        base_interest_rate: Decimal,
        quote_interest_rate: Decimal,
        days: int = 30,
    ) -> Decimal:
        """
        Calculate forward rate using interest rate parity.

        Forward = Spot * (1 + quote_rate * t) / (1 + base_rate * t)

        Args:
            spot_rate: Current spot rate
            base_interest_rate: Annual interest rate for base currency
            quote_interest_rate: Annual interest rate for quote currency
            days: Number of days forward

        Returns:
            Forward rate
        """
        t = Decimal(str(days)) / 365

        numerator = 1 + (quote_interest_rate * t)
        denominator = 1 + (base_interest_rate * t)

        return spot_rate * numerator / denominator

    @staticmethod
    def calculate_forward_points(
        spot_rate: Decimal,
        forward_rate: Decimal,
    ) -> Decimal:
        """
        Calculate forward points.

        Forward points = (Forward - Spot) / Spot * 10000

        Args:
            spot_rate: Spot rate
            forward_rate: Forward rate

        Returns:
            Forward points
        """
        if spot_rate == 0:
            return Decimal("0")

        return (forward_rate - spot_rate) / spot_rate * 10000


class CurrencyBasketCalculator:
    """
    Calculate values and rates for currency baskets.

    Used for multi-currency portfolios and currency indices.
    """

    def __init__(self, rate_manager: FxRateManager) -> None:
        """
        Initialize basket calculator.

        Args:
            rate_manager: FX rate manager instance
        """
        self.rate_manager = rate_manager

    def calculate_basket_value(
        self,
        basket: dict[Currency, Decimal],
        base_currency: Currency,
    ) -> Decimal | None:
        """
        Calculate basket value in base currency.

        Args:
            basket: Map of currency to amount
            base_currency: Base currency for valuation

        Returns:
            Total basket value or None if rates unavailable
        """
        total_value = Decimal("0")
        converter = FxConverter(self.rate_manager)

        for currency, amount in basket.items():
            if currency == base_currency:
                total_value += amount
            else:
                converted = converter.convert(amount, currency, base_currency)
                if converted is None:
                    return None
                total_value += converted

        return total_value

    def calculate_basket_composition(
        self,
        basket: dict[Currency, Decimal],
        base_currency: Currency,
    ) -> dict[Currency, Decimal] | None:
        """
        Calculate composition percentages of basket.

        Args:
            basket: Currency basket
            base_currency: Base currency

        Returns:
            Map of currency to percentage composition
        """
        total_value = self.calculate_basket_value(basket, base_currency)
        if total_value is None or total_value == 0:
            return None

        converter = FxConverter(self.rate_manager)
        composition = {}

        for currency, amount in basket.items():
            if currency == base_currency:
                value = amount
            else:
                converted = converter.convert(amount, currency, base_currency)
                if converted is None:
                    return None
                value = converted

            composition[currency] = (value / total_value) * 100

        return composition
