"""Property valuation methods and automated valuation models."""

import statistics
from datetime import date
from decimal import Decimal

from thomas.marketplace.real_estate._exceptions import InsufficientDataError
from thomas.marketplace.real_estate._types import Comparable, Property


class ComparableSalesAnalysis:
    """Comparable sales analysis (CMA) for property valuation."""

    @staticmethod
    def find_comparables(
        target_property: Property,
        candidates: list[Comparable],
        sqft_tolerance: float = 0.10,
        bed_tolerance: int = 1,
        bath_tolerance: float = 1.0,
        days_back: int = 180,
    ) -> list[Comparable]:
        """Find comparable properties for CMA.

        Args:
            target_property: Property being valued
            candidates: List of candidate comparable properties
            sqft_tolerance: Tolerance for square footage (default ±10%)
            bed_tolerance: Tolerance for bedrooms (default ±1)
            bath_tolerance: Tolerance for bathrooms (default ±1)
            days_back: Only include sales within this many days (default 180)

        Returns:
            List of matching comparable properties
        """
        comparables = []
        cutoff_date = date.today().replace(day=1)
        cutoff_date = cutoff_date.replace(month=cutoff_date.month - (days_back // 30))

        sqft_min = target_property.sqft * (1 - sqft_tolerance)
        sqft_max = target_property.sqft * (1 + sqft_tolerance)

        for comp in candidates:
            if comp.sale_date < cutoff_date:
                continue
            if not (sqft_min <= comp.sqft <= sqft_max):
                continue
            if abs(comp.bedrooms - target_property.bedrooms) > bed_tolerance:
                continue
            if abs(comp.bathrooms - target_property.bathrooms) > bath_tolerance:
                continue
            comparables.append(comp)

        return comparables

    @staticmethod
    def adjust_for_sqft(comp_price: Decimal, target_sqft: int, comp_sqft: int, price_per_sqft: Decimal) -> Decimal:
        """Adjust comparable price for square footage difference.

        Args:
            comp_price: Comparable property sale price
            target_sqft: Target property square footage
            comp_sqft: Comparable property square footage
            price_per_sqft: Market price per square foot

        Returns:
            Adjusted price
        """
        sqft_diff = target_sqft - comp_sqft
        adjustment = Decimal(sqft_diff) * price_per_sqft
        return comp_price + adjustment

    @staticmethod
    def adjust_for_condition(comp_price: Decimal, target_condition: int, comp_condition: int) -> Decimal:
        """Adjust comparable price for condition difference.

        Args:
            comp_price: Comparable property sale price
            target_condition: Target property condition (1-10 scale)
            comp_condition: Comparable property condition (1-10 scale)

        Returns:
            Adjusted price
        """
        condition_diff = target_condition - comp_condition
        adjustment_percent = Decimal(condition_diff) * Decimal("0.05")
        return comp_price * (1 + adjustment_percent)

    @staticmethod
    def adjust_for_age(
        comp_price: Decimal,
        target_age: int,
        comp_age: int,
        annual_depreciation: Decimal = Decimal("0.005"),
    ) -> Decimal:
        """Adjust comparable price for age/condition difference.

        Args:
            comp_price: Comparable property sale price
            target_age: Target property age in years
            comp_age: Comparable property age in years
            annual_depreciation: Annual depreciation rate (default 0.5%)

        Returns:
            Adjusted price
        """
        age_diff = target_age - comp_age
        adjustment_percent = Decimal(age_diff) * annual_depreciation
        return comp_price * (1 + adjustment_percent)

    @staticmethod
    def calculate_cma_value(
        comparables: list[Comparable],
        adjustments: dict[str, Decimal] | None = None,
    ) -> Decimal:
        """Calculate CMA value from adjusted comparables.

        Args:
            comparables: List of comparable properties with sales data
            adjustments: Optional dict of adjustment factors

        Returns:
            Estimated property value

        Raises:
            InsufficientDataError: If fewer than 3 comparables
        """
        if len(comparables) < 3:
            raise InsufficientDataError(f"Need at least 3 comparables, found {len(comparables)}")

        adjusted_prices = []
        for comp in comparables:
            price = comp.sale_price
            if adjustments:
                for factor_name, factor in adjustments.items():
                    price = price * (1 + factor)
            adjusted_prices.append(price)

        median_price = Decimal(statistics.median(adjusted_prices))
        return median_price


class IncomeApproach:
    """Income approach to property valuation."""

    @staticmethod
    def calculate_noi(
        gross_rental_income: Decimal,
        vacancy_rate: Decimal,
        operating_expenses: Decimal,
    ) -> Decimal:
        """Calculate Net Operating Income (NOI).

        NOI = (Gross Rental Income × (1 - Vacancy Rate)) - Operating Expenses

        Args:
            gross_rental_income: Annual gross rental income
            vacancy_rate: Vacancy rate as decimal (e.g., 0.05 for 5%)
            operating_expenses: Annual operating expenses

        Returns:
            Net Operating Income
        """
        effective_gross_income = gross_rental_income * (1 - vacancy_rate)
        noi = effective_gross_income - operating_expenses
        return noi

    @staticmethod
    def calculate_cap_rate(noi: Decimal, value: Decimal) -> Decimal:
        """Calculate capitalization rate.

        Cap Rate = NOI / Property Value

        Args:
            noi: Net Operating Income
            value: Property value

        Returns:
            Cap rate as decimal (e.g., 0.08 for 8%)

        Raises:
            ValueError: If value is zero
        """
        if value == 0:
            raise ValueError("Property value must be non-zero")
        return noi / value

    @staticmethod
    def value_from_cap_rate(noi: Decimal, cap_rate: Decimal) -> Decimal:
        """Calculate property value from NOI and cap rate.

        Value = NOI / Cap Rate

        Args:
            noi: Net Operating Income
            cap_rate: Target capitalization rate as decimal

        Returns:
            Estimated property value

        Raises:
            ValueError: If cap rate is zero
        """
        if cap_rate == 0:
            raise ValueError("Cap rate must be non-zero")
        return noi / cap_rate

    @staticmethod
    def calculate_gim(annual_income: Decimal, value: Decimal) -> Decimal:
        """Calculate Gross Income Multiplier.

        GIM = Property Value / Gross Annual Income

        Args:
            annual_income: Gross annual income
            value: Property value

        Returns:
            Gross Income Multiplier

        Raises:
            ValueError: If annual_income is zero
        """
        if annual_income == 0:
            raise ValueError("Annual income must be non-zero")
        return value / annual_income


class CostApproach:
    """Cost approach to property valuation."""

    @staticmethod
    def calculate_replacement_cost(
        sqft: int,
        cost_per_sqft: Decimal,
        site_improvements: Decimal = Decimal("0"),
    ) -> Decimal:
        """Calculate replacement cost of structure.

        Args:
            sqft: Building square footage
            cost_per_sqft: Construction cost per square foot
            site_improvements: Cost of site improvements

        Returns:
            Total replacement cost
        """
        building_cost = Decimal(sqft) * cost_per_sqft
        return building_cost + site_improvements

    @staticmethod
    def calculate_depreciation(
        replacement_cost: Decimal,
        property_age: int,
        useful_life: int = 50,
    ) -> Decimal:
        """Calculate straight-line depreciation.

        Args:
            replacement_cost: Replacement cost of structure
            property_age: Property age in years
            useful_life: Useful life of structure in years (default 50)

        Returns:
            Total accumulated depreciation
        """
        annual_depreciation = replacement_cost / Decimal(useful_life)
        total_depreciation = annual_depreciation * Decimal(property_age)
        return min(total_depreciation, replacement_cost)

    @staticmethod
    def calculate_cost_approach_value(
        land_value: Decimal,
        replacement_cost: Decimal,
        depreciation: Decimal,
    ) -> Decimal:
        """Calculate property value using cost approach.

        Value = Land Value + (Replacement Cost - Depreciation)

        Args:
            land_value: Estimated land value
            replacement_cost: Replacement cost of improvements
            depreciation: Accumulated depreciation

        Returns:
            Estimated property value
        """
        return land_value + (replacement_cost - depreciation)


class AutomatedValuationModel:
    """Automated Valuation Model (AVM) using regression."""

    def __init__(self) -> None:
        """Initialize AVM with default coefficients."""
        self.coefficients = {
            "intercept": Decimal("100000"),
            "sqft": Decimal("150"),
            "bedrooms": Decimal("25000"),
            "bathrooms": Decimal("20000"),
            "age": Decimal("-500"),
            "lot_sqft": Decimal("10"),
        }

    def set_coefficients(self, coefficients: dict[str, Decimal]) -> None:
        """Set custom regression coefficients.

        Args:
            coefficients: Dictionary of feature coefficients
        """
        self.coefficients = coefficients

    def train_from_comparables(self, comparables: list[Comparable]) -> None:
        """Train AVM coefficients from comparable sales.

        Simplified training using average price adjustments.

        Args:
            comparables: List of comparable sales with known prices
        """
        if len(comparables) < 5:
            raise InsufficientDataError("Need at least 5 comparables to train")

        avg_price = sum(c.sale_price for c in comparables) / Decimal(len(comparables))
        avg_sqft = statistics.mean(c.sqft for c in comparables)
        avg_beds = statistics.mean(c.bedrooms for c in comparables)
        avg_baths = statistics.mean(c.bathrooms for c in comparables)
        avg_age = statistics.mean(c.age_years for c in comparables)

        sqft_impact = avg_price * Decimal("0.00025")
        bed_impact = avg_price * Decimal("0.05")
        bath_impact = avg_price * Decimal("0.04")
        age_impact = -avg_price * Decimal("0.001")

        self.coefficients = {
            "intercept": avg_price
            - (
                sqft_impact * Decimal(avg_sqft)
                + bed_impact * Decimal(avg_beds)
                + bath_impact * Decimal(avg_baths)
                + age_impact * Decimal(avg_age)
            ),
            "sqft": sqft_impact,
            "bedrooms": bed_impact,
            "bathrooms": bath_impact,
            "age": age_impact,
            "lot_sqft": Decimal("0"),
        }

    def predict_value(self, prop: Property) -> Decimal:
        """Predict property value using trained model.

        Args:
            prop: Property to value

        Returns:
            Predicted property value
        """
        value = self.coefficients["intercept"]
        value += self.coefficients["sqft"] * Decimal(prop.sqft)
        value += self.coefficients["bedrooms"] * Decimal(prop.bedrooms)
        value += self.coefficients["bathrooms"] * prop.bathrooms
        value += self.coefficients["age"] * Decimal(prop.age_years())
        value += self.coefficients["lot_sqft"] * Decimal(prop.lot_sqft)

        return max(value, Decimal("0"))

    def predict_with_confidence(self, prop: Property, comparables: list[Comparable]) -> tuple[Decimal, float]:
        """Predict property value with confidence interval.

        Args:
            prop: Property to value
            comparables: List of comparable properties for confidence calc

        Returns:
            Tuple of (predicted value, confidence score 0-1)
        """
        predicted = self.predict_value(prop)

        if len(comparables) < 2:
            confidence = 0.5
        else:
            prices = [c.sale_price for c in comparables]
            mean = sum(prices) / Decimal(len(prices))
            variance = sum((p - mean) ** 2 for p in prices) / Decimal(len(prices))
            std_dev = float(variance ** Decimal("0.5"))
            coeff_var = std_dev / float(mean) if mean != 0 else 1
            confidence = max(0.0, 1.0 - coeff_var)

        return (predicted, confidence)


class PricePerSquareFoot:
    """Price per square foot analysis."""

    @staticmethod
    def calculate(price: Decimal, sqft: int) -> Decimal:
        """Calculate price per square foot.

        Args:
            price: Property price
            sqft: Square footage

        Returns:
            Price per square foot

        Raises:
            ValueError: If sqft is zero
        """
        if sqft == 0:
            raise ValueError("Square footage must be non-zero")
        return price / Decimal(sqft)

    @staticmethod
    def market_average(comparables: list[Comparable]) -> Decimal:
        """Calculate market average price per square foot.

        Args:
            comparables: List of comparable properties

        Returns:
            Average price per square foot

        Raises:
            InsufficientDataError: If no comparables provided
        """
        if not comparables:
            raise InsufficientDataError("No comparable properties provided")

        ppsf_list = [PricePerSquareFoot.calculate(c.sale_price, c.sqft) for c in comparables]
        return Decimal(statistics.mean(ppsf_list))

    @staticmethod
    def estimate_value(sqft: int, market_ppsf: Decimal) -> Decimal:
        """Estimate property value from size and market rate.

        Args:
            sqft: Property square footage
            market_ppsf: Market price per square foot

        Returns:
            Estimated value
        """
        return Decimal(sqft) * market_ppsf


class AppreciationForecasting:
    """Property appreciation and value forecasting."""

    @staticmethod
    def linear_appreciation(
        current_value: Decimal,
        annual_rate: Decimal,
        years: int,
    ) -> Decimal:
        """Forecast value with linear appreciation.

        Args:
            current_value: Current property value
            annual_rate: Annual appreciation rate as decimal (e.g., 0.03)
            years: Number of years to forecast

        Returns:
            Projected value
        """
        appreciation = current_value * annual_rate * Decimal(years)
        return current_value + appreciation

    @staticmethod
    def compound_appreciation(
        current_value: Decimal,
        annual_rate: Decimal,
        years: int,
    ) -> Decimal:
        """Forecast value with compound appreciation.

        Args:
            current_value: Current property value
            annual_rate: Annual appreciation rate as decimal
            years: Number of years to forecast

        Returns:
            Projected value
        """
        return current_value * ((1 + annual_rate) ** years)

    @staticmethod
    def historical_trend_forecast(
        historical_values: list[tuple[date, Decimal]], forecast_years: int
    ) -> list[tuple[date, Decimal]]:
        """Forecast future values using historical trend.

        Uses linear regression on historical data.

        Args:
            historical_values: List of (date, value) tuples
            forecast_years: Number of years to forecast

        Returns:
            List of (date, projected value) tuples
        """
        if len(historical_values) < 2:
            raise InsufficientDataError("Need at least 2 historical data points")

        x_values = [(d - historical_values[0][0]).days / 365.25 for d, v in historical_values]
        y_values = [float(v) for d, v in historical_values]

        x_mean = statistics.mean(x_values)
        y_mean = statistics.mean(y_values)

        numerator = sum((x_values[i] - x_mean) * (y_values[i] - y_mean) for i in range(len(x_values)))
        denominator = sum((x_values[i] - x_mean) ** 2 for i in range(len(x_values)))

        if denominator == 0:
            slope = 0
        else:
            slope = numerator / denominator

        intercept = y_mean - slope * x_mean

        forecasts = []
        last_date = historical_values[-1][0]

        for year in range(1, forecast_years + 1):
            forecast_date = last_date.replace(year=last_date.year + year)
            days_out = (forecast_date - historical_values[0][0]).days / 365.25
            forecast_value = Decimal(str(intercept + slope * days_out))
            forecasts.append((forecast_date, forecast_value))

        return forecasts
