"""
Tests for general ledger functionality.
"""

from datetime import date
from decimal import Decimal

import pytest

from thomas.marketplace.erp._exceptions import InvalidAccountError, JournalEntryError
from thomas.marketplace.erp._types import AccountType, Currency, JournalEntry, LineItem
from thomas.marketplace.erp.general_ledger import GeneralLedger


class TestGeneralLedger:
    """Test general ledger operations."""

    @pytest.fixture
    def gl(self) -> GeneralLedger:
        """Create a general ledger instance."""
        return GeneralLedger()

    @pytest.fixture
    def setup_accounts(self, gl: GeneralLedger) -> None:
        """Set up standard chart of accounts."""
        gl.create_account("1000", "Cash", AccountType.ASSET, currency=Currency.USD)
        gl.create_account("1100", "Accounts Receivable", AccountType.ASSET)
        gl.create_account("1200", "Inventory", AccountType.ASSET)
        gl.create_account("2000", "Accounts Payable", AccountType.LIABILITY)
        gl.create_account("2100", "Short-term Debt", AccountType.LIABILITY)
        gl.create_account("3000", "Common Stock", AccountType.EQUITY)
        gl.create_account("4000", "Sales Revenue", AccountType.REVENUE)
        gl.create_account("5000", "Cost of Goods Sold", AccountType.COGS)
        gl.create_account("6000", "Operating Expenses", AccountType.EXPENSE)

    def test_create_account(self, gl: GeneralLedger, setup_accounts) -> None:
        """Test account creation."""
        account = gl.get_account("1000")
        assert account.id == "1000"
        assert account.name == "Cash"
        assert account.account_type == AccountType.ASSET
        assert account.balance == Decimal("0.00")

    def test_duplicate_account_error(self, gl: GeneralLedger) -> None:
        """Test that duplicate accounts are rejected."""
        gl.create_account("1000", "Cash", AccountType.ASSET)
        with pytest.raises(InvalidAccountError):
            gl.create_account("1000", "Duplicate", AccountType.ASSET)

    def test_account_not_found(self, gl: GeneralLedger) -> None:
        """Test retrieving non-existent account."""
        with pytest.raises(InvalidAccountError):
            gl.get_account("9999")

    def test_simple_journal_entry(self, gl: GeneralLedger, setup_accounts) -> None:
        """Test posting a simple journal entry."""
        entry = JournalEntry(
            id="JE001",
            entry_date=date(2024, 1, 1),
            description="Sale on account",
            lines=[
                LineItem(
                    account_id="1100",
                    debit=Decimal("100.00"),
                    description="Invoice #101",
                ),
                LineItem(
                    account_id="4000",
                    credit=Decimal("100.00"),
                    description="Sales revenue",
                ),
            ],
        )

        gl.post_journal_entry(entry)

        assert gl.get_account("1100").balance == Decimal("100.00")
        assert gl.get_account("4000").balance == Decimal("-100.00")

    def test_unbalanced_entry_rejected(self, gl: GeneralLedger, setup_accounts) -> None:
        """Test that unbalanced entries are rejected."""
        entry = JournalEntry(
            id="JE002",
            entry_date=date(2024, 1, 1),
            description="Unbalanced entry",
            lines=[
                LineItem(account_id="1000", debit=Decimal("100.00")),
                LineItem(account_id="4000", credit=Decimal("50.00")),
            ],
        )

        with pytest.raises(JournalEntryError):
            gl.post_journal_entry(entry)

    def test_trial_balance(self, gl: GeneralLedger, setup_accounts) -> None:
        """Test trial balance calculation."""
        entry = JournalEntry(
            id="JE003",
            entry_date=date(2024, 1, 1),
            description="Test entry",
            lines=[
                LineItem(account_id="1000", debit=Decimal("500.00")),
                LineItem(account_id="3000", credit=Decimal("500.00")),
            ],
        )
        gl.post_journal_entry(entry)

        tb = gl.trial_balance()

        assert tb["1000"] == Decimal("500.00")
        assert tb["3000"] == Decimal("-500.00")

    def test_account_balance_as_of_date(self, gl: GeneralLedger, setup_accounts) -> None:
        """Test historical account balance calculation."""
        entry1 = JournalEntry(
            id="JE004",
            entry_date=date(2024, 1, 15),
            description="First transaction",
            lines=[
                LineItem(account_id="1000", debit=Decimal("100.00")),
                LineItem(account_id="3000", credit=Decimal("100.00")),
            ],
        )
        entry2 = JournalEntry(
            id="JE005",
            entry_date=date(2024, 2, 15),
            description="Second transaction",
            lines=[
                LineItem(account_id="1000", debit=Decimal("50.00")),
                LineItem(account_id="3000", credit=Decimal("50.00")),
            ],
        )

        gl.post_journal_entry(entry1)
        gl.post_journal_entry(entry2)

        as_of_jan31 = gl.get_account_balance("1000", date(2024, 1, 31))
        assert as_of_jan31 == Decimal("100.00")

        as_of_feb28 = gl.get_account_balance("1000", date(2024, 2, 28))
        assert as_of_feb28 == Decimal("150.00")

    def test_hierarchical_accounts(self, gl: GeneralLedger) -> None:
        """Test hierarchical account structure."""
        gl.create_account("1000", "Current Assets", AccountType.ASSET)
        gl.create_account("1100", "Cash", AccountType.ASSET, parent_id="1000")
        gl.create_account("1200", "AR", AccountType.ASSET, parent_id="1000")

        hierarchy = gl.get_hierarchical_accounts("1000")

        assert "1000" in hierarchy
        assert "1100" in hierarchy["1000"]
        assert "1200" in hierarchy["1000"]

    def test_period_closing(self, gl: GeneralLedger, setup_accounts) -> None:
        """Test period closing functionality."""
        gl.close_period("2024-Q1")

        closures = gl.get_period_closing_status()
        assert len(closures) == 1
        assert closures[0][0] == "2024-Q1"

    def test_adjusting_entry(self, gl: GeneralLedger, setup_accounts) -> None:
        """Test creation of adjusting entries."""
        entry = gl.create_adjusting_entry(
            entry_date=date(2024, 1, 31),
            description="Accrued expenses",
            lines=[
                LineItem(account_id="6000", debit=Decimal("250.00")),
                LineItem(account_id="2000", credit=Decimal("250.00")),
            ],
        )

        assert entry.posted
        assert gl.get_account("6000").balance == Decimal("250.00")
        assert gl.get_account("2000").balance == Decimal("250.00")

    def test_multi_currency_entry(self, gl: GeneralLedger, setup_accounts) -> None:
        """Test multi-currency journal entry posting."""
        gl.create_account("1010", "EUR Cash", AccountType.ASSET, currency=Currency.EUR)

        entry = JournalEntry(
            id="JE006",
            entry_date=date(2024, 1, 1),
            description="Multi-currency transaction",
            lines=[
                LineItem(account_id="1010", debit=Decimal("100.00")),
                LineItem(account_id="1000", credit=Decimal("110.00")),
            ],
        )

        exchange_rates = {
            "EUR": Decimal("1.10"),
            "USD": Decimal("1.00"),
        }

        gl.post_multi_currency_entry(entry, exchange_rates)

        assert entry.posted

    def test_recurring_entries(self, gl: GeneralLedger, setup_accounts) -> None:
        """Test recurring entry creation and posting."""
        template = JournalEntry(
            id="RECURRING_TEMPLATE",
            entry_date=date(2024, 1, 1),
            description="Monthly rent",
            lines=[
                LineItem(account_id="6000", debit=Decimal("1000.00")),
                LineItem(account_id="1000", credit=Decimal("1000.00")),
            ],
        )

        recurring_id = gl.create_recurring_entry(template, "MONTHLY")
        assert recurring_id in gl.recurring_entries

        posted = gl.post_recurring_entries(date(2024, 2, 1))
        assert len(posted) > 0

    def test_reconciliation(self, gl: GeneralLedger, setup_accounts) -> None:
        """Test account reconciliation."""
        gl.reconcile_account("1000", date(2024, 1, 31), Decimal("1500.00"), [])

        status = gl.get_reconciliation_status("1000")
        assert status is not None
        assert status["cleared_amount"] == Decimal("1500.00")

    def test_journal_entry_query(self, gl: GeneralLedger, setup_accounts) -> None:
        """Test querying journal entries."""
        for i in range(3):
            entry = JournalEntry(
                id=f"JE{i}",
                entry_date=date(2024, 1, i + 1),
                description=f"Entry {i}",
                lines=[
                    LineItem(account_id="1000", debit=Decimal("100.00")),
                    LineItem(account_id="4000", credit=Decimal("100.00")),
                ],
            )
            gl.post_journal_entry(entry)

        entries = gl.get_journal_entries(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )

        assert len(entries) == 3

        ar_entries = gl.get_journal_entries(account_id="1000")
        assert len(ar_entries) == 3

    def test_debit_credit_logic(self, gl: GeneralLedger, setup_accounts) -> None:
        """Test correct debit/credit account type logic."""
        entry = JournalEntry(
            id="JE007",
            entry_date=date(2024, 1, 1),
            description="Test debit/credit",
            lines=[
                LineItem(account_id="1000", debit=Decimal("100.00")),
                LineItem(account_id="3000", credit=Decimal("100.00")),
            ],
        )

        gl.post_journal_entry(entry)

        assert gl.get_account("1000").balance == Decimal("100.00")
        assert gl.get_account("3000").balance == Decimal("-100.00")
