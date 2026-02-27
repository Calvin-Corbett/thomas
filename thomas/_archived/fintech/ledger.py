"""
Double-entry bookkeeping and financial ledger.

Implements double-entry ledger system with account hierarchy,
journal entries, trial balance, and financial statement generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from ._exceptions import FintechError
from ._types import TransactionType


class AccountType(str, Enum):
    """Account classification."""

    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"


@dataclass
class Account:
    """
    General ledger account.

    Attributes:
        code: Account code (e.g., "1000")
        name: Account name
        account_type: Classification
        balance: Current balance (debit positive)
        parent_code: Parent account code for hierarchy
        is_contra: Whether this is a contra account
        created_at: Creation timestamp
    """

    code: str
    name: str
    account_type: AccountType
    balance: Decimal = Decimal("0")
    parent_code: str | None = None
    is_contra: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)

    def debit(self, amount: Decimal) -> None:
        """Record debit entry."""
        if self.account_type in (AccountType.LIABILITY, AccountType.EQUITY, AccountType.REVENUE):
            self.balance -= amount
        else:
            self.balance += amount

    def credit(self, amount: Decimal) -> None:
        """Record credit entry."""
        if self.account_type in (AccountType.LIABILITY, AccountType.EQUITY, AccountType.REVENUE):
            self.balance += amount
        else:
            self.balance -= amount

    def get_balance(self) -> Decimal:
        """Get account balance."""
        return self.balance


@dataclass
class JournalEntry:
    """
    Journal entry with debit/credit pairs.

    Attributes:
        id: Entry ID
        date: Entry date
        description: Entry description
        reference: Reference information
        debits: List of (account_code, amount) tuples
        credits: List of (account_code, amount) tuples
        transaction_type: Type of transaction
        posted: Whether entry is posted to ledger
    """

    id: str
    date: datetime
    description: str
    debits: list[tuple[str, Decimal]]
    credits: list[tuple[str, Decimal]]
    transaction_type: TransactionType
    reference: str = ""
    posted: bool = False

    def __post_init__(self) -> None:
        """Validate entry on creation."""
        if not self.is_balanced():
            raise ValueError("Journal entry must be balanced")

    def is_balanced(self) -> bool:
        """Check if debits equal credits."""
        total_debits = sum(amount for _, amount in self.debits)
        total_credits = sum(amount for _, amount in self.credits)
        return total_debits == total_credits

    def get_total_debits(self) -> Decimal:
        """Get total debit amount."""
        return sum(amount for _, amount in self.debits)

    def get_total_credits(self) -> Decimal:
        """Get total credit amount."""
        return sum(amount for _, amount in self.credits)


class GeneralLedger:
    """
    General ledger with double-entry accounting.

    Maintains chart of accounts and journal entries.
    """

    def __init__(self) -> None:
        """Initialize general ledger."""
        self.accounts: dict[str, Account] = {}
        self.journal: list[JournalEntry] = []
        self.entry_counter = 0

    def create_account(
        self,
        code: str,
        name: str,
        account_type: AccountType,
        parent_code: str | None = None,
    ) -> Account:
        """
        Create general ledger account.

        Args:
            code: Account code
            name: Account name
            account_type: Account classification
            parent_code: Parent account code

        Returns:
            Created account
        """
        if code in self.accounts:
            raise FintechError(f"Account {code} already exists")

        account = Account(
            code=code,
            name=name,
            account_type=account_type,
            parent_code=parent_code,
        )

        self.accounts[code] = account
        return account

    def get_account(self, code: str) -> Account | None:
        """Get account by code."""
        return self.accounts.get(code)

    def post_entry(self, entry: JournalEntry) -> bool:
        """
        Post journal entry to ledger.

        Args:
            entry: Journal entry to post

        Returns:
            True if posted

        Raises:
            FintechError: If entry invalid
        """
        if not entry.is_balanced():
            raise FintechError("Entry is not balanced")

        if entry.posted:
            raise FintechError("Entry already posted")

        # Verify accounts exist
        for account_code, _ in entry.debits + entry.credits:
            if account_code not in self.accounts:
                raise FintechError(f"Account {account_code} not found")

        # Post debits
        for account_code, amount in entry.debits:
            self.accounts[account_code].debit(amount)

        # Post credits
        for account_code, amount in entry.credits:
            self.accounts[account_code].credit(amount)

        entry.posted = True
        self.journal.append(entry)
        return True

    def create_and_post_entry(
        self,
        date: datetime,
        description: str,
        debits: dict[str, Decimal],
        credits: dict[str, Decimal],
        transaction_type: TransactionType,
        reference: str = "",
    ) -> JournalEntry:
        """
        Create and post journal entry in one operation.

        Args:
            date: Entry date
            description: Description
            debits: Map of account_code to debit amount
            credits: Map of account_code to credit amount
            transaction_type: Transaction type
            reference: Reference

        Returns:
            Posted journal entry
        """
        self.entry_counter += 1
        entry_id = f"JE-{self.entry_counter:09d}"

        entry = JournalEntry(
            id=entry_id,
            date=date,
            description=description,
            debits=list(debits.items()),
            credits=list(credits.items()),
            transaction_type=transaction_type,
            reference=reference,
        )

        self.post_entry(entry)
        return entry

    def get_trial_balance(self) -> dict[str, Decimal]:
        """
        Generate trial balance.

        Returns:
            Map of account code to balance
        """
        return {code: account.get_balance() for code, account in self.accounts.items()}

    def verify_trial_balance(self) -> bool:
        """
        Verify trial balance is balanced.

        Returns:
            True if balanced
        """
        trial_balance = self.get_trial_balance()

        debits = sum(
            bal
            for code, bal in trial_balance.items()
            if self.accounts[code].account_type
            in (
                AccountType.ASSET,
                AccountType.EXPENSE,
            )
            and bal > 0
        )

        credits = sum(
            -bal
            for code, bal in trial_balance.items()
            if self.accounts[code].account_type
            in (
                AccountType.LIABILITY,
                AccountType.EQUITY,
                AccountType.REVENUE,
            )
            and bal < 0
        )

        return debits == credits

    def get_account_balance(self, account_code: str) -> Decimal:
        """Get balance for single account."""
        account = self.get_account(account_code)
        if account is None:
            return Decimal("0")
        return account.get_balance()

    def get_accounts_by_type(self, account_type: AccountType) -> dict[str, Account]:
        """Get all accounts of a type."""
        return {code: account for code, account in self.accounts.items() if account.account_type == account_type}


class FinancialStatementGenerator:
    """
    Generate financial statements from ledger data.

    Creates income statements, balance sheets, and other financial reports.
    """

    def __init__(self, ledger: GeneralLedger) -> None:
        """
        Initialize statement generator.

        Args:
            ledger: General ledger instance
        """
        self.ledger = ledger

    def generate_income_statement(
        self,
        period_start: datetime,
        period_end: datetime,
    ) -> dict[str, Decimal]:
        """
        Generate income statement.

        Args:
            period_start: Period start date
            period_end: Period end date

        Returns:
            Income statement with revenues, expenses, and net income
        """
        # Get entries in period
        period_entries = [e for e in self.ledger.journal if period_start <= e.date <= period_end and e.posted]

        revenues = Decimal("0")
        expenses = Decimal("0")

        for entry in period_entries:
            for account_code, amount in entry.credits:
                if self.ledger.get_account(account_code).account_type == AccountType.REVENUE:
                    revenues += amount

            for account_code, amount in entry.debits:
                if self.ledger.get_account(account_code).account_type == AccountType.EXPENSE:
                    expenses += amount

        net_income = revenues - expenses

        return {
            "revenues": revenues,
            "expenses": expenses,
            "net_income": net_income,
        }

    def generate_balance_sheet(self, as_of: datetime) -> dict[str, Decimal]:
        """
        Generate balance sheet.

        Args:
            as_of: Date for balance sheet

        Returns:
            Balance sheet with assets, liabilities, and equity
        """
        trial_balance = self.ledger.get_trial_balance()

        assets = Decimal("0")
        liabilities = Decimal("0")
        equity = Decimal("0")

        for code, balance in trial_balance.items():
            account = self.ledger.get_account(code)

            if account.account_type == AccountType.ASSET:
                assets += balance
            elif account.account_type == AccountType.LIABILITY:
                liabilities += balance
            elif account.account_type == AccountType.EQUITY:
                equity += balance

        return {
            "assets": assets,
            "liabilities": liabilities,
            "equity": equity,
            "total_liabilities_and_equity": liabilities + equity,
        }

    def verify_balance_sheet(self, as_of: datetime) -> bool:
        """
        Verify balance sheet balances.

        Assets = Liabilities + Equity

        Args:
            as_of: As of date

        Returns:
            True if balanced
        """
        bs = self.generate_balance_sheet(as_of)
        return abs(bs["assets"] - (bs["liabilities"] + bs["equity"])) < Decimal("0.01")


class AccountReconciler:
    """
    Reconcile ledger accounts.

    Helps identify discrepancies between ledger and source documents.
    """

    @staticmethod
    def reconcile_account(
        account_code: str,
        ledger: GeneralLedger,
        expected_balance: Decimal,
    ) -> tuple[bool, Decimal]:
        """
        Reconcile account balance.

        Args:
            account_code: Account to reconcile
            ledger: General ledger
            expected_balance: Expected balance from source

        Returns:
            Tuple of (reconciled, difference)
        """
        actual_balance = ledger.get_account_balance(account_code)
        difference = actual_balance - expected_balance

        return difference == 0, difference

    @staticmethod
    def get_account_activity(
        account_code: str,
        ledger: GeneralLedger,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[tuple[datetime, Decimal]]:
        """
        Get account activity within date range.

        Args:
            account_code: Account to review
            ledger: General ledger
            start_date: Optional start date
            end_date: Optional end date

        Returns:
            List of (date, amount) tuples
        """
        activity = []
        running_balance = Decimal("0")

        for entry in ledger.journal:
            if start_date and entry.date < start_date:
                continue
            if end_date and entry.date > end_date:
                break

            for code, amount in entry.debits:
                if code == account_code:
                    account = ledger.get_account(code)
                    if account.account_type in (AccountType.LIABILITY, AccountType.EQUITY, AccountType.REVENUE):
                        running_balance -= amount
                    else:
                        running_balance += amount
                    activity.append((entry.date, running_balance))

            for code, amount in entry.credits:
                if code == account_code:
                    account = ledger.get_account(code)
                    if account.account_type in (AccountType.LIABILITY, AccountType.EQUITY, AccountType.REVENUE):
                        running_balance += amount
                    else:
                        running_balance -= amount
                    activity.append((entry.date, running_balance))

        return activity
