"""
Tests for supply chain production planning module.

Tests MRP explosion, capacity planning, job shop scheduling,
bottleneck detection, and lot sizing algorithms.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from thomas.supply_chain import SKU, BillOfMaterials, BOMComponent, ProductionOrder, ProductionPlanner


class TestMRPExplosion:
    """Test Material Requirements Planning explosion."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.planner = ProductionPlanner()
        self.product_sku = SKU(code="PROD001", product_id=uuid4())
        self.component_sku = SKU(code="COMP001", product_id=uuid4())

    def test_mrp_basic_explosion(self) -> None:
        """Test basic MRP explosion."""
        bom = BillOfMaterials(
            id=uuid4(),
            product_id=self.product_sku.product_id,
            components=[BOMComponent(id=uuid4(), component_sku=self.component_sku, quantity_per_unit=Decimal("2"))],
        )

        gross_demand = [Decimal("100")] * 4
        on_hand = {self.component_sku: Decimal("50")}
        lead_times = {self.component_sku: 1}
        safety_stock = {self.component_sku: Decimal("10")}

        explosion = self.planner.mrp_explosion(
            product_id=self.product_sku.product_id,
            gross_demand=gross_demand,
            bom=bom,
            on_hand_inventory=on_hand,
            lead_times=lead_times,
            safety_stock=safety_stock,
        )

        assert self.component_sku in explosion
        assert len(explosion[self.component_sku]) == 4

    def test_mrp_with_waste_factor(self) -> None:
        """Test MRP with waste/scrap factor."""
        bom = BillOfMaterials(
            id=uuid4(),
            product_id=self.product_sku.product_id,
            components=[
                BOMComponent(
                    id=uuid4(),
                    component_sku=self.component_sku,
                    quantity_per_unit=Decimal("1"),
                    waste_percentage=Decimal("5"),
                )
            ],
        )

        gross_demand = [Decimal("100")]
        on_hand = {self.component_sku: Decimal("0")}
        lead_times = {self.component_sku: 0}
        safety_stock = {self.component_sku: Decimal("0")}

        explosion = self.planner.mrp_explosion(
            product_id=self.product_sku.product_id,
            gross_demand=gross_demand,
            bom=bom,
            on_hand_inventory=on_hand,
            lead_times=lead_times,
            safety_stock=safety_stock,
        )

        # With 5% waste, requirement should be > 100
        assert explosion[self.component_sku][0].gross_requirement > Decimal("100")


class TestCapacityPlanning:
    """Test Capacity Requirements Planning."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.planner = ProductionPlanner()
        self.product_id = uuid4()

    def test_capacity_requirements(self) -> None:
        """Test capacity requirements calculation."""
        po = ProductionOrder(id=uuid4(), order_number="PO001", product_id=self.product_id, quantity=Decimal("100"))

        resource_capacity = {"RESOURCE1": Decimal("160")}

        crp_results = self.planner.capacity_requirements_planning(
            production_orders=[po], operations={}, resource_capacity=resource_capacity
        )

        assert isinstance(crp_results, list)

    def test_bottleneck_detection_high_utilization(self) -> None:
        """Test bottleneck detection with high utilization."""
        crp_results = self.planner.capacity_requirements_planning(
            production_orders=[], operations={}, resource_capacity={"RES1": Decimal("160")}
        )

        bottlenecks = self.planner.detect_bottlenecks(
            capacity_requirements=crp_results, threshold_percent=Decimal("85")
        )

        assert isinstance(bottlenecks, list)


class TestJobShopScheduling:
    """Test job shop scheduling."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.planner = ProductionPlanner()

    def test_job_shop_spt_rule(self) -> None:
        """Test Shortest Processing Time dispatching rule."""
        po = ProductionOrder(
            id=uuid4(),
            order_number="PO001",
            product_id=uuid4(),
            quantity=Decimal("100"),
            scheduled_start=datetime.utcnow(),
            scheduled_end=datetime.utcnow() + timedelta(days=5),
        )

        schedule = self.planner.job_shop_schedule(production_order=po, operations=[], scheduling_rule="SPT")

        assert schedule.job_id is not None
        assert schedule.total_makespan >= 0

    def test_job_shop_edd_rule(self) -> None:
        """Test Earliest Due Date dispatching rule."""
        po = ProductionOrder(
            id=uuid4(),
            order_number="PO001",
            product_id=uuid4(),
            quantity=Decimal("100"),
            scheduled_end=datetime.utcnow() + timedelta(days=5),
        )

        schedule = self.planner.job_shop_schedule(production_order=po, operations=[], scheduling_rule="EDD")

        assert schedule is not None


class TestBottleneckAnalysis:
    """Test bottleneck analysis."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.planner = ProductionPlanner()

    def test_bottleneck_identification(self) -> None:
        """Test bottleneck identification."""
        from thomas.supply_chain.production import CapacityRequirement

        requirements = [
            CapacityRequirement(
                resource_id="RES1",
                resource_name="Resource 1",
                period=0,
                required_hours=Decimal("150"),
                available_hours=Decimal("160"),
                utilization_percent=Decimal("94"),
                load_leveling_needed=True,
            ),
            CapacityRequirement(
                resource_id="RES2",
                resource_name="Resource 2",
                period=0,
                required_hours=Decimal("80"),
                available_hours=Decimal("160"),
                utilization_percent=Decimal("50"),
                load_leveling_needed=False,
            ),
        ]

        bottlenecks = self.planner.detect_bottlenecks(
            capacity_requirements=requirements, threshold_percent=Decimal("85")
        )

        # RES1 should be identified as bottleneck
        assert any(b.resource_id == "RES1" and b.is_bottleneck for b in bottlenecks)
        assert not any(b.resource_id == "RES2" and b.is_bottleneck for b in bottlenecks)

    def test_bottleneck_mitigation_actions(self) -> None:
        """Test bottleneck mitigation action recommendations."""
        from thomas.supply_chain.production import CapacityRequirement

        requirements = [
            CapacityRequirement(
                resource_id="RES1",
                resource_name="Resource 1",
                period=0,
                required_hours=Decimal("300"),
                available_hours=Decimal("160"),
                utilization_percent=Decimal("188"),
                load_leveling_needed=True,
            )
        ]

        bottlenecks = self.planner.detect_bottlenecks(requirements)

        assert len(bottlenecks) > 0
        assert len(bottlenecks[0].recommended_actions) > 0


class TestLotSizing:
    """Test production lot sizing."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.planner = ProductionPlanner()
        self.sku = SKU(code="LOT001", product_id=uuid4())

    def test_wagner_whitin_lot_sizing(self) -> None:
        """Test Wagner-Whitin dynamic programming lot sizing."""
        demands = [Decimal("100"), Decimal("150"), Decimal("200"), Decimal("50")]

        result = self.planner.wagner_whitin_lot_sizing(
            sku=self.sku, demands=demands, setup_cost=Decimal("100"), holding_cost_per_unit=Decimal("1")
        )

        assert result.sku == self.sku
        assert len(result.lot_sizes) == len(demands)
        assert result.total_cost > 0

    def test_lot_sizing_zero_demand(self) -> None:
        """Test lot sizing with zero demand periods."""
        demands = [Decimal("100"), Decimal("0"), Decimal("200"), Decimal("0")]

        result = self.planner.wagner_whitin_lot_sizing(
            sku=self.sku, demands=demands, setup_cost=Decimal("50"), holding_cost_per_unit=Decimal("2")
        )

        assert result.total_cost >= 0

    def test_lot_sizing_cost_minimization(self) -> None:
        """Test that lot sizing minimizes total cost."""
        demands = [Decimal("100")] * 12

        result = self.planner.wagner_whitin_lot_sizing(
            sku=self.sku, demands=demands, setup_cost=Decimal("50"), holding_cost_per_unit=Decimal("1")
        )

        # Cost per unit should be reasonable
        assert result.cost_per_unit > 0
        assert result.cost_per_unit < Decimal("10")


class TestWIPTracking:
    """Test work-in-process tracking."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.planner = ProductionPlanner()

    def test_wip_status_tracking(self) -> None:
        """Test WIP status tracking."""
        po = ProductionOrder(
            id=uuid4(),
            order_number="PO001",
            product_id=uuid4(),
            quantity=Decimal("100"),
            actual_start=datetime.utcnow() - timedelta(days=2),
            scheduled_start=datetime.utcnow() - timedelta(days=3),
            scheduled_end=datetime.utcnow() + timedelta(days=3),
        )

        wip = self.planner.track_wip(
            production_order=po,
            current_location="ASSEMBLY",
            quantity_completed=Decimal("50"),
            quantity_scrapped=Decimal("5"),
        )

        assert wip.quantity_started == Decimal("100")
        assert wip.quantity_completed == Decimal("50")
        assert wip.quantity_scrapped == Decimal("5")
        assert wip.quantity_in_process == Decimal("45")

    def test_wip_progress_tracking(self) -> None:
        """Test WIP progress calculation."""
        po = ProductionOrder(
            id=uuid4(),
            order_number="PO001",
            product_id=uuid4(),
            quantity=Decimal("100"),
            actual_start=datetime.utcnow() - timedelta(days=5),
            scheduled_start=datetime.utcnow() - timedelta(days=5),
            scheduled_end=datetime.utcnow() + timedelta(days=5),
        )

        wip = self.planner.track_wip(production_order=po, current_location="PACKING", quantity_completed=Decimal("75"))

        assert wip.elapsed_time_days >= 5
        assert wip.cycle_time_days > 0


class TestMaterialAvailability:
    """Test material availability checking."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.planner = ProductionPlanner()

    def test_material_available(self) -> None:
        """Test material availability check when sufficient."""
        sku1 = SKU(code="MAT001", product_id=uuid4())
        sku2 = SKU(code="MAT002", product_id=uuid4())

        po = ProductionOrder(id=uuid4(), order_number="PO001", product_id=uuid4(), quantity=Decimal("100"))

        # Add materials to production order
        from thomas.supply_chain._types import MaterialRequirement

        po.required_materials = [
            MaterialRequirement(id=uuid4(), sku=sku1, quantity_required=Decimal("2"), warehouse_id=uuid4()),
            MaterialRequirement(id=uuid4(), sku=sku2, quantity_required=Decimal("1"), warehouse_id=uuid4()),
        ]

        on_hand = {sku1: Decimal("300"), sku2: Decimal("150")}

        available, shortages = self.planner.check_material_availability(
            production_order=po, on_hand_inventory=on_hand, on_order_inventory={}
        )

        assert available
        assert len(shortages) == 0

    def test_material_shortage(self) -> None:
        """Test material shortage detection."""
        sku1 = SKU(code="MAT001", product_id=uuid4())

        po = ProductionOrder(id=uuid4(), order_number="PO001", product_id=uuid4(), quantity=Decimal("100"))

        from thomas.supply_chain._types import MaterialRequirement

        po.required_materials = [
            MaterialRequirement(id=uuid4(), sku=sku1, quantity_required=Decimal("3"), warehouse_id=uuid4())
        ]

        on_hand = {sku1: Decimal("100")}  # Need 300, only have 100

        available, shortages = self.planner.check_material_availability(
            production_order=po, on_hand_inventory=on_hand, on_order_inventory={}
        )

        assert not available
        assert len(shortages) > 0
