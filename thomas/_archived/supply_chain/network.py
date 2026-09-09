"""
Supply chain network design and optimization module.

Provides facility location optimization, network flow analysis, make-vs-buy
analysis, nearshoring/offshoring cost models, multi-period planning, and
disruption risk analysis.
"""

import math
import random
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from thomas.supply_chain._exceptions import FacilityLocationException
from thomas.supply_chain._types import SKU


@dataclass
class Facility:
    """Facility for location problem."""

    id: str
    name: str
    location: tuple[Decimal, Decimal]  # latitude, longitude
    fixed_cost_annual: Decimal
    capacity: Decimal
    variable_cost_per_unit: Decimal
    lead_time_days: int
    throughput_capacity: Decimal  # Units per year


@dataclass
class FacilityLocationResult:
    """Facility location optimization result."""

    selected_facilities: list[Facility]
    unselected_facilities: list[Facility]
    total_fixed_cost: Decimal
    total_variable_cost: Decimal
    total_transportation_cost: Decimal
    total_cost: Decimal
    coverage_percent: Decimal
    service_level: Decimal


@dataclass
class NetworkFlow:
    """Network flow edge."""

    source: str
    destination: str
    capacity: Decimal
    flow: Decimal = Decimal("0")
    cost: Decimal = Decimal("0")
    available_capacity: Decimal = field(default_factory=Decimal)

    def __post_init__(self) -> None:
        if not self.available_capacity:
            self.available_capacity = self.capacity


@dataclass
class MinCostFlow:
    """Min-cost flow solution."""

    flows: list[NetworkFlow]
    total_cost: Decimal
    total_flow: Decimal
    is_feasible: bool
    iterations: int


@dataclass
class MakeVsBuyAnalysis:
    """Make vs Buy cost analysis."""

    product_id: UUID
    make_cost_per_unit: Decimal
    buy_cost_per_unit: Decimal
    annual_volume: Decimal
    make_total_cost: Decimal
    buy_total_cost: Decimal
    recommendation: str  # "MAKE", "BUY", or "HYBRID"
    savings: Decimal
    breakeven_volume: Decimal
    strategic_considerations: list[str]


@dataclass
class LocationCost:
    """Cost breakdown for a location."""

    location: str
    labor_cost: Decimal
    material_cost: Decimal
    logistics_cost: Decimal
    regulatory_cost: Decimal
    tariff_cost: Decimal
    total_cost: Decimal
    total_cost_index: Decimal  # Relative to baseline


@dataclass
class NearshoreOffshoreAnalysis:
    """Nearshoring vs Offshoring analysis."""

    domestic_location: LocationCost
    nearshore_location: LocationCost
    offshore_location: LocationCost
    recommendation: str
    cost_savings_percent: Decimal
    risk_increase: Decimal
    lead_time_change_days: int


@dataclass
class MultiPeriodPlan:
    """Multi-period network plan."""

    periods: int
    facilities_by_period: dict[int, list[Facility]]
    capacity_utilization: list[Decimal]
    total_cost_by_period: list[Decimal]
    cumulative_cost: Decimal


@dataclass
class RiskScenario:
    """Risk scenario for Monte Carlo simulation."""

    scenario_id: int
    disruption_locations: list[str]
    probability: Decimal
    impact_days: int
    recovery_cost: Decimal
    total_impact_cost: Decimal


@dataclass
class DisruptionAnalysis:
    """Supply chain disruption risk analysis."""

    base_case_cost: Decimal
    average_risk_cost: Decimal
    worst_case_cost: Decimal
    resilience_score: Decimal  # 0-100
    critical_nodes: list[str]
    recommended_resilience_actions: list[str]
    monte_carlo_results: list[RiskScenario]


class NetworkDesigner:
    """
    Comprehensive supply chain network design system.

    Handles facility location optimization, network flow analysis,
    make-vs-buy decisions, nearshoring/offshoring analysis, and
    disruption risk assessment.
    """

    def __init__(self) -> None:
        """Initialize network designer."""
        pass

    def p_median_location(
        self,
        candidate_facilities: list[Facility],
        demand_locations: list[tuple[str, Decimal, Decimal]],  # (name, demand, location)
        p: int,  # Number of facilities to select
        service_distance_km: Decimal = Decimal("500"),
    ) -> FacilityLocationResult:
        """
        P-median facility location problem.

        Args:
            candidate_facilities: Potential facility locations
            demand_locations: Customer locations and demand
            p: Number of facilities to select
            service_distance_km: Maximum service distance

        Returns:
            FacilityLocationResult with optimal facility selection
        """
        if p > len(candidate_facilities):
            raise FacilityLocationException(f"Cannot select {p} facilities from {len(candidate_facilities)}")

        if p == 0:
            raise FacilityLocationException("Must select at least one facility")

        # Simple greedy selection based on demand coverage
        selected = []
        unselected = candidate_facilities.copy()
        total_cost = Decimal("0")
        covered_demand = Decimal("0")
        total_demand = Decimal(sum(d[1] for d in demand_locations))

        for _ in range(p):
            best_facility = None
            best_coverage = Decimal("0")
            best_cost = Decimal("999999999")

            for facility in unselected:
                # Calculate coverage for this facility
                coverage = Decimal("0")
                facility_cost = facility.fixed_cost_annual

                for demand_name, demand, demand_loc in demand_locations:
                    # Simple distance approximation
                    dist = self._approximate_distance(facility.location, demand_loc)
                    if dist <= service_distance_km:
                        coverage += demand
                        facility_cost += demand * facility.variable_cost_per_unit

                coverage_score = coverage / facility_cost if facility_cost > 0 else Decimal("0")

                if coverage_score > best_coverage or (coverage_score == best_coverage and facility_cost < best_cost):
                    best_facility = facility
                    best_coverage = coverage_score
                    best_cost = facility_cost

            if best_facility:
                selected.append(best_facility)
                unselected.remove(best_facility)
                total_cost += best_facility.fixed_cost_annual
                covered_demand += best_coverage

        coverage_percent = covered_demand / total_demand * Decimal("100") if total_demand > 0 else Decimal("0")

        return FacilityLocationResult(
            selected_facilities=selected,
            unselected_facilities=unselected,
            total_fixed_cost=Decimal(sum(f.fixed_cost_annual for f in selected)),
            total_variable_cost=Decimal("0"),
            total_transportation_cost=Decimal("0"),
            total_cost=total_cost,
            coverage_percent=coverage_percent,
            service_level=coverage_percent,
        )

    def _approximate_distance(self, loc1: tuple[Decimal, Decimal], loc2: tuple[Decimal, Decimal]) -> Decimal:
        """Approximate distance between two locations."""
        # Simple Euclidean distance
        lat_diff = loc1[0] - loc2[0]
        lon_diff = loc1[1] - loc2[1]

        distance = Decimal(str(math.sqrt(float(lat_diff**2 + lon_diff**2)))) * Decimal(
            "111"
        )  # Approximate km per degree

        return distance

    def min_cost_flow(
        self,
        network: list[tuple[str, str, Decimal, Decimal]],  # (source, dest, capacity, cost)
        supply: dict[str, Decimal],  # node -> supply (positive) or demand (negative)
        max_iterations: int = 100,
    ) -> MinCostFlow:
        """
        Successive shortest paths algorithm for min-cost flow.

        Args:
            network: Network edges with capacity and cost
            supply: Supply/demand at nodes
            max_iterations: Maximum algorithm iterations

        Returns:
            MinCostFlow solution
        """
        flows = []
        total_cost = Decimal("0")
        total_flow = Decimal("0")

        # Create flow edges
        for source, dest, capacity, cost in network:
            flows.append(
                NetworkFlow(source=source, destination=dest, capacity=capacity, cost=cost, available_capacity=capacity)
            )

        iteration = 0
        remaining_supply = supply.copy()

        while iteration < max_iterations:
            # Find node with positive supply
            source = None
            for node, s in remaining_supply.items():
                if s > 0:
                    source = node
                    break

            if not source:
                break

            # Find shortest path to demand node
            # (Simplified: direct path)
            sink = None
            for node, s in remaining_supply.items():
                if s < 0:
                    sink = node
                    break

            if not sink:
                break

            # Find direct edge
            path_flow = Decimal("0")
            for flow in flows:
                if flow.source == source and flow.destination == sink and flow.available_capacity > 0:
                    path_flow = min(remaining_supply[source], -remaining_supply[sink], flow.available_capacity)
                    flow.flow += path_flow
                    flow.available_capacity -= path_flow
                    total_cost += path_flow * flow.cost
                    total_flow += path_flow

                    remaining_supply[source] -= path_flow
                    remaining_supply[sink] += path_flow
                    break

            iteration += 1

        is_feasible = all(abs(s) < 1 for s in remaining_supply.values())

        return MinCostFlow(
            flows=flows, total_cost=total_cost, total_flow=total_flow, is_feasible=is_feasible, iterations=iteration
        )

    def make_vs_buy_analysis(
        self,
        product_id: UUID,
        annual_volume: Decimal,
        make_cost_per_unit: Decimal,
        make_fixed_cost: Decimal,
        buy_cost_per_unit: Decimal,
        capacity_constraint: Decimal | None = None,
        quality_score_make: Decimal = Decimal("85"),
        quality_score_buy: Decimal = Decimal("90"),
    ) -> MakeVsBuyAnalysis:
        """
        Analyze make vs buy decision.

        Args:
            product_id: Product ID
            annual_volume: Annual demand volume
            make_cost_per_unit: Variable cost to make
            make_fixed_cost: Fixed cost to make
            buy_cost_per_unit: Cost to buy
            capacity_constraint: Maximum make capacity
            quality_score_make: Make quality score (0-100)
            quality_score_buy: Buy quality score (0-100)

        Returns:
            MakeVsBuyAnalysis with recommendation
        """
        make_total = (annual_volume * make_cost_per_unit) + make_fixed_cost
        buy_total = annual_volume * buy_cost_per_unit

        savings = buy_total - make_total
        savings_pct = (savings / buy_total * Decimal("100")) if buy_total > 0 else Decimal("0")

        # Calculate breakeven volume
        if make_cost_per_unit < buy_cost_per_unit:
            breakeven = make_fixed_cost / (buy_cost_per_unit - make_cost_per_unit)
        else:
            breakeven = Decimal("999999999")

        # Recommendation logic
        considerations = []
        if capacity_constraint and annual_volume > capacity_constraint:
            considerations.append("Making exceeds capacity constraints")
            recommendation = "BUY"
        elif quality_score_buy > quality_score_make + Decimal("10"):
            considerations.append("Supplier quality significantly better")
            recommendation = "BUY"
        elif savings > 0 and savings_pct > Decimal("10"):
            considerations.append(f"Buying saves {savings_pct}%")
            recommendation = "BUY"
        elif make_total < buy_total:
            considerations.append("Making is more cost-effective")
            recommendation = "MAKE"
        else:
            considerations.append("Consider hybrid approach")
            recommendation = "HYBRID"

        considerations.append(f"Breakeven volume: {breakeven:.0f} units")

        return MakeVsBuyAnalysis(
            product_id=product_id,
            make_cost_per_unit=make_cost_per_unit,
            buy_cost_per_unit=buy_cost_per_unit,
            annual_volume=annual_volume,
            make_total_cost=make_total,
            buy_total_cost=buy_total,
            recommendation=recommendation,
            savings=abs(savings),
            breakeven_volume=breakeven,
            strategic_considerations=considerations,
        )

    def nearshore_vs_offshore_analysis(
        self,
        product_sku: SKU,
        annual_volume: Decimal,
        domestic_cost_per_unit: Decimal,
        nearshore_cost_per_unit: Decimal,
        offshore_cost_per_unit: Decimal,
        domestic_lead_days: int = 7,
        nearshore_lead_days: int = 14,
        offshore_lead_days: int = 35,
    ) -> NearshoreOffshoreAnalysis:
        """
        Analyze nearshoring vs offshoring decision.

        Args:
            product_sku: Product SKU
            annual_volume: Annual volume
            domestic_cost_per_unit: Domestic production cost
            nearshore_cost_per_unit: Nearshore production cost
            offshore_cost_per_unit: Offshore production cost
            domestic_lead_days: Domestic lead time
            nearshore_lead_days: Nearshore lead time
            offshore_lead_days: Offshore lead time

        Returns:
            NearshoreOffshoreAnalysis with recommendation
        """
        # Assume labor cost is 30%, material 50%, other 20%
        domestic_loc = LocationCost(
            location="Domestic",
            labor_cost=domestic_cost_per_unit * Decimal("0.3"),
            material_cost=domestic_cost_per_unit * Decimal("0.5"),
            logistics_cost=domestic_cost_per_unit * Decimal("0.15"),
            regulatory_cost=domestic_cost_per_unit * Decimal("0.05"),
            tariff_cost=Decimal("0"),
            total_cost=domestic_cost_per_unit * annual_volume,
            total_cost_index=Decimal("100"),
        )

        nearshore_loc = LocationCost(
            location="Nearshore",
            labor_cost=nearshore_cost_per_unit * Decimal("0.35"),
            material_cost=nearshore_cost_per_unit * Decimal("0.45"),
            logistics_cost=nearshore_cost_per_unit * Decimal("0.12"),
            regulatory_cost=nearshore_cost_per_unit * Decimal("0.05"),
            tariff_cost=nearshore_cost_per_unit * Decimal("0.03"),
            total_cost=nearshore_cost_per_unit * annual_volume,
            total_cost_index=(nearshore_cost_per_unit / domestic_cost_per_unit * Decimal("100"))
            if domestic_cost_per_unit > 0
            else Decimal("0"),
        )

        offshore_loc = LocationCost(
            location="Offshore",
            labor_cost=offshore_cost_per_unit * Decimal("0.40"),
            material_cost=offshore_cost_per_unit * Decimal("0.40"),
            logistics_cost=offshore_cost_per_unit * Decimal("0.10"),
            regulatory_cost=offshore_cost_per_unit * Decimal("0.03"),
            tariff_cost=offshore_cost_per_unit * Decimal("0.07"),
            total_cost=offshore_cost_per_unit * annual_volume,
            total_cost_index=(offshore_cost_per_unit / domestic_cost_per_unit * Decimal("100"))
            if domestic_cost_per_unit > 0
            else Decimal("0"),
        )

        # Risk factors (lead time, quality, supply chain disruption)
        lead_time_diff_nearshore = nearshore_lead_days - domestic_lead_days
        lead_time_diff_offshore = offshore_lead_days - domestic_lead_days
        risk_nearshore = Decimal("15")  # Percent increase in risk
        risk_offshore = Decimal("35")

        # Recommendation
        if offshore_loc.total_cost < nearshore_loc.total_cost and offshore_loc.total_cost < domestic_loc.total_cost:
            savings = domestic_loc.total_cost - offshore_loc.total_cost
            savings_pct = savings / domestic_loc.total_cost * Decimal("100")
            recommendation = "OFFSHORE"
            risk_increase = risk_offshore
            lead_time_change = lead_time_diff_offshore
        elif nearshore_loc.total_cost < domestic_loc.total_cost:
            savings = domestic_loc.total_cost - nearshore_loc.total_cost
            savings_pct = savings / domestic_loc.total_cost * Decimal("100")
            recommendation = "NEARSHORE"
            risk_increase = risk_nearshore
            lead_time_change = lead_time_diff_nearshore
        else:
            savings_pct = Decimal("0")
            recommendation = "DOMESTIC"
            risk_increase = Decimal("0")
            lead_time_change = 0

        return NearshoreOffshoreAnalysis(
            domestic_location=domestic_loc,
            nearshore_location=nearshore_loc,
            offshore_location=offshore_loc,
            recommendation=recommendation,
            cost_savings_percent=savings_pct,
            risk_increase=risk_increase,
            lead_time_change_days=lead_time_change,
        )

    def multi_period_network_planning(
        self, facilities: list[Facility], demand_forecast: list[Decimal], planning_periods: int = 12
    ) -> MultiPeriodPlan:
        """
        Plan network capacity over multiple periods.

        Args:
            facilities: Available facilities
            demand_forecast: Demand by period
            planning_periods: Number of planning periods

        Returns:
            MultiPeriodPlan with period-by-period allocation
        """
        if len(demand_forecast) < planning_periods:
            demand_forecast.extend([Decimal("0")] * (planning_periods - len(demand_forecast)))

        facilities_by_period = {}
        capacity_utilization = []
        total_costs = []
        cumulative_cost = Decimal("0")

        for period in range(planning_periods):
            demand = demand_forecast[period]

            # Select facilities needed for this period's demand
            selected = []
            total_capacity = Decimal("0")

            for facility in facilities:
                if total_capacity < demand:
                    selected.append(facility)
                    total_capacity += facility.capacity

            facilities_by_period[period] = selected

            # Calculate utilization
            utilization = demand / total_capacity * Decimal("100") if total_capacity > 0 else Decimal("0")
            capacity_utilization.append(utilization)

            # Calculate cost
            period_cost = Decimal(sum(f.fixed_cost_annual / planning_periods for f in selected))
            period_cost += demand * Decimal(
                sum(f.variable_cost_per_unit for f in selected) / len(selected) if selected else Decimal("0")
            )

            total_costs.append(period_cost)
            cumulative_cost += period_cost

        return MultiPeriodPlan(
            periods=planning_periods,
            facilities_by_period=facilities_by_period,
            capacity_utilization=capacity_utilization,
            total_cost_by_period=total_costs,
            cumulative_cost=cumulative_cost,
        )

    def disruption_risk_analysis(
        self,
        facilities: list[Facility],
        base_case_cost: Decimal,
        disruption_probability: dict[str, Decimal],  # facility -> probability
        simulation_runs: int = 1000,
    ) -> DisruptionAnalysis:
        """
        Monte Carlo simulation for supply chain disruption risk.

        Args:
            facilities: Network facilities
            base_case_cost: Base case operating cost
            disruption_probability: Disruption probability by facility
            simulation_runs: Number of Monte Carlo simulations

        Returns:
            DisruptionAnalysis with risk metrics
        """
        risk_costs = []
        scenarios = []

        for scenario_id in range(simulation_runs):
            disrupted_facilities = []
            impact_cost = Decimal("0")
            max_impact_days = 0

            for facility in facilities:
                prob = disruption_probability.get(facility.id, Decimal("0"))

                if Decimal(str(random.random())) < prob:
                    disrupted_facilities.append(facility.id)

                    # Impact cost: fixed cost for recovery + lost throughput
                    recovery_cost = facility.fixed_cost_annual * Decimal("0.2")  # 20% of annual cost
                    lost_throughput_cost = (
                        facility.throughput_capacity * facility.variable_cost_per_unit * Decimal("0.1")
                    )  # 10% lost
                    impact_cost += recovery_cost + lost_throughput_cost

                    max_impact_days = max(max_impact_days, 30)  # Assume 30 days recovery

            total_scenario_cost = base_case_cost + impact_cost
            risk_costs.append(total_scenario_cost)

            scenarios.append(
                RiskScenario(
                    scenario_id=scenario_id,
                    disruption_locations=disrupted_facilities,
                    probability=Decimal(str(len(disrupted_facilities) / len(facilities))),
                    impact_days=max_impact_days,
                    recovery_cost=impact_cost,
                    total_impact_cost=impact_cost,
                )
            )

        risk_costs.sort()
        avg_risk_cost = Decimal(sum(risk_costs)) / Decimal(len(risk_costs))
        worst_case = risk_costs[-1]

        # Identify critical nodes (those that appear in many failure scenarios)
        critical_count = {}
        for scenario in scenarios:
            for facility in scenario.disruption_locations:
                critical_count[facility] = critical_count.get(facility, 0) + 1

        critical_nodes = [f for f, count in sorted(critical_count.items(), key=lambda x: x[1], reverse=True)[:3]]

        # Calculate resilience score (0-100)
        # Higher is more resilient
        avg_vulnerability = Decimal(sum(disruption_probability.values())) / Decimal(len(disruption_probability))
        resilience_score = max(Decimal("0"), Decimal("100") - (avg_vulnerability * Decimal("100")))

        recommendations = [f"Diversify away from critical node: {node}" for node in critical_nodes]
        recommendations.append("Increase safety stock for critical components")
        recommendations.append("Develop disaster recovery plans for key facilities")

        return DisruptionAnalysis(
            base_case_cost=base_case_cost,
            average_risk_cost=avg_risk_cost,
            worst_case_cost=worst_case,
            resilience_score=resilience_score,
            critical_nodes=critical_nodes,
            recommended_resilience_actions=recommendations,
            monte_carlo_results=scenarios,
        )
