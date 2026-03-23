"""
Tests for manufacturing functionality.
"""

from datetime import date
from decimal import Decimal

import pytest

from thomas.marketplace.erp._exceptions import ManufacturingError
from thomas.marketplace.erp._types import BOMLine, PRStatus
from thomas.marketplace.erp.manufacturing import ManufacturingManager


class TestManufacturingManager:
    """Test manufacturing operations."""

    @pytest.fixture
    def mfg(self) -> ManufacturingManager:
        """Create a manufacturing manager instance."""
        return ManufacturingManager()

    def test_create_bom(self, mfg: ManufacturingManager) -> None:
        """Test BOM creation."""
        lines = [
            BOMLine(sku="MAT001", quantity=Decimal("2.00"), unit_cost=Decimal("5.00")),
            BOMLine(sku="MAT002", quantity=Decimal("1.00"), unit_cost=Decimal("10.00")),
        ]

        bom = mfg.create_bom(
            bom_id="BOM001",
            finished_sku="PRODUCT001",
            lines=lines,
        )

        assert bom.id == "BOM001"
        assert bom.finished_sku == "PRODUCT001"
        assert len(bom.lines) == 2

    def test_duplicate_bom_error(self, mfg: ManufacturingManager) -> None:
        """Test that duplicate BOMs are rejected."""
        lines = [BOMLine(sku="MAT001", quantity=Decimal("1.00"), unit_cost=Decimal("5.00"))]
        mfg.create_bom("BOM001", "PRODUCT001", lines)

        with pytest.raises(ManufacturingError):
            mfg.create_bom("BOM001", "PRODUCT001", lines)

    def test_explode_bom_single_level(self, mfg: ManufacturingManager) -> None:
        """Test single-level BOM explosion."""
        lines = [
            BOMLine(sku="MAT001", quantity=Decimal("2.00"), unit_cost=Decimal("5.00")),
            BOMLine(sku="MAT002", quantity=Decimal("1.00"), unit_cost=Decimal("10.00")),
        ]

        mfg.create_bom("BOM001", "PRODUCT001", lines)

        requirements = mfg.explode_bom("PRODUCT001", Decimal("10.00"), "BOM001")

        assert requirements["MAT001"] == Decimal("20.00")
        assert requirements["MAT002"] == Decimal("10.00")

    def test_explode_bom_with_scrap(self, mfg: ManufacturingManager) -> None:
        """Test BOM explosion with scrap/yield."""
        lines = [
            BOMLine(
                sku="MAT001",
                quantity=Decimal("2.00"),
                unit_cost=Decimal("5.00"),
                scrap_percent=Decimal("10.00"),
            ),
        ]

        mfg.create_bom("BOM001", "PRODUCT001", lines)

        requirements = mfg.explode_bom("PRODUCT001", Decimal("10.00"), "BOM001")

        expected = Decimal("10.00") * Decimal("2.00") * (Decimal("1.00") + (Decimal("10.00") / Decimal("100.00")))
        assert requirements["MAT001"] == expected

    def test_create_production_order(self, mfg: ManufacturingManager) -> None:
        """Test production order creation."""
        lines = [BOMLine(sku="MAT001", quantity=Decimal("2.00"), unit_cost=Decimal("5.00"))]
        mfg.create_bom("BOM001", "PRODUCT001", lines)

        pr = mfg.create_production_order(
            pr_id="PR001",
            bom_id="BOM001",
            finished_sku="PRODUCT001",
            quantity_ordered=Decimal("50.00"),
            start_date=date(2024, 1, 1),
            due_date=date(2024, 1, 31),
        )

        assert pr.id == "PR001"
        assert pr.status == PRStatus.DRAFT
        assert pr.planned_materials["MAT001"] == Decimal("100.00")

    def test_duplicate_production_order_error(self, mfg: ManufacturingManager) -> None:
        """Test that duplicate production orders are rejected."""
        lines = [BOMLine(sku="MAT001", quantity=Decimal("2.00"), unit_cost=Decimal("5.00"))]
        mfg.create_bom("BOM001", "PRODUCT001", lines)

        mfg.create_production_order(
            "PR001", "BOM001", "PRODUCT001", Decimal("50.00"), date(2024, 1, 1), date(2024, 1, 31)
        )

        with pytest.raises(ManufacturingError):
            mfg.create_production_order(
                "PR001", "BOM001", "PRODUCT001", Decimal("50.00"), date(2024, 1, 1), date(2024, 1, 31)
            )

    def test_release_production_order(self, mfg: ManufacturingManager) -> None:
        """Test releasing production order."""
        lines = [BOMLine(sku="MAT001", quantity=Decimal("2.00"), unit_cost=Decimal("5.00"))]
        mfg.create_bom("BOM001", "PRODUCT001", lines)

        pr = mfg.create_production_order(
            "PR001", "BOM001", "PRODUCT001", Decimal("50.00"), date(2024, 1, 1), date(2024, 1, 31)
        )

        mfg.release_production_order("PR001")

        assert pr.status == PRStatus.RELEASED

    def test_production_scheduling_forward(self, mfg: ManufacturingManager) -> None:
        """Test forward production scheduling."""
        lines = [BOMLine(sku="MAT001", quantity=Decimal("2.00"), unit_cost=Decimal("5.00"))]
        mfg.create_bom("BOM001", "PRODUCT001", lines)

        routing = mfg.create_routing(
            "ROUTE001",
            "PRODUCT001",
            [
                {"sequence": 1, "work_center": "WC001", "run_time": 60, "setup_time": 30},
                {"sequence": 2, "work_center": "WC002", "run_time": 45, "setup_time": 15},
            ],
        )

        pr = mfg.create_production_order(
            "PR001", "BOM001", "PRODUCT001", Decimal("50.00"), date(2024, 1, 1), date(2024, 1, 31)
        )

        schedule = mfg.schedule_production("PR001", forward_schedule=True)

        assert "1" in schedule
        assert "2" in schedule

    def test_mrp_calculation(self, mfg: ManufacturingManager) -> None:
        """Test material requirements planning."""
        lines = [BOMLine(sku="MAT001", quantity=Decimal("2.00"), unit_cost=Decimal("5.00"))]
        mfg.create_bom("BOM001", "PRODUCT001", lines)

        demand = {"PRODUCT001": (Decimal("100.00"), date(2024, 1, 31))}

        mrp = mfg.material_requirements_planning(demand)

        assert "MAT001" in mrp
        assert mrp["MAT001"]["gross_requirement"] == Decimal("200.00")

    def test_record_operation_start(self, mfg: ManufacturingManager) -> None:
        """Test recording work center operation start."""
        lines = [BOMLine(sku="MAT001", quantity=Decimal("2.00"), unit_cost=Decimal("5.00"))]
        mfg.create_bom("BOM001", "PRODUCT001", lines)

        pr = mfg.create_production_order(
            "PR001", "BOM001", "PRODUCT001", Decimal("50.00"), date(2024, 1, 1), date(2024, 1, 31)
        )

        operation = mfg.record_operation_start("PR001", "WC001", 1, Decimal("50.00"))

        assert operation.production_order_id == "PR001"
        assert operation.status == "IN_PROGRESS"

    def test_record_operation_completion(self, mfg: ManufacturingManager) -> None:
        """Test recording work center operation completion."""
        lines = [BOMLine(sku="MAT001", quantity=Decimal("2.00"), unit_cost=Decimal("5.00"))]
        mfg.create_bom("BOM001", "PRODUCT001", lines)

        pr = mfg.create_production_order(
            "PR001", "BOM001", "PRODUCT001", Decimal("50.00"), date(2024, 1, 1), date(2024, 1, 31)
        )

        operation = mfg.record_operation_start("PR001", "WC001", 1, Decimal("50.00"))

        mfg.record_operation_completion(operation.operation_id, Decimal("45.00"), scrap_quantity=Decimal("5.00"))

        assert operation.status == "COMPLETED"
        assert operation.quantity_completed == Decimal("45.00")

    def test_complete_production_order(self, mfg: ManufacturingManager) -> None:
        """Test completing a production order."""
        lines = [BOMLine(sku="MAT001", quantity=Decimal("2.00"), unit_cost=Decimal("5.00"))]
        mfg.create_bom("BOM001", "PRODUCT001", lines)

        pr = mfg.create_production_order(
            "PR001", "BOM001", "PRODUCT001", Decimal("50.00"), date(2024, 1, 1), date(2024, 1, 31)
        )

        operation = mfg.record_operation_start("PR001", "WC001", 1, Decimal("50.00"))

        mfg.record_operation_completion(operation.operation_id, Decimal("50.00"))
        mfg.complete_production_order("PR001")

        assert pr.status == PRStatus.COMPLETED
        assert pr.quantity_completed == Decimal("50.00")

    def test_get_work_in_progress(self, mfg: ManufacturingManager) -> None:
        """Test retrieving WIP status."""
        lines = [BOMLine(sku="MAT001", quantity=Decimal("2.00"), unit_cost=Decimal("5.00"))]
        mfg.create_bom("BOM001", "PRODUCT001", lines)

        pr = mfg.create_production_order(
            "PR001", "BOM001", "PRODUCT001", Decimal("50.00"), date(2024, 1, 1), date(2024, 1, 31)
        )

        operation = mfg.record_operation_start("PR001", "WC001", 1, Decimal("50.00"))

        mfg.record_operation_completion(operation.operation_id, Decimal("45.00"))

        wip = mfg.get_work_in_progress("PR001")

        assert "PRODUCT001" in wip
        assert wip["PRODUCT001"] == Decimal("45.00")

    def test_calculate_yield(self, mfg: ManufacturingManager) -> None:
        """Test yield calculation."""
        lines = [BOMLine(sku="MAT001", quantity=Decimal("2.00"), unit_cost=Decimal("5.00"))]
        mfg.create_bom("BOM001", "PRODUCT001", lines)

        pr = mfg.create_production_order(
            "PR001", "BOM001", "PRODUCT001", Decimal("100.00"), date(2024, 1, 1), date(2024, 1, 31)
        )

        operation = mfg.record_operation_start("PR001", "WC001", 1, Decimal("100.00"))

        mfg.record_operation_completion(operation.operation_id, Decimal("95.00"))
        mfg.complete_production_order("PR001")

        yield_pct = mfg.calculate_yield("PR001")

        assert yield_pct == Decimal("95.00")
