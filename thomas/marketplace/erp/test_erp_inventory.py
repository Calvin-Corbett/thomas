"""
Tests for inventory management functionality.
"""

from decimal import Decimal

import pytest

from thomas.marketplace.erp._exceptions import InsufficientInventoryError
from thomas.marketplace.erp._types import UnitOfMeasure
from thomas.marketplace.erp.inventory import InventoryManager, TransactionType


class TestInventoryManager:
    """Test inventory management operations."""

    @pytest.fixture
    def inv(self) -> InventoryManager:
        """Create an inventory manager instance."""
        return InventoryManager()

    def test_create_item(self, inv: InventoryManager) -> None:
        """Test inventory item creation."""
        item = inv.create_item(
            sku="SKU001",
            description="Widget A",
            uom=UnitOfMeasure.PIECE,
            cost_method="FIFO",
            standard_cost=Decimal("10.00"),
            min_quantity=Decimal("10.00"),
            max_quantity=Decimal("100.00"),
            reorder_quantity=Decimal("50.00"),
        )

        assert item.sku == "SKU001"
        assert item.description == "Widget A"
        assert item.cost_method == "FIFO"

    def test_duplicate_item_error(self, inv: InventoryManager) -> None:
        """Test that duplicate items are rejected."""
        inv.create_item("SKU001", "Widget A", UnitOfMeasure.PIECE, "FIFO")
        with pytest.raises(ValueError):
            inv.create_item("SKU001", "Duplicate", UnitOfMeasure.PIECE, "FIFO")

    def test_receive_stock(self, inv: InventoryManager) -> None:
        """Test stock receipt."""
        inv.create_item("SKU001", "Widget A", UnitOfMeasure.PIECE, "FIFO")

        transaction = inv.receive_stock(
            sku="SKU001",
            quantity=Decimal("100.00"),
            unit_cost=Decimal("10.00"),
            reference="PO001",
        )

        assert transaction.transaction_type == TransactionType.RECEIVE
        assert inv.items["SKU001"].quantity_on_hand == Decimal("100.00")

    def test_issue_stock(self, inv: InventoryManager) -> None:
        """Test stock issue."""
        inv.create_item("SKU001", "Widget A", UnitOfMeasure.PIECE, "FIFO")

        inv.receive_stock("SKU001", Decimal("100.00"), Decimal("10.00"))

        transaction = inv.issue_stock("SKU001", Decimal("30.00"), reference="SO001")

        assert transaction.transaction_type == TransactionType.ISSUE
        assert inv.items["SKU001"].quantity_on_hand == Decimal("70.00")

    def test_insufficient_stock_error(self, inv: InventoryManager) -> None:
        """Test that insufficient stock is rejected."""
        inv.create_item("SKU001", "Widget A", UnitOfMeasure.PIECE, "FIFO")

        inv.receive_stock("SKU001", Decimal("50.00"), Decimal("10.00"))

        with pytest.raises(InsufficientInventoryError):
            inv.issue_stock("SKU001", Decimal("100.00"))

    def test_transfer_stock(self, inv: InventoryManager) -> None:
        """Test stock transfer between locations."""
        inv.create_item("SKU001", "Widget A", UnitOfMeasure.PIECE, "FIFO")

        inv.receive_stock("SKU001", Decimal("100.00"), Decimal("10.00"), location="WH1")

        transaction = inv.transfer_stock("SKU001", Decimal("50.00"), "WH1", "WH2")

        assert transaction.transaction_type == TransactionType.TRANSFER
        assert inv.items["SKU001"].locations["WH1"] == Decimal("50.00")
        assert inv.items["SKU001"].locations["WH2"] == Decimal("50.00")

    def test_adjust_inventory(self, inv: InventoryManager) -> None:
        """Test inventory adjustment."""
        inv.create_item("SKU001", "Widget A", UnitOfMeasure.PIECE, "FIFO")

        inv.receive_stock("SKU001", Decimal("100.00"), Decimal("10.00"))

        inv.adjust_inventory("SKU001", Decimal("-5.00"), reason="Damage")

        assert inv.items["SKU001"].quantity_on_hand == Decimal("95.00")

    def test_reserve_stock(self, inv: InventoryManager) -> None:
        """Test stock reservation."""
        inv.create_item("SKU001", "Widget A", UnitOfMeasure.PIECE, "FIFO")

        inv.receive_stock("SKU001", Decimal("100.00"), Decimal("10.00"))

        inv.reserve_stock("SKU001", Decimal("30.00"))

        item = inv.items["SKU001"]
        assert item.quantity_reserved == Decimal("30.00")
        assert item.quantity_available == Decimal("70.00")

    def test_release_reservation(self, inv: InventoryManager) -> None:
        """Test releasing stock reservation."""
        inv.create_item("SKU001", "Widget A", UnitOfMeasure.PIECE, "FIFO")

        inv.receive_stock("SKU001", Decimal("100.00"), Decimal("10.00"))
        inv.reserve_stock("SKU001", Decimal("30.00"))

        inv.release_reservation("SKU001", Decimal("20.00"))

        item = inv.items["SKU001"]
        assert item.quantity_reserved == Decimal("10.00")
        assert item.quantity_available == Decimal("90.00")

    def test_fifo_valuation(self, inv: InventoryManager) -> None:
        """Test FIFO inventory valuation."""
        inv.create_item("SKU001", "Widget A", UnitOfMeasure.PIECE, "FIFO")

        inv.receive_stock("SKU001", Decimal("50.00"), Decimal("10.00"))
        inv.receive_stock("SKU001", Decimal("50.00"), Decimal("12.00"))

        valuation = inv.get_inventory_valuation("SKU001")
        expected = (Decimal("50.00") * Decimal("10.00")) + (Decimal("50.00") * Decimal("12.00"))
        assert valuation == expected

    def test_weighted_average_valuation(self, inv: InventoryManager) -> None:
        """Test weighted average inventory valuation."""
        inv.create_item("SKU001", "Widget A", UnitOfMeasure.PIECE, "WEIGHTED_AVERAGE")

        inv.receive_stock("SKU001", Decimal("50.00"), Decimal("10.00"))
        inv.receive_stock("SKU001", Decimal("50.00"), Decimal("12.00"))

        valuation = inv.get_inventory_valuation("SKU001")
        expected = (Decimal("50.00") * Decimal("10.00")) + (Decimal("50.00") * Decimal("12.00"))
        assert valuation == expected

    def test_cycle_count(self, inv: InventoryManager) -> None:
        """Test inventory cycle counting."""
        inv.create_item("SKU001", "Widget A", UnitOfMeasure.PIECE, "FIFO")

        inv.receive_stock("SKU001", Decimal("100.00"), Decimal("10.00"))

        counted_items = {"SKU001": Decimal("95.00")}
        discrepancies = inv.cycle_count("WH1", counted_items)

        assert "SKU001" in discrepancies
        assert discrepancies["SKU001"][2] == Decimal("-5.00")

    def test_check_reorder_points(self, inv: InventoryManager) -> None:
        """Test reorder point checking."""
        inv.create_item(
            "SKU001",
            "Widget A",
            UnitOfMeasure.PIECE,
            "FIFO",
            min_quantity=Decimal("20.00"),
        )

        inv.receive_stock("SKU001", Decimal("15.00"), Decimal("10.00"))

        reorder_needed = inv.check_reorder_points()

        assert "SKU001" in reorder_needed
        assert reorder_needed["SKU001"]["quantity_on_hand"] == Decimal("15.00")

    def test_abc_analysis(self, inv: InventoryManager) -> None:
        """Test ABC inventory analysis."""
        inv.create_item("SKU001", "High Value", UnitOfMeasure.PIECE, "FIFO")
        inv.create_item("SKU002", "Medium Value", UnitOfMeasure.PIECE, "FIFO")
        inv.create_item("SKU003", "Low Value", UnitOfMeasure.PIECE, "FIFO")

        inv.receive_stock("SKU001", Decimal("10.00"), Decimal("1000.00"))
        inv.receive_stock("SKU002", Decimal("50.00"), Decimal("100.00"))
        inv.receive_stock("SKU003", Decimal("1000.00"), Decimal("5.00"))

        analysis = inv.abc_analysis()

        assert "A" in analysis
        assert "B" in analysis
        assert "C" in analysis

    def test_stock_movement_report(self, inv: InventoryManager) -> None:
        """Test stock movement reporting."""
        inv.create_item("SKU001", "Widget A", UnitOfMeasure.PIECE, "FIFO")

        inv.receive_stock("SKU001", Decimal("100.00"), Decimal("10.00"))
        inv.issue_stock("SKU001", Decimal("30.00"))
        inv.receive_stock("SKU001", Decimal("50.00"), Decimal("11.00"))

        report = inv.stock_movement_report("SKU001")

        assert len(report) == 3

    def test_lot_tracking(self, inv: InventoryManager) -> None:
        """Test lot number tracking."""
        inv.create_item(
            "SKU001",
            "Widget A",
            UnitOfMeasure.PIECE,
            "FIFO",
            lot_tracking=True,
        )

        inv.receive_stock(
            "SKU001",
            Decimal("100.00"),
            Decimal("10.00"),
            lot_number="BATCH001",
        )

        assert "SKU001" in inv.lot_tracking
        assert len(inv.lot_tracking["SKU001"]) == 1

    def test_serial_tracking(self, inv: InventoryManager) -> None:
        """Test serial number tracking."""
        inv.create_item(
            "SKU001",
            "Widget A",
            UnitOfMeasure.PIECE,
            "FIFO",
            serial_tracking=True,
        )

        inv.receive_stock("SKU001", Decimal("5.00"), Decimal("100.00"))

        item = inv.items["SKU001"]
        assert item.serial_tracking

    def test_insufficient_reserved_stock(self, inv: InventoryManager) -> None:
        """Test that reserved stock cannot be issued."""
        inv.create_item("SKU001", "Widget A", UnitOfMeasure.PIECE, "FIFO")

        inv.receive_stock("SKU001", Decimal("100.00"), Decimal("10.00"))
        inv.reserve_stock("SKU001", Decimal("80.00"))

        with pytest.raises(InsufficientInventoryError):
            inv.issue_stock("SKU001", Decimal("50.00"))
