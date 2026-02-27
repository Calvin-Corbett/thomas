"""
Tests for supply chain logistics optimization module.

Tests vehicle routing, time-windowed deliveries, multi-depot routing,
last-mile optimization, freight consolidation, and cross-docking.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from thomas.supply_chain import Location, LogisticsOptimizer, Route, Vehicle


class TestClarkWrightSavingsAlgorithm:
    """Test Clarke-Wright savings algorithm."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.optimizer = LogisticsOptimizer()
        self.depot = Location(
            id=uuid4(), address="Distribution Center", latitude=Decimal("40.7128"), longitude=Decimal("-74.0060")
        )

    def test_clarke_wright_basic(self) -> None:
        """Test basic Clarke-Wright routing."""
        locations = [
            Location(
                id=uuid4(),
                address=f"Customer {i}",
                latitude=Decimal(str(40.7 + i * 0.01)),
                longitude=Decimal(str(-74.0 + i * 0.01)),
                demand=Decimal("10"),
            )
            for i in range(3)
        ]

        vehicles = [Vehicle(id="V1", capacity=Decimal("100")), Vehicle(id="V2", capacity=Decimal("100"))]

        result = self.optimizer.clarke_wright_savings(self.depot, locations, vehicles)

        assert len(result.routes) > 0
        assert result.total_distance > 0
        assert result.total_cost > 0

    def test_clarke_wright_feasibility(self) -> None:
        """Test Clarke-Wright with capacity constraints."""
        locations = [
            Location(
                id=uuid4(),
                address=f"Customer {i}",
                latitude=Decimal(str(40.7 + i * 0.01)),
                longitude=Decimal(str(-74.0 + i * 0.01)),
                demand=Decimal("50"),
            )
            for i in range(5)
        ]

        vehicles = [Vehicle(id="V1", capacity=Decimal("100"))]

        result = self.optimizer.clarke_wright_savings(self.depot, locations, vehicles)

        # Some locations should remain unserved due to capacity
        assert result.unserved_locations or len(result.routes) > 1

    def test_haversine_distance(self) -> None:
        """Test Haversine distance calculation."""
        lat1, lon1 = Decimal("40.7128"), Decimal("-74.0060")
        lat2, lon2 = Decimal("34.0522"), Decimal("-118.2437")

        distance = self.optimizer.haversine_distance(lat1, lon1, lat2, lon2)

        # NYC to LA should be around 3944 km
        assert Decimal("3900") < distance < Decimal("4000")


class TestTimeWindowedRouting:
    """Test time-windowed delivery routing."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.optimizer = LogisticsOptimizer()
        self.depot = Location(
            id=uuid4(), address="Distribution Center", latitude=Decimal("40.7128"), longitude=Decimal("-74.0060")
        )

    def test_time_window_routing(self) -> None:
        """Test routing with time windows."""
        locations = [
            Location(
                id=uuid4(),
                address=f"Customer {i}",
                latitude=Decimal(str(40.7 + i * 0.01)),
                longitude=Decimal(str(-74.0 + i * 0.01)),
                demand=Decimal("10"),
                time_window_start=8 + i,
                time_window_end=17 + i,
                service_time=30,
            )
            for i in range(3)
        ]

        vehicles = [Vehicle(id="V1", capacity=Decimal("100"))]

        result = self.optimizer.time_windowed_routing(self.depot, locations, vehicles)

        assert len(result.routes) > 0

    def test_missing_time_windows(self) -> None:
        """Test error when time windows not specified."""
        locations = [
            Location(
                id=uuid4(),
                address="Customer",
                latitude=Decimal("40.7"),
                longitude=Decimal("-74.0"),
                demand=Decimal("10"),
            )
        ]

        vehicles = [Vehicle(id="V1", capacity=Decimal("100"))]

        with pytest.raises(Exception):
            self.optimizer.time_windowed_routing(self.depot, locations, vehicles)


class TestLastMileOptimization:
    """Test last-mile delivery optimization."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.optimizer = LogisticsOptimizer()

    def test_last_mile_basic(self) -> None:
        """Test last-mile optimization."""
        customers = [
            Location(
                id=uuid4(),
                address=f"Customer {i}",
                latitude=Decimal(str(40.7 + i * 0.001)),
                longitude=Decimal(str(-74.0 + i * 0.001)),
                demand=Decimal(str(1 + i)),
            )
            for i in range(10)
        ]

        routes = self.optimizer.last_mile_optimization(customers=customers, vehicle_capacity=Decimal("20"))

        assert len(routes) > 0
        assert all(len(r.stops) > 0 for r in routes)

    def test_last_mile_capacity_constraints(self) -> None:
        """Test last-mile respects vehicle capacity."""
        customers = [
            Location(
                id=uuid4(),
                address=f"Customer {i}",
                latitude=Decimal(str(40.7 + i * 0.001)),
                longitude=Decimal(str(-74.0 + i * 0.001)),
                demand=Decimal("5"),
            )
            for i in range(10)
        ]

        routes = self.optimizer.last_mile_optimization(customers=customers, vehicle_capacity=Decimal("20"))

        # Check no route exceeds capacity
        for route in routes:
            total_demand = Decimal(sum(int(stop.items_count) for stop in route.stops))
            assert total_demand <= Decimal("20")


class TestFreightConsolidation:
    """Test freight consolidation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.optimizer = LogisticsOptimizer()

    def test_freight_consolidation_same_destination(self) -> None:
        """Test consolidation for same destination."""
        shipments = [
            {
                "shipment_id": uuid4(),
                "weight": Decimal("100"),
                "volume": Decimal("10"),
                "origin": "Origin1",
                "destination": "Destination1",
            }
            for _ in range(5)
        ]

        plans = self.optimizer.freight_consolidation(shipments)

        assert len(plans) > 0
        assert all(p.savings >= 0 for p in plans)

    def test_consolidation_cost_benefit(self) -> None:
        """Test that consolidation provides savings."""
        shipments = [
            {
                "shipment_id": uuid4(),
                "weight": Decimal("50"),
                "volume": Decimal("5"),
                "origin": "Origin1",
                "destination": "Destination1",
            }
            for _ in range(4)
        ]

        plans = self.optimizer.freight_consolidation(shipments, consolidation_cost_per_shipment=Decimal("10"))

        # Should show positive savings
        assert any(p.savings > 0 for p in plans)


class TestCrossDockingSchedule:
    """Test cross-docking operations scheduling."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.optimizer = LogisticsOptimizer()

    def test_cross_docking_schedule(self) -> None:
        """Test cross-docking schedule creation."""
        inbound = [{"shipment_id": uuid4(), "weight": Decimal("100"), "volume": Decimal("10")} for _ in range(5)]

        outbound = {f"Destination{i}": Decimal(str(100 + i * 50)) for i in range(3)}

        schedule = self.optimizer.cross_docking_schedule(
            inbound_shipments=inbound, outbound_demand=outbound, docking_bay_count=3
        )

        assert "bays" in schedule
        assert "inbound_assignments" in schedule
        assert "outbound_assignments" in schedule
        assert len(schedule["bays"]) == 3

    def test_dock_utilization(self) -> None:
        """Test dock bay utilization."""
        inbound = [{"shipment_id": uuid4(), "weight": Decimal("100"), "volume": Decimal("10")} for _ in range(10)]

        outbound = {"Destination": Decimal("500")}

        schedule = self.optimizer.cross_docking_schedule(
            inbound_shipments=inbound, outbound_demand=outbound, docking_bay_count=3
        )

        # Should utilize available bays
        assigned_count = len(schedule["inbound_assignments"])
        assert assigned_count > 0


class TestRouteCosting:
    """Test route cost calculation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.optimizer = LogisticsOptimizer()

    def test_route_costing(self) -> None:
        """Test route cost breakdown."""
        route = Route(
            id=uuid4(),
            route_code="ROUTE001",
            origin_warehouse_id=uuid4(),
            total_distance=Decimal("100"),
            total_duration_minutes=180,
        )

        costs = self.optimizer.route_costing(
            route=route, fuel_price_per_liter=Decimal("1.5"), toll_cost=Decimal("10"), labor_rate_per_hour=Decimal("25")
        )

        assert costs.total_cost > 0
        assert costs.fuel_surcharge > 0
        assert costs.labor_cost > 0

    def test_cost_components(self) -> None:
        """Test cost component breakdown."""
        route = Route(
            id=uuid4(),
            route_code="ROUTE001",
            origin_warehouse_id=uuid4(),
            total_distance=Decimal("500"),
            total_duration_minutes=600,
        )

        costs = self.optimizer.route_costing(route)

        # All components should be non-negative
        assert costs.freight_cost >= 0
        assert costs.fuel_surcharge >= 0
        assert costs.labor_cost >= 0
        assert costs.other_costs >= 0


class TestMultiDepotRouting:
    """Test multi-depot vehicle routing."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.optimizer = LogisticsOptimizer()

    def test_multi_depot_routing(self) -> None:
        """Test routing optimization across depots."""
        depots = [
            Location(
                id=uuid4(),
                address=f"Depot {i}",
                latitude=Decimal(str(40.7 + i * 0.1)),
                longitude=Decimal(str(-74.0 + i * 0.1)),
            )
            for i in range(2)
        ]

        locations = [
            Location(
                id=uuid4(),
                address=f"Customer {i}",
                latitude=Decimal(str(40.7 + i * 0.01)),
                longitude=Decimal(str(-74.0 + i * 0.01)),
                demand=Decimal("10"),
            )
            for i in range(5)
        ]

        vehicles = [Vehicle(id="V1", capacity=Decimal("100")) for _ in range(2)]

        result = self.optimizer.multi_depot_routing(depots, locations, vehicles)

        assert len(result.routes) > 0
