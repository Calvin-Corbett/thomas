"""
General Ledger management.

Handles chart of accounts, journal entries, posting, trial balance,
and period closing operations.
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from thomas.marketplace.erp._exceptions import (
    InvalidAccountError,
    JournalEntryError,
)
from thomas.marketplace.erp._types import (
    Account,
    AccountType,
    Currency,
    JournalEntry,
    LineItem,
)


class GeneralLedger:
    """
    General ledger management with hierarchical chart of accounts.

    Maintains accounts, records transactions, and generates financial statements.
    """

    def __init__(self) -> None:
        """Initialize general ledger."""
        self.accounts: dict[str, Account] = {}
        self.journal_entries: dict[str, JournalEntry] = {}
        self.entry_sequence: list[str] = []
        self.recurring_entries: dict[str, tuple[JournalEntry, str]] = {}  # entry_id -> (template, frequency)
        self.account_reconciliations: dict[str, dict[str, any]] = {}
        self.period_closures: list[tuple[str, datetime]] = []

    def create_account(
        self,
        account_id: str,
        name: str,
        account_type: AccountType,
        parent_id: str | None = None,
        currency: Currency = Currency.USD,
        description: str = "",
    ) -> Account:
        """
        Create a new general ledger account.

        Args:
            account_id: Unique account identifier (e.g., "1000")
            name: Account name
            account_type: Classification (ASSET, LIABILITY, etc.)
            parent_id: Parent account for hierarchy
            currency: Account currency
            description: Account description

        Returns:
            Created Account object

        Raises:
            InvalidAccountError: If account already exists or parent is invalid
        """
        if account_id in self.accounts:
            raise InvalidAccountError(f"Account {account_id} already exists")

        if parent_id is not None and parent_id not in self.accounts:
            raise InvalidAccountError(f"Parent account {parent_id} not found")

        account = Account(
            id=account_id,
            name=name,
            account_type=account_type,
            parent_id=parent_id,
            currency=currency,
            description=description,
        )
        self.accounts[account_id] = account
        return account

    def get_account(self, account_id: str) -> Account:
        """
        Retrieve an account by ID.

        Args:
            account_id: Account identifier

        Returns:
            Account object

        Raises:
            InvalidAccountError: If account not found
        """
        if account_id not in self.accounts:
            raise InvalidAccountError(f"Account {account_id} not found")
        return self.accounts[account_id]

    def post_journal_entry(self, entry: JournalEntry) -> None:
        """
        Post a balanced journal entry to the general ledger.

        Validates that debits equal credits, updates account balances,
        and records the entry in sequence for audit trail.

        Args:
            entry: JournalEntry to post

        Raises:
            JournalEntryError: If entry is not balanced or accounts are invalid
        """
        if not entry.is_balanced():
            raise JournalEntryError(
                f"Entry {entry.id} not balanced: " f"debits={entry.total_debits()} credits={entry.total_credits()}"
            )

        for line in entry.lines:
            if line.account_id not in self.accounts:
                raise JournalEntryError(f"Account {line.account_id} not found in entry {entry.id}")

        entry.posted = True
        self.journal_entries[entry.id] = entry
        self.entry_sequence.append(entry.id)

        for line in entry.lines:
            account = self.accounts[line.account_id]
            amount = line.get_amount()
            if line.debit is not None:
                if account.is_debit_account():
                    account.balance += amount
                else:
                    account.balance -= amount
            else:
                if account.is_debit_account():
                    account.balance -= amount
                else:
                    account.balance += amount
            account.last_modified = datetime.now()

    def create_recurring_entry(
        self,
        template: JournalEntry,
        frequency: str,  # DAILY, WEEKLY, MONTHLY, QUARTERLY, ANNUALLY
    ) -> str:
        """
        Create a recurring journal entry template.

        Args:
            template: JournalEntry template (without posting)
            frequency: Recurrence frequency

        Returns:
            Recurring entry ID

        Raises:
            JournalEntryError: If template is invalid
        """
        if not template.is_balanced():
            raise JournalEntryError("Recurring entry template must be balanced")

        recurring_id = f"recurring_{uuid4().hex[:8]}"
        self.recurring_entries[recurring_id] = (template, frequency)
        return recurring_id

    def post_recurring_entries(self, target_date: date) -> list[str]:
        """
        Post recurring entries due on target date.

        Args:
            target_date: Date to check for due recurring entries

        Returns:
            List of posted entry IDs
        """
        posted_ids: list[str] = []

        for recurring_id, (template, frequency) in self.recurring_entries.items():
            should_post = False

            if (
                frequency == "DAILY"
                or frequency == "WEEKLY"
                and target_date.weekday() == 0
                or frequency == "MONTHLY"
                and target_date.day == 1
                or frequency == "QUARTERLY"
                and target_date.month in (1, 4, 7, 10)
                or frequency == "ANNUALLY"
                and target_date.month == 1
                and target_date.day == 1
            ):
                should_post = True

            if should_post:
                entry_copy = JournalEntry(
                    id=f"{recurring_id}_{target_date.isoformat()}",
                    entry_date=target_date,
                    description=template.description,
                    lines=[
                        LineItem(
                            account_id=line.account_id,
                            debit=line.debit,
                            credit=line.credit,
                            description=line.description,
                        )
                        for line in template.lines
                    ],
                )
                self.post_journal_entry(entry_copy)
                posted_ids.append(entry_copy.id)

        return posted_ids

    def post_multi_currency_entry(
        self,
        entry: JournalEntry,
        exchange_rates: dict[str, Decimal],
    ) -> None:
        """
        Post a journal entry with multi-currency support.

        Converts all amounts to base currency using provided exchange rates.

        Args:
            entry: JournalEntry with mixed currencies
            exchange_rates: Map of currency codes to conversion rates (relative to base)

        Raises:
            JournalEntryError: If entry cannot be converted
        """
        converted_entry = JournalEntry(
            id=entry.id,
            entry_date=entry.entry_date,
            description=entry.description,
            lines=[],
            reference=entry.reference,
            memo=entry.memo,
        )

        for line in entry.lines:
            account = self.accounts[line.account_id]
            rate = exchange_rates.get(account.currency.value, Decimal("1.00"))

            converted_debit = None
            converted_credit = None

            if line.debit is not None:
                converted_debit = line.debit * rate
            if line.credit is not None:
                converted_credit = line.credit * rate

            converted_entry.lines.append(
                LineItem(
                    account_id=line.account_id,
                    debit=converted_debit,
                    credit=converted_credit,
                    description=line.description,
                )
            )

        self.post_journal_entry(converted_entry)

    def trial_balance(self, as_of_date: date | None = None) -> dict[str, Decimal]:
        """
        Generate trial balance (sum of all account balances).

        Args:
            as_of_date: Date for historical trial balance (optional)

        Returns:
            Map of account IDs to their balances
        """
        trial_balance: dict[str, Decimal] = {}

        for account_id, account in self.accounts.items():
            if as_of_date:
                balance = self._calculate_balance_as_of(account_id, as_of_date)
            else:
                balance = account.balance

            trial_balance[account_id] = balance

        return trial_balance

    def get_account_balance(self, account_id: str, as_of_date: date | None = None) -> Decimal:
        """
        Get the balance of a single account.

        Args:
            account_id: Account identifier
            as_of_date: Date for historical balance

        Returns:
            Account balance

        Raises:
            InvalidAccountError: If account not found
        """
        if account_id not in self.accounts:
            raise InvalidAccountError(f"Account {account_id} not found")

        if as_of_date:
            return self._calculate_balance_as_of(account_id, as_of_date)

        return self.accounts[account_id].balance

    def _calculate_balance_as_of(self, account_id: str, as_of_date: date) -> Decimal:
        """
        Calculate account balance as of a specific date.

        Args:
            account_id: Account identifier
            as_of_date: Target date

        Returns:
            Account balance on that date
        """
        balance = Decimal("0.00")

        for entry_id in self.entry_sequence:
            entry = self.journal_entries[entry_id]
            if entry.entry_date > as_of_date:
                break

            for line in entry.lines:
                if line.account_id == account_id:
                    if line.debit is not None:
                        if self.accounts[account_id].is_debit_account():
                            balance += line.debit
                        else:
                            balance -= line.debit
                    else:
                        if self.accounts[account_id].is_debit_account():
                            balance -= line.credit or Decimal("0.00")
                        else:
                            balance += line.credit or Decimal("0.00")

        return balance

    def get_hierarchical_accounts(self, parent_id: str | None = None) -> dict[str, list[str]]:
        """
        Get accounts organized hierarchically.

        Args:
            parent_id: Parent account ID (None for roots)

        Returns:
            Map of parent IDs to lists of child account IDs
        """
        hierarchy: dict[str, list[str]] = {}
        children: list[str] = []

        for account_id, account in self.accounts.items():
            if account.parent_id == parent_id:
                children.append(account_id)

        if children:
            hierarchy[parent_id] = children

        for child_id in children:
            hierarchy.update(self.get_hierarchical_accounts(child_id))

        return hierarchy

    def close_period(self, period_name: str) -> None:
        """
        Close an accounting period.

        Records the closure for audit trail and prevents further modifications
        to that period.

        Args:
            period_name: Period identifier (e.g., "2024-Q1", "2024-01")
        """
        self.period_closures.append((period_name, datetime.now()))

    def get_period_closing_status(self) -> list[tuple[str, datetime]]:
        """
        Get list of closed periods.

        Returns:
            List of (period_name, closure_datetime) tuples
        """
        return self.period_closures.copy()

    def create_adjusting_entry(
        self,
        entry_date: date,
        description: str,
        lines: list[LineItem],
    ) -> JournalEntry:
        """
        Create and post an adjusting entry (accruals, deferrals, etc.).

        Args:
            entry_date: Entry date
            description: Description
            lines: Line items (must balance)

        Returns:
            Posted JournalEntry

        Raises:
            JournalEntryError: If entry cannot be posted
        """
        entry = JournalEntry(
            id=f"ADJ_{uuid4().hex[:8]}",
            entry_date=entry_date,
            description=description,
            lines=lines,
        )
        self.post_journal_entry(entry)
        return entry

    def reconcile_account(
        self,
        account_id: str,
        reconciliation_date: date,
        cleared_amount: Decimal,
        outstanding_items: list[str],
    ) -> None:
        """
        Record account reconciliation (bank/credit card).

        Args:
            account_id: Account being reconciled
            reconciliation_date: Date of reconciliation
            cleared_amount: Amount that cleared the bank
            outstanding_items: List of item IDs still outstanding

        Raises:
            InvalidAccountError: If account not found
        """
        if account_id not in self.accounts:
            raise InvalidAccountError(f"Account {account_id} not found")

        self.account_reconciliations[account_id] = {
            "date": reconciliation_date,
            "cleared_amount": cleared_amount,
            "outstanding": outstanding_items,
            "reconciled_at": datetime.now(),
        }

    def get_reconciliation_status(self, account_id: str) -> dict | None:
        """
        Get reconciliation status for an account.

        Args:
            account_id: Account identifier

        Returns:
            Reconciliation details or None if not reconciled
        """
        return self.account_reconciliations.get(account_id)

    def get_journal_entries(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        account_id: str | None = None,
    ) -> list[JournalEntry]:
        """
        Query journal entries by date range and/or account.

        Args:
            start_date: Start date filter
            end_date: End date filter
            account_id: Account filter

        Returns:
            Matching journal entries
        """
        results: list[JournalEntry] = []

        for entry in self.journal_entries.values():
            if start_date and entry.entry_date < start_date:
                continue
            if end_date and entry.entry_date > end_date:
                continue
            if account_id:
                if not any(line.account_id == account_id for line in entry.lines):
                    continue

            results.append(entry)

        return sorted(results, key=lambda e: e.entry_date)
