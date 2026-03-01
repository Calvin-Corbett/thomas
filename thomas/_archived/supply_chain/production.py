"""
Production planning and scheduling module for supply chain.

Provides MRP (Material Requirements Planning), capacity requirements planning,
job shop scheduling, bottleneck detection, WIP tracking, and lot sizing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from typing import Any

from thomas.supply_chain._types import (
    SKU,
    BillOfMaterials,
    ProductionOrder,
)

Operation = Any


@dataclass
class MRPExplosion:
    """MRP explosion result."""

    product_id: UUID
    gross_requirement: Decimal
    scheduled_receipt: Decimal
    available_inventory: Decimal
    net_requirement: Decimal
    planned_order_release: Decimal
    lead_time_offset_periods: int


@dataclass
class CapacityRequirement:
    """Capacity requirement for a resource."""

    resource_id: str
    resource_name: str
    period: int
    required_hours: Decimal
    available_hours: Decimal
    utilization_percent: Decimal
    load_leveling_needed: bool


@dataclass
class JobSchedule:
    """Job shop schedule for a production order."""

    job_id: str
    product_id: UUID
    operation_sequence: list["OperationSchedule"]
    total_makespan: int  # Total duration in minutes
    critical_path: list[str]
    schedule_completion_date: datetime


@dataclass
class OperationSchedule:
    """Schedule for a single operation."""

    operation_id: str
    operation_name: str
    resource_id: str
    scheduled_start: datetime
    scheduled_end: datetime
    duration_minutes: int
    sequence: int


@dataclass
class BottleneckAnalysis:
    """Analysis of production bottlenecks."""

    resource_id: str
    resource_name: str
    utilization_percent: Decimal
    is_bottleneck: bool
    backlog_hours: Decimal
    recommended_actions: list[str]


@dataclass
class LotSizingResult:
    """Lot sizing calculation result."""

    sku: SKU
    total_periods: int
    demands: list[Decimal]
    lot_sizes: list[Decimal]
    setup_costs: list[Decimal]
    holding_costs: list[Decimal]
    total_cost: Decimal
    cost_per_unit: Decimal


@dataclass
class WIPStatus:
    """Work-in-process status."""

    production_order_id: UUID
    product_id: UUID
    quantity_started: Decimal
    quantity_completed: Decimal
    quantity_in_process: Decimal
    quantity_scrapped: Decimal
    elapsed_time_days: int
    cycle_time_days: int
    locations: list[str]  # Current locations in process


class ProductionPlanner:
    """
    Comprehensive production planning and scheduling system.

    Handles MRP explosion, capacity planning, job shop scheduling,
    bottleneck detection, and lot sizing optimization.
    """

    def __init__(self) -> None:
        """Initialize production planner."""
        pass

    def mrp_explosion(
        self,
        product_id: UUID,
        gross_demand: list[Decimal],
        bom: BillOfMaterials,
        on_hand_inventory: dict[SKU, Decimal],
        lead_times: dict[SKU, int],
        safety_stock: dict[SKU, Decimal],
    ) -> dict[SKU, list[MRPExplosion]]:
        """
        Perform MRP explosion to calculate material requirements.

        Args:
            product_id: Parent product ID
            gross_demand: Demand for each planning period
            bom: Bill of Materials for product
            on_hand_inventory: Current inventory by SKU
            lead_times: Lead times by SKU
            safety_stock: Safety stock by SKU

        Returns:
            Dictionary of MRP explosions by component SKU
        """
        explosions = {}

        for component in bom.components:
            sku = component.component_sku
            mrp_records = []

            available = on_hand_inventory.get(sku, Decimal("0"))
            lead_time = lead_times.get(sku, 1)

            for period, demand in enumerate(gross_demand):
                # Adjust for waste factor
                gross_requirement = demand * component.effective_quantity

                # Calculate net requirement
                net_requirement = max(Decimal("0"), gross_requirement + safety_stock.get(sku, Decimal("0")) - available)

                # Plan order release (offset by lead time)
                release_period = max(0, period - lead_time)

                # Update available inventory
                if net_requirement > 0:
                    available = Decimal("0")
                else:
                    available -= gross_requirement

                explosions_for_period = MRPExplosion(
                    product_id=sku.product_id if hasattr(sku, "product_id") else UUID(int=0),
                    gross_requirement=gross_requirement,
                    scheduled_receipt=net_requirement if release_period == period else Decimal("0"),
                    available_inventory=max(Decimal("0"), available),
                    net_requirement=net_requirement,
                    planned_order_release=net_requirement,
                    lead_time_offset_periods=lead_time,
                )
                mrp_records.append(explosions_for_period)

            explosions[sku] = mrp_records

        return explosions

    def capacity_requirements_planning(
        self,
        production_orders: list[ProductionOrder],
        operations: dict[UUID, list["Operation"]],
        resource_capacity: dict[str, Decimal],
        periods: int = 12,
    ) -> list[CapacityRequirement]:
        """
        Calculate capacity requirements across resources.

        Args:
            production_orders: Planned production orders
            operations: Operations required per product
            resource_capacity: Available capacity by resource (hours/period)
            periods: Planning periods

        Returns:
            List of capacity requirements by resource and period
        """
        capacity_needs = {}

        for po in production_orders:
            ops = operations.get(po.product_id, [])
            for op in ops:
                resource_id = op.resource_id if hasattr(op, "resource_id") else "UNKNOWN"
                period = 0  # Simplification - actual would calculate period

                key = (resource_id, period)
                if key not in capacity_needs:
                    capacity_needs[key] = Decimal("0")

                # Duration in hours (assuming minutes in op)
                duration_hours = Decimal(getattr(op, "duration_minutes", 60)) / Decimal("60")
                capacity_needs[key] += duration_hours * po.quantity

        # Convert to requirements list
        requirements = []
        for (resource_id, period), hours_needed in capacity_needs.items():
            available_hours = resource_capacity.get(resource_id, Decimal("160"))
            utilization = hours_needed / available_hours * Decimal("100") if available_hours > 0 else Decimal("0")

            requirement = CapacityRequirement(
                resource_id=resource_id,
                resource_name=resource_id,
                period=period,
                required_hours=hours_needed,
                available_hours=available_hours,
                utilization_percent=utilization,
                load_leveling_needed=utilization > Decimal("85"),
            )
            requirements.append(requirement)

        return requirements

    def job_shop_schedule(
        self,
        production_order: ProductionOrder,
        operations: list["Operation"],
        scheduling_rule: str = "SPT",  # SPT, EDD, CR
    ) -> JobSchedule:
        """
        Generate job shop schedule for production order.

        Args:
            production_order: Production order to schedule
            operations: List of operations required
            scheduling_rule: Dispatching rule (SPT, EDD, CR)

        Returns:
            JobSchedule with operation sequence and makespan
        """
        if scheduling_rule == "SPT":
            # Shortest Processing Time
            sorted_ops = sorted(operations, key=lambda x: getattr(x, "duration_minutes", 60))
        elif scheduling_rule == "EDD":
            # Earliest Due Date
            sorted_ops = sorted(operations, key=lambda x: getattr(x, "due_date", datetime.utcnow()))
        elif scheduling_rule == "CR":
            # Critical Ratio
            sorted_ops = sorted(operations, key=lambda x: self._calculate_critical_ratio(x))
        else:
            sorted_ops = operations

        operation_schedules = []
        current_time = datetime.utcnow()
        critical_path = []
        total_duration = 0

        for seq, op in enumerate(sorted_ops):
            duration = getattr(op, "duration_minutes", 60)
            start_time = current_time
            end_time = current_time + timedelta(minutes=duration)

            op_schedule = OperationSchedule(
                operation_id=getattr(op, "id", f"OP_{seq}"),
                operation_name=getattr(op, "name", f"Operation {seq}"),
                resource_id=getattr(op, "resource_id", "RES_UNKNOWN"),
                scheduled_start=start_time,
                scheduled_end=end_time,
                duration_minutes=duration,
                sequence=seq + 1,
            )
            operation_schedules.append(op_schedule)
            current_time = end_time
            total_duration += duration
            critical_path.append(op_schedule.operation_id)

        return JobSchedule(
            job_id=str(production_order.id),
            product_id=production_order.product_id,
            operation_sequence=operation_schedules,
            total_makespan=total_duration,
            critical_path=critical_path,
            schedule_completion_date=current_time,
        )

    def _calculate_critical_ratio(self, operation: "Operation") -> Decimal:
        """Calculate critical ratio for an operation."""
        due_date = getattr(operation, "due_date", datetime.utcnow())
        remaining_time = (due_date - datetime.utcnow()).total_seconds() / 3600
        processing_time = getattr(operation, "duration_minutes", 60) / 60

        if processing_time > 0:
            return Decimal(str(remaining_time / processing_time))
        return Decimal("0")

    def detect_bottlenecks(
        self, capacity_requirements: list[CapacityRequirement], threshold_percent: Decimal = Decimal("85")
    ) -> list[BottleneckAnalysis]:
        """
        Identify production bottlenecks.

        Args:
            capacity_requirements: Capacity requirements by resource
            threshold_percent: Utilization threshold for bottleneck

        Returns:
            List of bottleneck analyses
        """
        analyses = []
        by_resource = {}

        # Group by resource
        for req in capacity_requirements:
            if req.resource_id not in by_resource:
                by_resource[req.resource_id] = []
            by_resource[req.resource_id].append(req)

        # Analyze each resource
        for resource_id, reqs in by_resource.items():
            avg_utilization = Decimal(sum(r.utilization_percent for r in reqs)) / Decimal(len(reqs))
            is_bottleneck = avg_utilization >= threshold_percent

            backlog_hours = Decimal(sum(max(Decimal("0"), r.required_hours - r.available_hours) for r in reqs))

            recommendations = self._generate_bottleneck_actions(resource_id, avg_utilization)

            analysis = BottleneckAnalysis(
                resource_id=resource_id,
                resource_name=resource_id,
                utilization_percent=avg_utilization,
                is_bottleneck=is_bottleneck,
                backlog_hours=backlog_hours,
                recommended_actions=recommendations,
            )
            analyses.append(analysis)

        return analyses

    def _generate_bottleneck_actions(self, resource_id: str, utilization: Decimal) -> list[str]:
        """Generate recommendations for bottleneck resources."""
        actions = []

        if utilization > Decimal("95"):
            actions.append(f"Consider adding second shift for {resource_id}")
            actions.append(f"Evaluate subcontracting for {resource_id} operations")
        elif utilization > Decimal("85"):
            actions.append(f"Redistribute workload away from {resource_id}")
            actions.append("Implement preventive maintenance to minimize downtime")

        actions.append(f"Review scheduling of {resource_id} to reduce setup times")
        actions.append(f"Monitor queue times at {resource_id}")

        return actions

    def wagner_whitin_lot_sizing(
        self, sku: SKU, demands: list[Decimal], setup_cost: Decimal, holding_cost_per_unit: Decimal
    ) -> LotSizingResult:
        """
        Wagner-Whitin dynamic programming algorithm for lot sizing.

        Args:
            sku: Stock keeping unit
            demands: Period demands
            setup_cost: Cost to setup/order
            holding_cost_per_unit: Cost to hold inventory per period

        Returns:
            LotSizingResult with optimal lot sizes
        """
        n = len(demands)
        # Dynamic programming table
        cost = [[Decimal("999999999")] * n for _ in range(n)]
        lot_matrix = [[Decimal("0")] * n for _ in range(n)]

        # Base case: producing for single period
        for i in range(n):
            cost[i][i] = setup_cost + Decimal("0")
            lot_matrix[i][i] = demands[i]

        # Fill table for all periods
        for length in range(2, n + 1):
            for i in range(n - length + 1):
                j = i + length - 1
                cumulative_demand = Decimal("0")

                for k in range(i, j + 1):
                    cumulative_demand += demands[k]
                    # Cost of producing at period k for periods k to j
                    holding_periods = j - k
                    holding_cost = holding_cost_per_unit * cumulative_demand * Decimal(holding_periods) / Decimal("2")
                    total_cost = cost[i][k - 1] if k > i else Decimal("0")
                    total_cost += setup_cost + holding_cost

                    if total_cost < cost[i][j]:
                        cost[i][j] = total_cost
                        lot_matrix[i][j] = cumulative_demand

        # Backtrack to find optimal solution
        lot_sizes = [Decimal("0")] * n
        setup_costs_used = [Decimal("0")] * n
        holding_costs_used = [Decimal("0")] * n

        current = n - 1
        while current >= 0:
            lot_sizes[current] = lot_matrix[0][current]
            setup_costs_used[current] = setup_cost
            if current > 0:
                holding_costs_used[current] = holding_cost_per_unit * lot_matrix[0][current]
            current -= 1

        total_cost = sum(setup_costs_used) + sum(holding_costs_used)
        cost_per_unit = total_cost / Decimal(sum(demands)) if sum(demands) > 0 else Decimal("0")

        return LotSizingResult(
            sku=sku,
            total_periods=n,
            demands=demands,
            lot_sizes=lot_sizes,
            setup_costs=setup_costs_used,
            holding_costs=holding_costs_used,
            total_cost=total_cost,
            cost_per_unit=cost_per_unit,
        )

    def track_wip(
        self,
        production_order: ProductionOrder,
        current_location: str,
        quantity_completed: Decimal,
        quantity_scrapped: Decimal = Decimal("0"),
    ) -> WIPStatus:
        """
        Track work-in-process status.

        Args:
            production_order: Production order being tracked
            current_location: Current location in production
            quantity_completed: Quantity completed to date
            quantity_scrapped: Quantity scrapped

        Returns:
            WIPStatus with current progress
        """
        quantity_in_process = production_order.quantity - quantity_completed - quantity_scrapped

        elapsed_days = (datetime.utcnow() - production_order.actual_start).days if production_order.actual_start else 0

        # Estimate cycle time from scheduled dates
        cycle_time_days = (
            (production_order.scheduled_end - production_order.scheduled_start).days
            if production_order.scheduled_start and production_order.scheduled_end
            else 0
        )

        return WIPStatus(
            production_order_id=production_order.id,
            product_id=production_order.product_id,
            quantity_started=production_order.quantity,
            quantity_completed=quantity_completed,
            quantity_in_process=quantity_in_process,
            quantity_scrapped=quantity_scrapped,
            elapsed_time_days=elapsed_days,
            cycle_time_days=cycle_time_days,
            locations=[current_location],
        )

    def check_material_availability(
        self,
        production_order: ProductionOrder,
        on_hand_inventory: dict[SKU, Decimal],
        on_order_inventory: dict[SKU, Decimal],
    ) -> tuple[bool, list[str]]:
        """
        Check if materials are available for production.

        Args:
            production_order: Production order
            on_hand_inventory: Current inventory
            on_order_inventory: Inventory on order

        Returns:
            Tuple of (all_available, shortage_list)
        """
        shortages = []

        for material in production_order.required_materials:
            required_qty = material.quantity_required * production_order.quantity

            available = on_hand_inventory.get(material.sku, Decimal("0")) + on_order_inventory.get(
                material.sku, Decimal("0")
            )

            if available < required_qty:
                shortage_qty = required_qty - available
                shortages.append(f"{material.sku.code}: Short by {shortage_qty} units")

        return len(shortages) == 0, shortages
