"""
Integration tests covering multi-module ERP workflows.
"""

from datetime import date
from decimal import Decimal

import pytest

from thomas.erp._types import (
    AccountType,
    BOMLine,
    Currency,
    InvoiceStatus,
    LineItem,
    POStatus,
)
from thomas.erp.accounts_payable import AccountsPayable
from thomas.erp.accounts_receivable import AccountsReceivable
from thomas.erp.financial_reports import FinancialReporter
from thomas.erp.general_ledger import GeneralLedger
from thomas.erp.inventory import InventoryManager
from thomas.erp.manufacturing import ManufacturingManager
from thomas.erp.purchasing import PurchasingManager
from thomas.erp.sales import SalesManager
from thomas.erp.tax import TaxManager


class TestERPIntegration:
    """Integration tests for complete ERP workflows."""

    @pytest.fixture
    def setup_erp(self):
        """Set up complete ERP system."""
        return {
            "gl": GeneralLedger(),
            "ap": AccountsPayable(),
            "ar": AccountsReceivable(),
            "inv": InventoryManager(),
            "purch": PurchasingManager(),
            "sales": SalesManager(),
            "mfg": ManufacturingManager(),
            "tax": TaxManager(),
        }

    def test_complete_purchase_cycle(self, setup_erp) -> None:
        """Test complete purchase-to-pay cycle."""
        ap = setup_erp["ap"]
        inv = setup_erp["inv"]
        gl = setup_erp["gl"]

        gl.create_account("1200", "Inventory", AccountType.ASSET)
        gl.create_account("2000", "AP", AccountType.LIABILITY)
        gl.create_account("5000", "Purchases", AccountType.EXPENSE)

        ap.create_vendor("V001", "Supplier A")

        inv.create_item(
            "SKU001", "Widget", __import__("thomas.erp._types", fromlist=["UnitOfMeasure"]).UnitOfMeasure.PIECE, "FIFO"
        )

        lines = [LineItem(account_id="5000", debit=Decimal("1000.00"), description="Materials")]
        invoice = ap.record_purchase_invoice("INV001", "V001", date(2024, 1, 1), date(2024, 1, 31), lines)

        assert invoice.status == InvoiceStatus.SUBMITTED

        ap.approve_invoice("INV001", "APPROVER01")
        assert invoice.status == InvoiceStatus.APPROVED

        ap.record_payment("INV001", Decimal("1000.00"), date(2024, 1, 25))
        assert invoice.status == InvoiceStatus.PAID

    def test_complete_sales_cycle(self, setup_erp) -> None:
        """Test complete order-to-cash cycle."""
        ar = setup_erp["ar"]
        sales = setup_erp["sales"]

        ar.create_customer("C001", "Customer A", credit_limit=Decimal("10000.00"))

        lines = [LineItem(account_id="4000", credit=Decimal("500.00"), description="Service")]

        quote = sales.create_quote("Q001", "C001", date(2024, 2, 28), lines)

        so = sales.convert_quote_to_order("Q001", "SO001", date(2024, 2, 1))
        assert so.id == "SO001"

        shipment = sales.fulfill_order("SO001", {0: Decimal("1.00")}, date(2024, 1, 20), shipment_reference="TRACK123")

        invoice = ar.create_sales_invoice("INV001", "C001", date(2024, 1, 1), date(2024, 1, 31), lines)

        ar.apply_payment("C001", Decimal("500.00"), date(2024, 1, 25))
        assert invoice.status == InvoiceStatus.PAID

    def test_manufacturing_workflow(self, setup_erp) -> None:
        """Test complete manufacturing workflow."""
        mfg = setup_erp["mfg"]

        bom_lines = [
            BOMLine(sku="MAT001", quantity=Decimal("2.00"), unit_cost=Decimal("5.00")),
            BOMLine(sku="MAT002", quantity=Decimal("1.00"), unit_cost=Decimal("10.00")),
        ]

        bom = mfg.create_bom("BOM001", "PRODUCT001", bom_lines)

        pr = mfg.create_production_order(
            "PR001", "BOM001", "PRODUCT001", Decimal("50.00"), date(2024, 1, 1), date(2024, 1, 15)
        )

        assert pr.planned_materials["MAT001"] == Decimal("100.00")

        mfg.release_production_order("PR001")

        op1 = mfg.record_operation_start("PR001", "WC001", 1, Decimal("50.00"))
        mfg.record_operation_completion(op1.operation_id, Decimal("48.00"))

        op2 = mfg.record_operation_start("PR001", "WC002", 2, Decimal("48.00"))
        mfg.record_operation_completion(op2.operation_id, Decimal("48.00"))

        mfg.complete_production_order("PR001")

        yield_pct = mfg.calculate_yield("PR001")
        assert yield_pct == Decimal("48.00")

    def test_financial_reporting_workflow(self, setup_erp) -> None:
        """Test financial reporting with GL data."""
        gl = setup_erp["gl"]

        gl.create_account("1000", "Cash", AccountType.ASSET)
        gl.create_account("1100", "AR", AccountType.ASSET)
        gl.create_account("2000", "AP", AccountType.LIABILITY)
        gl.create_account("3000", "Equity", AccountType.EQUITY)
        gl.create_account("4000", "Revenue", AccountType.REVENUE)
        gl.create_account("5000", "COGS", AccountType.COGS)
        gl.create_account("6000", "Expenses", AccountType.EXPENSE)

        from thomas.erp._types import JournalEntry

        entry1 = JournalEntry(
            id="JE001",
            entry_date=date(2024, 1, 1),
            description="Initial capital",
            lines=[
                LineItem(account_id="1000", debit=Decimal("100000.00")),
                LineItem(account_id="3000", credit=Decimal("100000.00")),
            ],
        )
        gl.post_journal_entry(entry1)

        entry2 = JournalEntry(
            id="JE002",
            entry_date=date(2024, 1, 15),
            description="Sales",
            lines=[
                LineItem(account_id="1100", debit=Decimal("5000.00")),
                LineItem(account_id="4000", credit=Decimal("5000.00")),
            ],
        )
        gl.post_journal_entry(entry2)

        entry3 = JournalEntry(
            id="JE003",
            entry_date=date(2024, 1, 20),
            description="COGS",
            lines=[
                LineItem(account_id="5000", debit=Decimal("2000.00")),
                LineItem(account_id="1000", credit=Decimal("2000.00")),
            ],
        )
        gl.post_journal_entry(entry3)

        reporter = FinancialReporter(gl)

        pl = reporter.income_statement(date(2024, 1, 1), date(2024, 1, 31))
        assert pl["revenue"] == Decimal("5000.00")
        assert pl["cost_of_goods_sold"] == Decimal("2000.00")
        assert pl["gross_profit"] == Decimal("3000.00")

        bs = reporter.balance_sheet(date(2024, 1, 31))
        assert bs["assets"]["total"] > Decimal("0.00")
        assert bs["equity"]["total"] == Decimal("100000.00")

    def test_tax_integration(self, setup_erp) -> None:
        """Test tax calculation and reporting."""
        tax = setup_erp["tax"]

        tax.create_tax_code("TAX001", "Sales Tax CA", Decimal("7.25"), "US-CA", "SALES")
        tax.create_tax_code("TAX002", "Sales Tax NY", Decimal("8.00"), "US-NY", "SALES")

        tax.record_tax_transaction(date(2024, 1, 1), "SALES", Decimal("1000.00"), "TAX001")
        tax.record_tax_transaction(date(2024, 1, 5), "PURCHASE", Decimal("500.00"), "TAX001")

        liability = tax.calculate_tax_liability(date(2024, 1, 1), date(2024, 1, 31))

        assert "SALES" in liability

        return_data = tax.prepare_tax_return(date(2024, 1, 1), date(2024, 1, 31), "US-CA")

        assert return_data["output_tax"] > Decimal("0.00")

    def test_procurement_to_inventory(self, setup_erp) -> None:
        """Test procurement workflow affecting inventory."""
        purch = setup_erp["purch"]
        inv = setup_erp["inv"]
        ap = setup_erp["ap"]

        purch.vendors["V001"] = __import__("thomas.erp._types", fromlist=["Vendor"]).Vendor(
            id="V001", name="Supplier A"
        )

        UnitOfMeasure = __import__("thomas.erp._types", fromlist=["UnitOfMeasure"]).UnitOfMeasure
        inv.create_item("SKU001", "Component A", UnitOfMeasure.PIECE, "FIFO", standard_cost=Decimal("10.00"))

        lines = [
            LineItem(
                account_id="1200",
                debit=Decimal("1000.00"),
                description="SKU001 x100 @ $10",
                quantity=Decimal("100.00"),
                unit_price=Decimal("10.00"),
            )
        ]

        po = purch.create_purchase_order("PO001", "V001", date(2024, 1, 1), date(2024, 1, 15), lines)

        purch.approve_po("PO001", "APPROVER01")

        inv.receive_stock("SKU001", Decimal("100.00"), Decimal("10.00"))

        purch.record_goods_receipt("PO001", {0: Decimal("100.00")}, date(2024, 1, 10))

        assert inv.items["SKU001"].quantity_on_hand == Decimal("100.00")
        assert po.status == POStatus.RECEIVED

    def test_make_to_order_workflow(self, setup_erp) -> None:
        """Test make-to-order manufacturing workflow."""
        sales = setup_erp["sales"]
        mfg = setup_erp["mfg"]
        inv = setup_erp["inv"]

        sales.create_customer("C001", "Customer A")

        UnitOfMeasure = __import__("thomas.erp._types", fromlist=["UnitOfMeasure"]).UnitOfMeasure
        inv.create_item("MAT001", "Material A", UnitOfMeasure.PIECE, "FIFO")
        inv.create_item("MAT002", "Material B", UnitOfMeasure.PIECE, "FIFO")
        inv.create_item("PROD001", "Product A", UnitOfMeasure.PIECE, "FIFO")

        inv.receive_stock("MAT001", Decimal("1000.00"), Decimal("5.00"))
        inv.receive_stock("MAT002", Decimal("500.00"), Decimal("10.00"))

        lines = [LineItem(account_id="4000", credit=Decimal("1000.00"))]
        so = sales.create_sales_order("SO001", "C001", date(2024, 2, 15), lines)

        bom_lines = [
            BOMLine(sku="MAT001", quantity=Decimal("2.00"), unit_cost=Decimal("5.00")),
            BOMLine(sku="MAT002", quantity=Decimal("1.00"), unit_cost=Decimal("10.00")),
        ]
        mfg.create_bom("BOM001", "PROD001", bom_lines)

        pr = mfg.create_production_order(
            "PR001", "BOM001", "PROD001", Decimal("100.00"), date(2024, 1, 20), date(2024, 2, 15)
        )

        assert pr.planned_materials["MAT001"] == Decimal("200.00")
        assert pr.planned_materials["MAT002"] == Decimal("100.00")

    def test_multi_currency_operations(self, setup_erp) -> None:
        """Test multi-currency transactions."""
        gl = setup_erp["gl"]

        gl.create_account("1010", "EUR Cash", AccountType.ASSET, currency=Currency.EUR)
        gl.create_account("1000", "USD Cash", AccountType.ASSET, currency=Currency.USD)
        gl.create_account("3000", "Equity", AccountType.EQUITY)

        from thomas.erp._types import JournalEntry

        entry = JournalEntry(
            id="JE001",
            entry_date=date(2024, 1, 1),
            description="Multi-currency funding",
            lines=[
                LineItem(account_id="1010", debit=Decimal("1000.00")),
                LineItem(account_id="1000", credit=Decimal("1100.00")),
            ],
        )

        exchange_rates = {
            "EUR": Decimal("1.10"),
            "USD": Decimal("1.00"),
        }

        gl.post_multi_currency_entry(entry, exchange_rates)
        assert entry.posted

    def test_inventory_to_financial_reports(self, setup_erp) -> None:
        """Test how inventory transactions affect financial statements."""
        inv = setup_erp["inv"]
        gl = setup_erp["gl"]

        gl.create_account("1200", "Inventory", AccountType.ASSET)
        gl.create_account("5000", "COGS", AccountType.COGS)

        UnitOfMeasure = __import__("thomas.erp._types", fromlist=["UnitOfMeasure"]).UnitOfMeasure
        inv.create_item("SKU001", "Widget", UnitOfMeasure.PIECE, "FIFO", standard_cost=Decimal("10.00"))

        inv.receive_stock("SKU001", Decimal("100.00"), Decimal("10.00"))

        inv_value = inv.get_inventory_valuation("SKU001")
        assert inv_value == Decimal("1000.00")

        inv.issue_stock("SKU001", Decimal("50.00"))

        remaining_value = inv.get_inventory_valuation("SKU001")
        assert remaining_value == Decimal("500.00")
