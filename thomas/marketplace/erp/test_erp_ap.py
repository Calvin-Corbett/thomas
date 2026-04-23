"""
Tests for accounts payable functionality.
"""

from datetime import date
from decimal import Decimal

import pytest

from thomas.marketplace.erp._exceptions import InvoiceError, VendorError
from thomas.marketplace.erp._types import InvoiceStatus, LineItem, PaymentTerm
from thomas.marketplace.erp.accounts_payable import AccountsPayable


class TestAccountsPayable:
    """Test accounts payable operations."""

    @pytest.fixture
    def ap(self) -> AccountsPayable:
        """Create an accounts payable instance."""
        return AccountsPayable()

    @pytest.fixture
    def setup_vendors(self, ap: AccountsPayable) -> None:
        """Set up test vendors."""
        ap.create_vendor("V001", "Acme Corp", contact_name="John Doe", email="john@acme.com")
        ap.create_vendor("V002", "Tech Supply", contact_name="Jane Smith", email="jane@tech.com")

    @pytest.fixture
    def payment_terms(self) -> PaymentTerm:
        """Create payment terms."""
        return PaymentTerm(
            id="NET30",
            name="Net 30",
            days=30,
            discount_percent=Decimal("2.00"),
            discount_days=10,
        )

    def test_create_vendor(self, ap: AccountsPayable) -> None:
        """Test vendor creation."""
        vendor = ap.create_vendor("V001", "Test Vendor", contact_name="John")
        assert vendor.id == "V001"
        assert vendor.name == "Test Vendor"
        assert vendor.is_active

    def test_duplicate_vendor_error(self, ap: AccountsPayable) -> None:
        """Test that duplicate vendors are rejected."""
        ap.create_vendor("V001", "Vendor 1")
        with pytest.raises(VendorError):
            ap.create_vendor("V001", "Duplicate")

    def test_get_vendor(self, ap: AccountsPayable, setup_vendors) -> None:
        """Test retrieving a vendor."""
        vendor = ap.get_vendor("V001")
        assert vendor.id == "V001"
        assert vendor.name == "Acme Corp"

    def test_vendor_not_found(self, ap: AccountsPayable) -> None:
        """Test retrieving non-existent vendor."""
        with pytest.raises(VendorError):
            ap.get_vendor("V999")

    def test_record_purchase_invoice(self, ap: AccountsPayable, setup_vendors) -> None:
        """Test recording a purchase invoice."""
        lines = [
            LineItem(account_id="5000", debit=Decimal("500.00"), description="Office supplies"),
            LineItem(account_id="5100", debit=Decimal("300.00"), description="Equipment"),
        ]

        invoice = ap.record_purchase_invoice(
            invoice_id="INV001",
            vendor_id="V001",
            invoice_date=date(2024, 1, 1),
            due_date=date(2024, 1, 31),
            lines=lines,
        )

        assert invoice.id == "INV001"
        assert invoice.total == Decimal("800.00")
        assert invoice.status == InvoiceStatus.SUBMITTED

    def test_invoice_duplicate_error(self, ap: AccountsPayable, setup_vendors) -> None:
        """Test that duplicate invoices are rejected."""
        lines = [LineItem(account_id="5000", debit=Decimal("100.00"))]
        ap.record_purchase_invoice("INV001", "V001", date(2024, 1, 1), date(2024, 1, 31), lines)

        with pytest.raises(InvoiceError):
            ap.record_purchase_invoice("INV001", "V001", date(2024, 1, 1), date(2024, 1, 31), lines)

    def test_approve_invoice(self, ap: AccountsPayable, setup_vendors) -> None:
        """Test invoice approval workflow."""
        lines = [LineItem(account_id="5000", debit=Decimal("100.00"))]
        invoice = ap.record_purchase_invoice("INV001", "V001", date(2024, 1, 1), date(2024, 1, 31), lines)

        ap.approve_invoice("INV001", "USER001")

        assert invoice.status == InvoiceStatus.APPROVED
        assert "INV001" in ap.invoice_approvals

    def test_record_payment(self, ap: AccountsPayable, setup_vendors) -> None:
        """Test payment recording."""
        lines = [LineItem(account_id="5000", debit=Decimal("500.00"))]
        ap.record_purchase_invoice("INV001", "V001", date(2024, 1, 1), date(2024, 1, 31), lines)

        ap.record_payment("INV001", Decimal("300.00"), date(2024, 1, 15))

        invoice = ap.invoices["INV001"]
        assert invoice.paid_amount == Decimal("300.00")
        assert invoice.status == InvoiceStatus.PARTIALLY_PAID

    def test_full_payment(self, ap: AccountsPayable, setup_vendors) -> None:
        """Test full invoice payment."""
        lines = [LineItem(account_id="5000", debit=Decimal("500.00"))]
        ap.record_purchase_invoice("INV001", "V001", date(2024, 1, 1), date(2024, 1, 31), lines)

        ap.record_payment("INV001", Decimal("500.00"), date(2024, 1, 15))

        invoice = ap.invoices["INV001"]
        assert invoice.status == InvoiceStatus.PAID

    def test_payment_terms_calculation(self, ap: AccountsPayable, payment_terms) -> None:
        """Test due date calculation from payment terms."""
        invoice_date = date(2024, 1, 1)
        due_date = ap.calculate_payment_due_date(invoice_date, payment_terms)

        assert due_date == date(2024, 1, 31)

    def test_early_payment_discount(self, ap: AccountsPayable, payment_terms) -> None:
        """Test early payment discount calculation."""
        invoice_amount = Decimal("1000.00")
        invoice_date = date(2024, 1, 1)
        payment_date = date(2024, 1, 8)

        discount = ap.calculate_early_payment_discount(invoice_amount, payment_terms, payment_date, invoice_date)

        expected_discount = Decimal("1000.00") * (Decimal("2.00") / Decimal("100.00"))
        assert discount == expected_discount

    def test_no_discount_after_deadline(self, ap: AccountsPayable, payment_terms) -> None:
        """Test that discount is not applied after deadline."""
        invoice_amount = Decimal("1000.00")
        invoice_date = date(2024, 1, 1)
        payment_date = date(2024, 1, 15)

        discount = ap.calculate_early_payment_discount(invoice_amount, payment_terms, payment_date, invoice_date)

        assert discount == Decimal("0.00")

    def test_payment_batch_generation(self, ap: AccountsPayable, setup_vendors) -> None:
        """Test payment batch generation."""
        lines = [LineItem(account_id="5000", debit=Decimal("500.00"))]

        ap.record_purchase_invoice("INV001", "V001", date(2024, 1, 1), date(2024, 1, 15), lines)
        ap.record_purchase_invoice("INV002", "V001", date(2024, 1, 5), date(2024, 1, 20), lines)

        batch = ap.generate_payment_batch(date(2024, 1, 31))

        assert "V001" in batch
        assert len(batch["V001"]) >= 1

    def test_aging_report(self, ap: AccountsPayable, setup_vendors) -> None:
        """Test AP aging report."""
        lines = [LineItem(account_id="5000", debit=Decimal("500.00"))]

        ap.record_purchase_invoice("INV001", "V001", date(2024, 1, 1), date(2024, 1, 15), lines)

        aging = ap.aging_report(date(2024, 2, 15))

        assert "V001" in aging
        assert aging["V001"]["total"] == Decimal("500.00")

    def test_1099_tracking(self, ap: AccountsPayable, setup_vendors) -> None:
        """Test 1099 vendor tracking."""
        ap.track_1099_vendor("V001", Decimal("500.00"))
        ap.track_1099_vendor("V001", Decimal("300.00"))

        amount = ap.get_1099_amount("V001")
        assert amount == Decimal("800.00")

    def test_vendor_statement_reconciliation(self, ap: AccountsPayable, setup_vendors) -> None:
        """Test vendor statement reconciliation."""
        lines = [LineItem(account_id="5000", debit=Decimal("500.00"))]

        ap.record_purchase_invoice("INV001", "V001", date(2024, 1, 1), date(2024, 1, 31), lines)

        matches = ap.reconcile_vendor_statement("V001", date(2024, 1, 31), Decimal("500.00"))
        assert matches

    def test_three_way_match(self, ap: AccountsPayable, setup_vendors) -> None:
        """Test three-way matching initiation."""
        lines = [LineItem(account_id="5000", debit=Decimal("500.00"))]

        ap.record_purchase_invoice("INV001", "V001", date(2024, 1, 1), date(2024, 1, 31), lines, po_id="PO001")

        assert "INV001" in ap.three_way_matches

    def test_complete_three_way_match(self, ap: AccountsPayable, setup_vendors) -> None:
        """Test completing three-way match."""
        lines = [LineItem(account_id="5000", debit=Decimal("500.00"))]

        ap.record_purchase_invoice("INV001", "V001", date(2024, 1, 1), date(2024, 1, 31), lines, po_id="PO001")

        result = ap.complete_three_way_match("INV001", po_verified=True, receipt_verified=True)
        assert result

    def test_outstanding_invoices(self, ap: AccountsPayable, setup_vendors) -> None:
        """Test retrieving outstanding invoices."""
        lines = [LineItem(account_id="5000", debit=Decimal("500.00"))]

        ap.record_purchase_invoice("INV001", "V001", date(2024, 1, 1), date(2024, 1, 31), lines)
        ap.record_payment("INV001", Decimal("300.00"), date(2024, 1, 15))

        outstanding = ap.get_outstanding_invoices("V001")
        assert len(outstanding) == 1
        assert outstanding[0].id == "INV001"
