"""Tests for legal billing and time tracking module."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from thomas.marketplace.legal._exceptions import InsufficientFundsError
from thomas.marketplace.legal._types import BillingStatus
from thomas.marketplace.legal.billing import BillingManager, TimeTracker


class TestTimeTracker:
    """Test suite for TimeTracker."""

    @pytest.fixture
    def tracker(self) -> TimeTracker:
        """Create a TimeTracker instance."""
        return TimeTracker()

    def test_add_time_entry(self, tracker: TimeTracker) -> None:
        """Test adding a time entry."""
        entry = tracker.add_time_entry(
            attorney_id="attorney_001",
            case_id="case_001",
            date_worked=date.today(),
            hours=Decimal("2.0"),
            description="Legal research",
            activity_type="research",
        )

        assert entry.entry_id in tracker.time_entries
        assert entry.hours == Decimal("2.0")
        assert entry.billable is True

    def test_time_increment_validation(self, tracker: TimeTracker) -> None:
        """Test 6-minute increment validation."""
        # Valid: 0.1 hours (6 minutes)
        entry = tracker.add_time_entry(
            attorney_id="attorney_001",
            case_id="case_001",
            date_worked=date.today(),
            hours=Decimal("0.1"),
            description="Quick task",
        )
        assert entry.validate_increment()

        # Invalid: 0.15 hours (not valid increment)
        with pytest.raises(ValueError):
            tracker.add_time_entry(
                attorney_id="attorney_001",
                case_id="case_001",
                date_worked=date.today(),
                hours=Decimal("0.15"),
                description="Invalid increment",
            )

    def test_set_attorney_rate(self, tracker: TimeTracker) -> None:
        """Test setting attorney hourly rate."""
        tracker.set_attorney_rate("attorney_001", Decimal("350.00"))

        rate = tracker.get_attorney_rate("attorney_001")
        assert rate == Decimal("350.00")

    def test_get_time_entries_by_case(self, tracker: TimeTracker) -> None:
        """Test retrieving time entries by case."""
        today = date.today()
        yesterday = today - timedelta(days=1)

        tracker.add_time_entry(
            attorney_id="attorney_001",
            case_id="case_001",
            date_worked=today,
            hours=Decimal("2.0"),
            description="Research",
        )

        tracker.add_time_entry(
            attorney_id="attorney_001",
            case_id="case_001",
            date_worked=yesterday,
            hours=Decimal("1.5"),
            description="Drafting",
        )

        entries = tracker.get_time_entries_by_case("case_001")
        assert len(entries) == 2

        # Filter by date range
        entries = tracker.get_time_entries_by_case(
            "case_001",
            start_date=today,
        )
        assert len(entries) == 1

    def test_calculate_billable_hours(self, tracker: TimeTracker) -> None:
        """Test calculating billable hours."""
        tracker.add_time_entry(
            attorney_id="attorney_001",
            case_id="case_001",
            date_worked=date.today(),
            hours=Decimal("2.0"),
            description="Research",
            billable=True,
        )

        tracker.add_time_entry(
            attorney_id="attorney_001",
            case_id="case_001",
            date_worked=date.today(),
            hours=Decimal("1.0"),
            description="Administrative",
            billable=False,
        )

        billable = tracker.calculate_billable_hours("case_001")
        assert billable == Decimal("2.0")


class TestBillingManager:
    """Test suite for BillingManager."""

    @pytest.fixture
    def tracker(self) -> TimeTracker:
        """Create a TimeTracker instance."""
        return TimeTracker()

    @pytest.fixture
    def manager(self, tracker: TimeTracker) -> BillingManager:
        """Create a BillingManager instance."""
        return BillingManager(tracker)

    def test_create_invoice(self, manager: BillingManager) -> None:
        """Test creating a new invoice."""
        invoice = manager.create_invoice(
            client_id="client_001",
            case_id="case_001",
        )

        assert invoice.invoice_id in manager.invoices
        assert invoice.status == BillingStatus.DRAFT
        assert invoice.amount_due == Decimal("0.00")

    def test_add_line_item(self, manager: BillingManager) -> None:
        """Test adding line items to invoice."""
        invoice = manager.create_invoice(
            client_id="client_001",
            case_id="case_001",
        )

        updated = manager.add_line_item(
            invoice.invoice_id,
            "Legal research (5 hours @ $350/hr)",
            Decimal("1750.00"),
            attorney_id="attorney_001",
            hours=Decimal("5.0"),
            rate=Decimal("350.00"),
        )

        assert len(updated.line_items) == 1
        assert updated.amount_due == Decimal("1750.00")

    def test_populate_invoice_from_case(
        self,
        manager: BillingManager,
        tracker: TimeTracker,
    ) -> None:
        """Test populating invoice from case time entries."""
        # Add time entries
        tracker.add_time_entry(
            attorney_id="attorney_001",
            case_id="case_001",
            date_worked=date.today(),
            hours=Decimal("5.0"),
            description="Research",
        )

        tracker.add_time_entry(
            attorney_id="attorney_001",
            case_id="case_001",
            date_worked=date.today(),
            hours=Decimal("2.0"),
            description="Drafting",
        )

        tracker.set_attorney_rate("attorney_001", Decimal("350.00"))

        invoice = manager.create_invoice(
            client_id="client_001",
            case_id="case_001",
        )

        updated = manager.populate_invoice_from_case(
            invoice.invoice_id,
            "case_001",
        )

        assert len(updated.line_items) > 0
        assert updated.amount_due == Decimal("2450.00")  # 7 hours @ $350

    def test_record_payment(self, manager: BillingManager) -> None:
        """Test recording payments on invoices."""
        invoice = manager.create_invoice(
            client_id="client_001",
        )

        manager.add_line_item(
            invoice.invoice_id,
            "Services",
            Decimal("5000.00"),
        )

        # Partial payment
        updated = manager.record_payment(
            invoice.invoice_id,
            Decimal("3000.00"),
        )

        assert updated.amount_paid == Decimal("3000.00")
        assert updated.status == BillingStatus.SENT

        # Full payment
        updated = manager.record_payment(
            invoice.invoice_id,
            Decimal("2000.00"),
        )

        assert updated.amount_paid == Decimal("5000.00")
        assert updated.status == BillingStatus.PAID

    def test_write_off_invoice(self, manager: BillingManager) -> None:
        """Test writing off invoices or portions."""
        invoice = manager.create_invoice(
            client_id="client_001",
        )

        manager.add_line_item(
            invoice.invoice_id,
            "Services",
            Decimal("5000.00"),
        )

        updated = manager.write_off_invoice(
            invoice.invoice_id,
            "Client hardship",
            Decimal("500.00"),
        )

        assert updated.amount_due == Decimal("4500.00")
        assert updated.status == BillingStatus.WRITTEN_OFF
        assert len(manager.write_offs) == 1

    def test_create_trust_account(self, manager: BillingManager) -> None:
        """Test creating a trust account."""
        trust = manager.create_trust_account(
            firm_id="firm_001",
            account_number="123456789",
            bank_name="Bank of America",
        )

        assert trust.trust_id in manager.trusts
        assert trust.balance == Decimal("0.00")

    def test_deposit_and_withdraw_trust(
        self,
        manager: BillingManager,
    ) -> None:
        """Test trust account deposits and withdrawals."""
        trust = manager.create_trust_account(
            firm_id="firm_001",
            account_number="123456789",
            bank_name="Bank of America",
        )

        # Deposit
        updated = manager.deposit_to_trust(
            trust.trust_id,
            "client_001",
            Decimal("10000.00"),
            "Retainer",
        )

        assert updated.balance == Decimal("10000.00")
        assert len(updated.transactions) == 1

        # Withdraw
        updated = manager.withdraw_from_trust(
            trust.trust_id,
            "client_001",
            Decimal("3000.00"),
            "Fee withdrawal",
        )

        assert updated.balance == Decimal("7000.00")

        # Try to withdraw more than available
        with pytest.raises(InsufficientFundsError):
            manager.withdraw_from_trust(
                trust.trust_id,
                "client_001",
                Decimal("10000.00"),
                "Excessive withdrawal",
            )

    def test_finalize_invoice(self, manager: BillingManager) -> None:
        """Test finalizing invoice for sending."""
        invoice = manager.create_invoice(
            client_id="client_001",
        )

        manager.add_line_item(
            invoice.invoice_id,
            "Services @ $350/hr",
            Decimal("5000.00"),
            rate=Decimal("350.00"),
        )

        updated = manager.finalize_invoice(
            invoice.invoice_id,
            ocg_check=True,
        )

        assert updated.status == BillingStatus.SENT

    def test_realization_rate(self, manager: BillingManager) -> None:
        """Test calculating realization rate."""
        invoice = manager.create_invoice(
            client_id="client_001",
        )

        manager.add_line_item(
            invoice.invoice_id,
            "Services",
            Decimal("5000.00"),
        )

        # No payment yet
        rate = manager.calculate_realization_rate(invoice.invoice_id)
        assert rate == Decimal("0.00")

        # Partial payment
        manager.record_payment(invoice.invoice_id, Decimal("4000.00"))
        rate = manager.calculate_realization_rate(invoice.invoice_id)
        assert rate == Decimal("0.80")

    def test_collection_rate(self, manager: BillingManager) -> None:
        """Test calculating collection rate for client."""
        invoice1 = manager.create_invoice(
            client_id="client_001",
        )
        manager.add_line_item(invoice1.invoice_id, "Services", Decimal("1000.00"))
        manager.record_payment(invoice1.invoice_id, Decimal("1000.00"))

        invoice2 = manager.create_invoice(
            client_id="client_001",
        )
        manager.add_line_item(invoice2.invoice_id, "Services", Decimal("1000.00"))
        manager.record_payment(invoice2.invoice_id, Decimal("500.00"))

        rate = manager.calculate_collection_rate("client_001")
        assert rate == Decimal("0.75")  # 1500 / 2000
