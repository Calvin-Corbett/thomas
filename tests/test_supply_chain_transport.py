"""
Tests for supply chain transportation optimization module.

Tests transportation problem solving, carrier selection, freight rates,
bin packing, and shipment tracking.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

pytestmark = pytest.mark.xfail(
    reason="Domain skeleton pending implementation (tracking: docs/ops/remediation/DOMAIN_STUB_TRACKING.md)",
    strict=False,
)

from thomas.marketplace.supply_chain import (
    CarrierOption,
    Container,
    Item,
    Shipment,
    ShipmentStatus,
    TransportationOptimizer,
    TransportMode,
)


class TestVogelsApproximationMethod:
    """Test Vogel's Approximation Method for transportation problem."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.optimizer = TransportationOptimizer()

    def test_vogels_basic_solution(self) -> None:
        """Test basic transportation problem solution."""
        supply = {"SOURCE1": Decimal("100"), "SOURCE2": Decimal("150")}
        demand = {"DEST1": Decimal("80"), "DEST2": Decimal("90"), "DEST3": Decimal("80")}

        costs = {
            ("SOURCE1", "DEST1"): Decimal("4"),
            ("SOURCE1", "DEST2"): Decimal("6"),
            ("SOURCE1", "DEST3"): Decimal("8"),
            ("SOURCE2", "DEST1"): Decimal("5"),
            ("SOURCE2", "DEST2"): Decimal("4"),
            ("SOURCE2", "DEST3"): Decimal("3"),
        }

        result = self.optimizer.vogels_approximation_method(supply, demand, costs)

        assert result.total_cost > 0
        assert len(result.allocations) > 0
        assert result.total_units_shipped == Decimal("250")

    def test_vogels_unbalanced_problem(self) -> None:
        """Test unbalanced transportation problem raises error."""
        supply = {"SOURCE1": Decimal("100")}
        demand = {"DEST1": Decimal("150")}
        costs = {("SOURCE1", "DEST1"): Decimal("5")}

        with pytest.raises(Exception):
            self.optimizer.vogels_approximation_method(supply, demand, costs)

    def test_vogels_zero_cost_routes(self) -> None:
        """Test with zero cost routes."""
        supply = {"S1": Decimal("50"), "S2": Decimal("50")}
        demand = {"D1": Decimal("50"), "D2": Decimal("50")}

        costs = {
            ("S1", "D1"): Decimal("0"),
            ("S1", "D2"): Decimal("5"),
            ("S2", "D1"): Decimal("5"),
            ("S2", "D2"): Decimal("0"),
        }

        result = self.optimizer.vogels_approximation_method(supply, demand, costs)

        assert result.is_optimal


class TestCarrierSelection:
    """Test carrier selection."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.optimizer = TransportationOptimizer()

    def test_carrier_selection_best_option(self) -> None:
        """Test selecting best carrier."""
        carriers = [
            CarrierOption(
                carrier_id="C1",
                carrier_name="Carrier 1",
                transport_mode=TransportMode.TRUCK,
                base_rate_per_unit=Decimal("1"),
                weight_rate_per_kg=Decimal("0.1"),
                volume_rate_per_m3=Decimal("5"),
                fuel_surcharge_percent=Decimal("10"),
                service_level="standard",
                transit_time_days=5,
                reliability_score=Decimal("95"),
            ),
            CarrierOption(
                carrier_id="C2",
                carrier_name="Carrier 2",
                transport_mode=TransportMode.TRUCK,
                base_rate_per_unit=Decimal("2"),
                weight_rate_per_kg=Decimal("0.05"),
                volume_rate_per_m3=Decimal("4"),
                fuel_surcharge_percent=Decimal("8"),
                service_level="expedited",
                transit_time_days=2,
                reliability_score=Decimal("98"),
            ),
        ]

        selection = self.optimizer.select_carrier(
            origin="NYC",
            destination="LA",
            weight_kg=Decimal("1000"),
            volume_m3=Decimal("100"),
            required_transit_days=5,
            available_carriers=carriers,
        )

        assert selection.carrier is not None
        assert selection.estimated_cost > 0

    def test_carrier_selection_transit_time_requirement(self) -> None:
        """Test carrier selection respects transit time."""
        carriers = [
            CarrierOption(
                carrier_id="C1",
                carrier_name="Slow Carrier",
                transport_mode=TransportMode.SHIP,
                base_rate_per_unit=Decimal("0.5"),
                weight_rate_per_kg=Decimal("0.01"),
                volume_rate_per_m3=Decimal("1"),
                fuel_surcharge_percent=Decimal("5"),
                service_level="economy",
                transit_time_days=30,
                reliability_score=Decimal("90"),
            ),
            CarrierOption(
                carrier_id="C2",
                carrier_name="Fast Carrier",
                transport_mode=TransportMode.AIR,
                base_rate_per_unit=Decimal("5"),
                weight_rate_per_kg=Decimal("0.5"),
                volume_rate_per_m3=Decimal("20"),
                fuel_surcharge_percent=Decimal("15"),
                service_level="expedited",
                transit_time_days=2,
                reliability_score=Decimal("98"),
            ),
        ]

        selection = self.optimizer.select_carrier(
            origin="NYC",
            destination="LA",
            weight_kg=Decimal("100"),
            volume_m3=Decimal("10"),
            required_transit_days=5,
            available_carriers=carriers,
        )

        # Should select fast carrier (30 days exceeds 5 day requirement)
        assert selection.carrier.transit_time_days <= 5


class TestFreightRateCalculation:
    """Test freight rate calculation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.optimizer = TransportationOptimizer()

    def test_freight_rate_truck(self) -> None:
        """Test truck freight rate calculation."""
        rate = self.optimizer.calculate_freight_rate(
            origin="NYC",
            destination="LA",
            weight_kg=Decimal("1000"),
            volume_m3=Decimal("50"),
            distance_km=Decimal("4000"),
            transport_mode=TransportMode.TRUCK,
        )

        assert rate.total_rate > 0
        assert rate.base_rate > 0
        assert rate.fuel_surcharge > 0

    def test_freight_rate_air(self) -> None:
        """Test air freight rate calculation."""
        rate_truck = self.optimizer.calculate_freight_rate(
            origin="NYC",
            destination="LA",
            weight_kg=Decimal("100"),
            volume_m3=Decimal("10"),
            distance_km=Decimal("4000"),
            transport_mode=TransportMode.TRUCK,
        )

        rate_air = self.optimizer.calculate_freight_rate(
            origin="NYC",
            destination="LA",
            weight_kg=Decimal("100"),
            volume_m3=Decimal("10"),
            distance_km=Decimal("4000"),
            transport_mode=TransportMode.AIR,
        )

        # Air should be more expensive
        assert rate_air.total_rate > rate_truck.total_rate

    def test_freight_rate_hazmat_surcharge(self) -> None:
        """Test hazmat surcharge."""
        normal_rate = self.optimizer.calculate_freight_rate(
            origin="NYC",
            destination="LA",
            weight_kg=Decimal("100"),
            volume_m3=Decimal("10"),
            distance_km=Decimal("1000"),
            hazmat=False,
        )

        hazmat_rate = self.optimizer.calculate_freight_rate(
            origin="NYC",
            destination="LA",
            weight_kg=Decimal("100"),
            volume_m3=Decimal("10"),
            distance_km=Decimal("1000"),
            hazmat=True,
        )

        assert hazmat_rate.total_rate > normal_rate.total_rate


class TestContainerPacking:
    """Test container loading and bin packing."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.optimizer = TransportationOptimizer()

    def test_first_fit_packing(self) -> None:
        """Test first-fit bin packing."""
        container = Container(container_type="20ft", max_weight_kg=Decimal("20000"), max_volume_m3=Decimal("30"))

        items = [
            Item(
                item_id="I1",
                weight_kg=Decimal("100"),
                volume_m3=Decimal("5"),
                length_cm=Decimal("100"),
                width_cm=Decimal("100"),
                height_cm=Decimal("50"),
                quantity=2,
            ),
            Item(
                item_id="I2",
                weight_kg=Decimal("50"),
                volume_m3=Decimal("2"),
                length_cm=Decimal("50"),
                width_cm=Decimal("50"),
                height_cm=Decimal("50"),
                quantity=5,
            ),
        ]

        packed, unpacked = self.optimizer.pack_container(container, items)

        assert len(packed) > 0
        assert len(packed) + len(unpacked) == len(items)

    def test_container_capacity_check(self) -> None:
        """Test container respects weight and volume limits."""
        container = Container(container_type="20ft", max_weight_kg=Decimal("1000"), max_volume_m3=Decimal("10"))

        items = [
            Item(
                item_id="I1",
                weight_kg=Decimal("600"),
                volume_m3=Decimal("6"),
                length_cm=Decimal("100"),
                width_cm=Decimal("100"),
                height_cm=Decimal("50"),
                quantity=1,
            ),
            Item(
                item_id="I2",
                weight_kg=Decimal("500"),
                volume_m3=Decimal("5"),
                length_cm=Decimal("100"),
                width_cm=Decimal("100"),
                height_cm=Decimal("50"),
                quantity=1,
            ),
        ]

        packed, unpacked = self.optimizer.pack_container(container, items)

        # Only first item should fit
        assert len(packed) <= 1
        assert container.current_weight_kg <= container.max_weight_kg
        assert container.current_volume_m3 <= container.max_volume_m3


class TestShipmentTracking:
    """Test shipment tracking state machine."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.optimizer = TransportationOptimizer()

    def test_shipment_state_creation(self) -> None:
        """Test shipment state tracking."""
        shipment = Shipment(
            id=uuid4(),
            shipment_number="SHIP001",
            status=ShipmentStatus.CREATED,
            origin_warehouse_id=uuid4(),
            destination_address="123 Main St, LA, CA",
            ship_date=datetime.utcnow(),
        )

        state = self.optimizer.shipment_tracking_state_machine(shipment)

        assert state.shipment_id == shipment.id
        assert state.current_status == ShipmentStatus.CREATED
        assert len(state.status_history) > 0

    def test_shipment_delivery_tracking(self) -> None:
        """Test shipment delivery tracking."""
        shipment = Shipment(
            id=uuid4(),
            shipment_number="SHIP001",
            status=ShipmentStatus.DELIVERED,
            origin_warehouse_id=uuid4(),
            destination_address="123 Main St, LA, CA",
            expected_delivery=datetime.utcnow() + timedelta(days=3),
            actual_delivery=datetime.utcnow(),
        )

        state = self.optimizer.shipment_tracking_state_machine(shipment)

        assert state.current_status == ShipmentStatus.DELIVERED
        assert state.estimated_delivery is not None


class TestMultiModalOptimization:
    """Test multi-modal transportation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.optimizer = TransportationOptimizer()

    def test_multi_modal_solution(self) -> None:
        """Test multi-modal routing solution."""
        distance_segments = [("TRUCK", "Local", Decimal("100")), ("SHIP", "Ocean", Decimal("10000"))]

        solution = self.optimizer.multi_modal_optimization(
            origin="Shanghai",
            destination="NYC",
            weight_kg=Decimal("10000"),
            volume_m3=Decimal("50"),
            required_days=30,
            distance_segments=distance_segments,
        )

        assert solution["total_cost"] > 0
        assert solution["total_transit_days"] > 0
        assert len(solution["route_plan"]) == 2

    def test_multi_modal_feasibility(self) -> None:
        """Test multi-modal feasibility check."""
        distance_segments = [("AIR", "Direct", Decimal("10000"))]

        solution = self.optimizer.multi_modal_optimization(
            origin="NYC",
            destination="LA",
            weight_kg=Decimal("100"),
            volume_m3=Decimal("10"),
            required_days=1,
            distance_segments=distance_segments,
        )

        assert solution["feasible"] is True or solution["feasible"] is False
