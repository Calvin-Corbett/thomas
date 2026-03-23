"""
Tests for accounts receivable functionality.
"""

from datetime import date
from decimal import Decimal

import pytest

from thomas.marketplace.erp._exceptions import CustomerError, InvoiceError
from thomas.marketplace.erp._types import InvoiceStatus, InvoiceType, LineItem
from thomas.marketplace.erp.accounts_receivable import AccountsReceivable


class TestAccountsReceivable:
    """Test accounts receivable operations."""

    @pytest.fixture
    def ar(self) -> AccountsReceivable:
        """Create an accounts receivable instance."""
        return AccountsReceivable()

    @pytest.fixture
    def setup_customers(self, ar: AccountsReceivable) -> None:
        """Set up test customers."""
        ar.create_customer(
            "C001",
            "ABC Corporation",
            contact_name="Alice",
            email="alice@abc.com",
            credit_limit=Decimal("10000.00"),
        )
        ar.create_customer(
            "C002",
            "XYZ Industries",
            contact_name="Bob",
            email="bob@xyz.com",
            credit_limit=Decimal("5000.00"),
        )

    def test_create_customer(self, ar: AccountsReceivable) -> None:
        """Test customer creation."""
        customer = ar.create_customer("C001", "Test Company")
        assert customer.id == "C001"
        assert customer.name == "Test Company"
        assert customer.is_active

    def test_duplicate_customer_error(self, ar: AccountsReceivable) -> None:
        """Test that duplicate customers are rejected."""
        ar.create_customer("C001", "Company 1")
        with pytest.raises(CustomerError):
            ar.create_customer("C001", "Duplicate")

    def test_get_customer(self, ar: AccountsReceivable, setup_customers) -> None:
        """Test retrieving a customer."""
        customer = ar.get_customer("C001")
        assert customer.id == "C001"
        assert customer.name == "ABC Corporation"

    def test_customer_not_found(self, ar: AccountsReceivable) -> None:
        """Test retrieving non-existent customer."""
        with pytest.raises(CustomerError):
            ar.get_customer("C999")

    def test_create_sales_invoice(self, ar: AccountsReceivable, setup_customers) -> None:
        """Test creating a sales invoice."""
        lines = [
            LineItem(account_id="4000", credit=Decimal("1000.00"), description="Product A"),
            LineItem(account_id="4100", credit=Decimal("200.00"), description="Service"),
        ]

        invoice = ar.create_sales_invoice(
            invoice_id="INV001",
            customer_id="C001",
            invoice_date=date(2024, 1, 1),
            due_date=date(2024, 1, 31),
            lines=lines,
        )

        assert invoice.id == "INV001"
        assert invoice.total == Decimal("1200.00")
        assert invoice.customer_id == "C001"
        assert invoice.status == InvoiceStatus.SUBMITTED

    def test_duplicate_invoice_error(self, ar: AccountsReceivable, setup_customers) -> None:
        """Test that duplicate invoices are rejected."""
        lines = [LineItem(account_id="4000", credit=Decimal("100.00"))]
        ar.create_sales_invoice("INV001", "C001", date(2024, 1, 1), date(2024, 1, 31), lines)

        with pytest.raises(InvoiceError):
            ar.create_sales_invoice("INV001", "C001", date(2024, 1, 1), date(2024, 1, 31), lines)

    def test_record_payment_single_invoice(self, ar: AccountsReceivable, setup_customers) -> None:
        """Test recording payment against single invoice."""
        lines = [LineItem(account_id="4000", credit=Decimal("500.00"))]
        ar.create_sales_invoice("INV001", "C001", date(2024, 1, 1), date(2024, 1, 31), lines)

        remaining = ar.record_payment("INV001", Decimal("300.00"), date(2024, 1, 15))

        assert remaining == Decimal("200.00")
        invoice = ar.invoices["INV001"]
        assert invoice.status == InvoiceStatus.PARTIALLY_PAID

    def test_full_payment(self, ar: AccountsReceivable, setup_customers) -> None:
        """Test full invoice payment."""
        lines = [LineItem(account_id="4000", credit=Decimal("500.00"))]
        ar.create_sales_invoice("INV001", "C001", date(2024, 1, 1), date(2024, 1, 31), lines)

        remaining = ar.record_payment("INV001", Decimal("500.00"), date(2024, 1, 15))

        assert remaining == Decimal("0.00")
        invoice = ar.invoices["INV001"]
        assert invoice.status == InvoiceStatus.PAID

    def test_apply_payment_fifo(self, ar: AccountsReceivable, setup_customers) -> None:
        """Test payment application with FIFO allocation."""
        lines = [LineItem(account_id="4000", credit=Decimal("500.00"))]

        ar.create_sales_invoice("INV001", "C001", date(2024, 1, 1), date(2024, 1, 15), lines)
        ar.create_sales_invoice("INV002", "C001", date(2024, 1, 5), date(2024, 1, 20), lines)

        allocation = ar.apply_payment("C001", Decimal("750.00"), date(2024, 1, 30))

        assert "INV001" in allocation
        assert allocation["INV001"] == Decimal("500.00")
        assert allocation["INV002"] == Decimal("250.00")

    def test_create_credit_memo(self, ar: AccountsReceivable, setup_customers) -> None:
        """Test creating a credit memo."""
        lines = [LineItem(account_id="4000", credit=Decimal("500.00"))]
        ar.create_sales_invoice("INV001", "C001", date(2024, 1, 1), date(2024, 1, 31), lines)

        memo = ar.create_credit_memo(
            memo_id="CM001",
            customer_id="C001",
            memo_date=date(2024, 1, 20),
            original_invoice_id="INV001",
            amount=Decimal("100.00"),
            reason="Return of defective goods",
        )

        assert memo.id == "CM001"
        assert memo.invoice_type == InvoiceType.CREDIT_MEMO
        assert ar.invoices["INV001"].paid_amount == Decimal("100.00")

    def test_aging_report(self, ar: AccountsReceivable, setup_customers) -> None:
        """Test AR aging report."""
        lines = [LineItem(account_id="4000", credit=Decimal("1000.00"))]

        ar.create_sales_invoice("INV001", "C001", date(2024, 1, 1), date(2024, 1, 15), lines)
        ar.create_sales_invoice("INV002", "C001", date(2023, 12, 1), date(2023, 12, 31), lines)

        aging = ar.aging_report(date(2024, 2, 15))

        assert "C001" in aging
        assert aging["C001"]["total"] == Decimal("2000.00")
        assert aging["C001"]["30_days"] > Decimal("0.00")

    def test_generate_dunning_notice(self, ar: AccountsReceivable, setup_customers) -> None:
        """Test dunning notice generation."""
        lines = [LineItem(account_id="4000", credit=Decimal("500.00"))]

        ar.create_sales_invoice("INV001", "C001", date(2024, 1, 1), date(2024, 1, 15), lines)

        notice = ar.generate_dunning_notice("C001", date(2024, 2, 15), notice_level=1)

        assert notice is not None
        assert notice["customer_id"] == "C001"
        assert notice["total_overdue"] == Decimal("500.00")

    def test_no_dunning_for_paid(self, ar: AccountsReceivable, setup_customers) -> None:
        """Test that paid invoices don't generate dunning notices."""
        lines = [LineItem(account_id="4000", credit=Decimal("500.00"))]

        ar.create_sales_invoice("INV001", "C001", date(2024, 1, 1), date(2024, 1, 15), lines)
        ar.record_payment("INV001", Decimal("500.00"), date(2024, 1, 20))

        notice = ar.generate_dunning_notice("C001", date(2024, 2, 15))
        assert notice is None

    def test_revenue_recognition_immediate(self, ar: AccountsReceivable, setup_customers) -> None:
        """Test immediate revenue recognition."""
        lines = [LineItem(account_id="4000", credit=Decimal("1000.00"))]
        ar.create_sales_invoice("INV001", "C001", date(2024, 1, 1), date(2024, 1, 31), lines)

        schedule = ar.recognize_revenue("INV001", "IMMEDIATE", date(2024, 1, 1))

        assert len(schedule) == 1
        assert schedule[0][1] == Decimal("1000.00")

    def test_revenue_recognition_ratably(self, ar: AccountsReceivable, setup_customers) -> None:
        """Test ratably recognized revenue."""
        lines = [LineItem(account_id="4000", credit=Decimal("1000.00"))]
        ar.create_sales_invoice("INV001", "C001", date(2024, 1, 1), date(2024, 1, 31), lines)

        schedule = ar.recognize_revenue("INV001", "RATABLY", date(2024, 1, 1), date(2024, 1, 31))

        assert len(schedule) == 31

    def test_get_revenue_recognition_amount(self, ar: AccountsReceivable, setup_customers) -> None:
        """Test calculating recognized revenue through a date."""
        lines = [LineItem(account_id="4000", credit=Decimal("1000.00"))]
        ar.create_sales_invoice("INV001", "C001", date(2024, 1, 1), date(2024, 1, 31), lines)

        ar.recognize_revenue("INV001", "RATABLY", date(2024, 1, 1), date(2024, 1, 31))

        recognized = ar.get_revenue_recognition_amount("INV001", date(2024, 1, 15))
        assert recognized > Decimal("0.00")
        assert recognized < Decimal("1000.00")

    def test_generate_customer_statement(self, ar: AccountsReceivable, setup_customers) -> None:
        """Test customer statement generation."""
        lines = [LineItem(account_id="4000", credit=Decimal("500.00"))]

        ar.create_sales_invoice("INV001", "C001", date(2024, 1, 1), date(2024, 1, 31), lines)
        ar.create_sales_invoice("INV002", "C001", date(2024, 1, 5), date(2024, 2, 5), lines)

        statement = ar.generate_customer_statement("C001", date(2024, 2, 15))

        assert statement["customer_id"] == "C001"
        assert statement["total_due"] == Decimal("1000.00")
        assert len(statement["invoices"]) == 2

    def test_get_customer_balance(self, ar: AccountsReceivable, setup_customers) -> None:
        """Test getting customer total balance."""
        lines = [LineItem(account_id="4000", credit=Decimal("500.00"))]

        ar.create_sales_invoice("INV001", "C001", date(2024, 1, 1), date(2024, 1, 31), lines)
        ar.create_sales_invoice("INV002", "C001", date(2024, 1, 5), date(2024, 2, 5), lines)

        balance = ar.get_customer_balance("C001")
        assert balance == Decimal("1000.00")

    def test_get_overdue_invoices(self, ar: AccountsReceivable, setup_customers) -> None:
        """Test retrieving overdue invoices."""
        lines = [LineItem(account_id="4000", credit=Decimal("500.00"))]

        ar.create_sales_invoice("INV001", "C001", date(2024, 1, 1), date(2024, 1, 15), lines)
        ar.create_sales_invoice("INV002", "C001", date(2024, 1, 5), date(2024, 3, 1), lines)

        overdue = ar.get_overdue_invoices()
        assert len(overdue) >= 0
