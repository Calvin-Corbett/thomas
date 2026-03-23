"""Mortgage calculations and amortization."""

from datetime import date, timedelta
from decimal import Decimal


class MortgageCalculator:
    """Standard mortgage payment and amortization calculations."""

    @staticmethod
    def monthly_payment(principal: Decimal, annual_rate: Decimal, term_months: int) -> Decimal:
        """Calculate monthly mortgage payment.

        Uses standard amortization formula:
        M = P * [r(1+r)^n] / [(1+r)^n - 1]
        where P = principal, r = monthly rate, n = number of payments

        Args:
            principal: Loan amount
            annual_rate: Annual interest rate (e.g., 0.065 for 6.5%)
            term_months: Loan term in months

        Returns:
            Monthly payment amount

        Raises:
            ValueError: If term_months is zero
        """
        if term_months == 0:
            raise ValueError("Term must be greater than zero")

        if annual_rate == 0:
            return principal / Decimal(term_months)

        monthly_rate = annual_rate / Decimal(12)
        numerator = monthly_rate * ((1 + monthly_rate) ** term_months)
        denominator = ((1 + monthly_rate) ** term_months) - 1

        return principal * (numerator / denominator)

    @staticmethod
    def total_interest(principal: Decimal, monthly_payment: Decimal, term_months: int) -> Decimal:
        """Calculate total interest paid over loan term.

        Args:
            principal: Loan amount
            monthly_payment: Monthly payment amount
            term_months: Loan term in months

        Returns:
            Total interest paid
        """
        total_paid = monthly_payment * Decimal(term_months)
        return total_paid - principal

    @staticmethod
    def amortization_schedule(
        principal: Decimal, annual_rate: Decimal, term_months: int
    ) -> list[tuple[int, Decimal, Decimal, Decimal]]:
        """Generate full amortization schedule.

        Args:
            principal: Loan amount
            annual_rate: Annual interest rate
            term_months: Loan term in months

        Returns:
            List of (month, payment, principal, balance) tuples
        """
        payment = MortgageCalculator.monthly_payment(principal, annual_rate, term_months)
        monthly_rate = annual_rate / Decimal(12)

        schedule = []
        balance = principal

        for month in range(1, term_months + 1):
            interest_payment = balance * monthly_rate
            principal_payment = payment - interest_payment
            balance = balance - principal_payment

            schedule.append((month, payment, principal_payment, balance))

        return schedule

    @staticmethod
    def remaining_balance(
        principal: Decimal,
        annual_rate: Decimal,
        term_months: int,
        months_paid: int,
    ) -> Decimal:
        """Calculate remaining balance after N payments.

        Args:
            principal: Original loan amount
            annual_rate: Annual interest rate
            term_months: Original loan term
            months_paid: Number of months paid

        Returns:
            Remaining balance
        """
        schedule = MortgageCalculator.amortization_schedule(principal, annual_rate, term_months)

        if months_paid >= len(schedule):
            return Decimal("0")

        return schedule[months_paid - 1][3]


class APRCalculation:
    """APR and effective rate calculations."""

    @staticmethod
    def apr_from_closing_costs(
        nominal_rate: Decimal,
        principal: Decimal,
        closing_costs: Decimal,
        term_months: int,
    ) -> Decimal:
        """Calculate APR including closing costs.

        Args:
            nominal_rate: Nominal interest rate
            principal: Loan amount
            closing_costs: Closing costs
            term_months: Loan term

        Returns:
            APR as decimal

        Raises:
            ValueError: If principal or closing costs invalid
        """
        if principal <= 0:
            raise ValueError("Principal must be positive")

        net_proceeds = principal - closing_costs
        if net_proceeds <= 0:
            raise ValueError("Closing costs exceed principal")

        monthly_payment = MortgageCalculator.monthly_payment(principal, nominal_rate, term_months)

        monthly_rate = Decimal("0.005")
        for _ in range(100):
            pv = Decimal("0")
            for month in range(1, term_months + 1):
                pv += monthly_payment / ((1 + monthly_rate) ** month)

            if abs(pv - net_proceeds) < Decimal("1"):
                break

            if pv > net_proceeds:
                monthly_rate += Decimal("0.00001")
            else:
                monthly_rate -= Decimal("0.00001")

        apr = monthly_rate * Decimal(12)
        return apr

    @staticmethod
    def yield_from_points(nominal_rate: Decimal, points_percentage: Decimal) -> Decimal:
        """Estimate yield impact of discount points.

        Each point typically equals 1% of loan amount and reduces rate by ~0.25%.

        Args:
            nominal_rate: Nominal interest rate
            points_percentage: Points as percentage (e.g., 0.02 for 2 points)

        Returns:
            Yield as decimal
        """
        rate_reduction = points_percentage * Decimal("0.25")
        return nominal_rate - rate_reduction


class AffordabilityCalculator:
    """Mortgage affordability and qualification analysis."""

    @staticmethod
    def max_loan_amount_28_rule(monthly_income: Decimal, annual_rate: Decimal, term_months: int = 360) -> Decimal:
        """Calculate maximum loan amount using 28% debt-to-income rule.

        28% rule: Housing costs cannot exceed 28% of gross monthly income.

        Args:
            monthly_income: Gross monthly income
            annual_rate: Annual interest rate
            term_months: Loan term in months (default 360 for 30 years)

        Returns:
            Maximum loan amount
        """
        max_monthly_payment = monthly_income * Decimal("0.28")
        monthly_rate = annual_rate / Decimal(12)

        if monthly_rate == 0:
            return max_monthly_payment * Decimal(term_months)

        numerator = max_monthly_payment * (((1 + monthly_rate) ** term_months) - 1)
        denominator = monthly_rate * ((1 + monthly_rate) ** term_months)

        return numerator / denominator

    @staticmethod
    def max_loan_amount_36_rule(
        monthly_income: Decimal,
        other_debt_monthly: Decimal,
        annual_rate: Decimal,
        term_months: int = 360,
    ) -> Decimal:
        """Calculate maximum loan amount using 36% debt-to-income rule.

        36% rule: Total debt payments cannot exceed 36% of gross monthly income.

        Args:
            monthly_income: Gross monthly income
            other_debt_monthly: Other monthly debt obligations
            annual_rate: Annual interest rate
            term_months: Loan term in months (default 360 for 30 years)

        Returns:
            Maximum loan amount
        """
        max_total_debt = monthly_income * Decimal("0.36")
        max_mortgage_payment = max_total_debt - other_debt_monthly

        if max_mortgage_payment <= 0:
            return Decimal("0")

        monthly_rate = annual_rate / Decimal(12)

        if monthly_rate == 0:
            return max_mortgage_payment * Decimal(term_months)

        numerator = max_mortgage_payment * (((1 + monthly_rate) ** term_months) - 1)
        denominator = monthly_rate * ((1 + monthly_rate) ** term_months)

        return numerator / denominator

    @staticmethod
    def debt_to_income_ratio(
        monthly_mortgage: Decimal,
        other_monthly_debt: Decimal,
        monthly_income: Decimal,
    ) -> Decimal:
        """Calculate debt-to-income ratio.

        Args:
            monthly_mortgage: Monthly mortgage payment
            other_monthly_debt: Other monthly debt
            monthly_income: Gross monthly income

        Returns:
            DTI ratio as decimal (e.g., 0.36 for 36%)

        Raises:
            ValueError: If income is zero
        """
        if monthly_income == 0:
            raise ValueError("Monthly income must be non-zero")

        total_debt = monthly_mortgage + other_monthly_debt
        return total_debt / monthly_income


class MortgageComparison:
    """Comparison of mortgage options."""

    @staticmethod
    def compare_terms(
        principal: Decimal,
        annual_rate: Decimal,
        terms_months: list[int],
    ) -> list[tuple[int, Decimal, Decimal]]:
        """Compare payments for different loan terms.

        Args:
            principal: Loan amount
            annual_rate: Annual interest rate
            terms_months: List of terms to compare

        Returns:
            List of (term, monthly_payment, total_interest) tuples
        """
        results = []
        for term in terms_months:
            payment = MortgageCalculator.monthly_payment(principal, annual_rate, term)
            total_interest = MortgageCalculator.total_interest(principal, payment, term)
            results.append((term, payment, total_interest))

        return results

    @staticmethod
    def compare_rates(
        principal: Decimal,
        term_months: int,
        rates: list[Decimal],
    ) -> list[tuple[Decimal, Decimal, Decimal]]:
        """Compare payments for different interest rates.

        Args:
            principal: Loan amount
            term_months: Loan term in months
            rates: List of interest rates to compare

        Returns:
            List of (rate, monthly_payment, total_interest) tuples
        """
        results = []
        for rate in rates:
            payment = MortgageCalculator.monthly_payment(principal, rate, term_months)
            total_interest = MortgageCalculator.total_interest(principal, payment, term_months)
            results.append((rate, payment, total_interest))

        return results


class RefinanceAnalysis:
    """Refinance break-even and analysis."""

    @staticmethod
    def refinance_break_even(
        remaining_balance: Decimal,
        old_rate: Decimal,
        new_rate: Decimal,
        remaining_months: int,
        new_term_months: int,
        refinance_costs: Decimal,
    ) -> int:
        """Calculate break-even months for refinance.

        Args:
            remaining_balance: Current loan balance
            old_rate: Current annual interest rate
            new_rate: New annual interest rate
            remaining_months: Months remaining on old loan
            new_term_months: Term of new loan
            refinance_costs: Total refinance costs

        Returns:
            Months until refinance breaks even (payoff costs)
        """
        old_payment = MortgageCalculator.monthly_payment(remaining_balance, old_rate, remaining_months)
        new_payment = MortgageCalculator.monthly_payment(remaining_balance, new_rate, new_term_months)

        monthly_savings = old_payment - new_payment

        if monthly_savings <= 0:
            return 99999

        break_even_months = int(refinance_costs / monthly_savings)
        return break_even_months

    @staticmethod
    def should_refinance(
        remaining_balance: Decimal,
        old_rate: Decimal,
        new_rate: Decimal,
        remaining_months: int,
        new_term_months: int,
        refinance_costs: Decimal,
        months_to_breakeven_threshold: int = 36,
    ) -> bool:
        """Determine if refinance makes financial sense.

        Args:
            remaining_balance: Current loan balance
            old_rate: Current rate
            new_rate: New rate
            remaining_months: Remaining term
            new_term_months: New term
            refinance_costs: Refinance costs
            months_to_breakeven_threshold: Max acceptable breakeven (default 36)

        Returns:
            True if refinance recommended
        """
        break_even = RefinanceAnalysis.refinance_break_even(
            remaining_balance,
            old_rate,
            new_rate,
            remaining_months,
            new_term_months,
            refinance_costs,
        )
        return break_even <= months_to_breakeven_threshold


class ARMSimulation:
    """ARM (Adjustable Rate Mortgage) simulation."""

    @staticmethod
    def simulate_arm_adjustments(
        principal: Decimal,
        initial_rate: Decimal,
        initial_term_months: int,
        adjustment_dates: list[date],
        adjustment_rates: list[Decimal],
        rate_cap: Decimal | None = None,
    ) -> list[tuple[date, Decimal, Decimal]]:
        """Simulate ARM rate adjustments and payment changes.

        Args:
            principal: Loan amount
            initial_rate: Initial ARM rate
            initial_term_months: Initial fixed period
            adjustment_dates: Dates of rate adjustments
            adjustment_rates: New rates at adjustment dates
            rate_cap: Maximum rate cap (if any)

        Returns:
            List of (date, new_rate, new_payment) tuples
        """
        results = []
        current_rate = initial_rate
        remaining_balance = principal
        remaining_term = initial_term_months

        for adj_date, new_rate in zip(adjustment_dates, adjustment_rates):
            if rate_cap and new_rate > rate_cap:
                new_rate = rate_cap

            schedule = MortgageCalculator.amortization_schedule(remaining_balance, current_rate, remaining_term)
            if schedule:
                remaining_balance = schedule[-1][3]

            new_payment = MortgageCalculator.monthly_payment(remaining_balance, new_rate, remaining_term)

            results.append((adj_date, new_rate, new_payment))

            current_rate = new_rate

        return results


class PMICalculation:
    """PMI (Private Mortgage Insurance) calculation."""

    @staticmethod
    def calculate_pmi_rate(
        loan_to_value_ratio: Decimal,
    ) -> Decimal:
        """Calculate PMI rate based on LTV.

        Typical PMI rates:
        - LTV 80-84%: 0.40-0.60% annually
        - LTV 85-89%: 0.55-0.80% annually
        - LTV 90-94%: 0.75-1.00% annually
        - LTV 95%+: 1.00-1.25% annually

        Args:
            loan_to_value_ratio: LTV as decimal (e.g., 0.90 for 90%)

        Returns:
            Annual PMI rate as decimal
        """
        if loan_to_value_ratio <= Decimal("0.80"):
            return Decimal("0")
        elif loan_to_value_ratio <= Decimal("0.84"):
            return Decimal("0.005")
        elif loan_to_value_ratio <= Decimal("0.89"):
            return Decimal("0.0065")
        elif loan_to_value_ratio <= Decimal("0.94"):
            return Decimal("0.0085")
        else:
            return Decimal("0.0110")

    @staticmethod
    def calculate_monthly_pmi(loan_amount: Decimal, pmi_rate: Decimal) -> Decimal:
        """Calculate monthly PMI payment.

        Args:
            loan_amount: Loan amount
            pmi_rate: Annual PMI rate

        Returns:
            Monthly PMI payment
        """
        return loan_amount * pmi_rate / Decimal(12)

    @staticmethod
    def pmi_payoff_date(
        principal: Decimal,
        down_payment: Decimal,
        annual_rate: Decimal,
        term_months: int,
        appreciation_rate: Decimal = Decimal("0.03"),
    ) -> date:
        """Estimate when PMI can be removed.

        PMI typically removed when equity reaches 20%.

        Args:
            principal: Loan amount
            down_payment: Down payment amount
            annual_rate: Interest rate
            term_months: Loan term
            appreciation_rate: Expected annual appreciation

        Returns:
            Estimated date PMI can be removed
        """
        home_value = principal + down_payment
        current_equity = down_payment / home_value

        schedule = MortgageCalculator.amortization_schedule(principal, annual_rate, term_months)

        for month, _, _, balance in schedule:
            appreciated_value = home_value * ((1 + appreciation_rate) ** (month / 12))
            equity = (principal - balance) / appreciated_value + (down_payment / home_value)

            if equity >= Decimal("0.20"):
                start_date = date.today()
                return start_date + timedelta(days=month * 30)

        return date.today() + timedelta(days=term_months * 30)
