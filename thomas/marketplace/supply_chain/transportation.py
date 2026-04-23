"""
Transportation and mode selection module for supply chain.

Provides transportation problem solving, transshipment optimization,
multi-modal routing, carrier selection, shipment tracking, freight
rate calculation, and container loading optimization.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from thomas.marketplace.supply_chain._exceptions import InvalidTransportationProblemException, TransportationException
from thomas.marketplace.supply_chain._types import Shipment, ShipmentStatus, TransportMode


@dataclass
class TransportationAllocation:
    """Solution to transportation problem."""

    source: str
    destination: str
    quantity: Decimal
    unit_cost: Decimal
    total_cost: Decimal


@dataclass
class TransportationProblemResult:
    """Complete transportation problem solution."""

    allocations: list[TransportationAllocation]
    total_cost: Decimal
    total_units_shipped: Decimal
    is_optimal: bool
    unmet_demand: dict[str, Decimal]


@dataclass
class CarrierOption:
    """Carrier service option."""

    carrier_id: str
    carrier_name: str
    transport_mode: TransportMode
    base_rate_per_unit: Decimal
    weight_rate_per_kg: Decimal
    volume_rate_per_m3: Decimal
    fuel_surcharge_percent: Decimal
    service_level: str  # "standard", "expedited", "economy"
    transit_time_days: int
    reliability_score: Decimal  # 0-100


@dataclass
class CarrierSelection:
    """Selected carrier option."""

    carrier: CarrierOption
    estimated_cost: Decimal
    estimated_arrival: datetime
    score: Decimal


@dataclass
class FreightRate:
    """Calculated freight rate for shipment."""

    origin: str
    destination: str
    transport_mode: TransportMode
    base_rate: Decimal
    fuel_surcharge: Decimal
    weight_surcharge: Decimal
    distance_surcharge: Decimal
    handling_fee: Decimal
    total_rate: Decimal
    rate_per_kg: Decimal


@dataclass
class Container:
    """Container specification."""

    container_type: str  # "20ft", "40ft", "pallet", etc.
    max_weight_kg: Decimal
    max_volume_m3: Decimal
    current_weight_kg: Decimal = Decimal("0")
    current_volume_m3: Decimal = Decimal("0")
    items: list["Item"] = None

    def __post_init__(self) -> None:
        if self.items is None:
            self.items = []

    @property
    def available_weight(self) -> Decimal:
        return self.max_weight_kg - self.current_weight_kg

    @property
    def available_volume(self) -> Decimal:
        return self.max_volume_m3 - self.current_volume_m3

    @property
    def utilization_weight_percent(self) -> Decimal:
        if self.max_weight_kg > 0:
            return self.current_weight_kg / self.max_weight_kg * Decimal("100")
        return Decimal("0")

    @property
    def utilization_volume_percent(self) -> Decimal:
        if self.max_volume_m3 > 0:
            return self.current_volume_m3 / self.max_volume_m3 * Decimal("100")
        return Decimal("0")


@dataclass
class Item:
    """Item to be loaded."""

    item_id: str
    weight_kg: Decimal
    volume_m3: Decimal
    length_cm: Decimal
    width_cm: Decimal
    height_cm: Decimal
    quantity: int = 1
    stackable: bool = True
    fragile: bool = False


@dataclass
class ShipmentState:
    """State machine for shipment tracking."""

    shipment_id: UUID
    current_status: ShipmentStatus
    status_history: list[tuple[datetime, ShipmentStatus]]
    current_location: str
    last_updated: datetime
    estimated_delivery: datetime | None = None


class TransportationOptimizer:
    """
    Comprehensive transportation optimization system.

    Handles transportation problems, carrier selection, multi-modal routing,
    freight rate calculation, and container loading optimization.
    """

    def __init__(self) -> None:
        """Initialize transportation optimizer."""
        pass

    def vogels_approximation_method(
        self,
        supply: dict[str, Decimal],  # sources -> quantities
        demand: dict[str, Decimal],  # destinations -> quantities
        unit_costs: dict[tuple[str, str], Decimal],  # (source, dest) -> cost
    ) -> TransportationProblemResult:
        """
        Vogel's Approximation Method for transportation problem.

        Args:
            supply: Dictionary of supply at each source
            demand: Dictionary of demand at each destination
            unit_costs: Unit costs from each source to destination

        Returns:
            TransportationProblemResult with allocations and total cost
        """
        if sum(supply.values()) != sum(demand.values()):
            raise InvalidTransportationProblemException("Total supply must equal total demand")

        # Create copies for manipulation
        sources = list(supply.keys())
        destinations = list(demand.keys())
        supply_remaining = supply.copy()
        demand_remaining = demand.copy()
        allocations = []
        total_cost = Decimal("0")

        # Vogel's algorithm iterations
        while any(d > 0 for d in demand_remaining.values()):
            # Calculate penalties
            penalties = {}

            # Row penalties
            for source in sources:
                if supply_remaining[source] <= 0:
                    continue
                costs = [
                    unit_costs.get((source, dest), Decimal("999999"))
                    for dest in destinations
                    if demand_remaining[dest] > 0
                ]
                if len(costs) >= 2:
                    costs.sort()
                    penalties[(source, "row")] = costs[1] - costs[0]
                elif costs:
                    penalties[(source, "row")] = costs[0]

            # Column penalties
            for dest in destinations:
                if demand_remaining[dest] <= 0:
                    continue
                costs = [
                    unit_costs.get((source, dest), Decimal("999999"))
                    for source in sources
                    if supply_remaining[source] > 0
                ]
                if len(costs) >= 2:
                    costs.sort()
                    penalties[(dest, "col")] = costs[1] - costs[0]
                elif costs:
                    penalties[(dest, "col")] = costs[0]

            # Find cell with maximum penalty
            max_penalty = Decimal("0")
            best_cell = None
            for (key, ptype), penalty in penalties.items():
                if penalty > max_penalty:
                    max_penalty = penalty
                    best_cell = (key, ptype)

            if best_cell is None:
                break

            key, ptype = best_cell
            if ptype == "row":
                source = key
                # Find minimum cost destination
                min_cost_dest = min(
                    (dest for dest in destinations if demand_remaining[dest] > 0),
                    key=lambda d: unit_costs.get((source, d), Decimal("999999")),
                )
                dest = min_cost_dest
            else:
                dest = key
                min_cost_source = min(
                    (source for source in sources if supply_remaining[source] > 0),
                    key=lambda s: unit_costs.get((s, dest), Decimal("999999")),
                )
                source = min_cost_source

            # Allocate
            qty = min(supply_remaining[source], demand_remaining[dest])
            cost = unit_costs.get((source, dest), Decimal("0"))

            allocations.append(
                TransportationAllocation(
                    source=source, destination=dest, quantity=qty, unit_cost=cost, total_cost=qty * cost
                )
            )

            total_cost += qty * cost
            supply_remaining[source] -= qty
            demand_remaining[dest] -= qty

        return TransportationProblemResult(
            allocations=allocations,
            total_cost=total_cost,
            total_units_shipped=Decimal(sum(a.quantity for a in allocations)),
            is_optimal=True,
            unmet_demand=demand_remaining,
        )

    def select_carrier(
        self,
        origin: str,
        destination: str,
        weight_kg: Decimal,
        volume_m3: Decimal,
        required_transit_days: int,
        available_carriers: list[CarrierOption],
    ) -> CarrierSelection:
        """
        Select best carrier for shipment.

        Args:
            origin: Origin location
            destination: Destination location
            weight_kg: Shipment weight
            volume_m3: Shipment volume
            required_transit_days: Required transit time
            available_carriers: Available carrier options

        Returns:
            Selected CarrierSelection
        """
        if not available_carriers:
            raise TransportationException("No carriers available")

        scored_carriers = []

        for carrier in available_carriers:
            # Check feasibility
            if carrier.transit_time_days > required_transit_days:
                continue

            # Calculate cost
            estimated_cost = (
                carrier.base_rate_per_unit
                + (weight_kg * carrier.weight_rate_per_kg)
                + (volume_m3 * carrier.volume_rate_per_m3)
            )

            # Apply fuel surcharge
            estimated_cost *= Decimal("1") + carrier.fuel_surcharge_percent / Decimal("100")

            # Score based on cost and reliability
            cost_score = Decimal("100") / (Decimal("1") + (estimated_cost / Decimal("100")))
            reliability_score = carrier.reliability_score
            time_bonus = Decimal("100") if carrier.transit_time_days <= required_transit_days else Decimal("0")

            overall_score = (
                cost_score * Decimal("0.4") + reliability_score * Decimal("0.4") + time_bonus * Decimal("0.2")
            )

            estimated_arrival = datetime.utcnow() + __import__("datetime").timedelta(days=carrier.transit_time_days)

            scored_carriers.append(
                (
                    overall_score,
                    CarrierSelection(
                        carrier=carrier,
                        estimated_cost=estimated_cost,
                        estimated_arrival=estimated_arrival,
                        score=overall_score,
                    ),
                )
            )

        if not scored_carriers:
            raise TransportationException("No suitable carriers found for transit time requirement")

        scored_carriers.sort(key=lambda x: x[0], reverse=True)
        return scored_carriers[0][1]

    def calculate_freight_rate(
        self,
        origin: str,
        destination: str,
        weight_kg: Decimal,
        volume_m3: Decimal,
        distance_km: Decimal,
        transport_mode: TransportMode = TransportMode.TRUCK,
        hazmat: bool = False,
    ) -> FreightRate:
        """
        Calculate freight rate for shipment.

        Args:
            origin: Origin city/port
            destination: Destination city/port
            weight_kg: Shipment weight
            volume_m3: Shipment volume
            distance_km: Distance
            transport_mode: Mode of transport
            hazmat: Hazardous material flag

        Returns:
            FreightRate with itemized charges
        """
        # Base rate per kg (varies by mode)
        if transport_mode == TransportMode.TRUCK:
            base_rate_per_kg = Decimal("0.5")
        elif transport_mode == TransportMode.AIR:
            base_rate_per_kg = Decimal("3.0")
        elif transport_mode == TransportMode.SHIP:
            base_rate_per_kg = Decimal("0.1")
        elif transport_mode == TransportMode.RAIL:
            base_rate_per_kg = Decimal("0.2")
        else:
            base_rate_per_kg = Decimal("0.5")

        # Calculate components
        base_rate = weight_kg * base_rate_per_kg
        fuel_surcharge = base_rate * Decimal("0.15")  # 15% fuel surcharge
        distance_surcharge = distance_km * Decimal("0.01")  # 0.01 per km
        weight_surcharge = Decimal("0")  # No additional surcharge for normal weight

        # Volume surcharge if volume/weight ratio is high
        if weight_kg > 0:
            vol_weight_ratio = volume_m3 / (weight_kg / Decimal("1000"))
            if vol_weight_ratio > Decimal("6"):
                weight_surcharge = volume_m3 * Decimal("10")

        handling_fee = Decimal("50")

        # Hazmat surcharge
        if hazmat:
            handling_fee += Decimal("100")

        total_rate = base_rate + fuel_surcharge + distance_surcharge + weight_surcharge + handling_fee

        # Rate per kg
        rate_per_kg = total_rate / weight_kg if weight_kg > 0 else Decimal("0")

        return FreightRate(
            origin=origin,
            destination=destination,
            transport_mode=transport_mode,
            base_rate=base_rate,
            fuel_surcharge=fuel_surcharge,
            weight_surcharge=weight_surcharge,
            distance_surcharge=distance_surcharge,
            handling_fee=handling_fee,
            total_rate=total_rate,
            rate_per_kg=rate_per_kg,
        )

    def pack_container(
        self, container: Container, items: list[Item], packing_algorithm: str = "first_fit"
    ) -> tuple[list[Item], list[Item]]:
        """
        Pack items into container using bin packing heuristic.

        Args:
            container: Container to pack into
            items: Items to pack
            packing_algorithm: "first_fit", "best_fit", or "worst_fit"

        Returns:
            Tuple of (packed_items, unpacked_items)
        """
        packed = []
        unpacked = []

        # Sort items by volume (largest first) for better utilization
        sorted_items = sorted(items, key=lambda x: x.volume_m3, reverse=True)

        for item in sorted_items:
            item_weight = item.weight_kg * Decimal(item.quantity)
            item_volume = item.volume_m3 * Decimal(item.quantity)

            if container.available_weight >= item_weight and container.available_volume >= item_volume:
                packed.append(item)
                container.current_weight_kg += item_weight
                container.current_volume_m3 += item_volume
                container.items.append(item)
            else:
                unpacked.append(item)

        return packed, unpacked

    def shipment_tracking_state_machine(self, shipment: Shipment) -> ShipmentState:
        """
        Get current state of shipment in state machine.

        Args:
            shipment: Shipment to track

        Returns:
            ShipmentState with history
        """
        # Build status history
        history = [(shipment.created_at, ShipmentStatus.CREATED)]

        if shipment.ship_date:
            history.append((shipment.ship_date, ShipmentStatus.SHIPPED))

        if shipment.status == ShipmentStatus.IN_TRANSIT:
            history.append((datetime.utcnow(), ShipmentStatus.IN_TRANSIT))
        elif shipment.status == ShipmentStatus.DELIVERED:
            history.append((shipment.actual_delivery or datetime.utcnow(), ShipmentStatus.DELIVERED))

        # Determine estimated delivery
        if shipment.expected_delivery is None and shipment.ship_date:
            estimated = shipment.ship_date + __import__("datetime").timedelta(days=7)
        else:
            estimated = shipment.expected_delivery

        return ShipmentState(
            shipment_id=shipment.id,
            current_status=shipment.status,
            status_history=history,
            current_location=shipment.destination_address,
            last_updated=datetime.utcnow(),
            estimated_delivery=estimated,
        )

    def multi_modal_optimization(
        self,
        origin: str,
        destination: str,
        weight_kg: Decimal,
        volume_m3: Decimal,
        required_days: int,
        distance_segments: list[tuple[str, str, Decimal]],  # (mode, route, distance)
    ) -> dict[str, any]:
        """
        Optimize multi-modal transportation routing.

        Args:
            origin: Origin
            destination: Destination
            weight_kg: Shipment weight
            volume_m3: Shipment volume
            required_days: Required delivery time
            distance_segments: Segments with (mode, route, distance)

        Returns:
            Multi-modal solution with costs and transit time
        """
        total_cost = Decimal("0")
        total_transit_days = 0
        route_plan = []

        for mode_str, route, distance in distance_segments:
            try:
                mode = TransportMode[mode_str.upper()]
            except KeyError:
                mode = TransportMode.TRUCK

            rate = self.calculate_freight_rate(origin, destination, weight_kg, volume_m3, distance, mode)

            total_cost += rate.total_rate
            total_transit_days += int(distance / 1000)  # Rough estimate

            route_plan.append(
                {
                    "mode": mode.value,
                    "route": route,
                    "distance_km": float(distance),
                    "cost": float(rate.total_rate),
                    "transit_time_days": int(distance / 1000),
                }
            )

        feasible = total_transit_days <= required_days

        return {
            "origin": origin,
            "destination": destination,
            "total_cost": float(total_cost),
            "total_transit_days": total_transit_days,
            "required_transit_days": required_days,
            "feasible": feasible,
            "route_plan": route_plan,
            "cost_efficiency": float(total_cost / weight_kg) if weight_kg > 0 else 0,
        }
