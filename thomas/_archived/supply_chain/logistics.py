"""
Logistics optimization module for supply chain.

Provides vehicle routing optimization, time-windowed delivery management,
multi-depot routing, last-mile delivery, freight consolidation, and
cross-docking scheduling.
"""

import math
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from thomas.supply_chain._exceptions import (
    LogisticsException,
    TimeWindowViolationException,
)
from thomas.supply_chain._types import CostBreakdown, Route, RouteStop


@dataclass
class Location:
    """Location with coordinates."""

    id: UUID
    address: str
    latitude: Decimal
    longitude: Decimal
    demand: Decimal = Decimal("0")
    time_window_start: int | None = None
    time_window_end: int | None = None
    service_time: int = 0


@dataclass
class Vehicle:
    """Vehicle for delivery."""

    id: str
    capacity: Decimal
    current_load: Decimal = Decimal("0")
    fixed_cost: Decimal = Decimal("0")
    variable_cost_per_km: Decimal = Decimal("0")
    fuel_consumption_rate: Decimal = Decimal("0.1")  # liters per km
    max_range_km: Decimal = Decimal("1000")


@dataclass
class RoutingResult:
    """Vehicle routing problem solution."""

    routes: list[Route]
    total_distance: Decimal
    total_cost: Decimal
    total_vehicles_used: int
    unserved_locations: list[UUID]
    solution_quality: Decimal  # 0-100


@dataclass
class ConsolidationPlan:
    """Freight consolidation plan."""

    consolidation_id: str
    shipments: list[UUID]
    total_weight: Decimal
    total_volume: Decimal
    consolidation_cost: Decimal
    savings: Decimal


class LogisticsOptimizer:
    """
    Comprehensive logistics optimization system.

    Handles vehicle routing, time-windowed deliveries, multi-depot routing,
    last-mile optimization, freight consolidation, and cross-docking.
    """

    EARTH_RADIUS_KM = Decimal("6371")

    def __init__(self) -> None:
        """Initialize logistics optimizer."""
        pass

    def haversine_distance(self, lat1: Decimal, lon1: Decimal, lat2: Decimal, lon2: Decimal) -> Decimal:
        """
        Calculate great circle distance between two points (km).

        Args:
            lat1, lon1: Starting point latitude/longitude
            lat2, lon2: Ending point latitude/longitude

        Returns:
            Distance in kilometers
        """
        # Convert to radians
        lat1_rad = lat1 * Decimal("0.0174533")
        lon1_rad = lon1 * Decimal("0.0174533")
        lat2_rad = lat2 * Decimal("0.0174533")
        lon2_rad = lon2 * Decimal("0.0174533")

        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad

        # Haversine formula
        a = (dlat / Decimal("2")).sin() ** 2 + (lat1_rad).cos() * (lat2_rad).cos() * ((dlon / Decimal("2")).sin() ** 2)

        # Simplified calculation using decimal approximation
        a_float = float(a)
        if a_float > 1.0:
            a_float = 1.0

        c = Decimal("2") * Decimal(str(math.asin(math.sqrt(a_float))))
        return self.EARTH_RADIUS_KM * c

    def clarke_wright_savings(
        self, depot: Location, locations: list[Location], vehicles: list[Vehicle], max_iterations: int = 1000
    ) -> RoutingResult:
        """
        Clarke-Wright savings algorithm for vehicle routing.

        Args:
            depot: Depot/warehouse location
            locations: Customer locations to serve
            vehicles: Available vehicles
            max_iterations: Maximum algorithm iterations

        Returns:
            RoutingResult with optimized routes
        """
        if not locations:
            return RoutingResult([], Decimal("0"), Decimal("0"), 0, [], Decimal("100"))

        # Calculate savings for all pairs
        savings_list = []
        for i in range(len(locations)):
            for j in range(i + 1, len(locations)):
                dist_i_depot = self.haversine_distance(
                    locations[i].latitude, locations[i].longitude, depot.latitude, depot.longitude
                )
                dist_j_depot = self.haversine_distance(
                    locations[j].latitude, locations[j].longitude, depot.latitude, depot.longitude
                )
                dist_i_j = self.haversine_distance(
                    locations[i].latitude, locations[i].longitude, locations[j].latitude, locations[j].longitude
                )

                savings = dist_i_depot + dist_j_depot - dist_i_j
                savings_list.append((savings, i, j))

        # Sort by savings (descending)
        savings_list.sort(reverse=True, key=lambda x: x[0])

        # Build routes
        routes_data = []
        assigned_locs = set()

        for savings, i, j in savings_list:
            if i in assigned_locs or j in assigned_locs:
                continue

            route_locs = [locations[i], locations[j]]
            total_demand = locations[i].demand + locations[j].demand

            # Find vehicle with sufficient capacity
            vehicle = None
            for v in vehicles:
                if v.current_load + total_demand <= v.capacity:
                    vehicle = v
                    break

            if vehicle:
                routes_data.append((vehicle, route_locs))
                assigned_locs.add(i)
                assigned_locs.add(j)

        # Add remaining locations as individual routes
        for idx, loc in enumerate(locations):
            if idx not in assigned_locs:
                vehicle = None
                for v in vehicles:
                    if v.current_load + loc.demand <= v.capacity:
                        vehicle = v
                        break

                if vehicle:
                    routes_data.append((vehicle, [loc]))
                    assigned_locs.add(idx)

        # Convert to Route objects
        routes = []
        total_distance = Decimal("0")
        total_cost = Decimal("0")

        for vehicle, route_locs in routes_data:
            route_stops = []
            current_lat = depot.latitude
            current_lon = depot.longitude
            route_distance = Decimal("0")

            for seq, loc in enumerate(route_locs):
                distance = self.haversine_distance(current_lat, current_lon, loc.latitude, loc.longitude)
                route_distance += distance

                stop = RouteStop(
                    id=UUID(int=0),
                    sequence=seq + 1,
                    location_address=loc.address,
                    latitude=loc.latitude,
                    longitude=loc.longitude,
                    shipment_id=loc.id,
                    service_time_minutes=loc.service_time,
                    items_count=int(loc.demand),
                )
                route_stops.append(stop)

                current_lat = loc.latitude
                current_lon = loc.longitude

            # Return to depot
            route_distance += self.haversine_distance(current_lat, current_lon, depot.latitude, depot.longitude)

            # Calculate cost
            vehicle_cost = (
                vehicle.fixed_cost
                + (route_distance * vehicle.variable_cost_per_km)
                + (route_distance * vehicle.fuel_consumption_rate * Decimal("1.5"))  # Fuel cost estimate
            )

            route = Route(
                id=UUID(int=0),
                route_code=f"ROUTE_{vehicle.id}",
                origin_warehouse_id=depot.id,
                stops=route_stops,
                total_distance=route_distance,
                total_duration_minutes=int(route_distance / Decimal("20") * Decimal("60")),  # Approx 20 km/h
                vehicle_id=vehicle.id,
                total_cost=vehicle_cost,
            )

            routes.append(route)
            total_distance += route_distance
            total_cost += vehicle_cost

        unserved = [locations[i].id for i in range(len(locations)) if i not in assigned_locs]

        return RoutingResult(
            routes=routes,
            total_distance=total_distance,
            total_cost=total_cost,
            total_vehicles_used=len(routes),
            unserved_locations=unserved,
            solution_quality=Decimal("100") * (Decimal(len(assigned_locs)) / Decimal(len(locations)))
            if locations
            else Decimal("0"),
        )

    def time_windowed_routing(
        self, depot: Location, locations: list[Location], vehicles: list[Vehicle]
    ) -> RoutingResult:
        """
        Vehicle routing with time window constraints.

        Args:
            depot: Depot location
            locations: Customer locations with time windows
            vehicles: Available vehicles

        Returns:
            RoutingResult respecting time windows
        """
        if not all(loc.time_window_start and loc.time_window_end for loc in locations):
            raise LogisticsException("All locations must have time windows specified")

        # Use Clarke-Wright as base, then validate time windows
        result = self.clarke_wright_savings(depot, locations, vehicles)

        # Validate and adjust for time windows
        for route in result.routes:
            current_time = 0
            valid = True

            for stop in route.stops:
                # Estimate arrival time
                if stop.planned_arrival is None:
                    current_time += stop.service_time_minutes

                    if stop.time_window_start is not None:
                        if current_time > stop.time_window_end:
                            valid = False
                            break

            if not valid:
                raise TimeWindowViolationException(f"Route {route.route_code} violates time window constraints")

        return result

    def multi_depot_routing(
        self, depots: list[Location], locations: list[Location], vehicles: list[Vehicle]
    ) -> RoutingResult:
        """
        Vehicle routing optimization with multiple depots.

        Args:
            depots: List of depot locations
            locations: Customer locations
            vehicles: Available vehicles (assigned to depots)

        Returns:
            RoutingResult with multi-depot optimization
        """
        best_result = None
        best_cost = float("inf")

        # Try optimization from each depot
        for depot in depots:
            depot_vehicles = vehicles[: len(vehicles) // len(depots)]
            result = self.clarke_wright_savings(depot, locations, depot_vehicles)

            if result.total_cost < best_cost:
                best_cost = float(result.total_cost)
                best_result = result

        return best_result or RoutingResult([], Decimal("0"), Decimal("0"), 0, [], Decimal("0"))

    def last_mile_optimization(
        self, customers: list[Location], vehicle_capacity: Decimal, vehicle_speed_kmh: Decimal = Decimal("30")
    ) -> list[Route]:
        """
        Optimize last-mile delivery.

        Args:
            customers: Customer locations for last-mile delivery
            vehicle_capacity: Vehicle capacity in units
            vehicle_speed_kmh: Average delivery speed

        Returns:
            List of optimized last-mile routes
        """
        if not customers:
            return []

        # Group customers by proximity (simple geographic clustering)
        routes = []
        unserved = set(range(len(customers)))

        while unserved:
            # Start new route with first unserved customer
            start_idx = next(iter(unserved))
            route_locs = [customers[start_idx]]
            current_load = customers[start_idx].demand
            unserved.remove(start_idx)

            # Greedy nearest neighbor
            current_lat = customers[start_idx].latitude
            current_lon = customers[start_idx].longitude

            while unserved and current_load < vehicle_capacity:
                nearest_idx = None
                nearest_dist = float("inf")

                for idx in unserved:
                    dist = float(
                        self.haversine_distance(
                            current_lat, current_lon, customers[idx].latitude, customers[idx].longitude
                        )
                    )

                    if dist < nearest_dist and current_load + customers[idx].demand <= vehicle_capacity:
                        nearest_dist = dist
                        nearest_idx = idx

                if nearest_idx is None:
                    break

                route_locs.append(customers[nearest_idx])
                current_load += customers[nearest_idx].demand
                current_lat = customers[nearest_idx].latitude
                current_lon = customers[nearest_idx].longitude
                unserved.remove(nearest_idx)

            # Create route
            route_stops = []
            for seq, loc in enumerate(route_locs):
                stop = RouteStop(
                    id=UUID(int=0),
                    sequence=seq + 1,
                    location_address=loc.address,
                    latitude=loc.latitude,
                    longitude=loc.longitude,
                    service_time_minutes=15,
                )
                route_stops.append(stop)

            route = Route(
                id=UUID(int=0),
                route_code=f"LAST_MILE_{len(routes)}",
                origin_warehouse_id=UUID(int=0),
                stops=route_stops,
                total_cost=Decimal("50"),
            )

            routes.append(route)

        return routes

    def freight_consolidation(
        self,
        shipments: list[dict],  # {shipment_id, weight, volume, origin, destination}
        consolidation_cost_per_shipment: Decimal = Decimal("25"),
    ) -> list[ConsolidationPlan]:
        """
        Consolidate shipments to optimize freight costs.

        Args:
            shipments: List of shipment information
            consolidation_cost_per_shipment: Cost to consolidate each shipment

        Returns:
            List of consolidation plans
        """
        if not shipments:
            return []

        # Group by destination
        by_destination = {}
        for shipment in shipments:
            dest = shipment.get("destination", "unknown")
            if dest not in by_destination:
                by_destination[dest] = []
            by_destination[dest].append(shipment)

        plans = []
        consolidation_count = 1

        for destination, dest_shipments in by_destination.items():
            # Create consolidation groups (max 4 shipments per consolidation)
            for i in range(0, len(dest_shipments), 4):
                group = dest_shipments[i : i + 4]
                total_weight = Decimal(sum(s.get("weight", 0) for s in group))
                total_volume = Decimal(sum(s.get("volume", 0) for s in group))

                # Calculate savings
                individual_cost = Decimal(len(group)) * Decimal("100")
                consolidated_cost = Decimal("200") + (Decimal(len(group)) * consolidation_cost_per_shipment)
                savings = individual_cost - consolidated_cost

                plan = ConsolidationPlan(
                    consolidation_id=f"CONS_{consolidation_count}",
                    shipments=[s.get("shipment_id") for s in group],
                    total_weight=total_weight,
                    total_volume=total_volume,
                    consolidation_cost=consolidated_cost,
                    savings=max(Decimal("0"), savings),
                )

                plans.append(plan)
                consolidation_count += 1

        return plans

    def cross_docking_schedule(
        self,
        inbound_shipments: list[dict],
        outbound_demand: dict[str, Decimal],
        docking_bay_count: int = 5,
        processing_time_minutes: int = 30,
    ) -> dict:
        """
        Schedule cross-docking operations.

        Args:
            inbound_shipments: List of inbound shipments
            outbound_demand: Dictionary of outbound demand by destination
            docking_bay_count: Number of available docking bays
            processing_time_minutes: Time to process each shipment

        Returns:
            Cross-docking schedule with bay assignments
        """
        schedule = {"bays": {}, "inbound_assignments": [], "outbound_assignments": []}

        # Initialize bays
        for i in range(docking_bay_count):
            schedule["bays"][f"BAY_{i+1}"] = {"shipments": [], "total_time": 0}

        # Assign inbound shipments to bays
        for idx, shipment in enumerate(inbound_shipments):
            # Find bay with least occupancy
            min_bay = min(schedule["bays"].items(), key=lambda x: x[1]["total_time"])
            min_bay[1]["shipments"].append(shipment.get("shipment_id"))
            min_bay[1]["total_time"] += processing_time_minutes

            schedule["inbound_assignments"].append(
                {"shipment_id": shipment.get("shipment_id"), "bay": min_bay[0], "arrival_window": f"Hour {idx}"}
            )

        # Schedule outbound based on demand
        for destination, demand_qty in outbound_demand.items():
            # Allocate consolidated load
            schedule["outbound_assignments"].append(
                {
                    "destination": destination,
                    "demand": demand_qty,
                    "departure_window": "Window 2",
                    "consolidation_required": demand_qty > Decimal("500"),
                }
            )

        return schedule

    def route_costing(
        self,
        route: Route,
        fuel_price_per_liter: Decimal = Decimal("1.5"),
        toll_cost: Decimal = Decimal("0"),
        labor_rate_per_hour: Decimal = Decimal("25"),
    ) -> CostBreakdown:
        """
        Calculate detailed route costs.

        Args:
            route: Route to cost
            fuel_price_per_liter: Fuel price per liter
            toll_cost: Toll costs for route
            labor_rate_per_hour: Driver labor rate

        Returns:
            CostBreakdown with itemized costs
        """
        # Estimate fuel consumption (0.1 L/km)
        fuel_consumption = route.total_distance * Decimal("0.1")
        fuel_cost = fuel_consumption * fuel_price_per_liter

        # Labor cost
        hours = Decimal(route.total_duration_minutes) / Decimal("60")
        labor_cost = hours * labor_rate_per_hour

        # Vehicle depreciation/maintenance (0.5 per km)
        vehicle_cost = route.total_distance * Decimal("0.5")

        return CostBreakdown(
            freight_cost=Decimal("0"),
            fuel_surcharge=fuel_cost,
            handling_cost=Decimal("0"),
            labor_cost=labor_cost,
            taxes=Decimal("0"),
            storage_cost=Decimal("0"),
            packaging_cost=Decimal("0"),
            other_costs=vehicle_cost + toll_cost,
        )
