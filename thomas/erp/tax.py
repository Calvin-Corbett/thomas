"""
Tax management and reporting.

Handles tax codes, calculations, liability tracking,
and tax return preparation.
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from thomas.erp._exceptions import TaxError


class TaxCode:
    """Tax code definition."""

    def __init__(
        self,
        tax_code_id: str,
        name: str,
        tax_rate: Decimal,
        jurisdiction: str,
        tax_type: str,  # SALES, PURCHASE, VAT, GST, etc.
        is_active: bool = True,
    ) -> None:
        """Initialize tax code."""
        self.tax_code_id = tax_code_id
        self.name = name
        self.tax_rate = tax_rate
        self.jurisdiction = jurisdiction
        self.tax_type = tax_type
        self.is_active = is_active
        self.created_at = datetime.now()


class TaxableTransaction:
    """Record of a taxable transaction."""

    def __init__(
        self,
        transaction_id: str,
        transaction_date: date,
        transaction_type: str,  # SALES, PURCHASE
        amount: Decimal,
        tax_code_id: str,
        description: str = "",
    ) -> None:
        """Initialize taxable transaction."""
        self.transaction_id = transaction_id
        self.transaction_date = transaction_date
        self.transaction_type = transaction_type
        self.amount = amount
        self.tax_code_id = tax_code_id
        self.description = description
        self.recorded_at = datetime.now()


class TaxManager:
    """
    Tax management including calculations, liability tracking,
    and return preparation.
    """

    def __init__(self) -> None:
        """Initialize tax manager."""
        self.tax_codes: dict[str, TaxCode] = {}
        self.transactions: list[TaxableTransaction] = []
        self.tax_liability: dict[str, dict[str, Decimal]] = {}  # period -> {type: liability}
        self.tax_withholding: dict[str, Decimal] = {}  # transaction_id -> withheld_amount
        self.jurisdictional_rules: dict[str, dict[str, Decimal]] = {}  # jurisdiction -> rules
        self.tax_return_data: dict[str, dict[str, any]] = {}  # period -> return_data

    def create_tax_code(
        self,
        tax_code_id: str,
        name: str,
        tax_rate: Decimal,
        jurisdiction: str,
        tax_type: str,
    ) -> TaxCode:
        """
        Create a tax code.

        Args:
            tax_code_id: Unique code identifier
            name: Display name (e.g., "CA Sales Tax")
            tax_rate: Tax rate as percentage (0-100)
            jurisdiction: Jurisdiction code (US-CA, US-NY, etc.)
            tax_type: SALES, PURCHASE, VAT, GST, etc.

        Returns:
            Created TaxCode

        Raises:
            TaxError: If code already exists
        """
        if tax_code_id in self.tax_codes:
            raise TaxError(f"Tax code {tax_code_id} already exists")

        code = TaxCode(tax_code_id, name, tax_rate, jurisdiction, tax_type)
        self.tax_codes[tax_code_id] = code
        return code

    def get_tax_code(self, tax_code_id: str) -> TaxCode:
        """
        Retrieve a tax code.

        Args:
            tax_code_id: Tax code identifier

        Returns:
            TaxCode object

        Raises:
            TaxError: If code not found
        """
        if tax_code_id not in self.tax_codes:
            raise TaxError(f"Tax code {tax_code_id} not found")
        return self.tax_codes[tax_code_id]

    def calculate_tax(
        self,
        amount: Decimal,
        tax_code_id: str,
    ) -> Decimal:
        """
        Calculate tax on an amount.

        Args:
            amount: Taxable amount
            tax_code_id: Tax code to apply

        Returns:
            Calculated tax amount

        Raises:
            TaxError: If tax code not found
        """
        if tax_code_id not in self.tax_codes:
            raise TaxError(f"Tax code {tax_code_id} not found")

        code = self.tax_codes[tax_code_id]
        tax_rate = code.tax_rate / Decimal("100.00")
        return amount * tax_rate

    def record_tax_transaction(
        self,
        transaction_date: date,
        transaction_type: str,
        amount: Decimal,
        tax_code_id: str,
        description: str = "",
    ) -> TaxableTransaction:
        """
        Record a taxable transaction.

        Args:
            transaction_date: Date of transaction
            transaction_type: SALES or PURCHASE
            amount: Taxable amount
            tax_code_id: Tax code applied
            description: Transaction description

        Returns:
            Created TaxableTransaction

        Raises:
            TaxError: If tax code not found
        """
        if tax_code_id not in self.tax_codes:
            raise TaxError(f"Tax code {tax_code_id} not found")

        transaction_id = f"TAX_{uuid4().hex[:8]}"
        transaction = TaxableTransaction(
            transaction_id=transaction_id,
            transaction_date=transaction_date,
            transaction_type=transaction_type,
            amount=amount,
            tax_code_id=tax_code_id,
            description=description,
        )

        self.transactions.append(transaction)

        period_key = f"{transaction_date.year}_{transaction_date.month:02d}"
        if period_key not in self.tax_liability:
            self.tax_liability[period_key] = {}

        code = self.tax_codes[tax_code_id]
        tax_type = code.tax_type

        if tax_type not in self.tax_liability[period_key]:
            self.tax_liability[period_key][tax_type] = Decimal("0.00")

        tax_amount = self.calculate_tax(amount, tax_code_id)

        if transaction_type == "SALES":
            self.tax_liability[period_key][tax_type] += tax_amount
        elif transaction_type == "PURCHASE":
            self.tax_liability[period_key][tax_type] -= tax_amount

        return transaction

    def calculate_tax_liability(
        self,
        period_start: date,
        period_end: date,
    ) -> dict[str, Decimal]:
        """
        Calculate tax liability for a period.

        Separates output tax (sales) from input tax (purchases).

        Args:
            period_start: Period start date
            period_end: Period end date

        Returns:
            Map of tax type to net liability
        """
        liability: dict[str, Decimal] = {}

        for transaction in self.transactions:
            if transaction.transaction_date < period_start:
                continue
            if transaction.transaction_date > period_end:
                continue

            code = self.tax_codes[transaction.tax_code_id]
            tax_type = code.tax_type
            tax_amount = self.calculate_tax(transaction.amount, transaction.tax_code_id)

            if tax_type not in liability:
                liability[tax_type] = Decimal("0.00")

            if transaction.transaction_type == "SALES":
                liability[tax_type] += tax_amount
            elif transaction.transaction_type == "PURCHASE":
                liability[tax_type] -= tax_amount

        return liability

    def record_withholding_tax(
        self,
        transaction_id: str,
        withheld_amount: Decimal,
        payee_tax_id: str,
        withholding_code: str,
    ) -> None:
        """
        Record withholding tax (e.g., 1099 NEC withholding).

        Args:
            transaction_id: Original transaction ID
            withheld_amount: Amount withheld
            payee_tax_id: Payee tax ID
            withholding_code: Type of withholding

        Raises:
            ValueError: If transaction not found
        """
        self.tax_withholding[transaction_id] = withheld_amount

    def get_withholding_total(
        self,
        period_start: date,
        period_end: date,
        withholding_code: str,
    ) -> Decimal:
        """
        Get total withheld taxes for a period.

        Args:
            period_start: Period start date
            period_end: Period end date
            withholding_code: Type of withholding

        Returns:
            Total withheld amount
        """
        total = Decimal("0.00")

        for transaction in self.transactions:
            if transaction.transaction_date < period_start:
                continue
            if transaction.transaction_date > period_end:
                continue

            if transaction.transaction_id in self.tax_withholding:
                total += self.tax_withholding[transaction.transaction_id]

        return total

    def prepare_tax_return(
        self,
        period_start: date,
        period_end: date,
        jurisdiction: str,
    ) -> dict[str, any]:
        """
        Prepare tax return data for a jurisdiction.

        Args:
            period_start: Return period start
            period_end: Return period end
            jurisdiction: Jurisdiction code

        Returns:
            Tax return data

        Raises:
            TaxError: If no tax data for jurisdiction
        """
        liability = self.calculate_tax_liability(period_start, period_end)

        transactions_in_period = [
            t for t in self.transactions if t.transaction_date >= period_start and t.transaction_date <= period_end
        ]

        jurisdiction_transactions = [
            t for t in transactions_in_period if self.tax_codes[t.tax_code_id].jurisdiction == jurisdiction
        ]

        if not jurisdiction_transactions:
            raise TaxError(f"No tax transactions found for jurisdiction {jurisdiction}")

        output_tax = Decimal("0.00")
        input_tax = Decimal("0.00")

        for transaction in jurisdiction_transactions:
            code = self.tax_codes[transaction.tax_code_id]
            tax_amount = self.calculate_tax(transaction.amount, transaction.tax_code_id)

            if transaction.transaction_type == "SALES":
                output_tax += tax_amount
            elif transaction.transaction_type == "PURCHASE":
                input_tax += tax_amount

        net_tax = output_tax - input_tax

        return_id = f"RETURN_{uuid4().hex[:8]}"
        return_data = {
            "return_id": return_id,
            "jurisdiction": jurisdiction,
            "period_start": period_start,
            "period_end": period_end,
            "output_tax": output_tax,
            "input_tax": input_tax,
            "net_tax_liability": net_tax,
            "transactions": len(jurisdiction_transactions),
            "prepared_at": datetime.now(),
        }

        self.tax_return_data[return_id] = return_data
        return return_data

    def set_multi_jurisdiction_rules(
        self,
        jurisdiction: str,
        rules: dict[str, Decimal],
    ) -> None:
        """
        Set tax rules for a jurisdiction.

        Args:
            jurisdiction: Jurisdiction code
            rules: Map of rule_name to value
        """
        self.jurisdictional_rules[jurisdiction] = rules

    def apply_jurisdiction_rules(
        self,
        jurisdiction: str,
        base_amount: Decimal,
    ) -> dict[str, Decimal]:
        """
        Apply jurisdiction-specific tax rules.

        Args:
            jurisdiction: Jurisdiction code
            base_amount: Base taxable amount

        Returns:
            Map of tax component to amount
        """
        if jurisdiction not in self.jurisdictional_rules:
            return {"total_tax": Decimal("0.00")}

        rules = self.jurisdictional_rules[jurisdiction]
        result: dict[str, Decimal] = {}

        for rule_name, rate in rules.items():
            tax_rate = rate / Decimal("100.00")
            result[rule_name] = base_amount * tax_rate

        result["total_tax"] = sum(result.values())
        return result

    def get_tax_transactions_by_code(
        self,
        tax_code_id: str,
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> list[TaxableTransaction]:
        """
        Get transactions for a specific tax code.

        Args:
            tax_code_id: Tax code identifier
            period_start: Filter start date
            period_end: Filter end date

        Returns:
            List of matching transactions

        Raises:
            TaxError: If tax code not found
        """
        if tax_code_id not in self.tax_codes:
            raise TaxError(f"Tax code {tax_code_id} not found")

        results: list[TaxableTransaction] = []

        for transaction in self.transactions:
            if transaction.tax_code_id != tax_code_id:
                continue
            if period_start and transaction.transaction_date < period_start:
                continue
            if period_end and transaction.transaction_date > period_end:
                continue

            results.append(transaction)

        return sorted(results, key=lambda t: t.transaction_date)

    def reconcile_tax_accounts(
        self,
        period_start: date,
        period_end: date,
        general_ledger: any = None,
    ) -> dict[str, Decimal]:
        """
        Reconcile calculated tax liability with GL accounts.

        Args:
            period_start: Period start
            period_end: Period end
            general_ledger: GeneralLedger instance (optional)

        Returns:
            Reconciliation details
        """
        calculated_liability = self.calculate_tax_liability(period_start, period_end)

        reconciliation: dict[str, Decimal] = {}
        for tax_type, amount in calculated_liability.items():
            reconciliation[f"{tax_type}_calculated"] = amount

        if general_ledger:
            for account in general_ledger.accounts.values():
                if "tax" in account.id.lower():
                    balance = general_ledger.get_account_balance(
                        account.id,
                        period_end,
                    )
                    reconciliation[f"{account.id}_gl"] = balance

        return reconciliation
