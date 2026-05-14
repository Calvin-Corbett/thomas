"""Real estate investment analysis."""

from decimal import Decimal

from thomas.marketplace.real_estate._exceptions import InsufficientDataError


class CashFlowProjection:
    """Cash flow projections and analysis."""

    @staticmethod
    def calculate_annual_cash_flow(
        annual_rental_income: Decimal,
        vacancy_rate: Decimal,
        operating_expenses: Decimal,
        annual_debt_service: Decimal,
    ) -> Decimal:
        """Calculate annual net cash flow.

        Cash Flow = (Rental Income × (1 - Vacancy)) - Operating Expenses - Debt Service

        Args:
            annual_rental_income: Gross annual rental income
            vacancy_rate: Vacancy rate as decimal
            operating_expenses: Annual operating expenses
            annual_debt_service: Annual mortgage payments

        Returns:
            Annual net cash flow
        """
        effective_income = annual_rental_income * (1 - vacancy_rate)
        return effective_income - operating_expenses - annual_debt_service

    @staticmethod
    def project_cash_flows(
        initial_annual_income: Decimal,
        annual_expense_increase: Decimal,
        annual_income_increase: Decimal,
        annual_debt_service: Decimal,
        years: int,
    ) -> list[Decimal]:
        """Project cash flows over multiple years.

        Args:
            initial_annual_income: Starting annual income
            annual_expense_increase: Annual expense growth rate
            annual_income_increase: Annual income growth rate
            annual_debt_service: Annual debt service (constant)
            years: Number of years to project

        Returns:
            List of annual cash flows
        """
        projections = []
        current_income = initial_annual_income

        for year in range(1, years + 1):
            current_income = initial_annual_income * ((1 + annual_income_increase) ** year)
            projections.append(current_income - annual_debt_service)

        return projections

    @staticmethod
    def calculate_cumulative_cash_flow(
        annual_cash_flows: list[Decimal],
    ) -> list[Decimal]:
        """Calculate cumulative cash flow over time.

        Args:
            annual_cash_flows: List of annual cash flows

        Returns:
            List of cumulative cash flows
        """
        cumulative = []
        running_total = Decimal("0")

        for cash_flow in annual_cash_flows:
            running_total += cash_flow
            cumulative.append(running_total)

        return cumulative


class CapRateAnalysis:
    """Cap rate calculation and analysis."""

    @staticmethod
    def calculate_cap_rate(noi: Decimal, purchase_price: Decimal) -> Decimal:
        """Calculate capitalization rate.

        Cap Rate = NOI / Purchase Price

        Args:
            noi: Net Operating Income
            purchase_price: Property purchase price

        Returns:
            Cap rate (e.g., 0.08 for 8%)

        Raises:
            ValueError: If purchase_price is zero
        """
        if purchase_price == 0:
            raise ValueError("Purchase price must be non-zero")

        return noi / purchase_price

    @staticmethod
    def compare_cap_rates(properties: list[tuple[str, Decimal, Decimal]]) -> list[tuple[str, Decimal]]:
        """Compare cap rates across properties.

        Args:
            properties: List of (property_id, NOI, price) tuples

        Returns:
            List of (property_id, cap_rate) tuples sorted by rate descending
        """
        cap_rates = []

        for prop_id, noi, price in properties:
            if price != 0:
                cap_rate = noi / price
                cap_rates.append((prop_id, cap_rate))

        cap_rates.sort(key=lambda x: x[1], reverse=True)
        return cap_rates


class ReturnCalculation:
    """Investment return calculations."""

    @staticmethod
    def cash_on_cash_return(annual_cash_flow: Decimal, cash_invested: Decimal) -> Decimal:
        """Calculate cash-on-cash return.

        Returns = Annual Cash Flow / Cash Invested

        Args:
            annual_cash_flow: Annual net cash flow
            cash_invested: Initial cash invested (down payment + costs)

        Returns:
            Cash-on-cash return (e.g., 0.10 for 10%)

        Raises:
            ValueError: If cash_invested is zero
        """
        if cash_invested == 0:
            raise ValueError("Cash invested must be non-zero")

        return annual_cash_flow / cash_invested

    @staticmethod
    def internal_rate_of_return(
        initial_investment: Decimal,
        cash_flows: list[Decimal],
        sale_proceeds: Decimal,
    ) -> Decimal | None:
        """Calculate IRR using Newton's method.

        Args:
            initial_investment: Initial cash outflow (negative)
            cash_flows: List of annual cash flows
            sale_proceeds: Sale proceeds in final year

        Returns:
            IRR as decimal or None if cannot calculate
        """
        all_flows = [-initial_investment] + cash_flows[:-1] + [cash_flows[-1] + sale_proceeds]

        irr = Decimal("0.1")

        for _ in range(100):
            npv = Decimal("0")
            npv_derivative = Decimal("0")

            for t, cf in enumerate(all_flows):
                npv += cf / ((1 + irr) ** t)
                if t > 0:
                    npv_derivative += -t * cf / ((1 + irr) ** (t + 1))

            if abs(npv) < Decimal("0.01"):
                return irr

            if npv_derivative == 0:
                break

            irr = irr - (npv / npv_derivative)

        return irr if abs(npv) < Decimal("1") else None

    @staticmethod
    def net_present_value(cash_flows: list[Decimal], discount_rate: Decimal) -> Decimal:
        """Calculate net present value.

        NPV = Sum of (Cash Flow / (1 + Discount Rate)^t)

        Args:
            cash_flows: List of cash flows (negative for outflows)
            discount_rate: Discount rate as decimal

        Returns:
            Net present value
        """
        npv = Decimal("0")

        for t, cf in enumerate(cash_flows):
            npv += cf / ((1 + discount_rate) ** t)

        return npv


class LeverageAnalysis:
    """Leverage and financing analysis."""

    @staticmethod
    def debt_service_coverage_ratio(noi: Decimal, annual_debt_service: Decimal) -> Decimal:
        """Calculate DSCR (Debt Service Coverage Ratio).

        DSCR = NOI / Annual Debt Service

        Args:
            noi: Net Operating Income
            annual_debt_service: Annual debt service

        Returns:
            DSCR

        Raises:
            ValueError: If debt service is zero
        """
        if annual_debt_service == 0:
            raise ValueError("Annual debt service must be non-zero")

        return noi / annual_debt_service

    @staticmethod
    def loan_to_value_ratio(loan_amount: Decimal, property_value: Decimal) -> Decimal:
        """Calculate loan-to-value ratio.

        LTV = Loan Amount / Property Value

        Args:
            loan_amount: Loan amount
            property_value: Property value

        Returns:
            LTV (e.g., 0.80 for 80%)

        Raises:
            ValueError: If property_value is zero
        """
        if property_value == 0:
            raise ValueError("Property value must be non-zero")

        return loan_amount / property_value

    @staticmethod
    def equity_ratio(loan_amount: Decimal, property_value: Decimal) -> Decimal:
        """Calculate equity ratio.

        Equity Ratio = (Property Value - Loan Amount) / Property Value

        Args:
            loan_amount: Loan amount
            property_value: Property value

        Returns:
            Equity ratio (e.g., 0.20 for 20%)

        Raises:
            ValueError: If property_value is zero
        """
        if property_value == 0:
            raise ValueError("Property value must be non-zero")

        equity = property_value - loan_amount
        return equity / property_value

    @staticmethod
    def break_even_occupancy_rate(
        monthly_rent: Decimal,
        total_units: int,
        operating_expenses_monthly: Decimal,
        debt_service_monthly: Decimal,
    ) -> Decimal:
        """Calculate break-even occupancy rate.

        Args:
            monthly_rent: Monthly rent per unit
            total_units: Total number of units
            operating_expenses_monthly: Monthly operating expenses
            debt_service_monthly: Monthly debt service

        Returns:
            Break-even occupancy rate (e.g., 0.65 for 65%)
        """
        total_monthly_expenses = operating_expenses_monthly + debt_service_monthly

        if monthly_rent * Decimal(total_units) == 0:
            return Decimal("0")

        occupancy_needed = total_monthly_expenses / (monthly_rent * Decimal(total_units))
        return min(occupancy_needed, Decimal("1"))

    @staticmethod
    def gross_rent_multiplier(property_price: Decimal, annual_gross_rent: Decimal) -> Decimal:
        """Calculate gross rent multiplier.

        GRM = Property Price / Annual Gross Rent

        Args:
            property_price: Property purchase price
            annual_gross_rent: Annual gross rental income

        Returns:
            GRM

        Raises:
            ValueError: If annual_gross_rent is zero
        """
        if annual_gross_rent == 0:
            raise ValueError("Annual gross rent must be non-zero")

        return property_price / annual_gross_rent


class AcquisitionAnalysis:
    """Property acquisition and offer analysis."""

    @staticmethod
    def maximum_offer_price(target_cap_rate: Decimal, noi: Decimal) -> Decimal:
        """Calculate maximum offer price based on target cap rate.

        Max Price = NOI / Target Cap Rate

        Args:
            target_cap_rate: Target cap rate (e.g., 0.08 for 8%)
            noi: Net Operating Income

        Returns:
            Maximum offer price

        Raises:
            ValueError: If target_cap_rate is zero
        """
        if target_cap_rate == 0:
            raise ValueError("Target cap rate must be non-zero")

        return noi / target_cap_rate

    @staticmethod
    def estimate_closing_costs(
        purchase_price: Decimal,
        closing_cost_percentage: Decimal = Decimal("0.02"),
    ) -> Decimal:
        """Estimate total closing costs.

        Args:
            purchase_price: Purchase price
            closing_cost_percentage: Closing costs as % (default 2%)

        Returns:
            Estimated closing costs
        """
        return purchase_price * closing_cost_percentage

    @staticmethod
    def total_capital_required(
        purchase_price: Decimal,
        down_payment_percentage: Decimal,
        closing_costs: Decimal,
        initial_repairs: Decimal = Decimal("0"),
    ) -> Decimal:
        """Calculate total capital required for acquisition.

        Args:
            purchase_price: Purchase price
            down_payment_percentage: Down payment percentage
            closing_costs: Closing costs
            initial_repairs: Initial repair costs

        Returns:
            Total capital required
        """
        down_payment = purchase_price * down_payment_percentage
        return down_payment + closing_costs + initial_repairs


class ExchangeTracking:
    """1031 exchange tracking and analysis."""

    def __init__(self) -> None:
        """Initialize exchange tracker."""
        self._exchanges: dict[str, dict[str, any]] = {}

    def create_exchange(
        self,
        exchange_id: str,
        relinquished_property_id: str,
        relinquished_property_value: Decimal,
    ) -> None:
        """Create a 1031 exchange record.

        Args:
            exchange_id: Unique exchange ID
            relinquished_property_id: Property being exchanged
            relinquished_property_value: Value of relinquished property
        """
        self._exchanges[exchange_id] = {
            "relinquished_property": relinquished_property_id,
            "relinquished_value": relinquished_property_value,
            "replacement_properties": [],
            "like_kind_verified": False,
        }

    def add_replacement_property(self, exchange_id: str, property_id: str, price: Decimal) -> None:
        """Add replacement property to exchange.

        Args:
            exchange_id: Exchange ID
            property_id: Replacement property ID
            price: Purchase price of replacement

        Raises:
            ValueError: If exchange not found
        """
        if exchange_id not in self._exchanges:
            raise ValueError(f"Exchange {exchange_id} not found")

        self._exchanges[exchange_id]["replacement_properties"].append({"property_id": property_id, "price": price})

    def verify_exchange_rules(self, exchange_id: str) -> bool:
        """Verify 1031 exchange meets IRS rules.

        Args:
            exchange_id: Exchange ID

        Returns:
            True if exchange meets rules

        Raises:
            ValueError: If exchange not found
        """
        if exchange_id not in self._exchanges:
            raise ValueError(f"Exchange {exchange_id} not found")

        exchange = self._exchanges[exchange_id]
        relinquished_value = exchange["relinquished_value"]
        replacement_total = sum(p["price"] for p in exchange["replacement_properties"])

        if replacement_total < relinquished_value:
            return False

        return True


class PortfolioAnalysis:
    """Real estate portfolio analysis."""

    @staticmethod
    def portfolio_total_value(properties: list[tuple[str, Decimal]]) -> Decimal:
        """Calculate total portfolio value.

        Args:
            properties: List of (property_id, value) tuples

        Returns:
            Total portfolio value
        """
        return sum(value for _, value in properties)

    @staticmethod
    def portfolio_average_value(properties: list[tuple[str, Decimal]]) -> Decimal:
        """Calculate average property value in portfolio.

        Args:
            properties: List of (property_id, value) tuples

        Returns:
            Average value

        Raises:
            InsufficientDataError: If no properties
        """
        if not properties:
            raise InsufficientDataError("Portfolio is empty")

        total = PortfolioAnalysis.portfolio_total_value(properties)
        return total / Decimal(len(properties))

    @staticmethod
    def portfolio_concentration(
        properties: list[tuple[str, Decimal]],
    ) -> dict[str, Decimal]:
        """Calculate property allocation percentages.

        Args:
            properties: List of (property_id, value) tuples

        Returns:
            Dictionary of property_id -> percentage allocation
        """
        total = PortfolioAnalysis.portfolio_total_value(properties)

        if total == 0:
            return {}

        return {prop_id: (value / total) for prop_id, value in properties}

    @staticmethod
    def portfolio_diversification_score(
        allocations: dict[str, Decimal],
    ) -> float:
        """Calculate portfolio diversification score (0-1).

        Higher score = more diversified.

        Args:
            allocations: Dictionary of property_id -> allocation percentage

        Returns:
            Diversification score
        """
        if not allocations:
            return 0.0

        allocation_values = list(allocations.values())
        if len(allocation_values) == 1:
            return 0.0

        mean_allocation = sum(allocation_values) / len(allocation_values)
        variance = sum((a - mean_allocation) ** 2 for a in allocation_values) / len(allocation_values)

        equal_distribution = Decimal("1") / Decimal(len(allocation_values))
        max_variance = sum((equal_distribution**2) for _ in allocation_values) / len(allocation_values)

        if max_variance == 0:
            return 0.0

        return float(1 - (variance / max_variance))
