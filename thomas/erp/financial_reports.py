"""
Financial reporting and analysis.

Generates income statements, balance sheets, cash flow statements,
and financial ratios.
"""

from datetime import date
from decimal import Decimal

from thomas.erp._types import AccountType


class FinancialReporter:
    """
    Financial reporting engine.

    Generates statements and calculates ratios from general ledger data.
    """

    def __init__(self, general_ledger: any) -> None:
        """
        Initialize financial reporter.

        Args:
            general_ledger: GeneralLedger instance
        """
        self.gl = general_ledger

    def income_statement(
        self,
        period_start: date,
        period_end: date,
        department_id: str | None = None,
    ) -> dict[str, Decimal]:
        """
        Generate income statement (P&L) for a period.

        Args:
            period_start: Start of period
            period_end: End of period
            department_id: Filter by department (optional)

        Returns:
            Statement line items with amounts
        """
        revenue = Decimal("0.00")
        cogs = Decimal("0.00")
        expenses = Decimal("0.00")

        for account_id, account in self.gl.accounts.items():
            balance = self.gl.get_account_balance(account_id, period_end)

            if account.account_type == AccountType.REVENUE:
                revenue += balance
            elif account.account_type == AccountType.COGS:
                cogs += balance
            elif account.account_type == AccountType.EXPENSE:
                expenses += balance

        gross_profit = revenue - cogs
        net_income = gross_profit - expenses

        return {
            "revenue": revenue,
            "cost_of_goods_sold": cogs,
            "gross_profit": gross_profit,
            "operating_expenses": expenses,
            "net_income": net_income,
        }

    def balance_sheet(self, as_of_date: date) -> dict[str, dict[str, Decimal]]:
        """
        Generate balance sheet as of a date.

        Equation: Assets = Liabilities + Equity

        Args:
            as_of_date: Reporting date

        Returns:
            Dictionary with assets, liabilities, and equity sections
        """
        assets = Decimal("0.00")
        liabilities = Decimal("0.00")
        equity = Decimal("0.00")

        for account_id, account in self.gl.accounts.items():
            balance = self.gl.get_account_balance(account_id, as_of_date)

            if account.account_type == AccountType.ASSET:
                assets += balance
            elif account.account_type == AccountType.CONTRA_ASSET:
                assets -= balance
            elif account.account_type == AccountType.LIABILITY:
                liabilities += balance
            elif account.account_type == AccountType.EQUITY:
                equity += balance

        return {
            "assets": {"total": assets},
            "liabilities": {"total": liabilities},
            "equity": {"total": equity},
            "total_liabilities_and_equity": liabilities + equity,
        }

    def cash_flow_statement(
        self,
        period_start: date,
        period_end: date,
    ) -> dict[str, dict[str, Decimal]]:
        """
        Generate cash flow statement.

        Categories: operating, investing, financing activities.

        Args:
            period_start: Start of period
            period_end: End of period

        Returns:
            Cash flow by category
        """
        operating = Decimal("0.00")
        investing = Decimal("0.00")
        financing = Decimal("0.00")

        entries = self.gl.get_journal_entries(period_start, period_end)

        for entry in entries:
            for line in entry.lines:
                account = self.gl.accounts.get(line.account_id)
                if not account:
                    continue

                amount = line.get_amount()

                if (
                    account.account_type == AccountType.ASSET
                    and account.id.startswith("11")
                    or account.account_type == AccountType.LIABILITY
                    and account.id.startswith("21")
                ):
                    operating += amount
                elif account.account_type == AccountType.ASSET and account.id.startswith("12"):
                    investing += amount
                elif account.account_type == AccountType.LIABILITY and account.id.startswith("22"):
                    financing += amount

        net_change = operating + investing + financing

        return {
            "operating_activities": {"net": operating},
            "investing_activities": {"net": investing},
            "financing_activities": {"net": financing},
            "net_change_in_cash": net_change,
        }

    def budget_vs_actual(
        self,
        period_end: date,
        budget: dict[str, Decimal],
    ) -> dict[str, dict[str, Decimal]]:
        """
        Compare actual results to budget.

        Args:
            period_end: Period end date
            budget: Map of account_id to budgeted amount

        Returns:
            Budget vs actual comparison with variances
        """
        comparison: dict[str, dict[str, Decimal]] = {}

        for account_id, budgeted_amount in budget.items():
            if account_id not in self.gl.accounts:
                continue

            actual_amount = self.gl.get_account_balance(account_id, period_end)
            variance = actual_amount - budgeted_amount
            variance_pct = Decimal("0.00")

            if budgeted_amount != Decimal("0.00"):
                variance_pct = (variance / budgeted_amount) * Decimal("100.00")

            comparison[account_id] = {
                "budget": budgeted_amount,
                "actual": actual_amount,
                "variance": variance,
                "variance_percent": variance_pct,
            }

        return comparison

    def departmental_pl(
        self,
        period_start: date,
        period_end: date,
        departments: list[str],
    ) -> dict[str, dict[str, Decimal]]:
        """
        Generate P&L by department.

        Args:
            period_start: Period start
            period_end: Period end
            departments: List of department IDs

        Returns:
            P&L results by department
        """
        dept_pl: dict[str, dict[str, Decimal]] = {}

        for dept_id in departments:
            dept_pl[dept_id] = {
                "revenue": Decimal("0.00"),
                "cogs": Decimal("0.00"),
                "expenses": Decimal("0.00"),
                "gross_profit": Decimal("0.00"),
                "net_income": Decimal("0.00"),
            }

        entries = self.gl.get_journal_entries(period_start, period_end)

        for entry in entries:
            for line in entry.lines:
                if not line.reference:
                    continue

                dept_id = line.reference.split("_")[0]
                if dept_id not in departments:
                    continue

                account = self.gl.accounts.get(line.account_id)
                if not account:
                    continue

                amount = line.get_amount()

                if account.account_type == AccountType.REVENUE:
                    dept_pl[dept_id]["revenue"] += amount
                elif account.account_type == AccountType.COGS:
                    dept_pl[dept_id]["cogs"] += amount
                elif account.account_type == AccountType.EXPENSE:
                    dept_pl[dept_id]["expenses"] += amount

        for dept_id in departments:
            dept_pl[dept_id]["gross_profit"] = dept_pl[dept_id]["revenue"] - dept_pl[dept_id]["cogs"]
            dept_pl[dept_id]["net_income"] = dept_pl[dept_id]["gross_profit"] - dept_pl[dept_id]["expenses"]

        return dept_pl

    def current_ratio(self, as_of_date: date) -> Decimal:
        """
        Calculate current ratio (current assets / current liabilities).

        Measures short-term liquidity.

        Args:
            as_of_date: Reporting date

        Returns:
            Current ratio

        Raises:
            ValueError: If current liabilities are zero
        """
        current_assets = Decimal("0.00")
        current_liabilities = Decimal("0.00")

        for account_id, account in self.gl.accounts.items():
            balance = self.gl.get_account_balance(account_id, as_of_date)

            if account.account_type == AccountType.ASSET and account.id.startswith("1"):
                current_assets += balance
            elif account.account_type == AccountType.LIABILITY and account.id.startswith("2"):
                current_liabilities += balance

        if current_liabilities == Decimal("0.00"):
            raise ValueError("Current liabilities cannot be zero for ratio calculation")

        return current_assets / current_liabilities

    def quick_ratio(self, as_of_date: date) -> Decimal:
        """
        Calculate quick ratio (liquid assets / current liabilities).

        More conservative than current ratio; excludes inventory.

        Args:
            as_of_date: Reporting date

        Returns:
            Quick ratio

        Raises:
            ValueError: If current liabilities are zero
        """
        quick_assets = Decimal("0.00")
        current_liabilities = Decimal("0.00")

        for account_id, account in self.gl.accounts.items():
            balance = self.gl.get_account_balance(account_id, as_of_date)

            if account.account_type == AccountType.ASSET:
                if not account.id.startswith("1200"):
                    quick_assets += balance
            elif account.account_type == AccountType.LIABILITY and account.id.startswith("2"):
                current_liabilities += balance

        if current_liabilities == Decimal("0.00"):
            raise ValueError("Current liabilities cannot be zero for ratio calculation")

        return quick_assets / current_liabilities

    def return_on_equity(
        self,
        period_start: date,
        period_end: date,
    ) -> Decimal:
        """
        Calculate return on equity (net income / average equity).

        Measures profitability relative to shareholder investment.

        Args:
            period_start: Period start
            period_end: Period end

        Returns:
            ROE as percentage

        Raises:
            ValueError: If equity is zero
        """
        net_income = Decimal("0.00")

        for account in self.gl.accounts.values():
            if account.account_type == AccountType.REVENUE:
                ni = self.gl.get_account_balance(account.id, period_end)
                net_income += ni
            elif account.account_type == AccountType.EXPENSE:
                ni = self.gl.get_account_balance(account.id, period_end)
                net_income -= ni

        start_equity = Decimal("0.00")
        end_equity = Decimal("0.00")

        for account in self.gl.accounts.values():
            if account.account_type == AccountType.EQUITY:
                start_eq = self.gl.get_account_balance(account.id, period_start)
                end_eq = self.gl.get_account_balance(account.id, period_end)
                start_equity += start_eq
                end_equity += end_eq

        average_equity = (start_equity + end_equity) / Decimal("2.00")

        if average_equity == Decimal("0.00"):
            raise ValueError("Equity cannot be zero for ROE calculation")

        return (net_income / average_equity) * Decimal("100.00")

    def return_on_assets(
        self,
        period_start: date,
        period_end: date,
    ) -> Decimal:
        """
        Calculate return on assets (net income / average assets).

        Measures how efficiently assets generate profit.

        Args:
            period_start: Period start
            period_end: Period end

        Returns:
            ROA as percentage

        Raises:
            ValueError: If assets are zero
        """
        net_income = Decimal("0.00")

        for account in self.gl.accounts.values():
            if account.account_type == AccountType.REVENUE:
                ni = self.gl.get_account_balance(account.id, period_end)
                net_income += ni
            elif account.account_type == AccountType.EXPENSE:
                ni = self.gl.get_account_balance(account.id, period_end)
                net_income -= ni

        start_assets = Decimal("0.00")
        end_assets = Decimal("0.00")

        for account in self.gl.accounts.values():
            if account.account_type == AccountType.ASSET:
                start_ast = self.gl.get_account_balance(account.id, period_start)
                end_ast = self.gl.get_account_balance(account.id, period_end)
                start_assets += start_ast
                end_assets += end_ast

        average_assets = (start_assets + end_assets) / Decimal("2.00")

        if average_assets == Decimal("0.00"):
            raise ValueError("Assets cannot be zero for ROA calculation")

        return (net_income / average_assets) * Decimal("100.00")

    def debt_to_equity_ratio(self, as_of_date: date) -> Decimal:
        """
        Calculate debt-to-equity ratio (total liabilities / total equity).

        Measures financial leverage and solvency.

        Args:
            as_of_date: Reporting date

        Returns:
            Debt-to-equity ratio

        Raises:
            ValueError: If equity is zero
        """
        total_liabilities = Decimal("0.00")
        total_equity = Decimal("0.00")

        for account in self.gl.accounts.values():
            balance = self.gl.get_account_balance(account.id, as_of_date)

            if account.account_type == AccountType.LIABILITY:
                total_liabilities += balance
            elif account.account_type == AccountType.EQUITY:
                total_equity += balance

        if total_equity == Decimal("0.00"):
            raise ValueError("Equity cannot be zero for debt-to-equity calculation")

        return total_liabilities / total_equity

    def period_comparison(
        self,
        current_period_end: date,
        prior_period_end: date,
        period_type: str = "MONTHLY",
    ) -> dict[str, dict[str, Decimal]]:
        """
        Compare financial results month-over-month or year-over-year.

        Args:
            current_period_end: Current period end date
            prior_period_end: Prior period end date
            period_type: MONTHLY or YEARLY comparison

        Returns:
            Comparison data with changes and percentages
        """
        comparison: dict[str, dict[str, Decimal]] = {}

        for account_id, account in self.gl.accounts.items():
            if account.account_type not in (
                AccountType.REVENUE,
                AccountType.EXPENSE,
                AccountType.COGS,
            ):
                continue

            current = self.gl.get_account_balance(account_id, current_period_end)
            prior = self.gl.get_account_balance(account_id, prior_period_end)
            change = current - prior
            change_pct = Decimal("0.00")

            if prior != Decimal("0.00"):
                change_pct = (change / prior) * Decimal("100.00")

            comparison[account_id] = {
                "current_period": current,
                "prior_period": prior,
                "change": change,
                "change_percent": change_pct,
            }

        return comparison
