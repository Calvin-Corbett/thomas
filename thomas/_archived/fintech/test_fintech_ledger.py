"""
Tests for double-entry ledger and financial statements.

Tests for journal entry posting, trial balance, income statement,
balance sheet, and account reconciliation.
"""

from datetime import datetime
from decimal import Decimal

import pytest
from _types import TransactionType
from ledger import (
    AccountReconciler,
    AccountType,
    FinancialStatementGenerator,
    GeneralLedger,
    JournalEntry,
)


class TestGeneralLedger:
    """Test general ledger functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.ledger = GeneralLedger()

    def test_create_account(self):
        """Test account creation."""
        account = self.ledger.create_account(
            code="1000",
            name="Cash",
            account_type=AccountType.ASSET,
        )

        assert account.code == "1000"
        assert account.name == "Cash"
        assert account.account_type == AccountType.ASSET
        assert self.ledger.get_account("1000") == account

    def test_account_hierarchy(self):
        """Test account parent-child relationships."""
        self.ledger.create_account(
            code="1000",
            name="Assets",
            account_type=AccountType.ASSET,
        )

        child = self.ledger.create_account(
            code="1100",
            name="Cash",
            account_type=AccountType.ASSET,
            parent_code="1000",
        )

        assert child.parent_code == "1000"

    def test_duplicate_account(self):
        """Test that duplicate accounts cannot be created."""
        self.ledger.create_account(
            code="1000",
            name="Cash",
            account_type=AccountType.ASSET,
        )

        from _exceptions import FintechError

        with pytest.raises(FintechError):
            self.ledger.create_account(
                code="1000",
                name="Duplicate",
                account_type=AccountType.ASSET,
            )

    def test_journal_entry_balanced(self):
        """Test that journal entries must be balanced."""
        from _exceptions import ValueError

        with pytest.raises(ValueError):
            JournalEntry(
                id="JE001",
                date=datetime.utcnow(),
                description="Unbalanced entry",
                debits=[("1000", Decimal("100"))],
                credits=[("2000", Decimal("50"))],
                transaction_type=TransactionType.TRADE,
            )

    def test_post_entry(self):
        """Test posting journal entry."""
        # Create accounts
        cash = self.ledger.create_account("1000", "Cash", AccountType.ASSET)
        equity = self.ledger.create_account("3000", "Equity", AccountType.EQUITY)

        # Create entry
        entry = JournalEntry(
            id="JE001",
            date=datetime.utcnow(),
            description="Initial investment",
            debits=[("1000", Decimal("1000"))],
            credits=[("3000", Decimal("1000"))],
            transaction_type=TransactionType.DEPOSIT,
        )

        self.ledger.post_entry(entry)

        assert cash.balance == Decimal("1000")
        assert equity.balance == Decimal("-1000")

    def test_debit_credit_mechanics(self):
        """Test proper debit/credit mechanics."""
        # Asset accounts increase with debit
        asset = self.ledger.create_account("1000", "Cash", AccountType.ASSET)
        asset.debit(Decimal("100"))
        assert asset.balance == Decimal("100")

        # Liability accounts increase with credit
        liability = self.ledger.create_account("2000", "Loan", AccountType.LIABILITY)
        liability.credit(Decimal("100"))
        assert liability.balance == Decimal("100")

    def test_trial_balance(self):
        """Test trial balance generation."""
        self.ledger.create_account("1000", "Cash", AccountType.ASSET)
        self.ledger.create_account("2000", "Payable", AccountType.LIABILITY)
        self.ledger.create_account("3000", "Equity", AccountType.EQUITY)

        self.ledger.create_and_post_entry(
            date=datetime.utcnow(),
            description="Investment",
            debits={"1000": Decimal("1000")},
            credits={"3000": Decimal("1000")},
            transaction_type=TransactionType.DEPOSIT,
        )

        trial_balance = self.ledger.get_trial_balance()

        assert trial_balance["1000"] == Decimal("1000")
        assert trial_balance["3000"] == Decimal("-1000")

    def test_verify_trial_balance(self):
        """Test trial balance verification."""
        self.ledger.create_account("1000", "Cash", AccountType.ASSET)
        self.ledger.create_account("3000", "Equity", AccountType.EQUITY)

        self.ledger.create_and_post_entry(
            date=datetime.utcnow(),
            description="Investment",
            debits={"1000": Decimal("1000")},
            credits={"3000": Decimal("1000")},
            transaction_type=TransactionType.DEPOSIT,
        )

        assert self.ledger.verify_trial_balance() is True

    def test_multiple_entries(self):
        """Test posting multiple entries."""
        self.ledger.create_account("1000", "Cash", AccountType.ASSET)
        self.ledger.create_account("4000", "Revenue", AccountType.REVENUE)
        self.ledger.create_account("5000", "Expense", AccountType.EXPENSE)

        # Entry 1
        self.ledger.create_and_post_entry(
            date=datetime.utcnow(),
            description="Revenue",
            debits={"1000": Decimal("100")},
            credits={"4000": Decimal("100")},
            transaction_type=TransactionType.TRADE,
        )

        # Entry 2
        self.ledger.create_and_post_entry(
            date=datetime.utcnow(),
            description="Expense",
            debits={"5000": Decimal("30")},
            credits={"1000": Decimal("30")},
            transaction_type=TransactionType.FEE,
        )

        assert self.ledger.get_account_balance("1000") == Decimal("70")
        assert self.ledger.get_account_balance("4000") == Decimal("-100")
        assert self.ledger.get_account_balance("5000") == Decimal("30")


class TestFinancialStatementGenerator:
    """Test financial statement generation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.ledger = GeneralLedger()
        self.generator = FinancialStatementGenerator(self.ledger)

        # Create chart of accounts
        self.ledger.create_account("1000", "Cash", AccountType.ASSET)
        self.ledger.create_account("2000", "Payable", AccountType.LIABILITY)
        self.ledger.create_account("3000", "Equity", AccountType.EQUITY)
        self.ledger.create_account("4000", "Revenue", AccountType.REVENUE)
        self.ledger.create_account("5000", "Expense", AccountType.EXPENSE)

    def test_income_statement(self):
        """Test income statement generation."""
        now = datetime.utcnow()

        # Record revenue
        self.ledger.create_and_post_entry(
            date=now,
            description="Revenue",
            debits={"1000": Decimal("1000")},
            credits={"4000": Decimal("1000")},
            transaction_type=TransactionType.TRADE,
        )

        # Record expense
        self.ledger.create_and_post_entry(
            date=now,
            description="Expense",
            debits={"5000": Decimal("300")},
            credits={"1000": Decimal("300")},
            transaction_type=TransactionType.FEE,
        )

        statement = self.generator.generate_income_statement(
            now.replace(hour=0, minute=0, second=0),
            now.replace(hour=23, minute=59, second=59),
        )

        assert statement["revenues"] == Decimal("1000")
        assert statement["expenses"] == Decimal("300")
        assert statement["net_income"] == Decimal("700")

    def test_balance_sheet(self):
        """Test balance sheet generation."""
        # Create starting position
        self.ledger.create_and_post_entry(
            date=datetime.utcnow(),
            description="Initial investment",
            debits={"1000": Decimal("5000")},
            credits={"3000": Decimal("5000")},
            transaction_type=TransactionType.DEPOSIT,
        )

        # Add liability
        self.ledger.create_and_post_entry(
            date=datetime.utcnow(),
            description="Borrow",
            debits={"1000": Decimal("2000")},
            credits={"2000": Decimal("2000")},
            transaction_type=TransactionType.TRADE,
        )

        sheet = self.generator.generate_balance_sheet(datetime.utcnow())

        assert sheet["assets"] == Decimal("7000")
        assert sheet["liabilities"] == Decimal("2000")
        assert sheet["equity"] == Decimal("-5000")

    def test_balance_sheet_verification(self):
        """Test balance sheet balances."""
        self.ledger.create_and_post_entry(
            date=datetime.utcnow(),
            description="Investment",
            debits={"1000": Decimal("10000")},
            credits={"3000": Decimal("10000")},
            transaction_type=TransactionType.DEPOSIT,
        )

        assert self.generator.verify_balance_sheet(datetime.utcnow()) is True


class TestAccountReconciler:
    """Test account reconciliation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.ledger = GeneralLedger()
        self.ledger.create_account("1000", "Cash", AccountType.ASSET)

    def test_reconcile_account(self):
        """Test account reconciliation."""
        # Post an entry
        self.ledger.create_and_post_entry(
            date=datetime.utcnow(),
            description="Deposit",
            debits={"1000": Decimal("1000")},
            credits={"3000": Decimal("1000")},
            transaction_type=TransactionType.DEPOSIT,
        )

        # Verify account with expected balance
        reconciled, difference = AccountReconciler.reconcile_account(
            "1000",
            self.ledger,
            Decimal("1000"),
        )

        assert reconciled is True
        assert difference == Decimal("0")

    def test_reconcile_mismatch(self):
        """Test reconciliation with mismatch."""
        self.ledger.create_and_post_entry(
            date=datetime.utcnow(),
            description="Deposit",
            debits={"1000": Decimal("1000")},
            credits={"3000": Decimal("1000")},
            transaction_type=TransactionType.DEPOSIT,
        )

        # Verify with wrong balance
        reconciled, difference = AccountReconciler.reconcile_account(
            "1000",
            self.ledger,
            Decimal("500"),
        )

        assert reconciled is False
        assert difference == Decimal("500")

    def test_account_activity(self):
        """Test getting account activity."""
        now = datetime.utcnow()

        self.ledger.create_and_post_entry(
            date=now,
            description="Entry 1",
            debits={"1000": Decimal("100")},
            credits={"3000": Decimal("100")},
            transaction_type=TransactionType.DEPOSIT,
        )

        self.ledger.create_and_post_entry(
            date=now,
            description="Entry 2",
            debits={"1000": Decimal("50")},
            credits={"3000": Decimal("50")},
            transaction_type=TransactionType.DEPOSIT,
        )

        activity = AccountReconciler.get_account_activity("1000", self.ledger)

        assert len(activity) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
